import os
import json
import time
import re
import urllib.request
import urllib.error
from typing import Dict, Any, List

from config import get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass, get_movies_dir
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

MISSING_PLACEHOLDERS = [
    {"title": "The Lord of the Rings The Fellowship of the Ring", "year": "2001", "collection": "The Lord of the Rings Collection"},
    {"title": "The Lord of the Rings The Two Towers", "year": "2002", "collection": "The Lord of the Rings Collection"},
    {"title": "Jurassic Park", "year": "1993", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic Park III", "year": "2001", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic World", "year": "2015", "collection": "Jurassic Park Collection"},
    {"title": "Jurassic World Dominion", "year": "2022", "collection": "Jurassic Park Collection"},
    {"title": "Mad Max", "year": "1979", "collection": "Mad Max Collection"},
    {"title": "Mad Max 2", "year": "1981", "collection": "Mad Max Collection"},
    {"title": "Mad Max Beyond Thunderdome", "year": "1985", "collection": "Mad Max Collection"},
    {"title": "Transformers Revenge of the Fallen", "year": "2009", "collection": "Transformers Collection"},
    {"title": "Transformers Dark of the Moon", "year": "2011", "collection": "Transformers Collection"},
    {"title": "Transformers Age of Extinction", "year": "2014", "collection": "Transformers Collection"},
    {"title": "Transformers The Last Knight", "year": "2017", "collection": "Transformers Collection"},
    {"title": "Transformers Rise of the Beasts", "year": "2023", "collection": "Transformers Collection"},
    {"title": "Rocky II", "year": "1979", "collection": "Rocky Collection"},
    {"title": "Rocky III", "year": "1982", "collection": "Rocky Collection"},
    {"title": "Rocky IV", "year": "1985", "collection": "Rocky Collection"},
    {"title": "Rocky V", "year": "1990", "collection": "Rocky Collection"},
    {"title": "Rocky Balboa", "year": "2006", "collection": "Rocky Collection"},
    {"title": "Creed", "year": "2015", "collection": "Rocky Collection"},
    {"title": "Creed II", "year": "2018", "collection": "Rocky Collection"},
    {"title": "Creed III", "year": "2023", "collection": "Rocky Collection"},
    {"title": "Gremlins 2 The New Batch", "year": "1990", "collection": "The Gremlins Collection"},
    {"title": "Underworld", "year": "2003", "collection": "Underworld Collection"},
    {"title": "Underworld Rise of the Lycans", "year": "2009", "collection": "Underworld Collection"},
    {"title": "Underworld Awakening", "year": "2012", "collection": "Underworld Collection"},
    {"title": "Man of Steel", "year": "2013", "collection": "DC Extended Universe Collection"},
    {"title": "Batman v Superman Dawn of Justice", "year": "2016", "collection": "DC Extended Universe Collection"},
    {"title": "Justice League", "year": "2017", "collection": "DC Extended Universe Collection"},
    {"title": "Aquaman", "year": "2018", "collection": "DC Extended Universe Collection"},
    {"title": "Birds of Prey", "year": "2020", "collection": "DC Extended Universe Collection"},
    {"title": "Aquaman and the Lost Kingdom", "year": "2023", "collection": "DC Extended Universe Collection"},
    {"title": "Star Wars The Force Awakens", "year": "2015", "collection": "Star Wars Collection"},
    {"title": "Star Wars The Last Jedi", "year": "2017", "collection": "Star Wars Collection"},
    {"title": "Star Wars The Rise of Skywalker", "year": "2019", "collection": "Star Wars Collection"},
    {"title": "Solo A Star Wars Story", "year": "2018", "collection": "Star Wars Collection"},
    {"title": "Alien Covenant", "year": "2017", "collection": "Alien Collection"},
    {"title": "Alien Romulus", "year": "2024", "collection": "Alien Collection"},
    {"title": "Sonic the Hedgehog 3", "year": "2024", "collection": "Sonic the Hedgehog Collection"}
]

