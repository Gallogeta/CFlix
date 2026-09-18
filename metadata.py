import re
import urllib.request
import urllib.parse
import json
from typing import Dict, Any, List, Optional

TITLE_MAP = {
    "parasites": "Parasite",
    "electra": "Elektra",
    "tumstone": "Tombstone",
    "tombstoun": "Tombstone",
    "death to her face": "Death Becomes Her",
    "star troop": "Starship Troopers",
    "starship troopers": "Starship Troopers",
    "izgoy one": "Rogue One: A Star Wars Story",
    "rogue one": "Rogue One: A Star Wars Story",
    "ghostbusters 2": "Ghostbusters II",
    "ghostbusters ii": "Ghostbusters II",
    "star wars episode 6": "Star Wars: Episode VI - Return of the Jedi",
    "star wars return of the jedi": "Star Wars: Episode VI - Return of the Jedi",
    "saw playing survival": "Saw",
    "mad max the road of fury": "Mad Max: Fury Road",
    "cruella sterwell": "Cruella",
    "cruella": "Cruella",
    "birds of prey the stunning story": "Birds of Prey",
    "birds of prey": "Birds of Prey",
    "frieren beyond jurney's end": "Frieren: Beyond Journey's End",
    "frieren beyond journey's end": "Frieren: Beyond Journey's End",
    "sousou no frieren": "Frieren: Beyond Journey's End",
    "frieren": "Frieren: Beyond Journey's End"
}

AUDIO_CHANNELS_REGEX = r"(?:\b(?:aac|ddp|dd\+|dd|ac3|dts(?:-hd)?|truehd|flac|eac3)[\.\-_]*)?\b(?:5\.1|7\.1|7\.2|5\.2|2\.0|1\.0)\b"

MEDIA_TAGS_REGEX = (
    r"\b(?:2160p|1080p|1080i|720p|576p|480p|360p|4k|8k|uhd|hdr|hdr10(?:\+)?|dv|dovi|dolby-vision|sdr|"
    r"remux|bluray|blu-ray|bdrip|brrip|web-?dl|webrip|web-?rip|hdrip|dvdrip|dvd|hdtv|sdtv|pdtv|dsr|"
    r"x264|x265|h264|h265|h\.264|h\.265|hevc|avc|av1|vc1|divx|xvid|10bit|8bit|12bit|hi10p|"
    r"proper|repack|rerip|unrated|extended|directors\.cut|imax|criterion|"
    r"amzn|amazon|nf|netflix|atvp|apple|dnp|dsnp|disney|hmax|max|itunes|"
    r"aac|ac3|eac3|ddp|dts|dts-hd(?:-ma)?|truehd|atmos|flac|opus|mp3|lpcm|vorbis)\b"
)

CLEAN_REGEXES = [
    r"^watch\s+(?:the\s+)?(?:movie\s+|film\s+)?",
    r"\s+(?:movie|film)?\s*online\s+(?:for\s+)?(?:is\s+)?free[^\.]*",
    r"\s+online\s+free[^\.]*",
    r"\s+in\s+good\s+quality[^\.]*",
    AUDIO_CHANNELS_REGEX,
    MEDIA_TAGS_REGEX,
    r"rezka|voidboost|filmix|hdrezka",
]

SERIES_REGEXES = [
    r"[sS](\d{1,2})[ \.\-_]*[eE](\d{1,3})",
    r"(\d{1,2})x(\d{1,3})",
    r"[sS]eason\s*(\d{1,2})\s*[eE]pisode\s*(\d{1,3})",
    r"(?:^|[ \.\-_])(?:episode|ep)[ \.\-_]*(\d{1,4})"
]

