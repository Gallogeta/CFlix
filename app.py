import os
import shutil
import asyncio
import aiohttp
from aiohttp import web
import json
import secrets
import time
from typing import Dict, Any, Optional, List

from config import (
    PORT, HOST, DATA_DIR, cfg,
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir, get_watch_dir,
    get_staging_dir, get_upload_tmp_dir, get_jellyfin_url,
    get_jellyfin_user, get_jellyfin_pass, normalize_jellyfin_url
)
from logger import emit_log, subscribe, unsubscribe, get_recent_logs
from metadata import clean_filename, search_imdb, fetch_series_episodes, search_anime, fetch_anime_episodes
from processor import process_and_ingest, trigger_jellyfin_refresh
from collections_manager import collections_mgr
from directories_manager import directories_mgr, format_bytes
from theme_manager import theme_mgr
from watcher import watcher

# Persistent Active Sessions Store
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

# In-memory rate limiter for login protection: { ip: [timestamp, ...] }
FAILED_LOGINS: Dict[str, List[float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW = 60.0  # seconds

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    attempts = FAILED_LOGINS.get(ip, [])
    # Keep only attempts within window
    recent = [t for t in attempts if now - t < LOCKOUT_WINDOW]
    FAILED_LOGINS[ip] = recent
    return len(recent) < MAX_FAILED_ATTEMPTS

def record_failed_login(ip: str):
    now = time.time()
    attempts = FAILED_LOGINS.setdefault(ip, [])
    attempts.append(now)

def clear_failed_logins(ip: str):
    FAILED_LOGINS.pop(ip, None)

def load_sessions() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_sessions(sessions: Dict[str, Dict[str, Any]]):
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)
    except Exception:
        pass

SESSIONS: Dict[str, Dict[str, Any]] = load_sessions()

def get_current_user(request: web.Request) -> Optional[Dict[str, Any]]:
    cookie = request.cookies.get("cfmm_session")
    if cookie and cookie in SESSIONS:
        sess = SESSIONS[cookie]
        if time.time() - sess.get("created_at", 0) < 30 * 86400:
            return sess
    return None

def is_admin_request(request: web.Request) -> bool:
    user = get_current_user(request)
    return bool(user and user.get("is_admin"))

@web.middleware
async def error_handling_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException as ex:
        if request.path.startswith("/api/"):
            return web.json_response(
                {"success": False, "error": ex.reason or str(ex)},
                status=ex.status
            )
        raise
    except Exception as e:
        emit_log(f"Unhandled error on {request.method} {request.path}: {e}")
        if request.path.startswith("/api/"):
            return web.json_response(
                {"success": False, "error": f"Server processing error: {str(e)}"},
                status=500
            )
        raise

@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    resp = await handler(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp

@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    # Public routes: Homepage, static assets, and authentication endpoints
    if (
        path == "/"
        or path.startswith("/static/")
        or path.startswith("/api/auth/")
    ):
        return await handler(request)

    user = get_current_user(request)
    if not user:
        return web.json_response(
            {"success": False, "error": "Unauthorized. Media server authentication required.", "unauthorized": True},
            status=401
        )

    # Restrict core server-side administrative modifications to administrators
    admin_only_paths = (
        "/api/settings",
        "/api/directories/delete",
        "/api/directories/create",
        "/api/themes/apply",
        "/api/themes/save-preset"
    )
    if request.method == "POST" and any(path == p or path.startswith(p + "/") for p in admin_only_paths):
        if not user.get("is_admin"):
            return web.json_response(
                {"success": False, "error": "Forbidden: Server administrator permissions required for this action."},
                status=403
            )

    return await handler(request)

# Ensure upload temp directory exists
os.makedirs(get_upload_tmp_dir(), exist_ok=True)

routes = web.RouteTableDef()

# --- Static & Page Serving ---
@routes.get("/")
async def index_handler(request):
    index_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    return web.FileResponse(index_path)

# --- Auth Endpoints ---
@routes.get("/api/auth/me")
async def auth_me_handler(request):
    user = get_current_user(request)
    servers = cfg.get_servers(sanitize=True)
    active_id = cfg.get_active_server_id()
    if user:
        return web.json_response({
            "authenticated": True,
            "username": user.get("username", "User"),
            "is_admin": bool(user.get("is_admin", False)),
            "can_manage": bool(user.get("can_manage", False)),
            "server_url": get_jellyfin_url(),
            "active_id": active_id,
            "servers": servers
        })
    return web.json_response({
        "authenticated": False,
        "server_configured": bool(get_jellyfin_url()),
        "server_url": get_jellyfin_url(),
        "active_id": active_id,
        "servers": servers
    })

@routes.post("/api/auth/login")
async def auth_login_handler(request):
    client_ip = request.remote or "unknown"
    if not check_rate_limit(client_ip):
        return web.json_response({
            "success": False,
            "error": "Too many failed login attempts. Please wait 1 minute before trying again."
        }, status=429)

    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    server_url = normalize_jellyfin_url(data.get("server_url", "").strip())

    if not username or not password:
        return web.json_response({"success": False, "error": "Username and password are required."}, status=400)

    # Use provided server URL or existing configured URL
    jf_url = server_url or get_jellyfin_url()
    if not jf_url:
        return web.json_response({
            "success": False,
            "error": "Media server URL is not configured. Please provide the server URL."
        }, status=400)

    auth_res = cfg.test_jellyfin(jf_url, username, password)

    if not auth_res.get("success"):
        record_failed_login(client_ip)
        return web.json_response({
            "success": False,
            "error": auth_res.get("error", "Invalid media server credentials or server unreachable.")
        }, status=401)

    clear_failed_logins(client_ip)

    user_info = auth_res.get("user", {})
    policy = user_info.get("Policy", {})
    is_admin = policy.get("IsAdministrator", False)
    is_disabled = policy.get("IsDisabled", False)

    if is_disabled:
        return web.json_response({
            "success": False,
            "error": "Access denied: Account is disabled on the media server."
        }, status=403)

    # Check server-side permissions: Admin, content downloading, media conversion, collection management, or folder access
    can_manage = (
        is_admin or
        policy.get("EnableContentDownloading", False) or
        policy.get("EnableMediaConversion", False) or
        policy.get("EnableCollectionManagement", False) or
        policy.get("EnableAllFolders", False)
    )

    if not can_manage:
        emit_log(f"Login rejected for user '{username}': Insufficient media management permissions on server.")
        return web.json_response({
            "success": False,
            "error": "Access denied: Your account does not have media management or upload permissions on this server."
        }, status=403)

    # Persist the verified working resolved URL & match active server profile
    resolved_url = auth_res.get("resolved_url")
    if resolved_url:
        matched = False
        for s in cfg._settings.get("SERVERS", []):
            if normalize_jellyfin_url(s.get("url", "")) == normalize_jellyfin_url(resolved_url):
                cfg.switch_active_server(s.get("id"))
                if username: s["user"] = username
                if password: s["pass"] = password
                cfg.save()
                matched = True
                break
        if not matched and resolved_url != get_jellyfin_url():
            cfg.set("JELLYFIN_URL", resolved_url)
            emit_log(f"Media server URL verified and updated: {resolved_url}")

    session_token = secrets.token_urlsafe(32)
    SESSIONS[session_token] = {
        "username": user_info.get("Name", username),
        "user_id": user_info.get("Id"),
        "is_admin": is_admin,
        "can_manage": can_manage,
        "token": auth_res.get("token"),
        "created_at": time.time()
    }
    save_sessions(SESSIONS)

    role_str = "Administrator" if is_admin else "Media Manager"
    emit_log(f"User '{username}' ({role_str}) authenticated successfully via media server.")

    resp = web.json_response({
        "success": True,
        "username": user_info.get("Name", username),
        "is_admin": is_admin,
        "can_manage": can_manage
    })
    resp.set_cookie("cfmm_session", session_token, path="/", max_age=30*86400, httponly=True, samesite="Lax")
    return resp

@routes.post("/api/auth/logout")
async def auth_logout_handler(request):
    cookie = request.cookies.get("cfmm_session")
    if cookie and cookie in SESSIONS:
        del SESSIONS[cookie]
        save_sessions(SESSIONS)
    resp = web.json_response({"success": True})
    resp.del_cookie("cfmm_session", path="/")
    return resp

# --- API Endpoints ---
@routes.get("/api/status")
async def status_handler(request):
    jellyfin_ok = collections_mgr.login()
    return web.json_response({
        "status": "online",
        "jellyfin_online": jellyfin_ok,
        "jellyfin_url": get_jellyfin_url(),
        "watcher_enabled": watcher.enabled,
        "movies_dir": get_movies_dir(),
        "series_dir": get_series_dir(),
        "anime_dir": get_anime_dir(),
        "adult_dir": get_adult_dir(),
        "watch_dir": get_watch_dir()
    })

@routes.post("/api/upload")
async def upload_handler(request):
    reader = await request.multipart()
    temp_path = None
    original_filename = None

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            original_filename = part.filename
            temp_dir = get_upload_tmp_dir()
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, original_filename)
            emit_log(f"Receiving streaming upload: '{original_filename}'...")
            
            with open(temp_path, "wb") as f:
                while True:
                    chunk = await part.read_chunk(size=65536)  # 64KB chunks
                    if not chunk:
                        break
                    f.write(chunk)
            emit_log(f"Upload complete: '{original_filename}' ({os.path.getsize(temp_path)} bytes)")

    if not temp_path or not os.path.exists(temp_path):
        return web.json_response({"error": "No file received"}, status=400)

    return web.json_response({
        "success": True,
        "filename": original_filename,
        "temp_path": temp_path,
        "size": os.path.getsize(temp_path)
    })

UPLOAD_LOCKS: Dict[str, asyncio.Lock] = {}

def get_upload_lock(upload_id: str) -> asyncio.Lock:
    if upload_id not in UPLOAD_LOCKS:
        UPLOAD_LOCKS[upload_id] = asyncio.Lock()
    return UPLOAD_LOCKS[upload_id]

def _write_chunk_file(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)

def _reassemble_chunks(chunk_dir: str, final_path: str, total_chunks: int) -> bool:
    with open(final_path, "wb") as outfile:
        for i in range(total_chunks):
            part_path = os.path.join(chunk_dir, f"part_{i:06d}")
            if not os.path.exists(part_path):
                return False
            with open(part_path, "rb") as infile:
                while chunk := infile.read(1024 * 1024 * 16):
                    outfile.write(chunk)
    return True

@routes.post("/api/upload-chunk")
async def upload_chunk_handler(request):
    reader = await request.multipart()
    upload_id = None
    chunk_index = 0
    total_chunks = 1
    filename = "uploaded_file"
    chunk_data = None

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "upload_id":
            upload_id = (await part.text()).strip()
        elif part.name == "chunk_index":
            try:
                chunk_index = int(await part.text())
            except ValueError:
                chunk_index = 0
        elif part.name == "total_chunks":
            try:
                total_chunks = int(await part.text())
            except ValueError:
                total_chunks = 1
        elif part.name == "filename":
            filename = (await part.text()).strip()
        elif part.name == "chunk":
            chunk_data = await part.read()

    if not upload_id or chunk_data is None:
        return web.json_response({"success": False, "error": "Invalid chunk payload"}, status=400)

    # Sanitize upload_id
    clean_upload_id = "".join(c for c in upload_id if c.isalnum() or c in ("-", "_"))
    temp_dir = get_upload_tmp_dir()
    chunk_dir = os.path.join(temp_dir, f"chunks_{clean_upload_id}")
    os.makedirs(chunk_dir, exist_ok=True)

    chunk_file_path = os.path.join(chunk_dir, f"part_{chunk_index:06d}")
    await asyncio.to_thread(_write_chunk_file, chunk_file_path, chunk_data)

    safe_filename = os.path.basename(filename).replace("/", "_").replace("\\", "_")
    final_temp_path = os.path.join(temp_dir, f"up_{clean_upload_id}_{safe_filename}")

    lock = get_upload_lock(clean_upload_id)
    async with lock:
        if os.path.exists(final_temp_path):
            return web.json_response({
                "success": True,
                "completed": True,
                "filename": safe_filename,
                "temp_path": final_temp_path,
                "size": os.path.getsize(final_temp_path)
            })

        parts = [p for p in os.listdir(chunk_dir) if p.startswith("part_")]
        if len(parts) >= total_chunks:
            ok = await asyncio.to_thread(_reassemble_chunks, chunk_dir, final_temp_path, total_chunks)
            if not ok:
                return web.json_response({"success": False, "error": "Missing chunk part during reassembly"}, status=400)

            await asyncio.to_thread(shutil.rmtree, chunk_dir, True)
            try:
                os.chmod(final_temp_path, 0o666)
            except Exception:
                pass
            final_size_mb = os.path.getsize(final_temp_path) / (1024 * 1024)
            emit_log(f"Chunked upload complete: '{safe_filename}' ({final_size_mb:.1f} MB in {total_chunks} chunks)")
            UPLOAD_LOCKS.pop(clean_upload_id, None)

            return web.json_response({
                "success": True,
                "completed": True,
                "filename": safe_filename,
                "temp_path": final_temp_path,
                "size": os.path.getsize(final_temp_path)
            })

        return web.json_response({
            "success": True,
            "completed": False,
            "chunk_index": chunk_index,
            "received_chunks": len(parts),
            "total_chunks": total_chunks
        })

@routes.post("/api/upload/cancel")
async def cancel_upload_handler(request):
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass

    upload_id = data.get("upload_id")
    temp_path = data.get("temp_path")

    if upload_id:
        clean_id = "".join(c for c in str(upload_id) if c.isalnum() or c in ("-", "_"))
        temp_dir = get_upload_tmp_dir()
        chunk_dir = os.path.join(temp_dir, f"chunks_{clean_id}")
        if os.path.exists(chunk_dir):
            try:
                shutil.rmtree(chunk_dir, ignore_errors=True)
            except Exception:
                pass
        try:
            for f in os.listdir(temp_dir):
                if f.startswith(f"up_{clean_id}_"):
                    os.remove(os.path.join(temp_dir, f))
        except Exception:
            pass
        UPLOAD_LOCKS.pop(clean_id, None)

    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass

    emit_log(f"Upload cancelled by user (Upload ID: {upload_id or 'unknown'}). Intermediate chunks purged.")
    return web.json_response({"success": True, "message": "Upload cancelled and temporary files removed."})

@routes.post("/api/clean-title")
async def clean_title_handler(request):
    data = await request.json()
    filename = data.get("filename", "")
    res = clean_filename(filename)
    return web.json_response(res)

@routes.post("/api/batch-clean-titles")
async def batch_clean_titles_handler(request):
    data = await request.json()
    filenames = data.get("filenames", [])
    results = [clean_filename(fn) for fn in filenames]
    return web.json_response(results)

@routes.get("/api/search")
async def search_handler(request):
    query = request.query.get("q", "")
    source = request.query.get("source", "imdb")
    loop = asyncio.get_event_loop()
    if source == "anime":
        results = await loop.run_in_executor(None, search_anime, query)
    else:
        results = await loop.run_in_executor(None, search_imdb, query)
    return web.json_response(results)

@routes.get("/api/series-episodes")
async def series_episodes_handler(request):
    q = request.query.get("q", "")
    imdb_id = request.query.get("imdb_id", "")
    source = request.query.get("source", "imdb")
    loop = asyncio.get_event_loop()
    if source == "anime":
        res = await loop.run_in_executor(None, fetch_anime_episodes, q, imdb_id)
    else:
        res = await loop.run_in_executor(None, fetch_series_episodes, q, imdb_id)
    return web.json_response(res)

@routes.post("/api/process")
async def process_handler(request):
    data = await request.json()
    src_file = data.get("src_file")
    target_category = data.get("target_category", "movies")
    title = data.get("title")
    year = data.get("year")
    imdb_id = data.get("imdb_id")
    season = data.get("season")
    episode = data.get("episode")
    episode_title = data.get("episode_title")
    custom_dir = data.get("custom_dir")
    overwrite = data.get("overwrite", True)

    if not src_file or not title:
        return web.json_response({"success": False, "error": "Missing source file or title"}, status=400)

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        process_and_ingest,
        src_file,
        target_category,
        title,
        year,
        imdb_id,
        season,
        episode,
        episode_title,
        custom_dir,
        overwrite
    )
    return web.json_response(res)

