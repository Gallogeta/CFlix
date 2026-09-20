import os
import shutil
import urllib.request
import urllib.parse
import json
from typing import List, Dict, Any, Optional

from config import (
    get_movies_dir, get_series_dir, get_anime_dir, get_adult_dir, get_watch_dir,
    get_media_root, get_media_roots, get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass, cfg
)
from logger import emit_log

PROTECTED_NAMES = {
    "immich_data", "immich_fast", "immich", "hdd_test",
    "lost+found", "transcode", ".trash-1000", ".tmp_uploads", ".staging"
}

IGNORE_DIRS = {
    "immich_data", "immich_fast", "immich", "hdd_test",
    "lost+found", "transcode", ".trash-1000", ".tmp_uploads", ".staging",
    "kavita", "manga", "boost", "books", "comics", "config", "collections"
}

SYSTEM_ROOTS = {"/", "/media", "/mnt", "/home", "/etc", "/var", "/usr", "/bin", "/tmp"}

MEDIA_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".iso", ".ts"}

def is_excluded_path(path_or_name: str) -> bool:
    """Strict exclusion check. Ensures system directories and unlinked drives (e.g. Immich cold storage) are never touched."""
    if not path_or_name:
        return True
    norm = os.path.normpath(str(path_or_name))
    base = os.path.basename(norm).lower()
    full = norm.lower()

    # Strictly preserve cold-storage Immich HDD safety
    if "immich" in base or "immich" in full:
        return True
    if base in PROTECTED_NAMES:
        return True
    if base.startswith(".") or base.startswith("@"):
        return True
    if norm in SYSTEM_ROOTS:
        return True
    if any(full.startswith(sys_p) for sys_p in ["/proc", "/sys", "/dev", "/boot", "/etc", "/var/lib/docker", "/snap"]):
        return True
    return False

