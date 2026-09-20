import os
import json
import shutil
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
import uuid

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

import re
from urllib.parse import urlparse

def normalize_jellyfin_url(url: str) -> str:
    """Cleans and normalizes any Jellyfin server URL or address entered by user."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    # Strip any fragments (e.g. #/home)
    url = url.split("#")[0]
    # Strip any /web or /web/... paths
    url = re.sub(r"/web(?:/.*)?$", "", url, flags=re.IGNORECASE)
    return url.rstrip("/")

# Clean, Generic Default Profile (Configurable via UI or Environment Variables)
DEFAULT_SETTINGS: Dict[str, Any] = {
    "PORT": int(os.environ.get("PORT", 8090)),
    "HOST": os.environ.get("HOST", "0.0.0.0"),
    "JELLYFIN_URL": normalize_jellyfin_url(os.environ.get("JELLYFIN_URL", "")),
    "JELLYFIN_USER": os.environ.get("JELLYFIN_USER", ""),
    "JELLYFIN_PASS": os.environ.get("JELLYFIN_PASS", ""),
    "MOVIES_DIR": os.environ.get("MOVIES_DIR", "/media/movies"),
    "SERIES_DIR": os.environ.get("SERIES_DIR", "/media/tv"),
    "ANIME_DIR": os.environ.get("ANIME_DIR", "/media/anime"),
    "ADULT_DIR": os.environ.get("ADULT_DIR", "/media/adult"),
    "MEDIA_ROOT": os.environ.get("MEDIA_ROOT", "/media"),
    "MEDIA_ROOTS": os.environ.get("MEDIA_ROOTS", ""),
    "JELLYFIN_MEDIA_PATH": os.environ.get("JELLYFIN_MEDIA_PATH", "/data"),
    "WATCH_DIR": os.environ.get("WATCH_DIR", "/downloads"),
    "STAGING_DIR": os.environ.get("STAGING_DIR", "/downloads/.staging"),
    "UPLOAD_TMP_DIR": os.environ.get("UPLOAD_TMP_DIR", "/tmp/cfmm_uploads"),
    "WATCHER_ENABLED": True,
    "WATCHER_INTERVAL": 10,
    "AUTO_OVERFLOW_ENABLED": True,
    "AUTO_OVERFLOW_MIN_GB": 50,
    "STORAGE_ALLOCATION_STRATEGY": "most_free_space",
    "SERVERS": [],
    "ACTIVE_SERVER_ID": "server-local"
}

class ConfigManager:
    def __init__(self):
        self._settings: Dict[str, Any] = {}
        self.load()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    merged = dict(DEFAULT_SETTINGS)
                    merged.update(saved)
                    self._settings = merged
                    self._ensure_servers_profile()
                    return
            except Exception as e:
                print(f"[CFMM] Error loading {SETTINGS_FILE}: {e}")
        
        self._settings = dict(DEFAULT_SETTINGS)
        self._ensure_servers_profile()
        self.save()

    def _ensure_servers_profile(self):
        servers = self._settings.get("SERVERS")
        if not servers or not isinstance(servers, list):
            local_srv = {
                "id": "server-local",
                "name": "Home Server",
                "url": self._settings.get("JELLYFIN_URL", ""),
                "user": self._settings.get("JELLYFIN_USER", ""),
                "pass": self._settings.get("JELLYFIN_PASS", ""),
                "movies_dir": self._settings.get("MOVIES_DIR", "/mnt/media_ssd/jellyfin"),
                "series_dir": self._settings.get("SERIES_DIR", "/mnt/media_ssd/jellyfin_series"),
                "anime_dir": self._settings.get("ANIME_DIR", "/mnt/media_ssd/Anime"),
                "adult_dir": self._settings.get("ADULT_DIR", "/mnt/media_ssd/Adult"),
                "media_roots": self._settings.get("MEDIA_ROOTS", ""),
                "watch_dir": self._settings.get("WATCH_DIR", "/home/gallo/dwhelper"),
                "jellyfin_media_path": self._settings.get("JELLYFIN_MEDIA_PATH", "/data")
            }
            friend_srv = {
                "id": "server-friend",
                "name": "Hekafin (Friend's Server)",
                "url": "http://100.98.209.40:8096",
                "user": "",
                "pass": "",
                "movies_dir": "/mnt/das1/movies",
                "series_dir": "/mnt/das1/shows",
                "anime_dir": "/mnt/das1/anime",
                "adult_dir": "/mnt/das1/adult",
                "media_roots": "/mnt/das1,/mnt/das2",
                "watch_dir": "/mnt/das1/incoming",
                "jellyfin_media_path": "/media"
            }
            self._settings["SERVERS"] = [local_srv, friend_srv]
            self._settings["ACTIVE_SERVER_ID"] = "server-local"
            self.save()
        elif not self._settings.get("ACTIVE_SERVER_ID"):
            self._settings["ACTIVE_SERVER_ID"] = servers[0].get("id", "server-local")
            self.save()

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            print(f"[CFMM] Error saving {SETTINGS_FILE}: {e}")

    def get_media_roots(self) -> List[str]:
        raw = self.get("MEDIA_ROOTS", "")
        if isinstance(raw, str):
            return [r.strip() for r in raw.split(",") if r.strip()]
        elif isinstance(raw, (list, tuple)):
            return [str(r).strip() for r in raw if str(r).strip()]
        return []

    def get_active_server_id(self) -> str:
        return self._settings.get("ACTIVE_SERVER_ID", "server-local")

    def get_active_server(self) -> Dict[str, Any]:
        self._ensure_servers_profile()
        active_id = self.get_active_server_id()
        for s in self._settings.get("SERVERS", []):
            if s.get("id") == active_id:
                return s
        servers = self._settings.get("SERVERS", [])
        return servers[0] if servers else {}

    def get_servers(self, sanitize: bool = True) -> List[Dict[str, Any]]:
        self._ensure_servers_profile()
        res = []
        for s in self._settings.get("SERVERS", []):
            item = dict(s)
            if sanitize:
                item["has_pass"] = bool(item.get("pass"))
                item.pop("pass", None)
            res.append(item)
        return res

    def switch_active_server(self, server_id: str) -> bool:
        self._ensure_servers_profile()
        for s in self._settings.get("SERVERS", []):
            if s.get("id") == server_id:
                self._settings["ACTIVE_SERVER_ID"] = server_id
                self.save()
                return True
        return False

    def save_server(self, server_data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_servers_profile()
        sid = server_data.get("id")
        if not sid:
            sid = f"server-{uuid.uuid4().hex[:8]}"
            server_data["id"] = sid

        if "url" in server_data and server_data["url"]:
            server_data["url"] = normalize_jellyfin_url(server_data["url"])

        servers = self._settings.get("SERVERS", [])
        updated = False
        for idx, s in enumerate(servers):
            if s.get("id") == sid:
                # If password not provided in update, retain existing password
                if "pass" not in server_data or server_data["pass"] is None or server_data["pass"] == "":
                    server_data["pass"] = s.get("pass", "")
                servers[idx] = server_data
                updated = True
                break

        if not updated:
            servers.append(server_data)

        self._settings["SERVERS"] = servers
        # If currently active, ensure active references match
        if self._settings.get("ACTIVE_SERVER_ID") == sid:
            for k in ("url", "user", "pass", "movies_dir", "series_dir", "anime_dir", "adult_dir", "media_roots", "watch_dir", "jellyfin_media_path"):
                if k in server_data:
                    self._settings[k.upper()] = server_data[k]

        self.save()
        return server_data

    def delete_server(self, server_id: str) -> bool:
        self._ensure_servers_profile()
        servers = self._settings.get("SERVERS", [])
        if len(servers) <= 1:
            return False  # Do not delete the only server profile
        new_servers = [s for s in servers if s.get("id") != server_id]
        if len(new_servers) == len(servers):
            return False
        self._settings["SERVERS"] = new_servers
        if self._settings.get("ACTIVE_SERVER_ID") == server_id:
            self._settings["ACTIVE_SERVER_ID"] = new_servers[0].get("id")
        self.save()
        return True

    def get(self, key: str, default: Any = None) -> Any:
        active = self.get_active_server()
        mapping = {
            "JELLYFIN_URL": "url",
            "JELLYFIN_USER": "user",
            "JELLYFIN_PASS": "pass",
            "MOVIES_DIR": "movies_dir",
            "SERIES_DIR": "series_dir",
            "ANIME_DIR": "anime_dir",
            "ADULT_DIR": "adult_dir",
            "MEDIA_ROOTS": "media_roots",
            "WATCH_DIR": "watch_dir",
            "JELLYFIN_MEDIA_PATH": "jellyfin_media_path"
        }
        if key in mapping:
            field = mapping[key]
            if field in active and active[field] is not None:
                val = active[field]
                if val != "":
                    return val
        return self._settings.get(key, default)

    def set(self, key: str, value: Any):
        if key == "JELLYFIN_URL" and isinstance(value, str):
            value = normalize_jellyfin_url(value)
        self._settings[key] = value
        
        # Update in active server profile as well if applicable
        active = self.get_active_server()
        mapping = {
            "JELLYFIN_URL": "url",
            "JELLYFIN_USER": "user",
            "JELLYFIN_PASS": "pass",
            "MOVIES_DIR": "movies_dir",
            "SERIES_DIR": "series_dir",
            "ANIME_DIR": "anime_dir",
            "ADULT_DIR": "adult_dir",
            "MEDIA_ROOTS": "media_roots",
            "WATCH_DIR": "watch_dir",
            "JELLYFIN_MEDIA_PATH": "jellyfin_media_path"
        }
        if key in mapping and active:
            active[mapping[key]] = value

        self.save()

    def update(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        allowed_keys = set(DEFAULT_SETTINGS.keys())
        for k, v in new_settings.items():
            if k in allowed_keys:
                if k in ("PORT", "WATCHER_INTERVAL", "AUTO_OVERFLOW_MIN_GB"):
                    try:
                        self._settings[k] = int(v)
                    except (ValueError, TypeError):
                        pass
                elif k in ("WATCHER_ENABLED", "AUTO_OVERFLOW_ENABLED"):
                    self._settings[k] = bool(v)
                elif isinstance(v, str):
                    v_clean = v.strip()
                    if k.endswith("_DIR") or k in ("MEDIA_ROOT", "JELLYFIN_MEDIA_PATH"):
                        if v_clean and not v_clean.startswith("/") and not v_clean.startswith("\\"):
                            v_clean = "/" + v_clean
                        v_clean = os.path.normpath(v_clean)
                    elif k == "JELLYFIN_URL":
                        v_clean = normalize_jellyfin_url(v_clean)
                    self._settings[k] = v_clean
                else:
                    self._settings[k] = v
        self.save()
        return self.get_all()

    def get_all(self) -> Dict[str, Any]:
        data = dict(self._settings)
        return data

    def test_jellyfin(self, url: str, user: str, pw: str) -> Dict[str, Any]:
        if not url:
            return {"success": False, "error": "Media server URL is not configured."}
        url = normalize_jellyfin_url(url)
        if not url:
            return {"success": False, "error": "Invalid media server URL."}

        candidates = [url]
        if not url.endswith("/jellyfin"):
            candidates.append(f"{url}/jellyfin")

        auth_value = 'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0"'
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_value,
            "X-Emby-Authorization": auth_value,
            "User-Agent": "CFlixMediaManager/1.0"
        }
        payload = {"Username": user, "Pw": pw}
        last_error = "Connection failed"

        for target_url in candidates:
            auth_url = f"{target_url}/Users/AuthenticateByName"
            try:
                req = urllib.request.Request(auth_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=8) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    token = data.get("AccessToken")
                    user_name = data.get("User", {}).get("Name")
                    server_id = data.get("ServerId")
                    return {
                        "success": True,
                        "token": token,
                        "user_name": user_name,
                        "user": data.get("User", {}),
                        "server_id": server_id,
                        "resolved_url": target_url,
                        "message": f"Successfully connected to media server as '{user_name}'!"
                    }
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return {"success": False, "error": "Invalid username or password on media server."}
                if e.code in (404, 302, 301) and target_url != candidates[-1]:
                    continue
                last_error = f"HTTP {e.code}: Authentication Failed ({e.reason})"
            except urllib.error.URLError as e:
                if target_url != candidates[-1]:
                    continue
                last_error = f"Network connection error: {e.reason}"
            except Exception as e:
                last_error = f"Connection error: {str(e)}"

        return {"success": False, "error": last_error}

# Global singleton
cfg = ConfigManager()

# Direct convenience property accessors
def get_jellyfin_url() -> str:
    return cfg.get("JELLYFIN_URL", "")

def get_jellyfin_user() -> str:
    return cfg.get("JELLYFIN_USER", "")

def get_jellyfin_pass() -> str:
    return cfg.get("JELLYFIN_PASS", "")

def get_movies_dir() -> str:
    return cfg.get("MOVIES_DIR", "/media/movies")

def get_series_dir() -> str:
    return cfg.get("SERIES_DIR", "/media/tv")

def get_anime_dir() -> str:
    return cfg.get("ANIME_DIR", "/media/anime")

def get_adult_dir() -> str:
    return cfg.get("ADULT_DIR", "/media/adult")

def get_media_root() -> str:
    return cfg.get("MEDIA_ROOT", "/media")

def get_media_roots() -> List[str]:
    raw = cfg.get("MEDIA_ROOTS", "")
    if isinstance(raw, str):
        return [r.strip() for r in raw.split(",") if r.strip()]
    elif isinstance(raw, (list, tuple)):
        return [str(r).strip() for r in raw if str(r).strip()]
    return []

def get_watch_dir() -> str:
    return cfg.get("WATCH_DIR", "/downloads")

def get_staging_dir() -> str:
    target = cfg.get("STAGING_DIR", "/downloads/.staging")
    try:
        check = target
        while not os.path.exists(check) and os.path.dirname(check) != check:
            check = os.path.dirname(check)
        if os.path.exists(check):
            _, _, free = shutil.disk_usage(check)
            if free > 15 * (1024**3):
                os.makedirs(target, exist_ok=True)
                return target
    except Exception:
        pass

    try:
        from directories_manager import directories_mgr
        roots = directories_mgr.media_roots
        best_cand = None
        max_free = 0
        for r in roots:
            if os.path.exists(r):
                _, _, f = shutil.disk_usage(r)
                if f > max_free:
                    max_free = f
                    best_cand = os.path.join(r, ".staging")
        if best_cand and max_free > 15 * (1024**3):
            os.makedirs(best_cand, exist_ok=True)
            return best_cand
    except Exception:
        pass

    try:
        os.makedirs(target, exist_ok=True)
        return target
    except Exception:
        fallback = "/tmp/cfmm_staging"
        os.makedirs(fallback, exist_ok=True)
        return fallback

def get_upload_tmp_dir() -> str:
    tmp_dir = cfg.get("UPLOAD_TMP_DIR", "/tmp/cfmm_uploads")
    try:
        check = tmp_dir
        while not os.path.exists(check) and os.path.dirname(check) != check:
            check = os.path.dirname(check)
        if os.path.exists(check):
            _, _, free = shutil.disk_usage(check)
            if free > 15 * (1024**3):
                os.makedirs(tmp_dir, exist_ok=True)
                return tmp_dir
    except Exception:
        pass

    try:
        from directories_manager import directories_mgr
        roots = directories_mgr.media_roots
        best_cand = None
        max_free = 0
        for r in roots:
            if os.path.exists(r):
                _, _, f = shutil.disk_usage(r)
                if f > max_free:
                    max_free = f
                    best_cand = os.path.join(r, ".tmp_uploads")
        if best_cand and max_free > 15 * (1024**3):
            os.makedirs(best_cand, exist_ok=True)
            return best_cand
    except Exception:
        pass

    try:
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir
    except Exception:
        fallback = "/tmp/cfmm_uploads"
        os.makedirs(fallback, exist_ok=True)
        return fallback

PORT = cfg.get("PORT", 8090)
HOST = cfg.get("HOST", "0.0.0.0")
