import os
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

from config import (
    get_jellyfin_url, get_jellyfin_user, get_jellyfin_pass
)
from logger import emit_log

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
CUSTOM_THEMES_FILE = os.path.join(DATA_DIR, "custom_themes.json")
ACTIVE_THEME_FILE = os.path.join(DATA_DIR, "active_theme.json")

# Load Garchy OS Obsidian Glass CSS from file if available, or fallback
GARCHY_CSS_FILE = os.path.join(os.path.dirname(__file__), "themes", "garchy_obsidian.css")
GARCHY_OBSIDIAN_CSS = ""
if os.path.exists(GARCHY_CSS_FILE):
    try:
        with open(GARCHY_CSS_FILE, "r", encoding="utf-8") as f:
            GARCHY_OBSIDIAN_CSS = f.read()
    except Exception as e:
        emit_log(f"Warning: Could not read {GARCHY_CSS_FILE}: {e}")

MONOCHROME_CSS_FILE = os.path.join(os.path.dirname(__file__), "themes", "monochrome_square.css")
MONOCHROME_SQUARE_CSS = ""
if os.path.exists(MONOCHROME_CSS_FILE):
    try:
        with open(MONOCHROME_CSS_FILE, "r", encoding="utf-8") as f:
            MONOCHROME_SQUARE_CSS = f.read()
    except Exception as e:
        emit_log(f"Warning: Could not read {MONOCHROME_CSS_FILE}: {e}")

if not GARCHY_OBSIDIAN_CSS:
    GARCHY_OBSIDIAN_CSS = """/* --- Garchy OS Obsidian Glass Jellyfin Theme --- */
:root {
  --accent: #38bdf8;
  --accent-blue: #3b82f6;
  --accent-gold: #fbbf24;
  --bg-dark: #0a0f1d;
  --card-glass: rgba(19, 28, 49, 0.65);
  --border-glass: rgba(56, 189, 248, 0.2);
}
body, .backgroundContainer {
  background-color: var(--bg-dark) !important;
}
.cardBox, .card {
  background: var(--card-glass) !important;
  backdrop-filter: blur(12px) !important;
  -webkit-backdrop-filter: blur(12px) !important;
  border: 1px solid var(--border-glass) !important;
  border-radius: 12px !important;
  transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease !important;
}
.card:hover {
  transform: translateY(-4px) scale(1.02);
  border-color: var(--accent) !important;
  box-shadow: 0 8px 24px rgba(56, 189, 248, 0.25) !important;
}
.skinHeader-withBackground {
  background: rgba(10, 15, 29, 0.85) !important;
  backdrop-filter: blur(16px) !important;
  border-bottom: 1px solid var(--border-glass) !important;
}
.button-accent, .button-flat:hover, .raised.emby-button {
  background: linear-gradient(135deg, var(--accent-blue), var(--accent)) !important;
  color: #ffffff !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
}
.itemProgressBarForeground {
  background: linear-gradient(90deg, var(--accent-blue), var(--accent)) !important;
}
.starRating, .mediaInfoItem.mediaInfoOfficialRating {
  color: var(--accent-gold) !important;
}
"""