@routes.get("/api/incoming")
async def incoming_handler(request):
    req_folder = request.query.get("folder")
    watch_dir = req_folder.strip() if (req_folder and req_folder.strip()) else None
    if not watch_dir:
        watch_dir = get_watch_dir()
    if not os.path.exists(watch_dir):
        return web.json_response([])

    files = []
    try:
        entries = os.listdir(watch_dir)
        for e in entries:
            if e.lower().endswith((".mp4", ".mkv", ".avi", ".mov")) and not e.startswith("."):
                fpath = os.path.join(watch_dir, e)
                try:
                    sz = os.path.getsize(fpath)
                    sz_mb = round(sz / (1024 * 1024), 1)
                except OSError:
                    sz_mb = 0

                is_ready = watcher.is_file_ready(fpath)
                meta = clean_filename(e)
                files.append({
                    "filename": e,
                    "path": fpath,
                    "size_mb": sz_mb,
                    "is_ready": is_ready,
                    "cleaned_title": meta["cleaned_title"],
                    "guessed_year": meta.get("guessed_year")
                })
    except Exception as err:
        emit_log(f"Error listing incoming folder: {err}")

    return web.json_response(files)

@routes.get("/api/collections")
async def collections_handler(request):
    loop = asyncio.get_event_loop()
    overview = await loop.run_in_executor(None, collections_mgr.get_collections_overview)
    return web.json_response(overview)

