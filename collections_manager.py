import os
import json
import time
import re
import glob
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

from config import get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass, get_movies_dir
from directories_manager import directories_mgr
from logger import emit_log

MCU_CHRONOLOGICAL = [
    "Captain America: The First Avenger",
    "Captain Marvel",
    "Iron Man",
    "The Incredible Hulk",
    "Iron Man 2",
    "Thor",
    "The Avengers",
    "Iron Man 3",
    "Thor: The Dark World",
    "Captain America: The Winter Soldier",
    "Guardians of the Galaxy",
    "Guardians of the Galaxy Vol. 2",
    "Avengers: Age of Ultron",
    "Ant-Man",
    "Captain America: Civil War",
    "Black Widow",
    "Black Panther",
    "Spider-Man: Homecoming",
    "Doctor Strange",
    "Thor: Ragnarok",
    "Ant-Man and the Wasp",
    "Avengers: Infinity War",
    "Avengers: Endgame",
    "Spider-Man: Far From Home",
    "Shang-Chi and the Legend of the Ten Rings",
    "Eternals",
    "Spider-Man: No Way Home",
    "Doctor Strange in the Multiverse of Madness",
    "Thor: Love and Thunder",
    "Black Panther: Wakanda Forever",
    "Ant-Man and the Wasp: Quantumania",
    "Guardians of the Galaxy Vol. 3",
    "The Marvels",
    "Deadpool & Wolverine"
]