def clean_filename(filename: str) -> Dict[str, Any]:
    # Extract extension
    parts = filename.rsplit(".", 1)
    base_name = parts[0]
    ext = parts[1].lower() if len(parts) > 1 else "mp4"

    # 1. Strip release groups e.g. [SubsPlease], [Erai-raws], [Judas], (Group)
    m_grp = re.match(r"^[\[\(]([a-zA-Z0-9_\-\.\s]+)[\]\)]\s*", base_name)
    release_group = None
    if m_grp:
        release_group = m_grp.group(1).strip()
        base_name = base_name[m_grp.end():].strip()

    # 2. Strip CRC32 hashes like [7E1C8360]
    base_name = re.sub(r"\[[0-9a-fA-F]{8}\]", "", base_name)

    # 3. Strip trailing release/scene suffix (e.g. -FLUX, -FGT, -RARBG, -YTS.MX)
    base_name = re.sub(r"-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)?$", "", base_name)

    # 4. Strip bracketed quality/media tags: [1080p], (1080p), [Multiple Subtitle], etc.
    tag_clean_filter = lambda m: "" if re.search(r"1080p|720p|480p|2160p|4k|bdrip|web|x26|h26|hevc|hi10p|10bit|8bit|aac|flac|opus|dts|ac3|dual|sub|proper|repack|amzn|nf", m.group(0), re.I) else m.group(0)
    base_name = re.sub(r"\[[^\]]+\]|\([^\)]+\)", tag_clean_filter, base_name).strip(" -_.")

    is_series = False
    season_num = None
    episode_num = None
    series_show_name = None
    episode_title = None
    guessed_year = None

    # Detect season if mentioned in text (e.g. "Season 2", "2nd Season")
    m_s = re.search(r"\b(?:season\s*(\d{1,2})|(\d{1,2})(?:nd|rd|th|st)\s*season)\b", base_name, re.I)
    detected_season = int(m_s.group(1) or m_s.group(2)) if m_s else 1

    # Pattern A: Check standard series patterns: ShowName S01E02 EpTitle / 1x02 / Season 1 Episode 2
    m = re.search(
        r"^(.*?)[ \.\-_]+(?:[sS](\d{1,2})[ \.\-_]*[eE](\d{1,3})|(\d{1,2})x(\d{1,3})|[sS]eason[ \.\-_]*(\d{1,2})[ \.\-_]+[eE]pisode[ \.\-_]*(\d{1,3}))(?:[ \.\-_]+(.*?))?$",
        base_name,
        re.IGNORECASE
    )
    if m:
        is_series = True
        raw_show = m.group(1)
        year_m = re.search(r"\b(19\d\d|20[0-3]\d)\b", raw_show)
        if year_m:
            guessed_year = year_m.group(1)
            raw_show = re.sub(r"\b(19\d\d|20[0-3]\d)\b", "", raw_show)
        
        series_show_name = re.sub(r"[_\.\-\+]+", " ", raw_show).strip(" -_.")
        season_num = int(m.group(2) or m.group(4) or m.group(6) or detected_season)
        episode_num = int(m.group(3) or m.group(5) or m.group(7))
        
        rest = m.group(8) or ""
        rest_clean = re.sub(AUDIO_CHANNELS_REGEX, "", rest, flags=re.I)
        rest_clean = re.sub(MEDIA_TAGS_REGEX, "", rest_clean, flags=re.I)
        rest_clean = re.sub(r"[_\.\-\+]+", " ", rest_clean).strip(" -_.")
        if rest_clean:
            episode_title = rest_clean
    else:
        # Pattern B: Check explicit Episode prefix: e.g. "Show - Episode 01" or "Show - Ep 02"
        m_ep = re.search(r"^(.*?)[ \.\-_]+(?:episode|ep)[ \.\-_]*(\d{1,4})(?:[ \.\-_]+(.*?))?$", base_name, re.I)
        if m_ep:
            is_series = True
            raw_show = m_ep.group(1)
            year_m = re.search(r"\b(19\d\d|20[0-3]\d)\b", raw_show)
            if year_m:
                guessed_year = year_m.group(1)
                raw_show = re.sub(r"\b(19\d\d|20[0-3]\d)\b", "", raw_show)
            series_show_name = re.sub(r"[_\.\-\+]+", " ", raw_show).strip(" -_.")
            season_num = detected_season
            episode_num = int(m_ep.group(2))
            rest = m_ep.group(3) or ""
            rest_clean = re.sub(AUDIO_CHANNELS_REGEX, "", rest, flags=re.I)
            rest_clean = re.sub(MEDIA_TAGS_REGEX, "", rest_clean, flags=re.I)
            rest_clean = re.sub(r"[_\.\-\+]+", " ", rest_clean).strip(" -_.")
            if rest_clean:
                episode_title = rest_clean
        else:
            # Pattern C: Check Anime dash format: e.g. "Show Name - 01" or "Show Name - 01 - Episode Title"
            m_anime = re.search(r"^(.*?)\s+[-_–—]\s*(\d{1,4})(?:\s+[-_–—]\s*(.*?))?$", base_name)
            if m_anime and not re.search(r"^\d{4}$", m_anime.group(2)):
                is_series = True
                series_show_name = m_anime.group(1).strip(" -_.")
                season_num = detected_season
                episode_num = int(m_anime.group(2))
                if m_anime.group(3):
                    rest_clean = re.sub(AUDIO_CHANNELS_REGEX, "", m_anime.group(3), flags=re.I)
                    rest_clean = re.sub(MEDIA_TAGS_REGEX, "", rest_clean, flags=re.I)
                    rest_clean = re.sub(r"[_\.\-\+]+", " ", rest_clean).strip(" -_.")
                    if rest_clean:
                        episode_title = rest_clean

    # Detect year if not already found
    if not guessed_year:
        years = re.findall(r"\b(19\d\d|20[0-3]\d)\b", base_name)
        if years:
            guessed_year = years[-1] if len(years) > 1 and years[0] == "1917" else years[0]

    # Clean title string
    if is_series and series_show_name:
        cleaned = series_show_name
    else:
        cleaned = base_name
        cleaned = re.sub(AUDIO_CHANNELS_REGEX, " ", cleaned, flags=re.I)
        cleaned = re.sub(MEDIA_TAGS_REGEX, " ", cleaned, flags=re.I)
        for r in CLEAN_REGEXES:
            cleaned = re.sub(r, " ", cleaned, flags=re.IGNORECASE)
        if guessed_year:
            m_y = re.search(r"^(.*?)[ \.\-_\(\[]+" + guessed_year, cleaned)
            if m_y and m_y.group(1).strip():
                cleaned = m_y.group(1)
            else:
                cleaned = re.sub(r"[\(\[]?\s*" + guessed_year + r"\s*[\)\]]?", " ", cleaned)

    # Clean empty brackets/parentheses and normalize spaces
    cleaned = re.sub(r"[\(\[\{]\s*[\)\]\}]", "", cleaned)
    cleaned = re.sub(r"[_\.\-\+]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")

    # Check title map
    cleaned_lower = cleaned.lower()
    for k, v in TITLE_MAP.items():
        if k in cleaned_lower:
            cleaned = v
            if is_series:
                series_show_name = v
            break

    return {
        "original_filename": filename,
        "cleaned_title": cleaned,
        "series_show_name": series_show_name or (cleaned if is_series else None),
        "guessed_year": guessed_year,
        "is_series": is_series,
        "season": season_num,
        "episode": episode_num,
        "episode_title": episode_title,
        "release_group": release_group,
        "extension": ext
    }