def count_media_items(dir_path: str, content_type: str = "movies") -> int:
    """Accurately counts video titles and shows instead of raw files (ignoring metadata, posters, fanarts, subtitles, trickplay)."""
    if not os.path.exists(dir_path) or not os.path.isdir(dir_path) or is_excluded_path(dir_path):
        return 0
    try:
        entries = [
            e for e in os.listdir(dir_path)
            if not e.startswith(".")
            and not e.endswith(".trickplay")
            and not is_excluded_path(e)
        ]
        if content_type == "series":
            subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
            return len(subdirs) if subdirs else len([e for e in entries if os.path.splitext(e)[1].lower() in MEDIA_VIDEO_EXTS])
        
        video_files = [e for e in entries if not os.path.isdir(os.path.join(dir_path, e)) and os.path.splitext(e)[1].lower() in MEDIA_VIDEO_EXTS]
        subdirs = [e for e in entries if os.path.isdir(os.path.join(dir_path, e))]
        return len(video_files) + len(subdirs)
    except Exception:
        return 0

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
        """Discovers all available media root paths and mounted disks across the system (SSDs and HDDs)."""
        roots = set()

        # 1. Explicitly configured MEDIA_ROOTS in settings/env (comma-separated list or array)
        for r in get_media_roots():
            if r and not is_excluded_path(r) and os.path.exists(r) and os.path.isdir(r):
                roots.add(os.path.normpath(r))

        # 2. Configured primary MEDIA_ROOT
        cfg_root = cfg.get("MEDIA_ROOT", "/media")
        if cfg_root and not is_excluded_path(cfg_root) and os.path.exists(cfg_root) and os.path.isdir(cfg_root):
            roots.add(os.path.normpath(cfg_root))

        # 3. Mounts of configured primary directories (movies, series, anime, adult)
        for p in [get_movies_dir(), get_series_dir(), get_anime_dir(), get_adult_dir()]:
            if p and os.path.exists(p) and not is_excluded_path(p):
                curr = os.path.abspath(p)
                while curr != "/" and not os.path.ismount(curr):
                    curr = os.path.dirname(curr)
                if curr not in SYSTEM_ROOTS and os.path.exists(curr) and not is_excluded_path(curr):
                    roots.add(curr)
                else:
                    parent = os.path.dirname(os.path.normpath(p))
                    if parent and parent not in SYSTEM_ROOTS and os.path.exists(parent) and not is_excluded_path(parent):
                        roots.add(parent)

        # 4. Storage drives discovered in /mnt and /media (SSDs, HDDs, expansion pools)
        for base_mount in ["/mnt", "/media"]:
            if base_mount and os.path.exists(base_mount) and os.path.isdir(base_mount):
                try:
                    for entry in sorted(os.listdir(base_mount)):
                        full_p = os.path.normpath(os.path.join(base_mount, entry))
                        if is_excluded_path(full_p):
                            continue
                        if not os.path.isdir(full_p):
                            continue
                        # Valid media drive if it is an active mount point or contains media folders
                        is_mount = os.path.ismount(full_p)
                        has_media = any(
                            os.path.exists(os.path.join(full_p, sub))
                            for sub in [
                                "jellyfin", "movies", "Movies", "jellyfin_series",
                                "Shows", "shows", "Anime", "Adult", "Children",
                                "Eesti filmid", "Filmid"
                            ]
                        )
                        if is_mount or has_media:
                            roots.add(full_p)
                except Exception:
                    pass

        valid_roots = [r for r in sorted(list(roots)) if os.path.exists(r) and os.path.isdir(r) and not is_excluded_path(r)]
        return valid_roots if valid_roots else [os.path.normpath(cfg.get("MEDIA_ROOT", "/media"))]

    def get_storage_summary(self) -> Dict[str, Any]:
        """Calculates total media storage capacity and per-disk breakdown across all connected media drives."""
        candidate_paths = set()
        for r in self.media_roots:
            candidate_paths.add(r)

        for p in [get_movies_dir(), get_series_dir(), get_anime_dir(), get_adult_dir(), cfg.get("MEDIA_ROOT")]:
            if p and os.path.exists(p) and not is_excluded_path(p):
                candidate_paths.add(p)

        disks_by_dev = {}
        for p in candidate_paths:
            if not os.path.exists(p) or is_excluded_path(p):
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

    def translate_jellyfin_location_to_host(self, loc: str) -> List[str]:
        """Maps Jellyfin container paths (e.g. /data/..., /data2/..., /media/...) to host filesystem paths."""
        if not loc:
            return []
        resolved = []
        norm = os.path.normpath(loc)

        if os.path.exists(norm) and not is_excluded_path(norm):
            resolved.append(norm)

        sub_folder = os.path.basename(norm.rstrip("/\\"))
        roots = self.media_roots

        # Container volume prefix translations (/data -> root 0, /data2 -> root 1, /data3 -> root 2 ...)
        if norm.startswith("/data2") and len(roots) > 1:
            mapped = norm.replace("/data2", roots[1], 1)
            if os.path.exists(mapped) and not is_excluded_path(mapped):
                resolved.append(os.path.normpath(mapped))
        elif norm.startswith("/data") and len(roots) > 0:
            mapped = norm.replace("/data", roots[0], 1)
            if os.path.exists(mapped) and not is_excluded_path(mapped):
                resolved.append(os.path.normpath(mapped))

        # Check if matching folder exists directly on any discovered media root
        for r in roots:
            cand = os.path.join(r, sub_folder)
            if os.path.exists(cand) and not is_excluded_path(cand):
                resolved.append(os.path.normpath(cand))

        return list(dict.fromkeys(resolved))

    def get_candidate_paths_for_library(self, category_or_library: str) -> List[str]:
        """Returns all physical directory paths across all media storage drives for a given library or category."""
        cat = (category_or_library or "").strip()
        cat_lower = cat.lower()

        folder_names = []
        primary_dir = None

        if any(w in cat_lower for w in ["jellyfin_series", "series", "show", "tv"]):
            primary_dir = get_series_dir()
            folder_names = ["jellyfin_series", "Shows", "shows", "Series", "series", "tv", "TV"]
        elif "anime" in cat_lower:
            primary_dir = get_anime_dir()
            folder_names = ["Anime", "anime"]
        elif "adult" in cat_lower:
            primary_dir = get_adult_dir()
            folder_names = ["Adult", "adult"]
        elif "children" in cat_lower or "kids" in cat_lower:
            folder_names = ["Children", "children", "Kids", "kids"]
        elif "eesti" in cat_lower:
            folder_names = ["Eesti filmid", "eesti filmid"]
        elif any(w in cat_lower for w in ["movie", "film"]) or cat_lower.rstrip("/").endswith("/jellyfin") or cat_lower == "jellyfin":
            primary_dir = get_movies_dir()
            folder_names = ["jellyfin", "movies", "Movies", "filmid", "Films"]
        elif os.path.isabs(cat):
            base_folder = os.path.basename(cat.rstrip("/\\"))
            folder_names = [base_folder]
            primary_dir = cat
        else:
            folder_names = [cat]

        candidates = []
        seen = set()

        def add_candidate(p: str):
            if not p:
                return
            norm = os.path.normpath(p)
            if norm not in seen and not is_excluded_path(norm):
                seen.add(norm)
                candidates.append(norm)

        # 1. Configured primary path
        if primary_dir and not is_excluded_path(primary_dir):
            add_candidate(primary_dir)

        # 2. VirtualFolders from Jellyfin
        jf_vfs = self.get_jellyfin_virtual_folders()
        for vf in jf_vfs:
            vf_name = vf.get("Name", "").strip()
            vf_name_lower = vf_name.lower()

            match = False
            if cat_lower in (vf_name_lower, vf.get("ItemId", "").lower()):
                match = True
            elif any(fn.lower() == vf_name_lower for fn in folder_names):
                match = True
            elif cat_lower in ("movies", "movie") and vf_name_lower in ("movies", "filmid", "jellyfin"):
                match = True
            elif cat_lower in ("series", "show", "shows", "tv", "tvshows") and vf_name_lower in ("shows", "tv series", "series", "jellyfin_series"):
                match = True

            if match:
                for loc in vf.get("Locations", []):
                    for resolved_loc in self.translate_jellyfin_location_to_host(loc):
                        add_candidate(resolved_loc)

        # 3. Across ALL media roots (Root 1, Root 2, Root 3, ... Root N)
        roots = self.media_roots
        for r in roots:
            found_existing = False
            for fn in folder_names:
                p = os.path.join(r, fn)
                if os.path.exists(p) and os.path.isdir(p) and not is_excluded_path(p):
                    add_candidate(p)
                    found_existing = True
                    break

            if not found_existing:
                pref_folder = folder_names[0] if folder_names else "media"
                add_candidate(os.path.join(r, pref_folder))

        return candidates if candidates else [primary_dir or "/media"]

    def ensure_jellyfin_virtual_folder_path(self, category_or_library: str, host_path: str):
        """Ensures Jellyfin VirtualFolder includes the newly allocated path on expansion drives."""
        try:
            token = self.get_jellyfin_token()
            jf_url = get_jellyfin_url()
            if not token or not jf_url:
                return

            vfs = self.get_jellyfin_virtual_folders()
            matched_vf = None
            cat_clean = category_or_library.lower()

            for vf in vfs:
                name = vf.get("Name", "")
                ctype = (vf.get("CollectionType") or "").lower()
                locs = vf.get("Locations", [])

                # Already represented in Jellyfin locations
                for loc in locs:
                    trans = self.translate_jellyfin_location_to_host(loc)
                    if host_path in trans or os.path.normpath(host_path) == os.path.normpath(loc):
                        return

                if cat_clean in name.lower():
                    matched_vf = vf
                    break
                elif (ctype == "tvshows" and any(w in cat_clean for w in ["series", "show", "tv"])) or \
                     (ctype == "movies" and any(w in cat_clean for w in ["movie", "film"])):
                    matched_vf = vf
                    break

            if not matched_vf:
                return

            vf_name = matched_vf.get("Name")
            jf_path = host_path
            roots = self.media_roots

            # Container volume mapping
            if len(roots) > 1 and host_path.startswith(roots[1]):
                jf_path = host_path.replace(roots[1], "/data2", 1)
            elif len(roots) > 0 and host_path.startswith(roots[0]):
                jf_path = host_path.replace(roots[0], "/data", 1)

            url = (
                f"{jf_url}/Library/VirtualFolders/Paths?"
                f"name={urllib.parse.quote(vf_name)}&"
                f"path={urllib.parse.quote(jf_path)}&"
                f"refreshLibrary=true"
            )
            auth_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
            headers = {
                "Authorization": auth_val,
                "X-Emby-Authorization": auth_val,
                "X-MediaBrowser-Token": token,
                "User-Agent": "CFlixMediaManager/1.0"
            }
            req = urllib.request.Request(url, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=6) as res:
                emit_log(f"[Auto-Library] Linked storage location '{jf_path}' into Jellyfin library '{vf_name}'.")
        except Exception:
            pass

    def smart_allocate_path(self, category_or_library: str, required_bytes: int = 0, title: Optional[str] = None) -> str:
        """Dynamically chooses optimal destination storage directory across all available drives (SSDs and HDDs).
        - Series Affinity: If title belongs to an existing series, keeps episodes together on the same drive if space permits.
        - Multi-Drive Balancing: Checks all healthy candidate drives across all storage mounts, and selects the drive with the MOST FREE SPACE.
        - Auto-Overflow: If primary drive or existing show drive is low (< AUTO_OVERFLOW_MIN_GB or > 95% full), overflows to the drive with highest space.
        """
        candidates = self.get_candidate_paths_for_library(category_or_library)
        if not candidates:
            primary = get_movies_dir() or "/mnt/media_ssd/jellyfin"
            os.makedirs(primary, exist_ok=True)
            return primary

        if len(candidates) == 1:
            os.makedirs(candidates[0], exist_ok=True)
            return candidates[0]

        overflow_enabled = cfg.get("AUTO_OVERFLOW_ENABLED", True)
        overflow_min_gb = float(cfg.get("AUTO_OVERFLOW_MIN_GB", 50))
        overflow_min_bytes = int(overflow_min_gb * (1024**3))
        buffer_bytes = required_bytes + (5 * 1024 * 1024 * 1024)

        # 1. Series Affinity: Check if series folder already exists on any drive
        if title:
            clean_t = "".join(c for c in title if c not in r'\/*?:"<>|').strip()
            for cand in candidates:
                show_dir = os.path.join(cand, clean_t)
                if os.path.exists(show_dir) and os.path.isdir(show_dir):
                    try:
                        tot, used, free = shutil.disk_usage(cand)
                        used_pct = (used / tot * 100) if tot > 0 else 100
                        if free >= overflow_min_bytes and used_pct < 95.0 and free >= buffer_bytes:
                            emit_log(
                                f"[Smart Storage] Series '{clean_t}' exists on '{cand}' "
                                f"({free/(1024**3):.1f} GB free). Preserving show affinity on this drive."
                            )
                            return cand
                        else:
                            emit_log(
                                f"[Smart Storage] Series '{clean_t}' exists on '{cand}', but drive is low "
                                f"({free/(1024**3):.1f} GB free, {used_pct:.1f}% used). Auto-overflowing to balanced drive."
                            )
                    except Exception as e:
                        emit_log(f"Notice inspecting existing series disk '{cand}': {e}")

        # 2. Query disk stats across all candidate drives
        stats = []
        for cand in candidates:
            check_p = cand
            while not os.path.exists(check_p) and os.path.dirname(check_p) != check_p:
                check_p = os.path.dirname(check_p)
            try:
                tot, used, free = shutil.disk_usage(check_p)
                used_pct = (used / tot * 100) if tot > 0 else 100
                is_healthy = (free >= overflow_min_bytes and used_pct < 95.0 and free >= buffer_bytes)
                stats.append({
                    "path": cand,
                    "total": tot,
                    "used": used,
                    "free": free,
                    "used_pct": used_pct,
                    "free_gb": free / (1024**3),
                    "is_healthy": is_healthy
                })
            except Exception as e:
                emit_log(f"Notice inspecting candidate path '{cand}': {e}")

        if not stats:
            return candidates[0]

        # 3. Multi-Drive Balancing: Select drive with MOST FREE SPACE among healthy candidates
        healthy = [s for s in stats if s["is_healthy"]]
        if healthy:
            healthy.sort(key=lambda x: x["free"], reverse=True)
            chosen = healthy[0]
            emit_log(
                f"[Smart Storage] Multi-drive balanced: Selected drive with most free space '{chosen['path']}' "
                f"({chosen['free_gb']:.1f} GB free, {chosen['used_pct']:.1f}% used across {len(stats)} candidate drives)"
            )
            chosen_path = chosen["path"]
        else:
            # Best effort fallback
            stats.sort(key=lambda x: x["free"], reverse=True)
            chosen = stats[0]
            emit_log(
                f"[Smart Storage] All drives low on space. Selected best-effort drive '{chosen['path']}' "
                f"({chosen['free_gb']:.1f} GB free, {chosen['used_pct']:.1f}% used)"
            )
            chosen_path = chosen["path"]

        try:
            os.makedirs(chosen_path, exist_ok=True)
        except Exception as me:
            emit_log(f"Notice creating directory '{chosen_path}': {me}")

        self.ensure_jellyfin_virtual_folder_path(category_or_library, chosen_path)
        return chosen_path

    def list_all_directories(self) -> List[Dict[str, Any]]:
        """Returns unified list of active media libraries registered in Jellyfin.
        Merges multi-drive locations across all storage drives (SSDs and HDDs) into clean library entries.
        """
        jf_vfs = self.get_jellyfin_virtual_folders()

        lib_configs = [
            {
                "id": "movies",
                "name": "Movies",
                "display_name": "Movies",
                "type": "movies",
                "icon": "🎬"
            },
            {
                "id": "series",
                "name": "Shows",
                "display_name": "TV Series",
                "type": "series",
                "icon": "📺"
            },
            {
                "id": "anime",
                "name": "Anime",
                "display_name": "Anime",
                "type": "series",
                "icon": "⛩️"
            },
            {
                "id": "adult",
                "name": "Adult",
                "display_name": "Adult",
                "type": "adult",
                "icon": "🔞"
            },
            {
                "id": "children",
                "name": "Children",
                "display_name": "Children",
                "type": "movies",
                "icon": "🧸"
            },
            {
                "id": "eesti_filmid",
                "name": "Eesti filmid",
                "display_name": "Eesti filmid",
                "type": "movies",
                "icon": "🇪🇪"
            }
        ]

        # Discover custom VirtualFolders in Jellyfin
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
                "icon": "🎬"
            })

        all_libs = lib_configs + jf_extra
        results = []

        for lib in all_libs:
            locations = []
            total_items = 0
            candidate_paths = self.get_candidate_paths_for_library(lib["id"])

            for p in candidate_paths:
                norm_p = os.path.normpath(p)
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
                "drive_count": len(existing_locs),
                "locations": locations,
                "deletable": False
            })

        return results

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

        # Candidate pools
        # --- MOVIES_DIR ---
        movie_candidates = self.get_candidate_paths_for_library("movies")
        best_movies = None
        max_movie_items = -1
        for p in movie_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                cnt = count_media_items(p, "movies")
                if cnt > max_movie_items:
                    max_movie_items = cnt
                    best_movies = p
        detected["MOVIES_DIR"] = best_movies or current_paths["MOVIES_DIR"] or (movie_candidates[0] if movie_candidates else "/media/movies")

        # --- SERIES_DIR ---
        series_candidates = self.get_candidate_paths_for_library("series")
        best_series = None
        max_series_items = -1
        for p in series_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                cnt = count_media_items(p, "series")
                if cnt > max_series_items:
                    max_series_items = cnt
                    best_series = p
        detected["SERIES_DIR"] = best_series or current_paths["SERIES_DIR"] or (series_candidates[0] if series_candidates else "/media/tv")

        # --- ANIME_DIR ---
        anime_candidates = self.get_candidate_paths_for_library("anime")
        best_anime = None
        for p in anime_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                best_anime = p
                break
        detected["ANIME_DIR"] = best_anime or current_paths["ANIME_DIR"] or (anime_candidates[0] if anime_candidates else "/media/anime")

        # --- ADULT_DIR ---
        adult_candidates = self.get_candidate_paths_for_library("adult")
        best_adult = None
        for p in adult_candidates:
            if os.path.exists(p) and os.path.isdir(p):
                best_adult = p
                break
        detected["ADULT_DIR"] = best_adult or current_paths["ADULT_DIR"] or (adult_candidates[0] if adult_candidates else "/media/adult")

        # --- WATCH_DIR ---
        watch_candidates = []
        curr_w = current_paths["WATCH_DIR"]
        if curr_w and os.path.exists(curr_w) and curr_w not in ["/downloads", "/media/downloads"]:
            watch_candidates.append(curr_w)
        home = os.path.expanduser("~")
        generic_watch = [os.path.join(home, "dwhelper"), os.path.join(home, "Downloads"), "/downloads", "/var/downloads"]
        for p in generic_watch:
            if os.path.exists(p) and os.path.isdir(p):
                watch_candidates.append(p)
        default_fallback = os.path.join(home, "dwhelper") if os.path.exists(os.path.join(home, "dwhelper")) else (watch_candidates[0] if watch_candidates else "/downloads")
        detected["WATCH_DIR"] = watch_candidates[0] if watch_candidates else (current_paths["WATCH_DIR"] or default_fallback)

        # --- MEDIA_ROOT ---
        if self.media_roots:
            detected["MEDIA_ROOT"] = self.media_roots[0]
        else:
            detected["MEDIA_ROOT"] = "/media"

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
        """Returns list of selectable parent directories across all storage drives for creating new folders."""
        locations = []
        for r in self.media_roots:
            basename = os.path.basename(r)
            display = f"{basename} ({r})" if basename else r
            locations.append({"path": r, "name": display})
        return locations

    def create_directory(self, folder_name: str, content_type: str = "movies", add_to_jellyfin: bool = True, parent_path: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new filesystem directory in the chosen parent disk/root and optionally links it to Jellyfin."""
        folder_name = folder_name.strip().strip("/\\")
        if not folder_name or any(c in folder_name for c in [":", "..", "*", "?", "<", ">", "|"]):
            return {"success": False, "error": "Invalid directory name. Special characters are not allowed."}

        base = self.media_root
        if parent_path and os.path.exists(parent_path) and os.path.isdir(parent_path) and not is_excluded_path(parent_path):
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

        if add_to_jellyfin and get_jellyfin_url():
            token = self.get_jellyfin_token()
            if token:
                media_path_prefix = cfg.get("JELLYFIN_MEDIA_PATH", "/media")
                roots = self.media_roots
                if len(roots) > 1 and target_path.startswith(roots[1]):
                    jf_container_path = target_path.replace(roots[1], "/data2", 1)
                elif len(roots) > 0 and target_path.startswith(roots[0]):
                    jf_container_path = target_path.replace(roots[0], "/data", 1)
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
        
        target_path = None
        if path and os.path.exists(path):
            target_path = os.path.normpath(path)
        else:
            all_dirs = self.list_all_directories()
            for d in all_dirs:
                if d["name"].lower() == folder_name.lower() or d["path"].lower() == folder_name.lower():
                    target_path = d["path"]
                    folder_name = d["name"]
                    break
            if not target_path:
                target_path = os.path.normpath(os.path.join(self.media_root, folder_name))

        if target_path in SYSTEM_ROOTS or target_path in self.media_roots or is_excluded_path(target_path):
            return {"success": False, "error": f"Cannot delete core root or protected path '{target_path}'."}

        base_name = os.path.basename(target_path)
        if base_name.lower() in PROTECTED_NAMES:
            return {"success": False, "error": f"Cannot delete core protected directory '{base_name}'."}

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
