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
    "lost+found", "transcode", ".trash-1000", ".tmp_uploads", ".staging"
}

MEDIA_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".iso", ".ts"}

def count_media_items(dir_path: str, content_type: str = "movies") -> int:
    """Accurately counts video titles and shows instead of raw files (ignoring metadata, posters, fanarts, subtitles, trickplay)."""
    if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
        return 0
    try:
        entries = [
            e for e in os.listdir(dir_path)
            if not e.startswith(".")
            and not e.endswith(".trickplay")
            and e.lower() not in PROTECTED_NAMES
        ]
        if content_type == "series":
            subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
            return len(subdirs) if subdirs else len([e for e in entries if os.path.splitext(e)[1].lower() in MEDIA_VIDEO_EXTS])
        
        video_files = [e for e in entries if not os.path.isdir(os.path.join(dir_path, e)) and os.path.splitext(e)[1].lower() in MEDIA_VIDEO_EXTS]
        subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
        return len(video_files) + len(subdirs)
    except Exception:
        return 0

SYSTEM_ROOTS = {"/", "/media", "/mnt", "/home", "/etc", "/var", "/usr", "/bin", "/tmp"}

class DirectoriesManager:
    def __init__(self):
        pass

    @property
    def media_roots(self) -> List[str]:
        """Discovers all available media root paths and mounted disks (e.g. /mnt/media_ssd, /media, /media/disk1)."""
        roots = set()
        for p in [get_movies_dir(), get_series_dir(), get_anime_dir(), get_adult_dir()]:
            if p:
                norm = os.path.normpath(p)
                parent = os.path.dirname(norm)
                if parent and parent not in SYSTEM_ROOTS and os.path.exists(parent):
                    roots.add(parent)
        
        cfg_root = os.path.normpath(cfg.get("MEDIA_ROOT", "/media"))
        if os.path.exists(cfg_root) and cfg_root not in SYSTEM_ROOTS:
            roots.add(cfg_root)

        # Scan both /mnt and configured MEDIA_ROOT for external SSDs and storage drives
        for base_mount in ["/mnt", cfg.get("MEDIA_ROOT", "/media")]:
            if base_mount and os.path.exists(base_mount) and os.path.isdir(base_mount):
                try:
                    for entry in sorted(os.listdir(base_mount)):
                        if entry.startswith(".") or entry.lower() in PROTECTED_NAMES:
                            continue
                        full_p = os.path.join(base_mount, entry)
                        if os.path.isdir(full_p) and any(kw in entry.lower() for kw in ["media", "ssd", "disk", "drive", "hdd", "storage"]):
                            roots.add(os.path.normpath(full_p))
                except Exception:
                    pass

        valid_roots = [r for r in sorted(list(roots)) if os.path.exists(r) and os.path.isdir(r)]
        return valid_roots if valid_roots else [cfg_root]

    @property
    def media_root(self) -> str:
        roots = self.media_roots
        return roots[0] if roots else cfg.get("MEDIA_ROOT", "/media")

    def get_available_parent_locations(self) -> List[Dict[str, str]]:
        """Returns list of selectable parent directories for creating new libraries/folders."""
        locations = []
        for r in self.media_roots:
            basename = os.path.basename(r)
            display = f"{basename} ({r})" if basename else r
            locations.append({"path": r, "name": display})
        return locations

    def get_jellyfin_token(self) -> Optional[str]:
        auth = cfg.test_jellyfin(get_jellyfin_url(), get_jellyfin_user(), get_jellyfin_pass())
        return auth.get("token") if auth.get("success") else None

    def get_jellyfin_virtual_folders(self) -> List[Dict[str, Any]]:
        token = self.get_jellyfin_token()
        if not token or not get_jellyfin_url():
            return []
        
        url = f"{get_jellyfin_url()}/Library/VirtualFolders"
        auth_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": auth_val,
                "X-Emby-Authorization": auth_val,
                "X-MediaBrowser-Token": token,
                "X-Emby-Token": token,
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
        results = []
        seen_paths = set()
        
        # 1. Fetch live media server virtual folders
        jf_vfs = self.get_jellyfin_virtual_folders()
        jf_map = {}
        for vf in jf_vfs:
            name = vf.get("Name", "")
            ctype = vf.get("CollectionType", "movies")
            locs = vf.get("Locations", [])
            for loc in locs:
                folder_basename = os.path.basename(loc.rstrip("/"))
                norm_loc = os.path.normpath(loc)
                jf_map[norm_loc.lower()] = {
                    "jf_name": name,
                    "collection_type": ctype,
                    "internal_location": loc
                }
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

        for d in defaults:
            p = d["path"]
            if not p:
                continue
            norm_p = os.path.normpath(p)
            name = os.path.basename(norm_p)
            if not name or norm_p in seen_paths:
                continue
            seen_paths.add(norm_p)
            
            exists = os.path.exists(norm_p)
            item_count = count_media_items(norm_p, d["type"]) if exists else 0

            jf_info = jf_map.get(norm_p.lower()) or jf_map.get(name.lower(), {})
            
            results.append({
                "name": name,
                "display_name": jf_info.get("jf_name") or d["display_name"],
                "path": norm_p,
                "parent_path": os.path.dirname(norm_p),
                "type": d["type"],
                "exists": exists,
                "item_count": item_count,
                "in_jellyfin": bool(jf_info),
                "deletable": norm_p not in self.media_roots and norm_p not in SYSTEM_ROOTS and name.lower() not in PROTECTED_NAMES
            })

        # 3. Discover any subdirectories in all media roots
        for root in self.media_roots:
            if os.path.exists(root) and os.path.isdir(root):
                try:
                    for entry in sorted(os.listdir(root)):
                        if entry.startswith(".") or entry.lower() in PROTECTED_NAMES:
                            continue
                        full_p = os.path.normpath(os.path.join(root, entry))
                        if os.path.isdir(full_p) and full_p not in seen_paths and full_p not in self.media_roots:
                            seen_paths.add(full_p)
                            jf_info = jf_map.get(full_p.lower()) or jf_map.get(entry.lower(), {})
                            c_type = "series" if jf_info.get("collection_type") == "tvshows" else ("adult" if "adult" in entry.lower() else "movies")
                            item_count = count_media_items(full_p, c_type)

                            results.append({
                                "name": entry,
                                "display_name": jf_info.get("jf_name") or entry,
                                "path": full_p,
                                "parent_path": root,
                                "type": c_type,
                                "exists": True,
                                "item_count": item_count,
                                "in_jellyfin": bool(jf_info),
                                "deletable": full_p not in self.media_roots and full_p not in SYSTEM_ROOTS and entry.lower() not in PROTECTED_NAMES
                            })
                except Exception as e:
                    emit_log(f"Error inspecting media root '{root}': {e}")

        return results

    def create_directory(self, folder_name: str, content_type: str = "movies", add_to_jellyfin: bool = True, parent_path: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new filesystem directory in the chosen parent disk/root and optionally links it to Jellyfin."""
        folder_name = folder_name.strip().strip("/\\")
        if not folder_name or any(c in folder_name for c in [":", "..", "*", "?", "<", ">", "|"]):
            return {"success": False, "error": "Invalid directory name. Special characters are not allowed."}

        # Resolve parent base
        base = self.media_root
        if parent_path and os.path.exists(parent_path) and os.path.isdir(parent_path):
            base = os.path.normpath(parent_path)

        target_path = os.path.normpath(os.path.join(base, folder_name))
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
                rel_from_base = os.path.relpath(target_path, cfg.get("MEDIA_ROOT", "/media"))
                if not rel_from_base.startswith(".."):
                    jf_container_path = f"{media_path_prefix.rstrip('/')}/{rel_from_base}"
                else:
                    jf_container_path = target_path

                jf_collection_type = "tvshows" if content_type == "series" else "movies"
                
                url = (
                    f"{get_jellyfin_url()}/Library/VirtualFolders?"
                    f"name={urllib.parse.quote(folder_name)}&"
                    f"collectionType={jf_collection_type}&"
                    f"paths={urllib.parse.quote(jf_container_path)}&"
                    f"refreshLibrary=true"
                )
                auth_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
                headers = {
                    "Authorization": auth_val,
                    "X-Emby-Authorization": auth_val,
                    "X-MediaBrowser-Token": token,
                    "X-Emby-Token": token,
                    "User-Agent": "CFlixMediaManager/1.0"
                }
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
            "parent_path": base,
            "type": content_type,
            "in_jellyfin": add_to_jellyfin
        }

    def delete_directory(self, folder_name: str, remove_from_jellyfin: bool = True, force: bool = False, path: Optional[str] = None) -> Dict[str, Any]:
        """Deletes a directory from filesystem and unlinks it from Jellyfin."""
        folder_name = folder_name.strip()
        
        # Locate target path
        target_path = None
        if path and os.path.exists(path):
            target_path = os.path.normpath(path)
        else:
            # Match from list
            all_dirs = self.list_all_directories()
            for d in all_dirs:
                if d["name"].lower() == folder_name.lower() or d["path"].lower() == folder_name.lower():
                    target_path = d["path"]
                    folder_name = d["name"]
                    break
            if not target_path:
                target_path = os.path.normpath(os.path.join(self.media_root, folder_name))

        # Security check: never delete system roots or storage roots
        if target_path in SYSTEM_ROOTS or target_path in self.media_roots:
            return {"success": False, "error": f"Cannot delete core root filesystem path '{target_path}'."}

        base_name = os.path.basename(target_path)
        if base_name.lower() in PROTECTED_NAMES:
            return {"success": False, "error": f"Cannot delete core protected directory '{base_name}'."}

        # 1. Remove from media server if requested
        if remove_from_jellyfin and get_jellyfin_url():
            token = self.get_jellyfin_token()
            if token:
                url = f"{get_jellyfin_url()}/Library/VirtualFolders?name={urllib.parse.quote(folder_name)}&refreshLibrary=true"
                auth_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
                headers = {
                    "Authorization": auth_val,
                    "X-Emby-Authorization": auth_val,
                    "X-MediaBrowser-Token": token,
                    "X-Emby-Token": token,
                    "User-Agent": "CFlixMediaManager/1.0"
                }
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
                        "error": f"Directory '{base_name}' is not empty ({len(entries)} items). Confirm to force delete all contents.",
                        "requires_force": True
                    }
                
                if force:
                    shutil.rmtree(target_path)
                else:
                    os.rmdir(target_path)
                emit_log(f"Deleted directory '{target_path}' from media storage.")
            except Exception as e:
                emit_log(f"Error removing directory '{target_path}': {e}")
                return {"success": False, "error": f"Error deleting directory: {str(e)}"}

        return {"success": True, "message": f"Successfully deleted directory '{base_name}'."}

directories_mgr = DirectoriesManager()
