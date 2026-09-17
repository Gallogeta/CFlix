import os
import shutil
import subprocess
import urllib.request
import json
from typing import Optional, Dict, Any

from config import (
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir, get_staging_dir,
    get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass
)
from logger import emit_log

def sanitize_filename(name: str) -> str:
    # Replace invalid filesystem characters
    name = name.replace(":", " -")
    name = name.replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "")
    name = name.replace("\"", "'").replace("<", "").replace(">", "").replace("|", "")
    return " ".join(name.split()).strip()

def get_jellyfin_token():
    url = f"{get_jellyfin_url()}/Users/AuthenticateByName"
    headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": 'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0"'
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
    headers = {"Authorization": f'MediaBrowser Token="{token}"'}
    req = urllib.request.Request(url, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            emit_log("Triggered Jellyfin Library Refresh successfully.")
            return True
    except Exception as e:
        emit_log(f"Error triggering Jellyfin refresh: {e}")
        return False

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
    if is_series_format:
        if custom_dir:
            dest_base = custom_dir
        elif target_category == "anime":
            dest_base = get_anime_dir()
        else:
            dest_base = get_series_dir()

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
        dest_base = custom_dir if custom_dir else get_anime_dir()
        os.makedirs(dest_base, exist_ok=True)
        year_str = f" ({year})" if year else ""
        filename = f"{clean_title_str}{year_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    elif target_category == "adult":
        dest_base = custom_dir if custom_dir else get_adult_dir()
        os.makedirs(dest_base, exist_ok=True)
        filename = f"{clean_title_str}.{ext}"
        final_dest = os.path.join(dest_base, filename)

    elif target_category == "custom" and custom_dir:
        os.makedirs(custom_dir, exist_ok=True)
        year_str = f" ({year})" if year else ""
        filename = f"{clean_title_str}{year_str}.{ext}"
        final_dest = os.path.join(custom_dir, filename)

    else: # movies default
        dest_base = custom_dir if custom_dir else get_movies_dir()
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

    # Step 2: Move to destination storage
    emit_log(f"Moving file to media storage: '{final_dest}'...")
    try:
        if os.path.exists(final_dest) and overwrite:
            emit_log(f"Replacing existing file at '{final_dest}' as requested.")
            os.remove(final_dest)
        shutil.move(staging_file, final_dest)
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
