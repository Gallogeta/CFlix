import os
import shutil
import urllib.request
import urllib.parse
import json
from typing import List, Dict, Any, Optional

from config import (
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir, get_watch_dir,
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

def format_bytes(b: int) -> str:
    """Formats bytes into human readable format (GB, TB, etc.)."""
    if b < 1024:
        return f"{b} B"
    kb = b / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    if gb < 1024:
        return f"{gb:.1f} GB"
    tb = gb / 1024
    return f"{tb:.2f} TB"

class DirectoriesManager:
    def __init__(self):
        pass

    @property
    def media_roots(self) -> List[str]:
        """Discovers all available media root paths and mounted disks (e.g. /mnt/media_ssd, /mnt/media_ssd2)."""
        roots = set()
        for p in [get_movies_dir(), get_series_dir(), get_anime_dir(), get_adult_dir()]:
            if p and os.path.exists(p):
                curr = os.path.abspath(p)
                while curr != "/" and not os.path.ismount(curr):
                    curr = os.path.dirname(curr)
                if curr not in SYSTEM_ROOTS and os.path.exists(curr):
                    roots.add(curr)
                else:
                    norm = os.path.normpath(p)
                    parent = os.path.dirname(norm)
                    if parent and parent not in SYSTEM_ROOTS and os.path.exists(parent):
                        roots.add(parent)
        
        cfg_root = os.path.normpath(cfg.get("MEDIA_ROOT", "/media"))
        if os.path.exists(cfg_root) and cfg_root not in SYSTEM_ROOTS:
            roots.add(cfg_root)

        # Scan /mnt and /media for external SSDs and storage drives
        for base_mount in ["/mnt", "/media", cfg.get("MEDIA_ROOT", "/media")]:
            if base_mount and os.path.exists(base_mount) and os.path.isdir(base_mount):
                try:
                    for entry in sorted(os.listdir(base_mount)):
                        if entry.startswith(".") or entry.lower() in PROTECTED_NAMES:
                            continue
                        full_p = os.path.join(base_mount, entry)
                        if os.path.isdir(full_p) and any(kw in entry.lower() for kw in ["media", "ssd", "disk", "drive", "hdd", "storage", "kingston"]):
                            # Must be a mount point or contain media folders
                            if os.path.ismount(full_p) or any(os.path.exists(os.path.join(full_p, sub)) for sub in ["jellyfin", "movies", "Anime", "Adult", "jellyfin_series"]):
                                roots.add(os.path.normpath(full_p))
                except Exception:
                    pass

        valid_roots = [r for r in sorted(list(roots)) if os.path.exists(r) and os.path.isdir(r)]
        return valid_roots if valid_roots else [cfg_root]

    def get_storage_summary(self) -> Dict[str, Any]:
        """Calculates total media storage capacity and per-disk breakdown across all media disks."""
        candidate_paths = set()
        for r in self.media_roots:
            candidate_paths.add(r)

        for p in [get_movies_dir(), get_series_dir(), get_anime_dir(), get_adult_dir(), cfg.get("MEDIA_ROOT")]:
            if p and os.path.exists(p):
                candidate_paths.add(p)

        disks_by_dev = {}
        for p in candidate_paths:
            if not os.path.exists(p):
                continue
            try:
                st = os.stat(p)
                dev = st.st_dev
                if dev in disks_by_dev:
                    continue

                curr = os.path.abspath(p)
                while curr != "/" and not os.path.ismount(curr):
                    curr = os.path.dirname(curr)

                total, used, free = shutil.disk_usage(p)
                basename = os.path.basename(curr.rstrip("/")) or "root"
                disks_by_dev[dev] = {
                    "dev": dev,
                    "mount": curr,
                    "name": basename,
                    "is_root": curr in ("/", "/mnt"),
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "total_human": format_bytes(total),
                    "used_human": format_bytes(used),
                    "free_human": format_bytes(free),
                    "used_pct": round((used / total * 100), 1) if total > 0 else 0,
                    "free_pct": round((free / total * 100), 1) if total > 0 else 0,
                    "free_gb": round(free / (1024**3), 1),
                    "total_gb": round(total / (1024**3), 1),
                    "used_gb": round(used / (1024**3), 1)
                }
            except Exception as e:
                emit_log(f"Notice: Error inspecting disk for path '{p}': {e}")

        non_root_disks = [d for d in disks_by_dev.values() if not d["is_root"]]
        target_disks = non_root_disks if non_root_disks else list(disks_by_dev.values())
        target_disks.sort(key=lambda x: x["mount"])

        total_bytes = sum(d["total_bytes"] for d in target_disks)
        used_bytes = sum(d["used_bytes"] for d in target_disks)
        free_bytes = sum(d["free_bytes"] for d in target_disks)

        return {
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "total_human": format_bytes(total_bytes),
            "used_human": format_bytes(used_bytes),
            "free_human": format_bytes(free_bytes),
            "used_pct": round((used_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
            "free_pct": round((free_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0,
            "total_gb": round(total_bytes / (1024**3), 1),
            "free_gb": round(free_bytes / (1024**3), 1),
            "disk_count": len(target_disks),
            "disks": target_disks
        }

    def auto_detect_correct_paths(self, apply_changes: bool = False) -> Dict[str, Any]:
        """Scans host filesystem and Jellyfin virtual folders to detect active media libraries and fix broken/default paths."""
        detected = {}
        changes = {}
        reasons = []

        current_paths = {
            "MOVIES_DIR": get_movies_dir(),
            "SERIES_DIR": get_series_dir(),
            "ANIME_DIR": get_anime_dir(),
            "ADULT_DIR": get_adult_dir(),
            "WATCH_DIR": get_watch_dir(),
            "MEDIA_ROOT": cfg.get("MEDIA_ROOT")
        }

        # 1. Query Jellyfin VirtualFolders
        jf_vfs = self.get_jellyfin_virtual_folders()
        jf_movies_paths = []
        jf_series_paths = []
        jf_anime_paths = []

        for vf in jf_vfs:
            name = vf.get("Name", "").lower()
            ctype = vf.get("CollectionType", "").lower()
            locs = vf.get("Locations", [])
            for loc in locs:
                candidate_locs = [loc]
                if loc.startswith("/data2/"):
                    candidate_locs.append(loc.replace("/data2/", "/mnt/media_ssd2/"))
                elif loc.startswith("/data/"):
                    candidate_locs.append(loc.replace("/data/", "/mnt/media_ssd/"))
                
                folder_sub = os.path.basename(loc.rstrip("/"))
                for r in self.media_roots:
                    candidate_locs.append(os.path.join(r, folder_sub))

                for c in candidate_locs:
                    if os.path.exists(c) and os.path.isdir(c):
                        if "anime" in name:
                            jf_anime_paths.append(c)
                        elif ctype == "tvshows" or "show" in name or "series" in name:
                            jf_series_paths.append(c)
                        elif ctype == "movies" or "movie" in name or "film" in name:
                            jf_movies_paths.append(c)

        # 2. Candidate pool for each category
        # --- MOVIES_DIR ---
        movie_candidates = []
        curr_m = current_paths["MOVIES_DIR"]
        if curr_m and os.path.exists(curr_m) and curr_m not in ["/media/movies", "/media", "/movies"]:
            movie_candidates.append(curr_m)
        movie_candidates.extend(jf_movies_paths)
        for r in self.media_roots:
            for sub in ["jellyfin", "movies", "Movies", "Filmid", "Eesti filmid"]:
                p = os.path.join(r, sub)
                if os.path.exists(p) and os.path.isdir(p):
                    movie_candidates.append(p)

        best_movies = None
        max_movie_items = -1
        for p in movie_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                cnt = count_media_items(p, "movies")
                if cnt > max_movie_items:
                    max_movie_items = cnt
                    best_movies = p
        if not best_movies and movie_candidates:
            best_movies = movie_candidates[0]
        detected["MOVIES_DIR"] = best_movies or current_paths["MOVIES_DIR"] or "/mnt/media_ssd/jellyfin"

        # --- SERIES_DIR ---
        series_candidates = []
        curr_s = current_paths["SERIES_DIR"]
        if curr_s and os.path.exists(curr_s) and curr_s not in ["/media/tv", "/media/series", "/media", "/tv"]:
            series_candidates.append(curr_s)
        series_candidates.extend(jf_series_paths)
        for r in self.media_roots:
            for sub in ["jellyfin_series", "series", "Series", "TV", "tv", "Shows"]:
                p = os.path.join(r, sub)
                if os.path.exists(p) and os.path.isdir(p):
                    series_candidates.append(p)

        best_series = None
        max_series_items = -1
        for p in series_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                cnt = count_media_items(p, "series")
                if cnt > max_series_items:
                    max_series_items = cnt
                    best_series = p
        if not best_series and series_candidates:
            best_series = series_candidates[0]
        detected["SERIES_DIR"] = best_series or current_paths["SERIES_DIR"] or "/mnt/media_ssd/jellyfin_series"

        # --- ANIME_DIR ---
        anime_candidates = []
        curr_a = current_paths["ANIME_DIR"]
        if curr_a and os.path.exists(curr_a) and curr_a not in ["/media/anime", "/anime"]:
            anime_candidates.append(curr_a)
        anime_candidates.extend(jf_anime_paths)
        for r in self.media_roots:
            for sub in ["Anime", "anime"]:
                p = os.path.join(r, sub)
                if os.path.exists(p) and os.path.isdir(p):
                    anime_candidates.append(p)

        best_anime = None
        for p in anime_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                best_anime = p
                break
        detected["ANIME_DIR"] = best_anime or current_paths["ANIME_DIR"] or "/mnt/media_ssd/Anime"

        # --- ADULT_DIR ---
        adult_candidates = []
        curr_ad = current_paths["ADULT_DIR"]
        if curr_ad and os.path.exists(curr_ad) and curr_ad not in ["/media/adult", "/adult"]:
            adult_candidates.append(curr_ad)
        for r in self.media_roots:
            for sub in ["Adult", "adult", "xxx", "XXX"]:
                p = os.path.join(r, sub)
                if os.path.exists(p) and os.path.isdir(p):
                    adult_candidates.append(p)
        detected["ADULT_DIR"] = adult_candidates[0] if adult_candidates else (current_paths["ADULT_DIR"] or "/mnt/media_ssd/Adult")

        # --- WATCH_DIR ---
        watch_candidates = []
        curr_w = current_paths["WATCH_DIR"]
        if curr_w and os.path.exists(curr_w) and curr_w not in ["/downloads", "/media/downloads"]:
            watch_candidates.append(curr_w)
        for p in ["/home/gallo/dwhelper", "/home/gallo/Downloads", "/downloads", "/var/downloads"]:
            if os.path.exists(p) and os.path.isdir(p):
                watch_candidates.append(p)
        detected["WATCH_DIR"] = watch_candidates[0] if watch_candidates else (current_paths["WATCH_DIR"] or "/home/gallo/dwhelper")

        # --- MEDIA_ROOT ---
        if self.media_roots:
            detected["MEDIA_ROOT"] = self.media_roots[0]
        else:
            detected["MEDIA_ROOT"] = "/mnt/media_ssd"

        # Track differences
        for k, new_v in detected.items():
            old_v = current_paths.get(k)
            if old_v != new_v:
                changes[k] = {"old": old_v, "new": new_v}
                reasons.append(f"Updated {k} from '{old_v}' to '{new_v}'")

        if apply_changes and changes:
            to_update = {k: v["new"] for k, v in changes.items()}
            cfg.update(to_update)
            emit_log(f"Auto-fixed {len(changes)} media storage paths: {', '.join(changes.keys())}")

        return {
            "success": True,
            "detected_paths": detected,
            "previous_paths": current_paths,
            "changes_count": len(changes),
            "changes": changes,
            "reasons": reasons,
            "applied": apply_changes
        }

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