@routes.post("/api/collections/sync")
async def sync_collections_handler(request):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, collections_mgr.sync_all_collections)
    return web.json_response(res)

@routes.post("/api/collections/sync-one")
async def sync_single_collection_handler(request):
    data = await request.json()
    cid = data.get("collection_id")
    if not cid:
        return web.json_response({"success": False, "error": "Missing collection_id"})
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, collections_mgr.sync_single_collection_by_id, cid)
    return web.json_response(res)

@routes.post("/api/collections/clean-placeholders")
async def clean_placeholders_handler(request):
    loop = asyncio.get_event_loop()
    purged = await loop.run_in_executor(None, collections_mgr.clean_redundant_placeholders)
    return web.json_response({"success": True, "purged_count": purged})

@routes.get("/api/watcher/folders")
async def watcher_folders_handler(request):
    current = get_watch_dir()
    home = os.path.expanduser("~")
    candidates = [
        current,
        os.path.join(home, "dwhelper"),
        os.path.join(home, "Downloads"),
        "/downloads",
        "/mnt/incoming",
        "/mnt/downloads"
    ]
    # Dynamically discover incoming/downloads folders across all active media roots / drives
    for root in cfg.get_media_roots():
        if os.path.isdir(root):
            for sub in ["incoming", "downloads", "dwhelper"]:
                p = os.path.join(root, sub)
                if os.path.isdir(p):
                    candidates.append(p)
    existing = []
    seen = set()
    for c_path in candidates:
        if c_path and c_path not in seen and os.path.isdir(c_path):
            seen.add(c_path)
            existing.append(c_path)
    if current and current not in seen:
        existing.insert(0, current)
    return web.json_response({"current": current, "folders": existing, "enabled": watcher.enabled})

