import os
import shutil
import subprocess
import urllib.request
import json
import re
from typing import Optional, Dict, Any

from config import (
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir, get_staging_dir,
    get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass
)
from logger import emit_log
from directories_manager import directories_mgr

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".webm", ".m4v", ".wmv", ".iso"}

def sanitize_filename(name: str) -> str:
    # Replace invalid filesystem characters
    name = name.replace(":", " -")
    name = name.replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "")
    name = name.replace("\"", "'").replace("<", "").replace(">", "").replace("|", "")
    return " ".join(name.split()).strip()

def get_jellyfin_token():
    url = f"{get_jellyfin_url()}/Users/AuthenticateByName"
    auth_val = 'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0"'
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_val,
        "X-Emby-Authorization": auth_val,
        "User-Agent": "CFlixMediaManager/1.0"
    }
    payload = {"Username": get_jellyfin_user(), "Pw": get_jellyfin_pass()}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
            return data.get("AccessToken")
    except Exception as e:
        emit_log(f"Failed to authenticate with Jellyfin: {e}")
        return None

def trigger_jellyfin_refresh():
    token = get_jellyfin_token()
    if not token:
        return False
    
    url = f"{get_jellyfin_url()}/Library/Refresh"
    auth_token_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
    headers = {
        "Authorization": auth_token_val,
        "X-Emby-Authorization": auth_token_val,
        "X-MediaBrowser-Token": token,
        "X-Emby-Token": token,
        "User-Agent": "CFlixMediaManager/1.0"
    }
    req = urllib.request.Request(url, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            emit_log("Triggered Jellyfin Library Refresh successfully.")
            return True
    except Exception as e:
        emit_log(f"Error triggering Jellyfin refresh: {e}")
        return False

def cleanup_existing_duplicates(
    category_or_library: str,
    is_series: bool,
    title: str,
    year: Optional[str],
    season: Optional[int],
    episode: Optional[int],
    final_dest: str
):
    """When overwriting/re-uploading media, safely removes old versions of the same movie or episode
    both in the target directory and across ALL drives in the multi-drive storage pool so no duplicates remain."""
    final_norm = os.path.normpath(final_dest)

    # 1. Remove exact destination file if it already exists
    if os.path.exists(final_norm):
        try:
            os.remove(final_norm)
            emit_log(f"[Overwrite] Removed existing destination file: '{final_norm}'")
        except Exception as e:
            emit_log(f"Notice: Could not remove existing file at '{final_norm}': {e}")

    clean_t = sanitize_filename(title)
    candidate_roots = directories_mgr.get_candidate_paths_for_library(category_or_library)

    if is_series and season is not None and episode is not None:
        ep_pattern = re.compile(rf"(?i)\bs0*{season}e0*{episode}\b")
        season_folder = f"Season {season:02d}"

        for root in candidate_roots:
            show_dir = os.path.join(root, clean_t)
            if not os.path.exists(show_dir) or not os.path.isdir(show_dir):
                continue

            s_dir = os.path.join(show_dir, season_folder)
            check_dirs = [s_dir, show_dir] if os.path.exists(s_dir) else [show_dir]

            for d in check_dirs:
                if not os.path.exists(d):
                    continue
                try:
                    for f in os.listdir(d):
                        f_lower = f.lower()
                        ext = os.path.splitext(f_lower)[1]
                        if ext in VIDEO_EXTENSIONS and ep_pattern.search(f_lower):
                            old_file = os.path.normpath(os.path.join(d, f))
                            if old_file != final_norm and os.path.exists(old_file):
                                try:
                                    os.remove(old_file)
                                    emit_log(f"[Overwrite] Removed previous episode version from '{root}': '{old_file}'")
                                except Exception as err:
                                    emit_log(f"Notice removing old episode '{old_file}': {err}")
                except Exception as e:
                    emit_log(f"Notice checking old episodes in '{d}': {e}")

            # Clean up empty season directory if left empty
            if os.path.exists(s_dir):
                try:
                    if not [e for e in os.listdir(s_dir) if not e.startswith(".")]:
                        os.rmdir(s_dir)
                except Exception:
                    pass

    else:
        # Movies or single titles
        stems_to_match = {clean_t.lower()}
        if year:
            stems_to_match.add(f"{clean_t} ({year})".lower())

        for root in candidate_roots:
            if not os.path.exists(root) or not os.path.isdir(root):
                continue
            try:
                for f in os.listdir(root):
                    f_lower = f.lower()
                    f_stem, f_ext = os.path.splitext(f_lower)
                    if f_ext in VIDEO_EXTENSIONS and f_stem in stems_to_match:
                        old_file = os.path.normpath(os.path.join(root, f))
                        if old_file != final_norm and os.path.exists(old_file):
                            try:
                                os.remove(old_file)
                                emit_log(f"[Overwrite] Removed previous movie version from '{root}': '{old_file}'")
                            except Exception as err:
                                emit_log(f"Notice removing old movie '{old_file}': {err}")

                    # Also check subfolder structure (e.g. root/Movie (Year)/Movie (Year).mkv)
                    sub_p = os.path.join(root, f)
                    if os.path.isdir(sub_p) and f.lower() in stems_to_match:
                        for sf in os.listdir(sub_p):
                            sf_lower = sf.lower()
                            sf_ext = os.path.splitext(sf_lower)[1]
                            if sf_ext in VIDEO_EXTENSIONS:
                                old_file = os.path.normpath(os.path.join(sub_p, sf))
                                if old_file != final_norm and os.path.exists(old_file):
                                    try:
                                        os.remove(old_file)
                                        emit_log(f"[Overwrite] Removed previous movie in subfolder on '{root}': '{old_file}'")
                                    except Exception as err:
                                        emit_log(f"Notice removing old movie '{old_file}': {err}")
            except Exception as e:
                emit_log(f"Notice checking old movies in '{root}': {e}")

def process_and_ingest(
    src_file: str,
    target_category: str, # "movies", "series", "adult", or "custom"
    title: str,
    year: Optional[str] = None,
    imdb_id: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    episode_title: Optional[str] = None,
    custom_dir: Optional[str] = None,
    overwrite: bool = True
) -> Dict[str, Any]:
    if not os.path.exists(src_file):
        emit_log(f"ERROR: Source file does not exist: {src_file}")
        return {"success": False, "error": f"Source file does not exist: {src_file}"}

    os.makedirs(get_staging_dir(), exist_ok=True)
    ext = src_file.rsplit(".", 1)[-1].lower() if "." in src_file else "mp4"

    # Build destination paths
    clean_title_str = sanitize_filename(title)

    is_anime = target_category == "anime" or (custom_dir and "anime" in custom_dir.lower())
    has_season_or_ep = (season is not None) or (episode is not None)
    if is_anime:
        is_series_format = has_season_or_ep
    elif target_category in ("series", "shows"):
        is_series_format = True
    elif has_season_or_ep and target_category not in ("movies", "adult"):
        is_series_format = True
    else:
        is_series_format = False
    src_size = os.path.getsize(src_file) if os.path.exists(src_file) else 0

    if is_series_format:
        cat = "anime" if is_anime else "series"
        alloc_cat = cat
        if custom_dir and any(w in custom_dir.lower() for w in ["series", "show", "tv", "anime"]):
            alloc_cat = custom_dir
        dest_base = directories_mgr.smart_allocate_path(
            category_or_library=alloc_cat,
            required_bytes=src_size,
            title=clean_title_str
        )

        s_num = season if season is not None else 1
        e_num = episode if episode is not None else 1
        ep_name_part = f" - {sanitize_filename(episode_title)}" if episode_title else ""
        
        rel_path = os.path.join(
            clean_title_str,
            f"Season {s_num:02d}",
            f"{clean_title_str} - S{s_num:02d}E{e_num:02d}{ep_name_part}.{ext}"
        )
        final_dest = os.path.join(dest_base, rel_path)
        final_dir = os.path.dirname(final_dest)
        os.makedirs(final_dir, exist_ok=True)
    elif target_category == "anime":
        alloc_cat = custom_dir if custom_dir else "anime"
        dest_base = directories_mgr.smart_allocate_path(
            category_or_library=alloc_cat,
            required_bytes=src_size,
            title=clean_title_str
        )
        os.makedirs(dest_base, exist_ok=True)
        year_str = f" ({year})" if year else ""
        filename = f"{clean_title_str}{year_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    elif target_category == "adult":
        alloc_cat = custom_dir if custom_dir else "adult"
        dest_base = directories_mgr.smart_allocate_path(
            category_or_library=alloc_cat,
            required_bytes=src_size,
            title=clean_title_str
        )
        os.makedirs(dest_base, exist_ok=True)
        filename = f"{clean_title_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    elif target_category == "custom" and custom_dir:
        alloc_cat = custom_dir
        dest_base = directories_mgr.smart_allocate_path(
            category_or_library=alloc_cat,
            required_bytes=src_size,
            title=clean_title_str
        )
        os.makedirs(dest_base, exist_ok=True)
        year_str = f" ({year})" if year else ""
        filename = f"{clean_title_str}{year_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    else: # movies default
        alloc_cat = custom_dir if custom_dir else (target_category or "movies")
        dest_base = directories_mgr.smart_allocate_path(
            category_or_library=alloc_cat,
            required_bytes=src_size,
            title=clean_title_str
        )
        os.makedirs(dest_base, exist_ok=True)
        year_str = f" ({year})" if year else ""
        filename = f"{clean_title_str}{year_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    staging_file = os.path.join(get_staging_dir(), f"tag_{os.path.basename(final_dest)}")

    emit_log(f"Starting processing: '{os.path.basename(src_file)}' -> '{final_dest}'")

    # Step 1: ffmpeg metadata tagging
    if is_series_format:
        ep_tag = episode_title if episode_title else f"Episode {e_num}"
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", src_file,
            "-metadata", f"show={clean_title_str}",
            "-metadata", f"title={ep_tag}",
            "-metadata", f"season_number={s_num}",
            "-metadata", f"episode_sort={e_num}",
            "-c", "copy"
        ]
    else:
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", src_file,
            "-metadata", f"title={clean_title_str}",
            "-c", "copy"
        ]

    if imdb_id:
        ffmpeg_cmd.extend(["-metadata", f"comment={imdb_id}"])
    if year:
        ffmpeg_cmd.extend(["-metadata", f"date={year}", "-metadata", f"year={year}"])
    
    ffmpeg_cmd.append(staging_file)

    emit_log(f"Writing metadata via ffmpeg to staging file...")
    try:
        res = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            emit_log(f"Warning: ffmpeg tagging failed ({res.stderr[-200:] if res.stderr else 'unknown'}). Fallback to direct move.")
            shutil.copy2(src_file, staging_file)
    except Exception as e:
        emit_log(f"Warning: ffmpeg error ({e}). Fallback to copy.")
        shutil.copy2(src_file, staging_file)

    # Step 2: Overwrite cleanup & move to destination storage
    if overwrite:
        cleanup_existing_duplicates(
            category_or_library=alloc_cat,
            is_series=is_series_format,
            title=clean_title_str,
            year=year,
            season=s_num if is_series_format else None,
            episode=e_num if is_series_format else None,
            final_dest=final_dest
        )
    elif os.path.exists(final_dest):
        emit_log(f"Notice: Destination file '{final_dest}' already exists and overwrite is disabled. Skipping move.")
        return {"success": True, "destination": final_dest, "title": clean_title_str, "skipped": True}

    emit_log(f"Moving file to media storage: '{final_dest}'...")
    try:
        shutil.move(staging_file, final_dest)
        try:
            os.chmod(final_dest, 0o666)
        except Exception:
            pass
    except Exception as e:
        emit_log(f"Failed to move to destination: {e}")
        return {"success": False, "error": str(e)}

    # Step 3: Remove source file if it was uploaded or from incoming watch folder
    if os.path.exists(src_file) and src_file != final_dest:
        try:
            os.remove(src_file)
            emit_log(f"Cleaned up source file: {src_file}")
        except Exception as e:
            emit_log(f"Could not remove source file: {e}")

    # Step 4: Refresh Jellyfin
    trigger_jellyfin_refresh()

    emit_log(f"SUCCESS: Ingested '{os.path.basename(final_dest)}' into Jellyfin library.")
    return {
        "success": True,
        "destination": final_dest,
        "title": clean_title_str,
        "year": year,
        "imdb_id": imdb_id
    }
