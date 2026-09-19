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

IGNORE_DIRS = {
    "lost+found", "transcode", ".trash-1000", ".tmp_uploads", ".staging",
    "kavita", "manga", "boost", "books", "comics", "config", "collections"
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
        """Returns unified list of active media libraries registered in Jellyfin.
        Merges multi-drive locations (e.g. SSD1 and SSD2) into a single clean library entry.
        Filters out non-media directories (kavita, manga, boost, books, comics, etc.).
        """
        # Fetch live Jellyfin VirtualFolders
        jf_vfs = self.get_jellyfin_virtual_folders()

        lib_configs = [
            {
                "id": "movies",
                "name": "Movies",
                "display_name": "Movies",
                "type": "movies",
                "icon": "🎬",
                "default_paths": [get_movies_dir() or "/mnt/media_ssd/jellyfin", "/mnt/media_ssd2/movies"]
            },
            {
                "id": "series",
                "name": "Shows",
                "display_name": "TV Series",
                "type": "series",
                "icon": "📺",
                "default_paths": [get_series_dir() or "/mnt/media_ssd/jellyfin_series", "/mnt/media_ssd2/jellyfin_series"]
            },
            {
                "id": "anime",
                "name": "Anime",
                "display_name": "Anime",
                "type": "series",
                "icon": "⛩️",
                "default_paths": [get_anime_dir() or "/mnt/media_ssd/Anime", "/mnt/media_ssd2/Anime"]
            },
            {
                "id": "adult",
                "name": "Adult",
                "display_name": "Adult",
                "type": "adult",
                "icon": "🔞",
                "default_paths": [get_adult_dir() or "/mnt/media_ssd/Adult", "/mnt/media_ssd2/Adult"]
            },
            {
                "id": "children",
                "name": "Children",
                "display_name": "Children",
                "type": "movies",
                "icon": "🧸",
                "default_paths": ["/mnt/media_ssd/Children", "/mnt/media_ssd2/Children"]
            },
            {
                "id": "eesti_filmid",
                "name": "Eesti filmid",
                "display_name": "Eesti filmid",
                "type": "movies",
                "icon": "🇪🇪",
                "default_paths": ["/mnt/media_ssd/Eesti filmid", "/mnt/media_ssd2/Eesti filmid"]
            }
        ]

        # Discover any custom VirtualFolder in Jellyfin not already covered
        jf_extra = []
        for vf in jf_vfs:
            name = vf.get("Name", "").strip()
            ctype = (vf.get("CollectionType") or "").lower()
            if not name or ctype in ("boxsets", "books", "photos", "music") or name.lower() in IGNORE_DIRS:
                continue
            if any(name.lower() in (lc["name"].lower(), lc["display_name"].lower(), lc["id"]) for lc in lib_configs):
                continue
            jf_extra.append({
                "id": name.lower().replace(" ", "_"),
                "name": name,
                "display_name": name,
                "type": "series" if ctype == "tvshows" else "movies",
                "icon": "🎬",
                "default_paths": [os.path.join(r, name) for r in self.media_roots]
            })

        all_libs = lib_configs + jf_extra
        results = []

        for lib in all_libs:
            locations = []
            total_items = 0
            seen_locs = set()

            for p in lib["default_paths"]:
                norm_p = os.path.normpath(p)
                if norm_p in seen_locs:
                    continue
                seen_locs.add(norm_p)
                exists = os.path.exists(norm_p) and os.path.isdir(norm_p)
                items = count_media_items(norm_p, lib["type"]) if exists else 0
                total_items += items

                free_gb = 0
                free_human = "0 GB"
                mount = norm_p
                if exists:
                    try:
                        curr = os.path.abspath(norm_p)
                        while curr != "/" and not os.path.ismount(curr):
                            curr = os.path.dirname(curr)
                        mount = curr
                        t, u, f = shutil.disk_usage(norm_p)
                        free_gb = round(f / (1024**3), 1)
                        free_human = format_bytes(f)
                    except Exception:
                        pass

                locations.append({
                    "path": norm_p,
                    "exists": exists,
                    "items": items,
                    "mount": mount,
                    "disk_name": os.path.basename(mount.rstrip("/")) or "media",
                    "free_gb": free_gb,
                    "free_human": free_human
                })

            existing_locs = [l for l in locations if l["exists"]]
            if not existing_locs and lib["id"] not in ("movies", "series", "anime", "adult"):
                continue

            primary_loc = existing_locs[0]["path"] if existing_locs else locations[0]["path"]
            multi_drive = len(existing_locs) > 1

            results.append({
                "id": lib["id"],
                "name": lib["name"],
                "display_name": lib["display_name"],
                "type": lib["type"],
                "icon": lib["icon"],
                "path": primary_loc,
                "parent_path": os.path.dirname(primary_loc),
                "item_count": total_items,
                "in_jellyfin": True,
                "multi_drive": multi_drive,
                "locations": locations,
                "deletable": False
            })

        return results

    def smart_allocate_path(self, category_or_library: str, required_bytes: int = 0, title: Optional[str] = None) -> str:
        """Dynamically chooses optimal destination storage directory across all available SSDs.
        If primary SSD space is low or full, automatically overflows to the expansion SSD.
        If title belongs to an existing series, keeps episodes together if space permits.
        """
        lib_key = (category_or_library or "").lower().strip()

        # Prioritize explicit library matching without substring collision
        if any(w in lib_key for w in ["jellyfin_series", "series", "show", "tv"]):
            candidates = [get_series_dir() or "/mnt/media_ssd/jellyfin_series", "/mnt/media_ssd2/jellyfin_series"]
        elif "anime" in lib_key:
            candidates = [get_anime_dir() or "/mnt/media_ssd/Anime", "/mnt/media_ssd2/Anime"]
        elif "adult" in lib_key:
            candidates = [get_adult_dir() or "/mnt/media_ssd/Adult", "/mnt/media_ssd2/Adult"]
        elif "children" in lib_key:
            candidates = ["/mnt/media_ssd/Children", "/mnt/media_ssd2/Children"]
        elif "eesti" in lib_key:
            candidates = ["/mnt/media_ssd/Eesti filmid", "/mnt/media_ssd2/Eesti filmid"]
        elif any(w in lib_key for w in ["movie", "film"]) or lib_key.rstrip("/").endswith("/jellyfin") or lib_key == "jellyfin":
            candidates = [get_movies_dir() or "/mnt/media_ssd/jellyfin", "/mnt/media_ssd2/movies"]
        elif os.path.isabs(category_or_library) and os.path.exists(category_or_library):
            if "/mnt/media_ssd2" in category_or_library:
                return category_or_library
            basename = os.path.basename(category_or_library.rstrip("/"))
            candidates = [category_or_library, f"/mnt/media_ssd2/{basename}"]
        else:
            candidates = [get_movies_dir() or "/mnt/media_ssd/jellyfin", "/mnt/media_ssd2/movies"]

        primary_path = candidates[0]
        expansion_path = candidates[1] if len(candidates) > 1 else primary_path

        # 1. Check if series/anime already exists on one of the drives
        if title:
            clean_t = "".join(c for c in title if c not in r'\/*?:"<>|').strip()
            prim_show = os.path.join(primary_path, clean_t)
            exp_show = os.path.join(expansion_path, clean_t)
            if os.path.exists(prim_show):
                try:
                    _, _, free_b = shutil.disk_usage(primary_path)
                    if free_b >= required_bytes + (2 * 1024 * 1024 * 1024):
                        return primary_path
                except Exception:
                    pass
            elif os.path.exists(exp_show):
                try:
                    _, _, free_b = shutil.disk_usage(expansion_path)
                    if free_b >= required_bytes + (2 * 1024 * 1024 * 1024):
                        return expansion_path
                except Exception:
                    pass

        # 2. Check auto-overflow settings & primary drive capacity
        overflow_enabled = cfg.get("AUTO_OVERFLOW_ENABLED", True)
        if overflow_enabled and len(candidates) > 1:
            overflow_min_gb = float(cfg.get("AUTO_OVERFLOW_MIN_GB", 50))
            overflow_min_bytes = int(overflow_min_gb * (1024**3))
            try:
                check_path = primary_path
                while not os.path.exists(check_path) and os.path.dirname(check_path) != check_path:
                    check_path = os.path.dirname(check_path)
                if not os.path.exists(check_path):
                    check_path = "/"

                total_b, used_b, free_b = shutil.disk_usage(check_path)
                used_pct = (used_b / total_b * 100) if total_b > 0 else 100
                is_full = (
                    free_b <= overflow_min_bytes
                    or used_pct >= 95.0
                    or free_b < (required_bytes + (5 * 1024 * 1024 * 1024))
                )
                if is_full:
                    try:
                        os.makedirs(expansion_path, exist_ok=True)
                    except Exception as me:
                        emit_log(f"Notice creating expansion dir: {me}")
                    free_gb = free_b / (1024**3)
                    emit_log(
                        f"[Smart Storage] Primary SSD space low ({free_gb:.1f} GB left / threshold {overflow_min_gb:.0f} GB). "
                        f"Auto-allocating upload to expansion SSD: '{expansion_path}'"
                    )
                    return expansion_path
            except Exception as e:
                emit_log(f"Notice in smart storage check: {e}")

        try:
            os.makedirs(primary_path, exist_ok=True)
        except Exception as me:
            emit_log(f"Notice creating primary dir: {me}")
        return primary_path

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
