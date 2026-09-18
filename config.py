import os
import json
import urllib.request
import urllib.parse
from typing import Dict, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

import re
from urllib.parse import urlparse

def normalize_jellyfin_url(url: str) -> str:
    """Cleans and normalizes any Jellyfin server URL or address entered by user."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    # Strip any fragments (e.g. #/home)
    url = url.split("#")[0]
    # Strip any /web or /web/... paths
    url = re.sub(r"/web(?:/.*)?$", "", url, flags=re.IGNORECASE)
    return url.rstrip("/")

# Clean, Generic Default Profile (Configurable via UI or Environment Variables)
DEFAULT_SETTINGS: Dict[str, Any] = {
    "PORT": int(os.environ.get("PORT", 8090)),
    "HOST": os.environ.get("HOST", "0.0.0.0"),
    "JELLYFIN_URL": normalize_jellyfin_url(os.environ.get("JELLYFIN_URL", "")),
    "JELLYFIN_USER": os.environ.get("JELLYFIN_USER", ""),
    "JELLYFIN_PASS": os.environ.get("JELLYFIN_PASS", ""),
    "MOVIES_DIR": os.environ.get("MOVIES_DIR", "/media/movies"),
    "SERIES_DIR": os.environ.get("SERIES_DIR", "/media/tv"),
    "ANIME_DIR": os.environ.get("ANIME_DIR", "/media/anime"),
    "ADULT_DIR": os.environ.get("ADULT_DIR", "/media/adult"),
    "MEDIA_ROOT": os.environ.get("MEDIA_ROOT", "/media"),
    "JELLYFIN_MEDIA_PATH": os.environ.get("JELLYFIN_MEDIA_PATH", "/media"),
    "WATCH_DIR": os.environ.get("WATCH_DIR", "/downloads"),
    "STAGING_DIR": os.environ.get("STAGING_DIR", "/downloads/.staging"),
    "UPLOAD_TMP_DIR": os.environ.get("UPLOAD_TMP_DIR", "/tmp/cfmm_uploads"),
    "WATCHER_ENABLED": os.environ.get("WATCHER_ENABLED", "true").lower() == "true",
    "WATCHER_INTERVAL": int(os.environ.get("WATCHER_INTERVAL", 10))
}

class ConfigManager:
    def __init__(self):
        self._settings: Dict[str, Any] = {}
        self.load()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    # Merge with defaults so new fields are never missing
                    merged = dict(DEFAULT_SETTINGS)
                    merged.update(saved)
                    self._settings = merged
                    return
            except Exception as e:
                print(f"[CFMM] Error loading {SETTINGS_FILE}: {e}")
        
        # If file doesn't exist or failed to load, initialize with defaults
        self._settings = dict(DEFAULT_SETTINGS)
        self.save()

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            print(f"[CFMM] Error saving {SETTINGS_FILE}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any):
        if key == "JELLYFIN_URL" and isinstance(value, str):
            value = normalize_jellyfin_url(value)
        self._settings[key] = value
        self.save()

    def update(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        # Filter and sanitize
        allowed_keys = set(DEFAULT_SETTINGS.keys())
        for k, v in new_settings.items():
            if k in allowed_keys:
                if k in ("PORT", "WATCHER_INTERVAL"):
                    try:
                        self._settings[k] = int(v)
                    except (ValueError, TypeError):
                        pass
                elif k in ("WATCHER_ENABLED",):
                    self._settings[k] = bool(v)
                elif isinstance(v, str):
                    # Clean trailing slashes for paths and URLs
                    v_clean = v.strip()
                    if k.endswith("_DIR") or k in ("MEDIA_ROOT", "JELLYFIN_MEDIA_PATH"):
                        if v_clean and not v_clean.startswith("/") and not v_clean.startswith("\\"):
                            v_clean = "/" + v_clean
                        v_clean = os.path.normpath(v_clean)
                    elif k == "JELLYFIN_URL":
                        v_clean = normalize_jellyfin_url(v_clean)
                    self._settings[k] = v_clean
                else:
                    self._settings[k] = v
        self.save()
        return self.get_all()

    def get_all(self) -> Dict[str, Any]:
        data = dict(self._settings)
        return data

    def test_jellyfin(self, url: str, user: str, pw: str) -> Dict[str, Any]:
        if not url:
            return {"success": False, "error": "Media server URL is not configured."}
        url = normalize_jellyfin_url(url)
        if not url:
            return {"success": False, "error": "Invalid media server URL."}

        candidates = [url]
        if not url.endswith("/jellyfin"):
            candidates.append(f"{url}/jellyfin")

        auth_value = 'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0"'
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_value,
            "X-Emby-Authorization": auth_value,
            "User-Agent": "CFlixMediaManager/1.0"
        }
        payload = {"Username": user, "Pw": pw}
        last_error = "Connection failed"

        for target_url in candidates:
            auth_url = f"{target_url}/Users/AuthenticateByName"
            try:
                req = urllib.request.Request(auth_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=8) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    token = data.get("AccessToken")
                    user_name = data.get("User", {}).get("Name")
                    server_id = data.get("ServerId")
                    return {
                        "success": True,
                        "token": token,
                        "user_name": user_name,
                        "user": data.get("User", {}),
                        "server_id": server_id,
                        "resolved_url": target_url,
                        "message": f"Successfully connected to media server as '{user_name}'!"
                    }
            except urllib.error.HTTPError as e:
                # If credentials are wrong, don't fallback to /jellyfin candidate and return 404
                if e.code == 401:
                    return {"success": False, "error": "Invalid username or password on media server."}
                if e.code in (404, 302, 301) and target_url != candidates[-1]:
                    continue
                last_error = f"HTTP {e.code}: Authentication Failed ({e.reason})"
            except urllib.error.URLError as e:
                if target_url != candidates[-1]:
                    continue
                last_error = f"Network connection error: {e.reason}"
            except Exception as e:
                last_error = f"Connection error: {str(e)}"

        return {"success": False, "error": last_error}

# Global singleton
cfg = ConfigManager()

# Direct convenience property accessors
def get_jellyfin_url() -> str:
    return cfg.get("JELLYFIN_URL", "")

def get_jellyfin_user() -> str:
    return cfg.get("JELLYFIN_USER", "")

def get_jellyfin_pass() -> str:
    return cfg.get("JELLYFIN_PASS", "")

def get_movies_dir() -> str:
    return cfg.get("MOVIES_DIR", "/media/movies")

def get_series_dir() -> str:
    return cfg.get("SERIES_DIR", "/media/tv")

def get_anime_dir() -> str:
    return cfg.get("ANIME_DIR", "/media/anime")

def get_adult_dir() -> str:
    return cfg.get("ADULT_DIR", "/media/adult")

def get_media_root() -> str:
    return cfg.get("MEDIA_ROOT", "/media")

def get_watch_dir() -> str:
    return cfg.get("WATCH_DIR", "/downloads")

def get_staging_dir() -> str:
    return cfg.get("STAGING_DIR", "/downloads/.staging")

def get_upload_tmp_dir() -> str:
    tmp_dir = cfg.get("UPLOAD_TMP_DIR", "/tmp/cfmm_uploads")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir
    except Exception:
        fallback = "/tmp/cfmm_uploads"
        os.makedirs(fallback, exist_ok=True)
        return fallback

PORT = cfg.get("PORT", 8090)
HOST = cfg.get("HOST", "0.0.0.0")