EPISODES_CACHE: Dict[str, Any] = {}

def fetch_series_episodes(series_name: str, imdb_id: Optional[str] = None) -> Dict[str, Any]:
    cache_key = f"{imdb_id or ''}:{series_name.strip().lower()}"
    if cache_key in EPISODES_CACHE:
        return EPISODES_CACHE[cache_key]

    episodes = []
    show_name = series_name

    # 1. Try TVmaze by IMDb ID if provided
    if imdb_id:
        try:
            url = f"https://api.tvmaze.com/lookup/shows?imdb={imdb_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=6) as r:
                d = json.loads(r.read().decode("utf-8"))
                show_id = d.get("id")
                show_name = d.get("name") or show_name
                ep_url = f"https://api.tvmaze.com/shows/{show_id}/episodes"
                req_ep = urllib.request.Request(ep_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req_ep, timeout=6) as r_ep:
                    raw_eps = json.loads(r_ep.read().decode("utf-8"))
                    for ep in raw_eps:
                        episodes.append({
                            "season": ep.get("season", 1),
                            "episode": ep.get("number", 1),
                            "title": ep.get("name", "")
                        })
                    if episodes:
                        res = {"success": True, "source": "tvmaze_imdb", "show": show_name, "episodes": episodes}
                        EPISODES_CACHE[cache_key] = res
                        return res
        except Exception as e:
            print(f"TVmaze IMDb lookup failed for '{imdb_id}': {e}")

    # 2. Try TVmaze by text query
    cleaned_query = series_name.strip()
    for k, v in TITLE_MAP.items():
        if k in cleaned_query.lower():
            cleaned_query = v
            break

    if cleaned_query:
        try:
            encoded_q = urllib.parse.quote(cleaned_query)
            url = f"https://api.tvmaze.com/singlesearch/shows?q={encoded_q}&embed=episodes"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=6) as r:
                d = json.loads(r.read().decode("utf-8"))
                show_name = d.get("name") or show_name
                raw_eps = d.get("_embedded", {}).get("episodes", [])
                for ep in raw_eps:
                    episodes.append({
                        "season": ep.get("season", 1),
                        "episode": ep.get("number", 1),
                        "title": ep.get("name", "")
                    })
                if episodes:
                    res = {"success": True, "source": "tvmaze_search", "show": show_name, "episodes": episodes}
                    EPISODES_CACHE[cache_key] = res
                    return res
        except Exception as e:
            print(f"TVmaze query failed for '{cleaned_query}': {e}")

    res = {"success": False, "source": "none", "show": show_name, "episodes": []}
    return res