@routes.post("/api/watcher/set-folder")
async def watcher_set_folder_handler(request):
    data = await request.json()
    folder = (data.get("folder") or "").strip()
    create_if_missing = data.get("create_if_missing", False)

    if not folder:
        return web.json_response({"success": False, "error": "Folder path cannot be empty."})

    if not os.path.exists(folder):
        if create_if_missing:
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                return web.json_response({"success": False, "error": f"Failed to create directory: {e}"})
        else:
            return web.json_response({"success": False, "error": f"Directory does not exist: {folder}"})

    cfg.set("WATCH_DIR", folder)
    cfg.save()
    emit_log(f"Monitored incoming folder updated to: {folder}")

    try:
        f_list = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov")) and not f.startswith(".")]
        f_count = len(f_list)
    except Exception:
        f_count = 0

    return web.json_response({"success": True, "watch_dir": folder, "file_count": f_count})

@routes.post("/api/watcher/toggle")
async def watcher_toggle_handler(request):
    data = await request.json()
    enabled = data.get("enabled", True)
    watcher.toggle(enabled)
    return web.json_response({"enabled": watcher.enabled})

@routes.post("/api/refresh-library")
async def refresh_library_handler(request):
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, trigger_jellyfin_refresh)
    return web.json_response({"success": bool(ok)})
