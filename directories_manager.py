import os
import shutil
import urllib.request
import urllib.parse
import json
from typing import List, Dict, Any, Optional

from config import (
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir,
    get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass, cfg
)
from logger import emit_log

PROTECTED_NAMES = {
    "movies", "tv", "series", "anime", "adult", "lost+found",
    "transcode", ".trash-1000", ".tmp_uploads", ".staging"
}

class DirectoriesManager:
    def __init__(self):
        pass

    @property
    def media_root(self) -> str:
        movies_dir = get_movies_dir()
        if movies_dir and os.path.exists(movies_dir):
            return os.path.dirname(movies_dir)
        return cfg.get("MEDIA_ROOT", "/media")

    def get_jellyfin_token(self) -> Optional[str]:
        auth = cfg.test_jellyfin(get_jellyfin_url(), get_jellyfin_user(), get_jellyfin_pass())
        return auth.get("token") if auth.get("success") else None

    def get_jellyfin_virtual_folders(self) -> List[Dict[str, Any]]:
        token = self.get_jellyfin_token()
        if not token or not get_jellyfin_url():
            return []
        
        url = f"{get_jellyfin_url()}/Library/VirtualFolders"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f'MediaBrowser Token="{token}"',
                "User-Agent": "CFlixMediaManager/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            emit_log(f"Notice: Unable to query VirtualFolders: {e}")
            return []

    def list_all_directories(self) -> List[Dict[str, Any]]:
        root = self.media_root
        results = []
        
        # 1. Fetch live media server virtual folders
        jf_vfs = self.get_jellyfin_virtual_folders()
        jf_map = {}
        for vf in jf_vfs:
            name = vf.get("Name", "")
            ctype = vf.get("CollectionType", "movies")
            locs = vf.get("Locations", [])
            for loc in locs:
                folder_basename = os.path.basename(loc.rstrip("/"))
                jf_map[folder_basename.lower()] = {
                    "jf_name": name,
                    "collection_type": ctype,
                    "internal_location": loc
                }

        # 2. Configured standard directories
        defaults = [
            {"name": os.path.basename(get_movies_dir()), "display_name": "Movies", "type": "movies", "path": get_movies_dir()},
            {"name": os.path.basename(get_series_dir()), "display_name": "TV Series", "type": "series", "path": get_series_dir()},
            {"name": os.path.basename(get_anime_dir()), "display_name": "Anime", "type": "series", "path": get_anime_dir()},
            {"name": os.path.basename(get_adult_dir()), "display_name": "Adult", "type": "adult", "path": get_adult_dir()},
        ]

        seen_names = set()

        for d in defaults:
            p = d["path"]
            name = os.path.basename(p.rstrip("/"))
            if not name:
                continue
            seen_names.add(name.lower())
            
            exists = os.path.exists(p)
            item_count = 0
            if exists:
                try:
                    entries = os.listdir(p)
                    item_count = len([e for e in entries if not e.startswith(".")])
                except Exception:
                    pass

            jf_info = jf_map.get(name.lower(), {})
            
            results.append({
                "name": name,
                "display_name": jf_info.get("jf_name") or d["display_name"],
                "path": p,
                "type": d["type"],
                "exists": exists,
                "item_count": item_count,
                "in_jellyfin": bool(jf_info),
                "deletable": name.lower() not in PROTECTED_NAMES
            })

        # 3. Discover any other subdirectories in media root
        if os.path.exists(root) and os.path.isdir(root):
            try:
                for entry in sorted(os.listdir(root)):
                    if entry.startswith(".") or entry.lower() in seen_names or entry.lower() in ("transcode", "lost+found", ".tmp_uploads"):
                        continue
                    full_p = os.path.join(root, entry)
                    if os.path.isdir(full_p):
                        seen_names.add(entry.lower())
                        jf_info = jf_map.get(entry.lower(), {})
                        c_type = "series" if jf_info.get("collection_type") == "tvshows" else "movies"
                        
                        try:
                            item_count = len([e for e in os.listdir(full_p) if not e.startswith(".")])
                        except Exception:
                            item_count = 0

                        results.append({
                            "name": entry,
                            "display_name": jf_info.get("jf_name") or entry,
                            "path": full_p,
                            "type": c_type,
                            "exists": True,
                            "item_count": item_count,
                            "in_jellyfin": bool(jf_info),
                            "deletable": entry.lower() not in PROTECTED_NAMES
                        })
            except Exception as e:
                emit_log(f"Error inspecting media root '{root}': {e}")

        return results

    def create_directory(self, folder_name: str, content_type: str = "movies", add_to_jellyfin: bool = True) -> Dict[str, Any]:
        folder_name = folder_name.strip()
        if not folder_name or any(c in folder_name for c in [":", "/", "\\", "..", "*", "?", "<", ">", "|"]):
            return {"success": False, "error": "Invalid directory name. Special characters are not allowed."}

        target_path = os.path.join(self.media_root, folder_name)
        try:
            os.makedirs(target_path, exist_ok=True)
            try:
                os.chmod(target_path, 0o777)
            except Exception:
                pass
            emit_log(f"Created filesystem directory: '{target_path}'")
        except Exception as e:
            emit_log(f"Failed to create directory '{target_path}': {e}")
            return {"success": False, "error": f"Failed to create directory: {str(e)}"}

        # Optional Jellyfin VirtualFolder creation
        if add_to_jellyfin and get_jellyfin_url():
            token = self.get_jellyfin_token()
            if token:
                media_path_prefix = cfg.get("JELLYFIN_MEDIA_PATH", "/media")
                jf_container_path = f"{media_path_prefix.rstrip('/')}/{folder_name}"
                jf_collection_type = "tvshows" if content_type == "series" else "movies"
                
                url = (
                    f"{get_jellyfin_url()}/Library/VirtualFolders?"
                    f"name={urllib.parse.quote(folder_name)}&"
                    f"collectionType={jf_collection_type}&"
                    f"paths={urllib.parse.quote(jf_container_path)}&"
                    f"refreshLibrary=true"
                )
                headers = {"Authorization": f'MediaBrowser Token="{token}"'}
                req = urllib.request.Request(url, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=8) as res:
                        emit_log(f"Successfully registered Library '{folder_name}' in media server ({jf_collection_type})!")
                except Exception as e:
                    emit_log(f"Directory created, but library registration returned: {e}")
            else:
                emit_log("Could not authenticate with media server to register new library.")

        return {
            "success": True,
            "name": folder_name,
            "path": target_path,
            "type": content_type,
            "in_jellyfin": add_to_jellyfin
        }

    def delete_directory(self, folder_name: str, remove_from_jellyfin: bool = True, force: bool = False) -> Dict[str, Any]:
        folder_name = folder_name.strip()
        if folder_name.lower() in PROTECTED_NAMES:
            return {"success": False, "error": f"Cannot delete core protected directory '{folder_name}'."}

        target_path = os.path.join(self.media_root, folder_name)
        
        # 1. Remove from media server if requested
        if remove_from_jellyfin and get_jellyfin_url():
            token = self.get_jellyfin_token()
            if token:
                url = f"{get_jellyfin_url()}/Library/VirtualFolders?name={urllib.parse.quote(folder_name)}&refreshLibrary=true"
                headers = {"Authorization": f'MediaBrowser Token="{token}"'}
                req = urllib.request.Request(url, headers=headers, method="DELETE")
                try:
                    with urllib.request.urlopen(req, timeout=8) as res:
                        emit_log(f"Removed VirtualFolder '{folder_name}' from media server.")
                except Exception as e:
                    emit_log(f"Notice: Remove library returned: {e}")

        # 2. Remove from filesystem
        if os.path.exists(target_path):
            try:
                entries = [e for e in os.listdir(target_path) if not e.startswith(".")]
                if entries and not force:
                    return {
                        "success": False,
                        "error": f"Directory '{folder_name}' is not empty ({len(entries)} items). Set force=true to delete contents."
                    }
                
                if force:
                    shutil.rmtree(target_path)
                else:
                    os.rmdir(target_path)
                emit_log(f"Deleted directory '{target_path}' from media storage.")
            except Exception as e:
                emit_log(f"Error removing directory '{target_path}': {e}")
                return {"success": False, "error": f"Error deleting directory: {str(e)}"}

        return {"success": True, "message": f"Successfully deleted directory '{folder_name}'."}

directories_mgr = DirectoriesManager()