# Only truly missing films that need .disc placeholders
MISSING_PLACEHOLDERS = [
    # Lord of the Rings
    {"title": "The Lord of the Rings The Fellowship of the Ring", "year": "2001", "collection": "The Lord of the Rings Collection"},
    {"title": "The Lord of the Rings The Two Towers", "year": "2002", "collection": "The Lord of the Rings Collection"},
    
    # Jurassic Park
    {"title": "Jurassic Park", "year": "1993", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic Park III", "year": "2001", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic World", "year": "2015", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic World Dominion", "year": "2022", "collection": "Jurassic Park Collection"},
    
    # Mad Max
    {"title": "Mad Max", "year": "1979", "collection": "Mad Max Collection"},
    {"title": "Mad Max 2", "year": "1981", "collection": "Mad Max Collection"},
    {"title": "Mad Max Beyond Thunderdome", "year": "1985", "collection": "Mad Max Collection"},
    
    # Transformers
    {"title": "Transformers Revenge of the Fallen", "year": "2009", "collection": "Transformers Collection"},
    {"title": "Transformers Dark of the Moon", "year": "2011", "collection": "Transformers Collection"},
    {"title": "Transformers Age of Extinction", "year": "2014", "collection": "Transformers Collection"},
    {"title": "Transformers The Last Knight", "year": "2017", "collection": "Transformers Collection"},
    {"title": "Transformers Rise of the Beasts", "year": "2023", "collection": "Transformers Collection"},
    
    # Rocky
    {"title": "Rocky II", "year": "1979", "collection": "Rocky Collection"},
    {"title": "Rocky III", "year": "1982", "collection": "Rocky Collection"},
    {"title": "Rocky IV", "year": "1985", "collection": "Rocky Collection"},
    {"title": "Rocky V", "year": "1990", "collection": "Rocky Collection"},
    {"title": "Rocky Balboa", "year": "2006", "collection": "Rocky Collection"},
    {"title": "Creed", "year": "2015", "collection": "Rocky Collection"},
    {"title": "Creed II", "year": "2018", "collection": "Rocky Collection"},
    {"title": "Creed III", "year": "2023", "collection": "Rocky Collection"},
    
    # Gremlins
    {"title": "Gremlins 2 The New Batch", "year": "1990", "collection": "The Gremlins Collection"},
    
    # Underworld
    {"title": "Underworld", "year": "2003", "collection": "Underworld Collection"},
    {"title": "Underworld Rise of the Lycans", "year": "2009", "collection": "Underworld Collection"},
    {"title": "Underworld Awakening", "year": "2012", "collection": "Underworld Collection"},
    
    # DC
    {"title": "Justice League", "year": "2017", "collection": "DC Extended Universe Collection"},
    
    # Star Wars
    {"title": "Star Wars The Last Jedi", "year": "2017", "collection": "Star Wars Collection"},
    {"title": "Star Wars The Rise of Skywalker", "year": "2019", "collection": "Star Wars Collection"},
    {"title": "Solo A Star Wars Story", "year": "2018", "collection": "Star Wars Collection"},

    # Sonic
    {"title": "Sonic the Hedgehog 3", "year": "2024", "collection": "Sonic the Hedgehog Collection"}
]

# Map BoxSet name or ID to Movie TmdbCollection ID if different
BOXSET_TMDB_MAP = {
    "The Mummy Collection": "1733",
    "Underworld Collection": "2326",
    "A Quiet Place Collection": "521226",
    "Venom Collection": "558216",
    "Tron Collection": "63043",
    "Rocky Collection": "1575"
}

CUSTOM_CSS = """
/* Auto-styled by Jellyfin Collection Fixer: Grey out missing items marked (Not Available) */
.card:has([title*="Not Available"]),
.card:has([aria-label*="Not Available"]),
.card:has(.cardTextTitle[title*="Not Available"]),
.card[title*="Not Available"],
.card[aria-label*="Not Available"],
.card[data-itemname*="Not Available"] {
    opacity: 0.42 !important;
    filter: grayscale(100%) contrast(90%) !important;
    transition: opacity 0.2s ease, filter 0.2s ease !important;
}

.card:has([title*="Not Available"]):hover,
.card:has([aria-label*="Not Available"]):hover,
.card[title*="Not Available"]:hover,
.card[aria-label*="Not Available"]:hover {
    opacity: 0.78 !important;
    filter: grayscale(35%) contrast(100%) !important;
}

/* Badge for (Not Available) */
.card:has([title*="Not Available"]) .cardImageContainer::after,
.card:has([aria-label*="Not Available"]) .cardImageContainer::after,
.card[title*="Not Available"] .cardImageContainer::after,
.card[aria-label*="Not Available"] .cardImageContainer::after {
    content: "NOT AVAILABLE";
    position: absolute;
    top: 8px;
    right: 8px;
    background: rgba(225, 29, 72, 0.92);
    color: #ffffff;
    font-size: 0.65rem;
    font-weight: 800;
    padding: 2px 7px;
    border-radius: 4px;
    letter-spacing: 0.6px;
    z-index: 3;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.6);
    pointer-events: none;
}
"""

def normalize(name: str) -> str:
    if not name:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', name).lower()

class CollectionsManager:
    def __init__(self):
        self.token = None
        self.user_id = None

    def reset_session(self):
        self.token = None
        self.user_id = None

    def login(self) -> bool:
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
            with urllib.request.urlopen(req, timeout=6) as res:
                data = json.loads(res.read().decode("utf-8"))
                self.token = data.get("AccessToken")
                self.user_id = data.get("User", {}).get("Id")
                return True
        except Exception as e:
            emit_log(f"CollectionsManager login failed: {e}")
            return False

    def api_request(self, path: str, method: str = "GET", data: Any = None, retry_on_401: bool = True):
        if not self.token:
            if not self.login():
                return None

        url = f"{get_jellyfin_url()}{path}"
        auth_token_val = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{self.token}"'
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_token_val,
            "X-Emby-Authorization": auth_token_val,
            "X-MediaBrowser-Token": self.token,
            "X-Emby-Token": self.token,
            "User-Agent": "CFlixMediaManager/1.0"
        }
        body = json.dumps(data).encode("utf-8") if data is not None else None

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                res_data = res.read()
                return json.loads(res_data.decode("utf-8")) if res_data else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry_on_401:
                self.token = None
                if self.login():
                    return self.api_request(path, method=method, data=data, retry_on_401=False)
            if e.code != 204:
                emit_log(f"Jellyfin API HTTP Error ({method} {path}): {e.code}")
            return None
        except Exception as e:
            emit_log(f"Jellyfin API General Error ({method} {path}): {e}")
            return None

    def get_collections_overview(self) -> List[Dict[str, Any]]:
        boxsets_data = self.api_request("/Items?IncludeItemTypes=BoxSet&Recursive=true&Fields=ProviderIds,ItemCounts")
        if not boxsets_data:
            return []

        colls = boxsets_data.get("Items", [])
        overview = []
        for c in sorted(colls, key=lambda x: x["Name"]):
            cid = c["Id"]
            cname = c["Name"]
            items_data = self.api_request(f"/Items?ParentId={cid}&Fields=Path,ProductionYear")
            items = items_data.get("Items", []) if items_data else []
            
            movies = []
            owned_count = 0
            missing_count = 0
            
            for item in items:
                name = item.get("Name", "")
                is_missing = "(Not Available)" in name or (item.get("Path", "") and item["Path"].endswith(".disc"))
                if is_missing:
                    missing_count += 1
                else:
                    owned_count += 1
                movies.append({
                    "id": item["Id"],
                    "name": name,
                    "year": item.get("ProductionYear"),
                    "is_missing": is_missing
                })

            overview.append({
                "id": cid,
                "name": cname,
                "total_items": len(items),
                "owned_count": owned_count,
                "missing_count": missing_count,
                "movies": movies
            })

        return overview

    def apply_custom_css(self):
        try:
            branding = self.api_request("/Branding/Configuration")
            if branding is not None:
                cur_css = branding.get("CustomCss", "") or ""
                if "Auto-styled by Jellyfin Collection Fixer" not in cur_css:
                    new_css = cur_css + "\n" + CUSTOM_CSS
                    branding["CustomCss"] = new_css.strip()
                    self.api_request("/Branding/Configuration", method="POST", data=branding)
                    emit_log("Custom CSS applied to Jellyfin branding successfully.")
        except Exception as e:
            emit_log(f"Note on Custom CSS: {e}")

    def clean_redundant_placeholders(self, all_movies: Optional[List[Dict[str, Any]]] = None) -> int:
        """Deletes any .disc placeholder and its companion art files on disk if the real movie is owned."""
        if all_movies is None:
            movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=Path,ProductionYear")
            all_movies = movies_data.get("Items", []) if movies_data else []

        real_movies = [
            m for m in all_movies
            if not (m.get("Path", "").endswith(".disc")) and "(Not Available)" not in m.get("Name", "")
        ]

        candidate_dirs = directories_mgr.get_candidate_paths_for_library("movies")
        primary = get_movies_dir()
        if primary and primary not in candidate_dirs:
            candidate_dirs.append(primary)

        purged_count = 0
        for folder in candidate_dirs:
            if not os.path.exists(folder):
                continue
            try:
                entries = os.listdir(folder)
            except OSError:
                continue

            for f in entries:
                if f.endswith(".disc"):
                    disc_path = os.path.join(folder, f)
                    clean_title = re.sub(r'[\(\[]?\b(19\d\d|20\d\d)\b[\)\]]?', '', f)
                    clean_title = clean_title.replace("[Not Available]", "").replace(".disc", "").strip()
                    fnorm = normalize(clean_title)

                    ym = re.search(r'\b(19\d\d|20\d\d)\b', f)
                    fyear = ym.group(1) if ym else ""

                    matched_real = None
                    for rm in real_movies:
                        rname = rm.get("Name", "")
                        ryear = str(rm.get("ProductionYear") or "")
                        rnorm = normalize(rname)

                        if (fnorm in rnorm or rnorm in fnorm) and (not fyear or not ryear or fyear == ryear) and len(fnorm) >= 4:
                            matched_real = rm
                            break

                    if matched_real:
                        stem = f[:-5]
                        companion_patterns = [
                            disc_path,
                            os.path.join(folder, f"{stem}-poster.*"),
                            os.path.join(folder, f"{stem}-backdrop.*"),
                            os.path.join(folder, f"{stem}-landscape.*"),
                            os.path.join(folder, f"{stem}-logo.*"),
                            os.path.join(folder, f"{stem}.nfo"),
                            os.path.join(folder, f"{stem}.trickplay")
                        ]
                        for pat in companion_patterns:
                            for matched_file in glob.glob(pat):
                                try:
                                    os.remove(matched_file)
                                except OSError:
                                    pass
                        purged_count += 1
                        emit_log(f"Cleaned redundant placeholder: '{f}' (now owned: '{matched_real['Name']}')")

        if purged_count > 0:
            emit_log(f"Purged {purged_count} redundant placeholders from disk. Refreshing Jellyfin library...")
            self.api_request("/Library/Refresh", method="POST")

        return purged_count

    def create_missing_placeholders(self, all_movies: Optional[List[Dict[str, Any]]] = None):
        emit_log("Checking for missing collection movie placeholders...")
        if all_movies is None:
            movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=Path,ProductionYear")
            all_movies = movies_data.get("Items", []) if movies_data else []

        real_movies = [
            m for m in all_movies
            if not (m.get("Path", "").endswith(".disc")) and "(Not Available)" not in m.get("Name", "")
        ]

        candidate_dirs = directories_mgr.get_candidate_paths_for_library("movies")
        primary = get_movies_dir()
        target_dir = primary if os.path.exists(primary) else (candidate_dirs[0] if candidate_dirs else None)
        if not target_dir:
            return

        created = 0
        for p in MISSING_PLACEHOLDERS:
            title = p["title"]
            year = str(p["year"])
            fname = f"{title} ({year}) [Not Available].disc"
            pnorm = normalize(title)

            # Check if real movie is already registered in Jellyfin
            already_owned = False
            for rm in real_movies:
                rname = rm.get("Name", "")
                ryear = str(rm.get("ProductionYear") or "")
                rnorm = normalize(rname)
                if (pnorm in rnorm or rnorm in pnorm) and (not year or not ryear or year == ryear):
                    already_owned = True
                    break

            if already_owned:
                continue

            # Check if file exists across candidate directories
            file_exists = False
            for cdir in candidate_dirs:
                if not os.path.exists(cdir):
                    continue
                try:
                    for ef in os.listdir(cdir):
                        if ef.startswith(f"{title} ({year})") and (ef.endswith(".mp4") or ef.endswith(".mkv") or ef.endswith(".disc")):
                            file_exists = True
                            break
                except OSError:
                    pass
                if file_exists:
                    break

            if not file_exists:
                dest_path = os.path.join(target_dir, fname)
                try:
                    with open(dest_path, "w") as f:
                        pass
                    created += 1
                    emit_log(f"Created missing placeholder: {fname}")
                except Exception as e:
                    emit_log(f"Error creating placeholder {fname}: {e}")

        if created > 0:
            emit_log(f"Created {created} new placeholders. Triggering library refresh...")
            self.api_request("/Library/Refresh", method="POST")
            time.sleep(10)

    def format_placeholder_names(self):
        movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=Path")
        if not movies_data:
            return

        for m in movies_data.get("Items", []):
            path = m.get("Path", "")
            name = m.get("Name", "")
            mid = m.get("Id")
            if path and path.endswith(".disc"):
                if "(Not Available)" not in name:
                    new_name = f"{name} (Not Available)"
                    details = self.api_request(f"/Items/{mid}")
                    if details:
                        details["Name"] = new_name
                        details["LockedFields"] = list(set(details.get("LockedFields", []) + ["Name"]))
                        details["LockData"] = True
                        self.api_request(f"/Items/{mid}", method="POST", data=details)
                        emit_log(f"Updated placeholder: '{name}' -> '{new_name}'")

    def deduplicate_targets(self, target_movies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicates movies within a collection: prefers real movies over placeholders, avoids duplicates."""
        grouped = {}
        for m in target_movies:
            name = m.get("Name", "").replace("(Not Available)", "").strip()
            year = str(m.get("ProductionYear") or "")
            path = m.get("Path", "")
            is_placeholder = path.endswith(".disc") or "(Not Available)" in m.get("Name", "")

            norm_key = (normalize(name), year)

            if norm_key not in grouped:
                grouped[norm_key] = m
            else:
                existing = grouped[norm_key]
                exist_is_placeholder = existing.get("Path", "").endswith(".disc") or "(Not Available)" in existing.get("Name", "")
                if exist_is_placeholder and not is_placeholder:
                    grouped[norm_key] = m
                elif not exist_is_placeholder and not is_placeholder:
                    if "[voiceover]" in existing.get("Path", "").lower() and "[voiceover]" not in path.lower():
                        grouped[norm_key] = m

        deduped = list(grouped.values())
        deduped.sort(key=lambda x: (x.get("ProductionYear") or 9999, x.get("Name", "")))
        return deduped

    def sync_single_boxset(self, b: Dict[str, Any], all_movies: List[Dict[str, Any]], movies_by_tmdb_coll: Dict[str, List[Dict[str, Any]]]) -> int:
        bname = b["Name"]
        bid = b["Id"]
        bproviders = b.get("ProviderIds", {})
        btmdb = str(bproviders.get("Tmdb", ""))

        if bname in BOXSET_TMDB_MAP:
            btmdb = BOXSET_TMDB_MAP[bname]

        target_movies = []
        if btmdb and btmdb in movies_by_tmdb_coll:
            target_movies.extend(movies_by_tmdb_coll[btmdb])

        bname_lower = bname.lower()
        if "rocky" in bname_lower:
            if "553717" in movies_by_tmdb_coll:
                target_movies.extend(movies_by_tmdb_coll["553717"])
            for m in all_movies:
                mn = m["Name"].lower()
                if "rocky" in mn or "creed" in mn:
                    target_movies.append(m)

        elif "marvel cinematic universe" in bname_lower:
            norm_chrono = [normalize(t) for t in MCU_CHRONOLOGICAL]
            for m in all_movies:
                mnorm = normalize(m["Name"].replace("(Not Available)", ""))
                if any(mnorm == target or target in mnorm for target in norm_chrono):
                    target_movies.append(m)

        elif "dc extended universe" in bname_lower:
            dceu_kws = ["man of steel", "batman v superman", "suicide squad", "wonder woman", "justice league", "aquaman", "shazam", "birds of prey", "black adam", "the flash", "blue beetle"]
            for m in all_movies:
                mnorm = m["Name"].lower()
                if any(kw in mnorm for kw in dceu_kws) and "nolan" not in mnorm:
                    target_movies.append(m)

        elif "godzilla" in bname_lower or "monsterverse" in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if any(kw in mnorm for kw in ["godzilla", "kong"]) and "minus one" not in mnorm:
                    target_movies.append(m)

        elif "star wars" in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if "star wars" in mnorm or "empire strikes" in mnorm or "return of the jedi" in mnorm or "rogue one" in mnorm or "solo" in mnorm:
                    target_movies.append(m)

        elif "unbreakable" in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if any(kw in mnorm for kw in ["unbreakable", "split", "glass"]):
                    target_movies.append(m)

        elif "alien" in bname_lower and "vs" not in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if ("prometheus" in mnorm or "alien" in mnorm) and "predator" not in mnorm:
                    target_movies.append(m)

        elif "predator" in bname_lower and "vs" not in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if ("predator" in mnorm or "prey" in mnorm) and "alien vs" not in mnorm and "avp" not in mnorm:
                    target_movies.append(m)

        elif "transformers" in bname_lower:
            for m in all_movies:
                mnorm = m["Name"].lower()
                if "transformers" in mnorm or "bumblebee" in mnorm:
                    target_movies.append(m)

        elif "a quiet place" in bname_lower:
            for m in all_movies:
                if "quiet place" in m["Name"].lower():
                    target_movies.append(m)

        elif "sonic" in bname_lower:
            for m in all_movies:
                if "sonic" in m["Name"].lower():
                    target_movies.append(m)

        elif "cloverfield" in bname_lower:
            for m in all_movies:
                if "cloverfield" in m["Name"].lower():
                    target_movies.append(m)

        elif "jumanji" in bname_lower:
            for m in all_movies:
                if "jumanji" in m["Name"].lower():
                    target_movies.append(m)

        elif "men in black" in bname_lower:
            for m in all_movies:
                mn = m["Name"].lower()
                if "men in black" in mn or "mib" in mn:
                    target_movies.append(m)

        elif "the mummy" in bname_lower:
            for m in all_movies:
                if "mummy" in m["Name"].lower():
                    target_movies.append(m)

        elif "underworld" in bname_lower:
            for m in all_movies:
                if "underworld" in m["Name"].lower():
                    target_movies.append(m)

        elif "tron" in bname_lower:
            for m in all_movies:
                if "tron" in m["Name"].lower():
                    target_movies.append(m)

        elif "venom" in bname_lower:
            for m in all_movies:
                if "venom" in m["Name"].lower():
                    target_movies.append(m)

        elif "spider-man (mcu)" in bname_lower:
            for m in all_movies:
                mn = m["Name"].lower()
                if "homecoming" in mn or "far from home" in mn or "no way home" in mn:
                    target_movies.append(m)

        elif "the amazing spider-man" in bname_lower:
            for m in all_movies:
                if "amazing spider-man" in m["Name"].lower():
                    target_movies.append(m)

        elif "spider-man" in bname_lower:
            for m in all_movies:
                mn = m["Name"].lower()
                if "spider-man" in mn and "amazing" not in mn and "homecoming" not in mn and "far from" not in mn and "no way" not in mn:
                    target_movies.append(m)

        # Deduplicate & sort
        deduped = self.deduplicate_targets(target_movies)

        # Bi-directional sync with Jellyfin
        cur_items_data = self.api_request(f"/Items?ParentId={bid}&Fields=Path")
        current_ids = set(it["Id"] for it in (cur_items_data.get("Items", []) if cur_items_data else []))
        target_ids = set(m["Id"] for m in deduped)

        to_remove = current_ids - target_ids
        to_add = target_ids - current_ids

        if to_remove:
            rem_str = ",".join(to_remove)
            self.api_request(f"/Collections/{bid}/Items?ids={rem_str}", method="DELETE")
            emit_log(f"Removed {len(to_remove)} redundant/duplicate items from '{bname}'.")

        if to_add:
            add_str = ",".join(to_add)
            self.api_request(f"/Collections/{bid}/Items?ids={add_str}", method="POST")
            emit_log(f"Added {len(to_add)} movies to '{bname}'.")

        return len(deduped)

    def sync_all_collections(self) -> Dict[str, Any]:
        emit_log("=== Synchronizing All Jellyfin Collections ===")
        self.apply_custom_css()

        movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=ProviderIds,Path,ProductionYear")
        all_movies = movies_data.get("Items", []) if movies_data else []

        # 1. Clean redundant placeholders for movies we now own
        self.clean_redundant_placeholders(all_movies)

        # 2. Re-create truly missing placeholders
        self.create_missing_placeholders(all_movies)
        self.format_placeholder_names()

        # Re-fetch movies after placeholder adjustments
        movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=ProviderIds,Path,ProductionYear")
        all_movies = movies_data.get("Items", []) if movies_data else []

        # Index movies by TMDb collection ID
        movies_by_tmdb_coll = {}
        for m in all_movies:
            providers = m.get("ProviderIds", {})
            tmdb_coll = providers.get("TmdbCollection")
            if tmdb_coll:
                movies_by_tmdb_coll.setdefault(str(tmdb_coll), []).append(m)

        boxsets_data = self.api_request("/Items?IncludeItemTypes=BoxSet&Recursive=true&Fields=ProviderIds")
        if not boxsets_data:
            emit_log("No boxsets found.")
            return {"success": False, "error": "No boxsets found"}

        boxsets = boxsets_data.get("Items", [])
        updated_count = 0
        for b in sorted(boxsets, key=lambda x: x["Name"]):
            self.sync_single_boxset(b, all_movies, movies_by_tmdb_coll)
            updated_count += 1

        # Refresh collections folder
        virtual_folders = self.api_request("/Library/VirtualFolders")
        if virtual_folders:
            for vf in virtual_folders:
                if vf.get("Name") == "Collections":
                    cid = vf.get("ItemId")
                    if cid:
                        self.api_request(f"/Items/{cid}/Refresh?Recursive=true", method="POST")

        emit_log(f"=== Collections Synchronization Complete ({updated_count} collections verified) ===")
        return {"success": True, "updated_count": updated_count}

    def sync_single_collection_by_id(self, collection_id: str) -> Dict[str, Any]:
        """Synchronizes just one collection given its Jellyfin ID."""
        boxsets_data = self.api_request("/Items?IncludeItemTypes=BoxSet&Recursive=true&Fields=ProviderIds")
        if not boxsets_data:
            return {"success": False, "error": "No boxsets found"}

        target_b = None
        for b in boxsets_data.get("Items", []):
            if b["Id"] == collection_id:
                target_b = b
                break

        if not target_b:
            return {"success": False, "error": f"Collection ID {collection_id} not found."}

        movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=ProviderIds,Path,ProductionYear")
        all_movies = movies_data.get("Items", []) if movies_data else []

        movies_by_tmdb_coll = {}
        for m in all_movies:
            providers = m.get("ProviderIds", {})
            tmdb_coll = providers.get("TmdbCollection")
            if tmdb_coll:
                movies_by_tmdb_coll.setdefault(str(tmdb_coll), []).append(m)

        count = self.sync_single_boxset(target_b, all_movies, movies_by_tmdb_coll)
        return {"success": True, "collection_name": target_b["Name"], "total_items": count}

collections_mgr = CollectionsManager()