# --- Multi-Server Management Endpoints ---
@routes.get("/api/servers")
async def get_servers_handler(request):
    servers = cfg.get_servers(sanitize=True)
    active_id = cfg.get_active_server_id()
    return web.json_response({"active_id": active_id, "servers": servers})

@routes.post("/api/servers/switch")
async def switch_server_handler(request):
    data = await request.json()
    server_id = data.get("server_id")
    if not server_id:
        return web.json_response({"success": False, "error": "Missing server_id"})

    ok = cfg.switch_active_server(server_id)
    if not ok:
        return web.json_response({"success": False, "error": f"Server ID '{server_id}' not found"})

    collections_mgr.reset_session()
    active = cfg.get_active_server()
    emit_log(f"Active media server switched to: '{active.get('name')}' ({active.get('url')})")

    return web.json_response({
        "success": True,
        "active_id": cfg.get_active_server_id(),
        "server": {
            "id": active.get("id"),
            "name": active.get("name"),
            "url": active.get("url"),
            "user": active.get("user")
        }
    })

@routes.post("/api/servers/save")
async def save_server_handler(request):
    data = await request.json()
    server_data = data.get("server") or data
    name = (server_data.get("name") or "").strip()
    url = (server_data.get("url") or "").strip()

    if not name or not url:
        return web.json_response({"success": False, "error": "Server Name and URL are required"})

    saved = cfg.save_server(server_data)
    emit_log(f"Saved media server profile: '{saved.get('name')}'")
    return web.json_response({"success": True, "server": saved})