BUILTIN_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "monochrome_square",
        "name": "Monochrome Modern Square",
        "description": "Architectural monochrome aesthetic: deep obsidian blacks, pure white accents, strictly 100% square borders, and high-contrast hover transitions.",
        "badge": "Modern Square",
        "accent": "#ffffff",
        "gradient": "linear-gradient(135deg, #050505 0%, #1c1c1c 50%, #ffffff 100%)",
        "css": MONOCHROME_SQUARE_CSS
    },
    {
        "id": "garchy_obsidian",
        "name": "Garchy OS Obsidian Glass",
        "description": "Bespoke 5-color dark rice: Deep obsidian #0a0f1d, cyan border highlights, gold badges, and frosted cards.",
        "badge": "Default Garchy",
        "accent": "#38bdf8",
        "gradient": "linear-gradient(135deg, #0a0f1d 0%, #1e293b 50%, #38bdf8 100%)",
        "css": GARCHY_OBSIDIAN_CSS
    },
    {
        "id": "jellyflix",
        "name": "Jellyflix (Netflix Style)",
        "description": "Sleek Netflix streaming interface featuring red accents, horizontal carousels, and dark backdrop.",
        "badge": "Popular",
        "accent": "#e50914",
        "gradient": "linear-gradient(135deg, #141414 0%, #221f1f 50%, #e50914 100%)",
        "css": '/* Jellyflix - Netflix Style Theme */\n@import url("https://cdn.jsdelivr.net/gh/prayag17/JellyFlix@latest/default.css");\n'
    },
    {
        "id": "jellyskin",
        "name": "JellySkin (Modern UI)",
        "description": "Award-winning clean modern design with subtle shadows, rounded cards, and smooth navigation.",
        "badge": "Modern",
        "accent": "#8b5cf6",
        "gradient": "linear-gradient(135deg, #0f172a 0%, #2e1065 50%, #8b5cf6 100%)",
        "css": '/* JellySkin - Modern UI Theme */\n@import url("https://cdn.jsdelivr.net/npm/jellyskin@latest/dist/main.css");\n'
    },
    {
        "id": "ultrachromic",
        "name": "Ultrachromic (Frosted Glass)",
        "description": "Modern frosted translucent glass cards, dynamic background blur, and refined controls.",
        "badge": "Glassmorphism",
        "accent": "#a855f7",
        "gradient": "linear-gradient(135deg, #0f172a 0%, #312e81 50%, #a855f7 100%)",
        "css": '/* Ultrachromic - Modern Frosted Glass */\n@import url("https://cdn.jsdelivr.net/gh/CTalvio/Ultrachromic/base.css");\n'
    },
    {
        "id": "novachromic",
        "name": "Novachromic (Minimalist Dark)",
        "description": "Futuristic clean dark aesthetic with minimalist cards, neon lines, and smooth transitions.",
        "badge": "Minimal Dark",
        "accent": "#06b6d4",
        "gradient": "linear-gradient(135deg, #030712 0%, #111827 50%, #06b6d4 100%)",
        "css": '/* Novachromic - Minimalist Dark */\n@import url("https://ctalvio.github.io/Novachromic/default_style.css");\n'
    },
    {
        "id": "vanilla",
        "name": "Vanilla Stock Jellyfin",
        "description": "Completely clears custom styling and resets Jellyfin to standard vanilla factory theme.",
        "badge": "Stock",
        "accent": "#00a4dc",
        "gradient": "linear-gradient(135deg, #101010 0%, #1c1c1c 50%, #00a4dc 100%)",
        "css": ""
    }
]