BOXSET_TMDB_MAP = {
    "The Mummy Collection": "1733",
    "Underworld Collection": "2326",
    "A Quiet Place Collection": "521226",
    "Venom Collection": "558216",
    "Tron Collection": "63043"
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
    return re.sub(r'[^a-zA-Z0-9]', '', name).lower()

class CollectionsManager:
    def __init__(self):
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

    def api_request(self, path: str, method: str = "GET", data: Any = None):
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
        emit_log("Applying Custom CSS for (Not Available) Items in Jellyfin...")
        branding = self.api_request("/Branding/Configuration")
        if branding is not None:
            cur_css = branding.get("CustomCss", "") or ""
            if "Auto-styled by Jellyfin Collection Fixer" not in cur_css:
                new_css = cur_css + "\n" + CUSTOM_CSS
                branding["CustomCss"] = new_css.strip()
                self.api_request("/Branding/Configuration", method="POST", data=branding)
                emit_log("Custom CSS applied to Jellyfin branding successfully.")

    def create_missing_placeholders(self):
        emit_log("Checking for missing collection movie placeholders...")
        movies_dir = get_movies_dir()
        if not os.path.exists(movies_dir):
            return

        existing_files = set(os.listdir(movies_dir))
        created = 0
        for p in MISSING_PLACEHOLDERS:
            title = p["title"]
            year = p["year"]
            fname = f"{title} ({year}) [Not Available].disc"
            
            already_exists = False
            for ef in existing_files:
                if ef.startswith(f"{title} ({year})") and (ef.endswith(".mp4") or ef.endswith(".mkv") or ef.endswith(".disc")):
                    already_exists = True
                    break
            
            if not already_exists:
                dest_path = os.path.join(movies_dir, fname)
                try:
                    with open(dest_path, "w") as f:
                        pass
                    created += 1
                    emit_log(f"Created placeholder: {fname}")
                except Exception as e:
                    emit_log(f"Error creating placeholder {fname}: {e}")

        if created > 0:
            emit_log(f"Created {created} new placeholders. Triggering library refresh...")
            self.api_request("/Library/Refresh", method="POST")
            time.sleep(12)

    def format_placeholder_names(self):
        emit_log("Formatting placeholder names to include '(Not Available)'...")
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

    def sync_all_collections(self) -> Dict[str, Any]:
        emit_log("=== Synchronizing All Jellyfin Collections ===")
        self.apply_custom_css()
        self.create_missing_placeholders()
        self.format_placeholder_names()

        boxsets_data = self.api_request("/Items?IncludeItemTypes=BoxSet&Recursive=true&Fields=ProviderIds")
        if not boxsets_data:
            emit_log("No boxsets found.")
            return {"success": False, "error": "No boxsets found"}

        boxsets = boxsets_data.get("Items", [])
        movies_data = self.api_request("/Items?IncludeItemTypes=Movie&Recursive=true&Fields=ProviderIds,Path,ProductionYear")
        all_movies = movies_data.get("Items", []) if movies_data else []

        # Index movies by TMDb collection ID
        movies_by_tmdb_coll = {}
        for m in all_movies:
            providers = m.get("ProviderIds", {})
            tmdb_coll = providers.get("TmdbCollection")
            if tmdb_coll:
                movies_by_tmdb_coll.setdefault(str(tmdb_coll), []).append(m)

        updated_count = 0
        for b in sorted(boxsets, key=lambda x: x["Name"]):
            bname = b["Name"]
            bid = b["Id"]
            bproviders = b.get("ProviderIds", {})
            btmdb = str(bproviders.get("Tmdb", ""))

            if bname in BOXSET_TMDB_MAP:
                btmdb = BOXSET_TMDB_MAP[bname]

            target_movies = []
            if btmdb and btmdb in movies_by_tmdb_coll:
                target_movies.extend(movies_by_tmdb_coll[btmdb])

            # Franchise rules
            if "Rocky" in bname and "553717" in movies_by_tmdb_coll:
                target_movies.extend(movies_by_tmdb_coll["553717"])

            elif "Marvel Cinematic Universe" in bname:
                norm_chrono = [normalize(t) for t in MCU_CHRONOLOGICAL]
                for m in all_movies:
                    mnorm = normalize(m["Name"].replace("(Not Available)", ""))
                    if any(mnorm == target or target in mnorm for target in norm_chrono):
                        target_movies.append(m)

            elif "DC Extended Universe" in bname:
                dceu_kws = ["man of steel", "batman v superman", "suicide squad", "wonder woman", "justice league", "aquaman", "shazam", "birds of prey", "black adam", "the flash", "blue beetle"]
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if any(kw in mnorm for kw in dceu_kws) and "nolan" not in mnorm:
                        target_movies.append(m)

            elif "Godzilla x Kong" in bname or "MonsterVerse" in bname:
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if any(kw in mnorm for kw in ["godzilla", "kong"]) and "minus one" not in mnorm:
                        target_movies.append(m)

            elif "Star Wars" in bname:
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if "star wars" in mnorm or "empire strikes" in mnorm or "return of the jedi" in mnorm or "rogue one" in mnorm or "solo" in mnorm:
                        target_movies.append(m)

            elif "Unbreakable" in bname:
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if any(kw in mnorm for kw in ["unbreakable", "split", "glass"]):
                        target_movies.append(m)

            elif "Alien Collection" in bname:
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if ("prometheus" in mnorm or "alien" in mnorm) and "predator" not in mnorm:
                        target_movies.append(m)

            elif "Transformers" in bname:
                for m in all_movies:
                    mnorm = m["Name"].lower()
                    if "transformers" in mnorm or "bumblebee" in mnorm:
                        target_movies.append(m)

            # Deduplicate & Sort
            unique = {m["Id"]: m for m in target_movies}
            sorted_targets = sorted(unique.values(), key=lambda x: (x.get("ProductionYear") or 9999, x.get("Name", "")))

            if sorted_targets:
                ids_str = ",".join([m["Id"] for m in sorted_targets])
                self.api_request(f"/Collections/{bid}/Items?ids={ids_str}", method="POST")
                updated_count += 1
                emit_log(f"Collection '{bname}' synchronized with {len(sorted_targets)} movies.")

        # Refresh collections folder
        virtual_folders = self.api_request("/Library/VirtualFolders")
        if virtual_folders:
            for vf in virtual_folders:
                if vf.get("Name") == "Collections":
                    cid = vf.get("ItemId")
                    if cid:
                        self.api_request(f"/Items/{cid}/Refresh?Recursive=true", method="POST")

        emit_log(f"=== Collections Synchronization Complete ({updated_count} collections updated) ===")
        return {"success": True, "updated_count": updated_count}

collections_mgr = CollectionsManager()