@routes.post("/api/servers/delete")
async def delete_server_handler(request):
    data = await request.json()
    server_id = data.get("server_id")
    if not server_id:
        return web.json_response({"success": False, "error": "Missing server_id"})

    ok = cfg.delete_server(server_id)
    if not ok:
        return web.json_response({"success": False, "error": "Cannot delete server (not found or only server profile)"})

    emit_log(f"Deleted media server profile: '{server_id}'")
    return web.json_response({
        "success": True,
        "active_id": cfg.get_active_server_id(),
        "servers": cfg.get_servers(sanitize=True)
    })

@routes.post("/api/servers/test")
async def test_server_handler(request):
    data = await request.json()
    url = data.get("url", "")
    user = data.get("user", "")
    pw = data.get("pass") or data.get("pw", "")
    server_id = data.get("server_id") or data.get("id")
    if not pw and server_id:
        for s in cfg._settings.get("SERVERS", []):
            if s.get("id") == server_id and s.get("pass"):
                pw = s.get("pass")
                break
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, cfg.test_jellyfin, url, user, pw)
    return web.json_response(res)

# --- Themes & Skins Endpoints ---
@routes.get("/api/themes")
async def get_themes_handler(request):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, theme_mgr.get_theme_status)
    return web.json_response(res)

@routes.post("/api/themes/apply")
async def apply_theme_handler(request):
    data = await request.json()
    css = data.get("css", "")
    preset_id = data.get("preset_id")
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, theme_mgr.apply_theme, css, preset_id)
    return web.json_response(res)