class ThemeManager:
    def __init__(self):
        self._custom_presets: List[Dict[str, Any]] = []
        self._active_preset_id: Optional[str] = None
        self._load_storage()

    def _load_storage(self):
        if os.path.exists(CUSTOM_THEMES_FILE):
            try:
                with open(CUSTOM_THEMES_FILE, "r", encoding="utf-8") as f:
                    self._custom_presets = json.load(f)
            except Exception as e:
                emit_log(f"Error loading custom themes: {e}")
                self._custom_presets = []
        
        if os.path.exists(ACTIVE_THEME_FILE):
            try:
                with open(ACTIVE_THEME_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._active_preset_id = data.get("active_preset_id")
            except Exception:
                pass

    def _save_storage(self):
        try:
            with open(CUSTOM_THEMES_FILE, "w", encoding="utf-8") as f:
                json.dump(self._custom_presets, f, indent=2)
        except Exception as e:
            emit_log(f"Error saving custom themes: {e}")

    def _save_active(self, preset_id: Optional[str]):
        self._active_preset_id = preset_id
        try:
            with open(ACTIVE_THEME_FILE, "w", encoding="utf-8") as f:
                json.dump({"active_preset_id": preset_id}, f, indent=2)
        except Exception as e:
            emit_log(f"Error saving active theme: {e}")

    def get_jellyfin_auth_token(self) -> Optional[str]:
        base_url = get_jellyfin_url()
        user = get_jellyfin_user()
        password = get_jellyfin_pass()
        if not base_url or not user:
            return None

        auth_val = 'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0"'
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_val,
            "X-Emby-Authorization": auth_val,
            "User-Agent": "CFlixMediaManager/1.0"
        }
        payload = {"Username": user, "Pw": password}
        req = urllib.request.Request(
            f"{base_url}/Users/AuthenticateByName",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("AccessToken")
        except Exception as e:
            emit_log(f"ThemeManager auth failed: {e}")
            return None

    def get_all_presets(self) -> List[Dict[str, Any]]:
        return BUILTIN_PRESETS + self._custom_presets

    def get_theme_status(self) -> Dict[str, Any]:
        base_url = get_jellyfin_url()
        presets = self.get_all_presets()
        active_css = ""
        is_connected = False
        login_disclaimer = ""
        splash_enabled = True

        token = self.get_jellyfin_auth_token()
        if token and base_url:
            auth_hdr = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
            headers = {
                "Authorization": auth_hdr,
                "X-Emby-Authorization": auth_hdr,
                "X-MediaBrowser-Token": token,
                "X-Emby-Token": token,
                "User-Agent": "CFlixMediaManager/1.0"
            }
            try:
                b_req = urllib.request.Request(f"{base_url}/Branding/Configuration", headers=headers)
                with urllib.request.urlopen(b_req, timeout=5) as b_res:
                    cfg = json.loads(b_res.read().decode("utf-8"))
                    active_css = cfg.get("CustomCss", "") or ""
                    login_disclaimer = cfg.get("LoginDisclaimer", "") or ""
                    splash_enabled = cfg.get("SplashscreenEnabled", True)
                    is_connected = True
            except Exception as e:
                emit_log(f"ThemeManager: Could not fetch branding config from Jellyfin: {e}")

        # Detect active preset if not explicitly tracked or if changed externally
        detected_id = self._active_preset_id
        if active_css:
            for p in presets:
                if p.get("css", "").strip() == active_css.strip():
                    detected_id = p["id"]
                    break
        elif is_connected:
            detected_id = "vanilla"

        return {
            "success": True,
            "connected": is_connected,
            "jellyfin_url": base_url,
            "active_preset_id": detected_id,
            "active_css": active_css,
            "login_disclaimer": login_disclaimer,
            "splash_enabled": splash_enabled,
            "presets": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "badge": p.get("badge", ""),
                    "accent": p.get("accent", "#38bdf8"),
                    "gradient": p.get("gradient", ""),
                    "is_custom": p.get("is_custom", False),
                    "css": p.get("css", "")
                }
                for p in presets
            ]
        }

    def apply_theme(self, css: str, preset_id: Optional[str] = None) -> Dict[str, Any]:
        base_url = get_jellyfin_url()
        token = self.get_jellyfin_auth_token()
        if not base_url or not token:
            return {"success": False, "error": "Could not authenticate with Jellyfin server."}

        auth_hdr = f'MediaBrowser Client="CFlixMediaManager", Device="Server", DeviceId="CFMM", Version="1.0.0", Token="{token}"'
        headers = {
            "Content-Type": "application/json",
            "Authorization": auth_hdr,
            "X-Emby-Authorization": auth_hdr,
            "X-MediaBrowser-Token": token,
            "X-Emby-Token": token,
            "User-Agent": "CFlixMediaManager/1.0"
        }

        # 1. Fetch current branding configuration to preserve splashscreen & disclaimer
        existing_cfg = {"LoginDisclaimer": "", "CustomCss": "", "SplashscreenEnabled": True}
        try:
            b_req = urllib.request.Request(f"{base_url}/Branding/Configuration", headers=headers)
            with urllib.request.urlopen(b_req, timeout=5) as b_res:
                existing_cfg = json.loads(b_res.read().decode("utf-8"))
        except Exception as e:
            emit_log(f"Warning: Failed to fetch prior branding config before saving: {e}")

        existing_cfg["CustomCss"] = css

        # 2. Update via POST /System/Configuration/Branding (or fallback /Branding/Configuration)
        applied = False
        endpoints = ["/System/Configuration/Branding", "/Branding/Configuration"]
        for ep in endpoints:
            try:
                post_req = urllib.request.Request(
                    f"{base_url}{ep}",
                    data=json.dumps(existing_cfg).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(post_req, timeout=6) as post_res:
                    if post_res.status in (200, 204):
                        applied = True
                        break
            except Exception as e:
                emit_log(f"ThemeManager: POST to {ep} returned error: {e}")

        if applied:
            self._save_active(preset_id)
            preset_label = preset_id or "Custom CSS"
            emit_log(f"[THEME] Successfully applied theme '{preset_label}' to Jellyfin ({base_url}) on the fly.")
            return {"success": True, "active_preset_id": preset_id, "css_len": len(css)}
        else:
            return {"success": False, "error": "Jellyfin API rejected branding update."}

    def save_custom_preset(self, name: str, css: str, description: str = "") -> Dict[str, Any]:
        preset_id = "custom_" + str(abs(hash(name)))[:8]
        new_preset = {
            "id": preset_id,
            "name": name.strip(),
            "description": description.strip() or "User saved custom style preset.",
            "badge": "Custom",
            "accent": "#38bdf8",
            "gradient": "linear-gradient(135deg, #0a0f1d 0%, #1e293b 50%, #38bdf8 100%)",
            "is_custom": True,
            "css": css
        }
        # Remove existing if same ID or name
        self._custom_presets = [p for p in self._custom_presets if p["id"] != preset_id and p["name"] != name]
        self._custom_presets.append(new_preset)
        self._save_storage()
        emit_log(f"[THEME] Saved custom preset '{name}'")
        return {"success": True, "preset": new_preset}

    def delete_custom_preset(self, preset_id: str) -> Dict[str, Any]:
        initial_len = len(self._custom_presets)
        self._custom_presets = [p for p in self._custom_presets if p["id"] != preset_id]
        if len(self._custom_presets) < initial_len:
            self._save_storage()
            emit_log(f"[THEME] Deleted custom preset '{preset_id}'")
            return {"success": True}
        return {"success": False, "error": "Preset not found"}

theme_mgr = ThemeManager()