def search_imdb(query: str) -> List[Dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    
    # Check title map first
    q_lower = query.lower()
    for k, v in TITLE_MAP.items():
        if k in q_lower:
            query = v
            break

    encoded = urllib.parse.quote(query)
    first_char = query[0].lower() if query else "a"
    url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{encoded}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("d", [])
            matches = []
            for item in results:
                qid = item.get("qid")
                if qid in ("movie", "tvMovie", "tvSeries", "tvMiniSeries") and "y" in item:
                    poster_url = None
                    if "i" in item and "imageUrl" in item["i"]:
                        poster_url = item["i"]["imageUrl"]
                    matches.append({
                        "title": item.get("l"),
                        "year": str(item.get("y")),
                        "imdb_id": item.get("id"),
                        "type": "series" if "tv" in (qid or "") else "movie",
                        "actors": item.get("s", ""),
                        "poster": poster_url
                    })
            return matches
    except Exception as e:
        print(f"IMDb search error for '{query}': {e}")
        return []

ANIME_EPISODES_CACHE: Dict[str, Any] = {}

def search_anime(query: str) -> List[Dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    q_lower = query.lower()
    for k, v in TITLE_MAP.items():
        if k in q_lower:
            query = v
            break

    encoded = urllib.parse.quote(query)
    url = f"https://kitsu.io/api/edge/anime?filter[text]={encoded}&page[limit]=10"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.api+json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            matches = []
            for item in data.get("data", []):
                attr = item.get("attributes", {})
                subtype = (attr.get("subtype") or "tv").lower()
                is_movie = subtype in ("movie", "special")
                titles = attr.get("titles", {})
                chosen_title = titles.get("en") or attr.get("canonicalTitle") or titles.get("en_jp") or ""
                jp_title = titles.get("ja_jp") or ""
                year = (attr.get("startDate") or "")[:4]
                poster = attr.get("posterImage", {}).get("medium") or attr.get("posterImage", {}).get("original") or None
                eps = attr.get("episodeCount")
                eps_label = f"{eps} eps" if eps else "Unknown eps"
                actors_desc = f"Anime ({subtype.upper()}) • {eps_label}"
                if jp_title:
                    actors_desc += f" • {jp_title}"

                matches.append({
                    "title": chosen_title,
                    "year": year,
                    "imdb_id": f"kitsu-{item.get('id')}",
                    "type": "movie" if is_movie else "series",
                    "actors": actors_desc,
                    "poster": poster,
                    "subtype": subtype,
                    "source": "anime_db"
                })
            return matches
    except Exception as e:
        print(f"Anime search error for \x27{query}\x27: {e}")
        return []

def fetch_anime_episodes(kitsu_id_or_query: str, series_name: str = "") -> Dict[str, Any]:
    cache_key = f"anime:{kitsu_id_or_query.strip().lower()}:{series_name.strip().lower()}"
    if cache_key in ANIME_EPISODES_CACHE:
        return ANIME_EPISODES_CACHE[cache_key]

    anime_id = kitsu_id_or_query
    if anime_id.startswith("kitsu-"):
        anime_id = anime_id.replace("kitsu-", "")

    if not anime_id.isdigit():
        q = series_name or kitsu_id_or_query
        res = search_anime(q)
        if res and res[0].get("imdb_id", "").startswith("kitsu-"):
            anime_id = res[0]["imdb_id"].replace("kitsu-", "")
            series_name = series_name or res[0]["title"]
        else:
            return fetch_series_episodes(series_name or kitsu_id_or_query)

    episodes = []
    try:
        offset = 0
        while True:
            url = f"https://kitsu.io/api/edge/episodes?filter[mediaType]=Anime&filter[media_id]={anime_id}&page[limit]=20&page[offset]={offset}&sort=number"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.api+json"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                batch = data.get("data", [])
                if not batch:
                    break
                for ep in batch:
                    ep_attr = ep.get("attributes", {})
                    ep_num = ep_attr.get("number") or ep_attr.get("relativeNumber") or (len(episodes) + 1)
                    ep_season = ep_attr.get("seasonNumber") or 1
                    ep_title = ep_attr.get("canonicalTitle") or ep_attr.get("titles", {}).get("en") or ep_attr.get("titles", {}).get("en_jp") or f"Episode {ep_num}"
                    episodes.append({
                        "season": ep_season,
                        "episode": ep_num,
                        "title": ep_title
                    })
                if len(batch) < 20 or offset >= 500:
                    break
                offset += 20
        if episodes:
            res = {"success": True, "source": "kitsu_anime", "show": series_name, "episodes": episodes}
            ANIME_EPISODES_CACHE[cache_key] = res
            return res
    except Exception as e:
        print(f"Kitsu episodes lookup failed: {e}")

    return fetch_series_episodes(series_name)