@routes.post("/api/themes/save-preset")
async def save_preset_handler(request):
    data = await request.json()
    name = data.get("name", "")
    css = data.get("css", "")
    desc = data.get("description", "")
    if not name or not name.strip():
        return web.json_response({"success": False, "error": "Preset name is required"}, status=400)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, theme_mgr.save_custom_preset, name, css, desc)
    return web.json_response(res)

@routes.delete("/api/themes/preset/{id}")
async def delete_preset_handler(request):
    preset_id = request.match_info.get("id")
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, theme_mgr.delete_custom_preset, preset_id)
    return web.json_response(res)

# --- Settings & Transportability Endpoints ---
@routes.get("/api/settings")
async def get_settings_handler(request):
    return web.json_response(cfg.get_all())

@routes.post("/api/settings")
async def update_settings_handler(request):
    data = await request.json()
    updated = cfg.update(data)
    emit_log("Configuration settings updated successfully.")
    return web.json_response({"success": True, "settings": updated})

@routes.post("/api/settings/test-connection")
async def test_connection_handler(request):
    data = await request.json()
    url = data.get("url", get_jellyfin_url())
    user = data.get("user", get_jellyfin_user())
    pw = data.get("pw", get_jellyfin_pass())
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, cfg.test_jellyfin, url, user, pw)
    return web.json_response(res)

@routes.post("/api/settings/validate-path")
async def validate_path_handler(request):
    data = await request.json()
    path = (data.get("path") or "").strip()
    category = (data.get("category") or "").strip().lower()
    create_if_missing = data.get("create_if_missing", False)
    
    if create_if_missing and path:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            return web.json_response({"exists": False, "error": f"Failed to create: {e}"})

    exists = os.path.exists(path)
    is_dir = os.path.isdir(path) if exists else False
    free_gb = 0
    total_gb = 0
    free_human = "0 GB"
    total_human = "0 GB"
    disk_mount = ""
    disk_name = ""
    writable = False

    if exists and is_dir:
        try:
            total, used, free = shutil.disk_usage(path)
            free_gb = round(free / (1024 * 1024 * 1024), 1)
            total_gb = round(total / (1024 * 1024 * 1024), 1)
            free_human = format_bytes(free)
            total_human = format_bytes(total)

            curr = os.path.abspath(path)
            while curr != "/" and not os.path.ismount(curr):
                curr = os.path.dirname(curr)
            disk_mount = curr
            disk_name = os.path.basename(curr.rstrip("/")) or "root"
            writable = os.access(path, os.W_OK)
        except Exception:
            pass

    # Multi-drive locations and active write target
    multi_drive = False
    locations = []
    active_target = None
    if category:
        try:
            cands = directories_mgr.get_candidate_paths_for_library(category)
            if len(cands) > 1:
                multi_drive = True
            for c in cands:
                c_exists = os.path.exists(c) and os.path.isdir(c)
                c_free_b = 0
                c_tot_b = 0
                c_disk = "media"
                if c_exists:
                    try:
                        tot, u, f = shutil.disk_usage(c)
                        c_free_b = f
                        c_tot_b = tot
                        curr = os.path.abspath(c)
                        while curr != "/" and not os.path.ismount(curr):
                            curr = os.path.dirname(curr)
                        c_disk = os.path.basename(curr.rstrip("/")) or "media"
                    except Exception:
                        pass
                locations.append({
                    "path": c,
                    "exists": c_exists,
                    "disk_name": c_disk,
                    "free_gb": round(c_free_b / (1024**3), 1),
                    "free_human": format_bytes(c_free_b)
                })
            healthy = [l for l in locations if l["free_gb"] >= 50]
            active_target = max(healthy, key=lambda x: x["free_gb"]) if healthy else (max(locations, key=lambda x: x["free_gb"]) if locations else None)
        except Exception:
            pass

    return web.json_response({
        "exists": exists,
        "is_dir": is_dir,
        "free_gb": free_gb,
        "total_gb": total_gb,
        "free_human": free_human,
        "total_human": total_human,
        "disk_mount": disk_mount,
        "disk_name": disk_name,
        "writable": writable,
        "multi_drive": multi_drive,
        "locations": locations,
        "active_target": active_target
    })

@routes.get("/api/settings/storage-summary")
async def get_storage_summary_handler(request):
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, directories_mgr.get_storage_summary)
    return web.json_response(summary)

@routes.post("/api/settings/auto-fix-paths")
async def auto_fix_paths_handler(request):
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    apply_changes = data.get("apply", True)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, directories_mgr.auto_detect_correct_paths, apply_changes)
    return web.json_response(res)

# --- Media Directories & Library Management Endpoints ---
@routes.get("/api/directories")
async def get_directories_handler(request):
    loop = asyncio.get_event_loop()
    dirs = await loop.run_in_executor(None, directories_mgr.list_all_directories)
    return web.json_response(dirs)

@routes.get("/api/directories/parents")
async def get_directory_parents_handler(request):
    loop = asyncio.get_event_loop()
    parents = await loop.run_in_executor(None, directories_mgr.get_available_parent_locations)
    return web.json_response(parents)

@routes.post("/api/directories/create")
async def create_directory_handler(request):
    data = await request.json()
    name = data.get("name", "").strip()
    content_type = data.get("content_type", "movies")
    add_to_jellyfin = data.get("add_to_jellyfin", True)
    parent_path = data.get("parent_path", "").strip() or None
    
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, directories_mgr.create_directory, name, content_type, add_to_jellyfin, parent_path
    )
    return web.json_response(res)

@routes.post("/api/directories/delete")
async def delete_directory_handler(request):
    data = await request.json()
    name = data.get("name", "").strip()
    path = data.get("path", "").strip() or None
    remove_from_jellyfin = data.get("remove_from_jellyfin", True)
    force = data.get("force", False)

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, directories_mgr.delete_directory, name, remove_from_jellyfin, force, path
    )
    return web.json_response(res)

# --- Live Log Streaming (SSE) ---
@routes.get("/api/logs/stream")
async def logs_stream_handler(request):
    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*'
        }
    )
    await response.prepare(request)

    for line in get_recent_logs()[-30:]:
        msg = f"data: {line}\n\n"
        await response.write(msg.encode('utf-8'))

    queue = subscribe()
    try:
        while True:
            line = await queue.get()
            msg = f"data: {line}\n\n"
            await response.write(msg.encode('utf-8'))
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        unsubscribe(queue)

    return response

def create_app():
    app = web.Application(
        client_max_size=1024 * 1024 * 1024 * 20,  # Support up to 20GB streaming upload
        middlewares=[error_handling_middleware, security_headers_middleware, auth_middleware]
    )
    app.add_routes(routes)
    
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.router.add_static("/static", static_dir)
    
    return app

if __name__ == "__main__":
    emit_log("=== CFlix Media Manager (CFMM) Starting ===")
    
    watcher.start()
    
    app = create_app()
    web.run_app(app, host=HOST, port=PORT)
