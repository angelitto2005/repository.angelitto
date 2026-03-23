import hashlib
import json
import os
import random
import re
import string
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from urllib.parse import parse_qsl, quote_plus, urlencode

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from requests.adapters import HTTPAdapter

try:
    import orjson

    def json_loads(s):
        if hasattr(s, "read"):
            s = s.read()
        return orjson.loads(s)

    def json_dumps(obj, fp=None):
        result = orjson.dumps(obj)
        if fp:
            fp.write(result.decode("utf-8") if isinstance(result, bytes) else result)
            return None
        return result.decode("utf-8") if isinstance(result, bytes) else result
except ImportError:

    def json_loads(s):
        if hasattr(s, "read"):
            s = s.read()
        return json.loads(s)

    def json_dumps(obj, fp=None):
        result = json.dumps(obj)
        if fp:
            fp.write(result)
            return None
        return result


from epg import EpgManager, format_epg_tooltip

RE_STREAM_ID = re.compile(r"stream=(\d+)")
RE_MACPH_TOKENPH = re.compile(r"MACPH|TOKENPH")
RE_BOX_CHARS = re.compile(r"[\u2500-\u259F\u2500-\u257F]")
RE_CATEGORY_PREFIX = re.compile(r"^[\|\-\s]+ro[\|\s\:\-\[\(]?", re.IGNORECASE)
RE_EXTINF = re.compile(r"#EXTINF:", re.IGNORECASE)
RE_GROUP_TITLE = re.compile(r'group-title="?([^",]*)"?', re.IGNORECASE)
RE_TVG_LOGO = re.compile(r'tvg-logo=["\']([^"\']*)["\']', re.IGNORECASE)

import threading

# Thread-local storage for HTTP sessions to ensure thread-safety in Mega Search
_session_storage = threading.local()


def get_session():
    """Get or create a thread-safe HTTP session."""
    if not hasattr(_session_storage, "session") or _session_storage.session is None:
        s = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=20, pool_maxsize=30, max_retries=3, pool_block=False
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
                "X-User-Agent": "Model: MAG250; Link: WiFi",
                "Connection": "keep-alive",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        _session_storage.session = s
    return _session_storage.session


TIMEOUTS = {
    "handshake": 5,
    "categories": 10,
    "channels": 20,
    "epg": 15,
    "playlink": 8,
    "play": 15,
}

_portal_response_cache = {}
_PORTAL_CACHE_TTL = 300  # 5 minutes


def get_cached_response(key):
    """Get cached API response if still valid."""
    if key in _portal_response_cache:
        cached = _portal_response_cache[key]
        if time.time() - cached["timestamp"] < _PORTAL_CACHE_TTL:
            return cached["data"]
    return None


def set_cached_response(key, data):
    """Cache API response."""
    _portal_response_cache[key] = {"timestamp": time.time(), "data": data}


# Plugin version
PLUGIN_VERSION = "1.0.4"
MIN_KODI_VERSION = "19.0"
MIN_PYTHON_VERSION = (3, 6)


def check_version_compatibility():
    """Check if the plugin is compatible with the current environment."""
    import platform

    checks_passed = True
    errors = []

    # Check Python version
    current_python = sys.version_info[:2]
    if current_python < MIN_PYTHON_VERSION:
        checks_passed = False
        errors.append(
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ required, found {current_python[0]}.{current_python[1]}"
        )

    # Check Kodi version
    try:
        kodi_version = xbmc.getInfoLabel("System.BuildVersion")
        kodi_major = int(kodi_version.split(".")[0]) if kodi_version else 0
        min_kodi_major = int(MIN_KODI_VERSION.split(".")[0])
        if kodi_major < min_kodi_major:
            checks_passed = False
            errors.append(f"Kodi {MIN_KODI_VERSION}+ required, found {kodi_version}")
    except Exception as e:
        xbmc.log(
            f"[Version] Could not determine Kodi version: {e}", level=xbmc.LOGWARNING
        )

    # Check required modules
    required_modules = ["requests"]
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            checks_passed = False
            errors.append(f"Required module '{module}' not found")

    if not checks_passed:
        error_msg = " | ".join(errors)
        xbmc.log(
            f"[Version] Compatibility checks FAILED: {error_msg}", level=xbmc.LOGERROR
        )
        xbmcgui.Dialog().notification(
            "Version Error",
            f"Plugin may not work correctly: {error_msg}",
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return False

    xbmc.log(
        f"[Version] Compatibility checks PASSED (Python {'.'.join(map(str, current_python))}, Kodi {kodi_version})",
        level=xbmc.LOGINFO,
    )
    return True


# EPG data store
epg_data = {}

# EPG Cache management
EPG_CACHE_FILE = None
EPG_CACHE_TTL = 1800  # 30 minutes in seconds


def get_epg_cache_file():
    """Get the EPG cache file path."""
    global EPG_CACHE_FILE
    if EPG_CACHE_FILE is None:
        # Get Kodi's special path and translate it to real filesystem path
        addon_profile_path = xbmcaddon.Addon().getAddonInfo("profile")
        # Use xbmcvfs.translatePath (or xbmc.translatePath for older Kodi versions)
        try:
            addon_path = xbmcvfs.translatePath(addon_profile_path)
        except:
            # Fallback for older Kodi versions
            addon_path = xbmc.translatePath(addon_profile_path)

        if not os.path.exists(addon_path):
            os.makedirs(addon_path)
        EPG_CACHE_FILE = os.path.join(addon_path, "epg_cache.json")
    return EPG_CACHE_FILE


def load_epg_cache():
    """Load EPG data from cache file."""
    cache_file = get_epg_cache_file()
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json_loads(f)
                current_time = time.time()

                # Load only non-expired entries
                for stream_id, cache_entry in cache_data.items():
                    timestamp = cache_entry.get("timestamp", 0)
                    if current_time - timestamp < EPG_CACHE_TTL:
                        # Convert datetime strings back to datetime objects
                        items = cache_entry.get("items", [])
                        for item in items:
                            if item.get("start_dt"):
                                from datetime import datetime

                                item["start_dt"] = datetime.fromisoformat(
                                    item["start_dt"]
                                )
                            if item.get("end_dt"):
                                from datetime import datetime

                                item["end_dt"] = datetime.fromisoformat(item["end_dt"])
                        epg_data[stream_id] = items

                xbmc.log(
                    f"[EPG] Loaded {len(epg_data)} channels from cache",
                    level=xbmc.LOGDEBUG,
                )
    except Exception as e:
        xbmc.log(f"[EPG] Failed to load cache: {e}", level=xbmc.LOGWARNING)


def save_epg_cache():
    """Save EPG data to cache file."""
    cache_file = get_epg_cache_file()
    try:
        cache_data = {}
        current_time = time.time()

        for stream_id, items in epg_data.items():
            # Convert datetime objects to ISO format strings for JSON
            serializable_items = []
            for item in items:
                serializable_item = item.copy()
                if item.get("start_dt"):
                    serializable_item["start_dt"] = item["start_dt"].isoformat()
                if item.get("end_dt"):
                    serializable_item["end_dt"] = item["end_dt"].isoformat()
                serializable_items.append(serializable_item)

            cache_data[stream_id] = {
                "timestamp": current_time,
                "items": serializable_items,
            }

        with open(cache_file, "w", encoding="utf-8") as f:
            json_dumps(cache_data, f)

        xbmc.log(f"[EPG] Saved {len(cache_data)} channels to cache", level=xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[EPG] Failed to save cache: {e}", level=xbmc.LOGWARNING)


def get_current_program(epg_items):
    """Extract the current program name from EPG items."""
    if not epg_items:
        return None

    from datetime import datetime

    now = datetime.now()

    for item in epg_items:
        start_dt = item.get("start_dt")
        end_dt = item.get("end_dt")

        if start_dt and end_dt:
            if start_dt <= now < end_dt:
                # Current program
                name = item.get("name") or item.get("title") or ""
                return name.strip()

    # If no current program, return the next upcoming one
    for item in epg_items:
        start_dt = item.get("start_dt")
        if start_dt and now < start_dt:
            name = item.get("name") or item.get("title") or ""
            return f"Next: {name.strip()}"

    return None


def epg_callback(channel_key, items):
    xbmc.log(
        f"[DEBUG] EPG callback for channel {channel_key} with {len(items)} items. Data: {items}",
        level=xbmc.LOGDEBUG,
    )
    epg_data[channel_key] = items


# Plugin specific variables
_ADDON = xbmcaddon.Addon()
_HANDLE = int(sys.argv[1])
_BASE_URL = sys.argv[0]


# Check if EPG is enabled
def is_epg_enabled():
    """Check if EPG is enabled in settings."""
    return _ADDON.getSetting("epg_enabled") == "true"


def is_server_check_enabled():
    """Check if automatic server ON/OFF detection is enabled in settings."""
    return _ADDON.getSetting("server_check_enabled") == "true"


# Category mapping and sorting
CATEGORY_MAPPING = {
    # Server 1
    "RO| CANALE DE CINEMA": "Filme",
    "RO| CANALE DE DIVERTISMENT": "Divertisment",
    "RO| CANALE DE SPORT": "Sport",
    "RO| CANALE DOCUMENTARE": "Documentare",
    "RO| CANALE GENERALE": "Generale",
    "RO| CANALE MUZICALE": "Muzica",
    "RO| CANALE PENTRU COPII": "Pentru Copii",
    "RO| FOCUS SAT VIP": "Focus Sat",
    # Server 2
    "RO : ROMAINE": "Generale",
    "RO : COPİİ": "Pentru Copii",
    "RO : DOCU & REALITATE": "Documentare",
    "RO : MUZICÄ": "Muzica",
    "RO : SPORT": "Sport",
    "RO : FILM": "Filme",
}

# Custom sort order for categories
CATEGORY_ORDER = [
    "Generale",
    "Divertisment",
    "Sport",
    "Filme",
    "Documentare",
    "Muzica",
    "Pentru Copii",
    "Focus Sat",
]

# Category icons (using Kodi's built-in icons)
CATEGORY_ICONS = {
    "Generale": "DefaultTVShows.png",
    "Divertisment": "DefaultMusicVideos.png",
    "Sport": "DefaultAddonGame.png",
    "Filme": "DefaultMovies.png",
    "Documentare": "DefaultAddonPVRClient.png",
    "Muzica": "DefaultMusicAlbums.png",
    "Pentru Copii": "DefaultAddonGame.png",
    "Focus Sat": "DefaultAddonService.png",
}


def map_category_name(original_name):
    """Map original category name to display name."""
    return CATEGORY_MAPPING.get(original_name, original_name)


def get_category_icon(category_name):
    """Get icon for a category."""
    return CATEGORY_ICONS.get(category_name, "DefaultFolder.png")


def get_category_sort_key(category_name):
    """Get sort key for a category. Returns index in CATEGORY_ORDER or 999 for unmapped."""
    try:
        return CATEGORY_ORDER.index(category_name)
    except ValueError:
        return 999  # Put unmapped categories at the end


# JSON Server Configuration
_servers_config = None


def load_servers_config():
    """Load server configuration from remote URL or local file."""
    global _servers_config

    if _servers_config is not None:
        return _servers_config

    return _load_servers_config_internal()


def reload_servers_config():
    """Force reload server configuration (clears cache)."""
    global _servers_config
    _servers_config = None
    return _load_servers_config_internal()


def _load_servers_config_internal():
    """Internal function to actually load the config."""
    global _servers_config

    _servers_config = {"servers": []}

    # Try remote URL first
    json_url = _ADDON.getSetting("servers_json_url")
    if json_url and json_url.strip():
        try:
            xbmc.log(
                f"[Config] Fetching servers.json from URL: {json_url}",
                level=xbmc.LOGINFO,
            )
            response = get_session().get(json_url.strip(), timeout=15)
            response.raise_for_status()
            _servers_config = response.json()
            xbmc.log(
                f"[Config] Loaded servers.json from remote URL", level=xbmc.LOGINFO
            )
            return _servers_config
        except Exception as e:
            xbmc.log(f"[Config] Failed to load from URL: {e}", level=xbmc.LOGWARNING)
            # Continue to try local file

    # Try local file
    addon_path = _ADDON.getAddonInfo("path")
    servers_file = os.path.join(addon_path, "servers.json")

    try:
        with open(servers_file, "r", encoding="utf-8") as f:
            _servers_config = json_loads(f)
        xbmc.log(f"[Config] Loaded servers.json from local file", level=xbmc.LOGINFO)
        return _servers_config
    except FileNotFoundError:
        xbmc.log(
            f"[Config] servers.json not found at {servers_file}", level=xbmc.LOGWARNING
        )
        return _servers_config
    except json.JSONDecodeError as e:
        xbmc.log(f"[Config] Invalid JSON in servers.json: {e}", level=xbmc.LOGERROR)
        return _servers_config
    except Exception as e:
        xbmc.log(f"[Config] Error loading servers.json: {e}", level=xbmc.LOGERROR)
        return _servers_config
        return _servers_config


@lru_cache(maxsize=8)
def get_server_config(server_id):
    """Get configuration for a specific server."""
    config = load_servers_config()
    for server in config.get("servers", []):
        if server.get("id") == server_id:
            return server
    return None


@lru_cache(maxsize=8)
def get_portal_url_for_server(server_id):
    """Get portal URL for a server from JSON config."""
    server = get_server_config(server_id)
    if server and server.get("portal_url"):
        return server["portal_url"]
    return None


@lru_cache(maxsize=8)
def get_macs_for_server(server_id):
    """Get MAC addresses for a server from JSON config."""
    server = get_server_config(server_id)
    if server and server.get("macs"):
        return server["macs"]
    return None


@lru_cache(maxsize=8)
def get_server_type(server_id):
    """Get server type for customization from JSON config."""
    server = get_server_config(server_id)
    if server:
        return server.get("type", "stalker")
    return "stalker"


# MAC list cache
_mac_list_cache = {}
_MAC_CACHE_TTL = 7200  # 2 hours in seconds


def get_random_mac_from_file(server="server1"):
    """Get a random MAC address from JSON config only"""
    global _mac_list_cache

    current_time = time.time()

    # Check if we have a valid cached MAC list
    if (
        server in _mac_list_cache
        and (current_time - _mac_list_cache[server]["timestamp"]) < _MAC_CACHE_TTL
    ):
        return random.choice(_mac_list_cache[server]["macs"])

    # JSON config only
    json_macs = get_macs_for_server(server)
    if json_macs and len(json_macs) > 0:
        if server not in _mac_list_cache:
            _mac_list_cache[server] = {"macs": [], "timestamp": 0}
        _mac_list_cache[server]["macs"] = json_macs
        _mac_list_cache[server]["timestamp"] = current_time
        return random.choice(json_macs)

    # No MACs found in JSON
    xbmcgui.Dialog().notification(
        "Error",
        f"No MAC addresses found for {server} in servers.json",
        xbmcgui.NOTIFICATION_ERROR,
    )
    return None


def handshake(portal_url, mac, server="server1"):
    """Perform handshake with Stalker portal to get a session token."""
    session = get_session()
    # CRITICAL: Clear cookies from previous server handshakes
    session.cookies.clear()

    from urllib.parse import urlparse

    parsed_url = urlparse(portal_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
        "X-User-Agent": "Model: MAG250; Link: WiFi",
        "Referer": f"{portal_url}/stalker_portal/c/index.html",
        "Host": parsed_url.netloc,
    }
    cookies = {"mac": mac}

    # Use params for robust URL construction
    url = f"{portal_url}/portal.php"
    params = {
        "type": "stb",
        "action": "handshake",
        "token": "",
        "JsHttpRequest": "1-xml",
    }

    try:
        response = session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=TIMEOUTS["handshake"],
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            js_data = data.get("js", {})
            if isinstance(js_data, dict):
                token = js_data.get("token")
                if token:
                    return token
                else:
                    xbmc.log(
                        f"[Handshake] No token in response. js data: {js_data}",
                        level=xbmc.LOGWARNING,
                    )
                    return None
            elif isinstance(js_data, list):
                xbmc.log(
                    f"[Handshake] Server returned error list: {js_data}",
                    level=xbmc.LOGWARNING,
                )
                return None
            else:
                xbmc.log(
                    f"[Handshake] Unexpected js data type: {type(js_data)}",
                    level=xbmc.LOGWARNING,
                )
                return None
        elif isinstance(data, list):
            xbmc.log(
                f"[Handshake] Server returned error list at root level: {data}",
                level=xbmc.LOGWARNING,
            )
            return None

        xbmc.log(
            f"[Handshake] Unexpected response format: {type(data)}",
            level=xbmc.LOGWARNING,
        )
        return None
    except requests.exceptions.RequestException as e:
        xbmc.log(f"[Handshake] Request failed: {e}", level=xbmc.LOGERROR)
        return None
    except Exception as e:
        xbmc.log(f"[Handshake] Error: {e}", level=xbmc.LOGERROR)
        return None


# Token cache to avoid handshake for every channel
_token_cache = {"token": None, "mac": None, "timestamp": 0}
_TOKEN_TTL = 600  # 10 minutes

# Current server for EPG operations
_epg_current_server = "server1"

# Category cache (in-memory)
_categories_cache = {}
_CATEGORIES_CACHE_TTL = 604800  # 7 days

# Cached server cache folder path — avoids repeated xbmcaddon.Addon() IPC calls
_server_cache_folder_path = None

# Per-server authentication cache — avoids a full handshake on every request
_auth_cache = {}  # {server_id: {"token": str, "mac": str, "timestamp": float}}
_AUTH_TOKEN_TTL = 3600  # 1 hour (increased from 5m to avoid 429 Too Many Requests)

# In-memory channels cache — avoids re-reading large JSON files on every category click
_channels_memory_cache = {}  # {server_id: {"channels": list, "timestamp": float}}

# Shared probe session for server status checks — reused across all parallel checks
_probe_session = None


def get_server_cache_folder():
    """Get the server cache folder path (result is cached to avoid repeated IPC calls)."""
    global _server_cache_folder_path
    if _server_cache_folder_path is not None:
        return _server_cache_folder_path
    addon_profile_path = xbmcaddon.Addon().getAddonInfo("profile")
    try:
        addon_path = xbmcvfs.translatePath(addon_profile_path)
    except Exception:
        addon_path = xbmc.translatePath(addon_profile_path)
    cache_folder = os.path.join(addon_path, "server_cache")
    if not os.path.exists(cache_folder):
        os.makedirs(cache_folder)
    _server_cache_folder_path = cache_folder
    return _server_cache_folder_path


def get_server_cache_file(server_id):
    """Get the cache file path for a specific server."""
    return os.path.join(get_server_cache_folder(), f"{server_id}_cache.json")


def get_categories_cache_file(server_id):
    """Get the categories cache file path for a specific server."""
    return os.path.join(get_server_cache_folder(), f"{server_id}_categories.json")


def get_channels_cache_file(server_id):
    """Get the channels cache file path for a specific server."""
    return os.path.join(get_server_cache_folder(), f"{server_id}_channels.json")


def load_categories_cache(server_id):
    """Load categories cache from file."""
    cache_file = get_categories_cache_file(server_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                content = f.read()
                if not content:
                    xbmc.log(
                        f"[ServerCache] Categories cache file empty for {server_id}",
                        level=xbmc.LOGDEBUG,
                    )
                    return None
                data = json_loads(content)
            xbmc.log(
                f"[ServerCache] Loaded categories for {server_id}", level=xbmc.LOGDEBUG
            )
            return data
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to load categories for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )
    return None


def save_categories_cache(server_id, categories):
    """Save categories cache to file."""
    cache_file = get_categories_cache_file(server_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json_dumps({"categories": categories, "timestamp": time.time()}, f)
        xbmc.log(f"[ServerCache] Saved categories for {server_id}", level=xbmc.LOGDEBUG)
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to save categories for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )


def clear_all_cache(server="server1"):
    """Clear all cache files for a server (categories and channels)."""
    try:
        categories_file = get_categories_cache_file(server)
        channels_file = get_channels_cache_file(server)

        deleted_count = 0

        if categories_file and os.path.exists(categories_file):
            os.remove(categories_file)
            deleted_count += 1
            xbmc.log(f"[Cache] Deleted categories cache: {categories_file}")

        if channels_file and os.path.exists(channels_file):
            os.remove(channels_file)
            deleted_count += 1
            xbmc.log(f"[Cache] Deleted channels cache: {channels_file}")

        if deleted_count > 0:
            xbmcgui.Dialog().notification(
                "Succes",
                f"Cache șters: {deleted_count} fișiere",
                xbmcgui.NOTIFICATION_INFO,
            )
        else:
            xbmcgui.Dialog().notification(
                "Info",
                "Nu există cache de șters",
                xbmcgui.NOTIFICATION_INFO,
            )
    except Exception as e:
        xbmc.log(f"[Cache] Error clearing cache: {e}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Eroare",
            f"Nu s-a putut șterge cache-ul: {e}",
            xbmcgui.NOTIFICATION_ERROR,
        )


def clear_all_cache_for_all_servers():
    """Clear all cache files for all servers."""
    xbmc.log("[Cache] Starting clear_all_cache_for_all_servers", level=xbmc.LOGINFO)
    try:
        servers_config = reload_servers_config()
        available_servers = servers_config.get("servers", [])
        xbmc.log(f"[Cache] Found {len(available_servers)} servers", level=xbmc.LOGINFO)

        if not available_servers:
            xbmcgui.Dialog().notification(
                "Info",
                "Nu s-au găsit servere",
                xbmcgui.NOTIFICATION_INFO,
            )
            return

        dp = xbmcgui.DialogProgress()
        dp.create("Se șterge cache-ul...", "Se pregătește...")

        total_deleted = 0
        total_servers = len(available_servers)

        for idx, srv in enumerate(available_servers):
            srv_id = srv.get("id")
            srv_name = srv.get("name", srv_id)

            if dp.iscanceled():
                break

            dp.update(
                int((idx / total_servers) * 100),
                f"Se șterge cache pentru {srv_name}...",
            )

            if not srv_id:
                continue

            categories_file = get_categories_cache_file(srv_id)
            channels_file = get_channels_cache_file(srv_id)

            xbmc.log(
                f"[Cache] Checking cache for {srv_id}: categories={categories_file}, channels={channels_file}",
                level=xbmc.LOGDEBUG,
            )

            if categories_file and os.path.exists(categories_file):
                os.remove(categories_file)
                total_deleted += 1
                xbmc.log(f"[Cache] Deleted categories cache for {srv_id}")

            if channels_file and os.path.exists(channels_file):
                os.remove(channels_file)
                total_deleted += 1
                xbmc.log(f"[Cache] Deleted channels cache for {srv_id}")

        dp.close()

        if total_deleted > 0:
            xbmcgui.Dialog().notification(
                "Succes",
                f"Cache șters: {total_deleted} fișiere",
                xbmcgui.NOTIFICATION_INFO,
            )
        else:
            xbmcgui.Dialog().notification(
                "Info",
                "Nu există cache de șters",
                xbmcgui.NOTIFICATION_INFO,
            )
    except Exception as e:
        xbmc.log(f"[Cache] Error clearing all cache: {e}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Eroare",
            f"Nu s-a putut șterge cache-ul: {e}",
            xbmcgui.NOTIFICATION_ERROR,
        )


def load_channels_cache(server_id):
    """Load channels cache from file."""
    cache_file = get_channels_cache_file(server_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json_loads(f)
            xbmc.log(
                f"[ServerCache] Loaded channels for {server_id}", level=xbmc.LOGDEBUG
            )
            return data
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to load channels for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )
    return None


def save_channels_cache(server_id, channels):
    """Save channels cache to file."""
    cache_file = get_channels_cache_file(server_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json_dumps({"channels": channels, "timestamp": time.time()}, f)
        xbmc.log(
            f"[ServerCache] Saved {len(channels)} channels for {server_id}",
            level=xbmc.LOGDEBUG,
        )
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to save channels for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )


def load_server_data_cache(server_id):
    """Load server data (categories and channels) from cache file for specific server."""
    cache_file = get_server_cache_file(server_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json_loads(f)
            xbmc.log(f"[ServerCache] Loaded cache for {server_id}", level=xbmc.LOGDEBUG)
            return cache_data
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to load cache for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )
    return {}


def save_server_data_cache(server_id, cache_data):
    """Save server data (categories and channels) to cache file for specific server."""
    cache_file = get_server_cache_file(server_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json_dumps(cache_data, f)
        xbmc.log(f"[ServerCache] Saved cache for {server_id}", level=xbmc.LOGDEBUG)
    except Exception as e:
        xbmc.log(
            f"[ServerCache] Failed to save cache for {server_id}: {e}",
            level=xbmc.LOGWARNING,
        )


def get_server_auth(server="server1"):
    """Get authentication credentials (MAC and token) for server.

    Results are cached per server for _AUTH_TOKEN_TTL seconds to avoid
    a full HTTP handshake on every categories/channels request.
    """
    global _auth_cache
    current_time = time.time()
    cached = _auth_cache.get(server, {})

    if (
        cached.get("token")
        and cached.get("mac")
        and (current_time - cached.get("timestamp", 0)) < _AUTH_TOKEN_TTL
    ):
        xbmc.log(
            f"[Auth] Using cached token for {server} "
            f"(age: {int(current_time - cached['timestamp'])}s)",
            level=xbmc.LOGDEBUG,
        )
        portal_url = get_portal_url_for_server(server)
        from urllib.parse import urlparse

        parsed_url = urlparse(portal_url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
                "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
            ),
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Referer": f"{portal_url}/stalker_portal/c/index.html",
            "Host": parsed_url.netloc,
        }
        cookies = {"mac": cached["mac"], "token": cached["token"]}
        return cached["token"], headers, cookies, portal_url

    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        return None, None, None, portal_url

    mac = get_random_mac_from_file(server)
    if not mac:
        return None, None, None, portal_url

    token = handshake(portal_url, mac, server)
    if not token:
        return None, None, None, portal_url

    _auth_cache[server] = {"token": token, "mac": mac, "timestamp": current_time}

    from urllib.parse import urlparse

    parsed_url = urlparse(portal_url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
            "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
        ),
        "X-User-Agent": "Model: MAG250; Link: WiFi",
        "Referer": f"{portal_url}/stalker_portal/c/index.html",
        "Host": parsed_url.netloc,
    }
    cookies = {"mac": mac, "token": token}
    return token, headers, cookies, portal_url


def fetch_server_categories(server="server1", force_refresh=False):
    """Fetch categories directly from STB server with file caching."""
    global _categories_cache

    current_time = time.time()
    cache_key = f"categories_{server}"
    session = get_session()

    # Try to load from file cache first
    if not _categories_cache.get(cache_key):
        file_cache = load_categories_cache(server)
        if file_cache and file_cache.get("categories"):
            _categories_cache[cache_key] = file_cache["categories"]
            _categories_cache[f"timestamp_{server}"] = file_cache.get("timestamp", 0)
            xbmc.log(
                f"[Categories] Loaded categories from file cache: {len(_categories_cache[cache_key])}",
                level=xbmc.LOGDEBUG,
            )

    # Return from memory cache if valid
    if (
        not force_refresh
        and cache_key in _categories_cache
        and _categories_cache[cache_key]
        and (current_time - _categories_cache.get(f"timestamp_{server}", 0))
        < _CATEGORIES_CACHE_TTL
    ):
        xbmc.log(
            f"[Categories] Using cached categories for {server}: {len(_categories_cache[cache_key])}",
            level=xbmc.LOGINFO,
        )
        return _categories_cache[cache_key]

    # Need to fetch fresh data
    xbmc.log(f"[Categories] Fast fetch genres for {server}", level=xbmc.LOGINFO)
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    url = f"{portal_url}/portal.php"
    params = {"type": "itv", "action": "get_genres", "token": token, "JsHttpRequest": "1-xml"}
    
    try:
        res = get_session().get(url, params=params, headers=headers, cookies=cookies, timeout=TIMEOUTS["categories"])
        res.raise_for_status()
        data = res.json()
        
        categories = []
        if isinstance(data, dict):
            js_data = data.get("js", {})
            if isinstance(js_data, list):
                for item in js_data:
                    cat_id = item.get("id")
                    cat_title = item.get("title", "")
                    if cat_id and cat_title:
                        categories.append({
                            "id": cat_id,
                            "title": cat_title.strip(),
                            "original_title": cat_title.strip(),
                        })
            elif isinstance(js_data, dict):
                genres = js_data.get("genres") or js_data.get("data") or []
                if isinstance(genres, list):
                    for item in genres:
                        cat_id = item.get("id")
                        cat_title = item.get("title") or item.get("name", "")
                        if cat_id and cat_title:
                            categories.append({
                                "id": cat_id,
                                "title": cat_title.strip(),
                                "original_title": cat_title.strip(),
                            })

        if categories:
            save_categories_cache(server, categories)
            _categories_cache[cache_key] = categories
            _categories_cache[f"timestamp_{server}"] = current_time
            return categories
    except Exception as e:
        xbmc.log(f"[Categories] Fast fetch failed: {e}", level=xbmc.LOGERROR)

    # If we reach here, fetch failed or returned empty.
    # Fallback to whatever is in memory (even if expired)
    return _categories_cache.get(cache_key, [])


def fetch_vod_categories(server="server1"):
    """Fetch VOD categories from server."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    url = f"{portal_url}/portal.php?type=vod&action=get_categories&JsHttpRequest=1-xml"
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["categories"]
        )
        response.raise_for_status()
        data = response.json()
        return data.get("js", [])
    except Exception as e:
        xbmc.log(f"[VOD] Failed to fetch VOD categories: {e}", level=xbmc.LOGERROR)
        return []


def fetch_series_categories(server="server1"):
    """Fetch Series categories from server."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    url = (
        f"{portal_url}/portal.php?type=series&action=get_categories&JsHttpRequest=1-xml"
    )
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["categories"]
        )
        response.raise_for_status()
        data = response.json()
        return data.get("js", [])
    except Exception as e:
        xbmc.log(
            f"[Series] Failed to fetch Series categories: {e}", level=xbmc.LOGERROR
        )
        return []


def clean_category_title(title):
    """Remove Unicode box drawing characters, stars and clean up category title."""
    if not title:
        return ""

    cleaned = RE_BOX_CHARS.sub("", str(title))
    cleaned = cleaned.replace("✰", "")
    cleaned = cleaned.strip(r"|-[]:() ")
    return cleaned.strip()


def get_sport_categories(server_categories):
    """Filter categories that are Sport related (anywhere in the title)."""
    if not server_categories:
        return []

    sport_keywords = [
        "sport",
        "bundesliga",
        "football",
        "laliga",
        "la liga",
        "deportes",
        "liga de campeones",
        "formula 1",
        "moto gp",
        "ligue 1",
        "equipe",
        "basket",
        "hockey",
        "espn",
        "championship",
        "games",
        "premier leagues",
        "league",
        "rugby",
        "rally",
        "serie a",
        "boxing",
        "tennis",
    ]

    sport_cats = []
    keywords_lower = [k.lower() for k in sport_keywords]

    for cat in server_categories:
        title = cat["title"].strip()
        title_lower = title.lower()

        is_sport = False
        for keyword in keywords_lower:
            if keyword in title_lower:
                is_sport = True
                break

        if is_sport:
            sport_cats.append(cat)
            xbmc.log(
                f"[Categories] Matched Sport category: {cat['title']}",
                level=xbmc.LOGDEBUG,
            )

    xbmc.log(
        f"[Categories] Found {len(sport_cats)} Sport categories", level=xbmc.LOGINFO
    )
    return sport_cats


def get_romanian_categories(server_categories):
    """Filter categories that are Romanian (must START with RO, Romania, Roumanie, etc.)"""
    if not server_categories:
        return []

    romanian_prefixes = [
        "ro",
        "ro|",
        "ro :",
        "ro-",
        "ro ",
        "ro\u2503",
        "ro\u2502",
        "ro\u2551",
        "ro\u2550",
        "ro\u2588",
        "\u2503ro",
        "\u2502ro",
        "\u2551ro",
        "\u2550ro",
        "\u2588ro",
        "ro[",
        "ro]",
        "[ro]",
        "[ro[",
        "ro(",
        "ro)",
        "ro:",
        "|EU| ROMANIA",
        "romania",
        "roumanie",
        "romanie",
        "✰ romania",
        "✰romania",
    ]

    romanian_cats = []
    prefixes_lower = [p.lower() for p in romanian_prefixes]

    for cat in server_categories:
        title = cat["title"].strip()
        title_lower = title.lower()

        is_romanian = False
        for prefix in prefixes_lower:
            if title_lower.startswith(prefix):
                is_romanian = True
                break

        if not is_romanian:
            if RE_CATEGORY_PREFIX.match(title_lower):
                is_romanian = True
                break

        if not is_romanian and title_lower.startswith("ro"):
            if len(title_lower) == 2 or title_lower[2] in " |:-":
                is_romanian = True

        if is_romanian:
            romanian_cats.append(cat)
            xbmc.log(
                f"[Categories] Matched Romanian category: {cat['title']}",
                level=xbmc.LOGDEBUG,
            )

    xbmc.log(
        f"[Categories] Found {len(romanian_cats)} Romanian categories",
        level=xbmc.LOGINFO,
    )
    return romanian_cats


def fetch_channels_by_category_from_server(category_id, server="server1"):
    """Fetch channels with Lazy Loading. 
    Downloads full channel list ONLY when first category is accessed.
    """
    global _channels_memory_cache
    current_time = time.time()

    # 1. Memory/File Cache check
    mem = _channels_memory_cache.get(server, {})
    if mem.get("channels") and (current_time - mem.get("timestamp", 0)) < _CATEGORIES_CACHE_TTL:
        channels = mem["channels"]
    else:
        file_cache = load_channels_cache(server)
        if file_cache and file_cache.get("channels") and (current_time - file_cache.get("timestamp", 0)) < _CATEGORIES_CACHE_TTL:
            channels = file_cache["channels"]
            _channels_memory_cache[server] = {"channels": channels, "timestamp": file_cache["timestamp"]}
        else:
            channels = None

    # 2. Lazy Full Fetch
    if not channels:
        xbmc.log(f"[Channels] Lazy loading full channel list for {server}", level=xbmc.LOGINFO)
        dp = xbmcgui.DialogProgress()
        dp.create("HubLive", "Se descarcă grila de canale...")
        
        token, headers, cookies, portal_url = get_server_auth(server)
        if not token or not portal_url:
            dp.close()
            return []

        url = f"{portal_url}/portal.php"
        params = {"type": "itv", "action": "get_all_channels", "token": token, "JsHttpRequest": "1-xml"}
        
        try:
            res = get_session().get(url, params=params, headers=headers, cookies=cookies, timeout=TIMEOUTS["channels"])
            res.raise_for_status()
            data = res.json()
            
            raw_channels = []
            if isinstance(data, dict):
                js_data = data.get("js", {})
                if isinstance(js_data, list):
                    raw_channels = js_data
                elif isinstance(js_data, dict):
                    raw_channels = js_data.get("data") or js_data.get("channels") or []
            elif isinstance(data, list):
                raw_channels = data

            if raw_channels:
                channels = []
                for ch in raw_channels:
                    logo = ch.get("logo") or ""
                    if logo and RE_BOX_CHARS.search(logo): logo = ""
                    channels.append({
                        "id": ch.get("id"),
                        "name": clean_category_title(ch.get("name")),
                        "cmd": ch.get("cmd"),
                        "logo": logo,
                        "tv_genre_id": ch.get("tv_genre_id"),
                    })
                
                _channels_memory_cache[server] = {"channels": channels, "timestamp": current_time}
                save_channels_cache(server, channels)
            
            dp.close()
        except Exception as e:
            xbmc.log(f"[Channels] Lazy fetch failed: {e}", level=xbmc.LOGERROR)
            dp.close()
            return []

    if not channels: return []
    if category_id is None: return channels
    return [ch for ch in channels if str(ch.get("tv_genre_id", "")) == str(category_id)]


# Token provider for EPG Manager — delegates to the unified per-server auth cache
def epg_token_provider(server=None):
    """Provide token, headers, and cookies for EPG requests.

    Delegates to get_server_auth which now uses the unified per-server
    _auth_cache, so no duplicate handshakes occur.
    """
    global _epg_current_server
    if server is None:
        server = _epg_current_server

    token, headers, cookies, _ = get_server_auth(server)
    if not token:
        xbmc.log("[EPG] Failed to get token via get_server_auth", level=xbmc.LOGWARNING)
        return None, {}, {}
    return token, headers, cookies


# Initialize EPG Manager AFTER defining token provider (only if enabled)
# Optimized settings for faster EPG fetching with parallel workers
epg_manager = None
if is_epg_enabled():
    epg_portal_url = get_portal_url_for_server("server1")
    epg_manager = EpgManager(
        mode="stalker",
        base_url=epg_portal_url,
        callback=epg_callback,
        token_provider=epg_token_provider,
        connect_timeout=10.0,  # Increased timeout for connection
        read_timeout=30.0,  # Increased timeout for reading
        max_retries=3,  # Retry 3 times on failure
        backoff_factor=1.0,  # More aggressive backoff
        cache_ttl=1800.0,  # 30 minutes cache
        max_items_default=10,
        num_workers=10,  # Process 10 channels in parallel
    )


# Favorites file
FAVORITES_FILE = os.path.join(
    xbmcvfs.translatePath(_ADDON.getAddonInfo("profile")), "favorites_{server}.json"
)


def list_global_favorites():
    """List favorite channels from all servers, filtering by online status."""
    xbmcplugin.setPluginCategory(_HANDLE, "Favorite")
    xbmcplugin.setContent(_HANDLE, "videos")

    servers_config = reload_servers_config()
    available_servers = servers_config.get("servers", [])
    server_ids = {srv.get("id") for srv in available_servers}
    
    # Try to get statuses from session cache
    server_statuses = get_session_server_statuses()
    
    all_favorites = []
    
    for srv in available_servers:
        srv_id = srv.get("id")
        srv_name = srv.get("name", srv_id)
        
        # Skip if server is offline in current session
        if server_statuses and not server_statuses.get(srv_id, False):
            continue
            
        favorites_file = FAVORITES_FILE.format(server=srv_id)
        if os.path.exists(favorites_file):
            try:
                with open(favorites_file, "r", encoding="utf-8") as f:
                    favorites = json_loads(f)
                    for fav in favorites:
                        fav["_server_id"] = srv_id
                        fav["_server_name"] = srv_name
                        all_favorites.append(fav)
            except:
                pass

    if not all_favorites:
        li = xbmcgui.ListItem(label="[COLOR yellow]Nu există canale favorite (sau serverele sunt OFF).[/COLOR]")
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    for fav in all_favorites:
        display_label = f"{fav['name']} - [COLOR cyan]{fav['_server_name']}[/COLOR]"
        li = xbmcgui.ListItem(label=display_label)
        
        logo = fav.get("logo", "")
        if logo:
            li.setArt({"thumb": logo, "icon": logo})
            
        li.setProperty("IsPlayable", "true")
        
        # InfoTag for Kodi 21
        video_info = li.getVideoInfoTag()
        video_info.setTitle(fav["name"])

        url = f"{_BASE_URL}?mode=play&stream_id={fav['stream_id']}&name={quote_plus(fav['name'])}&server={fav['_server_id']}"
        if fav['_server_id'] == "server2" and fav.get("url_template"):
            url += f"&url_template={quote_plus(fav['url_template'])}"

        # Context menu
        li.addContextMenuItems([
            ("Remove from Favorites", f"RunPlugin({_BASE_URL}?mode=remove_from_favorites&stream_id={fav['stream_id']}&server={fav['_server_id']})")
        ])

        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(_HANDLE)


def list_favorites(server="server1"):
    """List favorite channels."""
    # Add "Change MAC" button at the top
    change_mac_button = xbmcgui.ListItem(
        label="[COLOR orange]Change MAC Address[/COLOR]"
    )
    change_mac_button.setArt(
        {"icon": "DefaultIconInfo.png", "thumb": "DefaultIconInfo.png"}
    )
    change_mac_url = f"{_BASE_URL}?mode=change_mac&category=favorites&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=change_mac_url, listitem=change_mac_button, isFolder=False
    )

    favorites_file = FAVORITES_FILE.format(server=server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as f:
            favorites = json_loads(f)
    except (FileNotFoundError, json.JSONDecodeError):
        favorites = []

    if not favorites:
        li = xbmcgui.ListItem(label="[COLOR yellow]No favorite channels.[/COLOR]")
        li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    for fav in favorites:
        li = xbmcgui.ListItem(label=fav["name"])
        li.setArt({"thumb": fav.get("logo", ""), "icon": fav.get("logo", "")})
        li.setProperty("IsPlayable", "true")

        url = f"{_BASE_URL}?mode=play&stream_id={fav['stream_id']}&name={quote_plus(fav['name'])}&server={server}"
        if server == "server2" and fav.get("url_template"):
            url += f"&url_template={quote_plus(fav['url_template'])}"

        # Context menu to remove from favorites
        li.addContextMenuItems(
            [
                (
                    "Remove from Favorites",
                    f"RunPlugin({_BASE_URL}?mode=remove_from_favorites&stream_id={fav['stream_id']}&server={server})",
                )
            ]
        )

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def add_to_favorites(stream_id, name, logo, server="server1", url_template=None):
    """Add a channel to favorites."""
    favorites_file = FAVORITES_FILE.format(server=server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as f:
            favorites = json_loads(f)
    except (FileNotFoundError, json.JSONDecodeError):
        favorites = []

    favorite_ids = {fav["stream_id"] for fav in favorites}
    if stream_id not in favorite_ids:
        favorites.append(
            {
                "stream_id": stream_id,
                "name": name,
                "logo": logo,
                "url_template": url_template,
            }
        )
        with open(favorites_file, "w", encoding="utf-8") as f:
            json_dumps(favorites, f)
        xbmcgui.Dialog().notification(
            "Favorites", f"{name} added to favorites", xbmcgui.NOTIFICATION_INFO, 2000
        )
    else:
        xbmcgui.Dialog().notification(
            "Favorites",
            f"{name} is already in favorites",
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )


def remove_from_favorites(stream_id, server="server1"):
    """Remove a channel from favorites."""
    favorites_file = FAVORITES_FILE.format(server=server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as f:
            favorites = json_loads(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    favorites = [fav for fav in favorites if fav["stream_id"] != stream_id]

    with open(favorites_file, "w", encoding="utf-8") as f:
        json_dumps(favorites, f)
    xbmcgui.Dialog().notification(
        "Favorites", "Channel removed from favorites", xbmcgui.NOTIFICATION_INFO, 2000
    )
    xbmc.executebuiltin("Container.Refresh")


def get_params():
    """Get the plugin parameters"""
    paramstring = sys.argv[2][1:]
    return dict(parse_qsl(paramstring))


def parse_m3u_channels(m3u_file, server="server1"):
    """
    Parse M3U file and return list of channel dictionaries.
    Centralized M3U parsing to avoid code duplication.

    Args:
        m3u_file: Path to the M3U file
        server: 'server1' or 'server2'

    Returns:
        List of channel dicts with keys: name, group, logo, stream_id, url
    """
    channels = []

    try:
        with open(m3u_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        xbmc.log(f"[M3U] Failed to read {m3u_file}: {e}", level=xbmc.LOGERROR)
        return []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:") or RE_EXTINF.search(line):
            group_title_match = RE_GROUP_TITLE.search(line)
            tvg_logo_match = RE_TVG_LOGO.search(line)

            last_comma_pos = line.rfind(",")
            if last_comma_pos != -1:
                channel_name = line[last_comma_pos + 1 :].strip()
            else:
                channel_name = "Unknown Channel"

            group_title = (
                group_title_match.group(1).strip()
                if group_title_match
                else "Uncategorized"
            )
            tvg_logo = tvg_logo_match.group(1) if tvg_logo_match else ""
            group_title = map_category_name(group_title)

            if i + 1 < len(lines):
                url_line = lines[i + 1].strip()
                if url_line and not url_line.startswith("#"):
                    if RE_MACPH_TOKENPH.search(url_line):
                        stream_id = f"s2_{len(channels)}"
                        channels.append(
                            {
                                "name": channel_name,
                                "group": group_title,
                                "logo": tvg_logo,
                                "stream_id": stream_id,
                                "url": url_line,
                            }
                        )
                    else:
                        stream_id_match = RE_STREAM_ID.search(url_line)
                        if stream_id_match:
                            stream_id = stream_id_match.group(1)
                            channels.append(
                                {
                                    "name": channel_name,
                                    "group": group_title,
                                    "logo": tvg_logo,
                                    "stream_id": stream_id,
                                    "url": url_line,
                                }
                            )

        i += 1

    xbmc.log(
        f"[M3U] Parsed {len(channels)} channels from {os.path.basename(m3u_file)}",
        level=xbmc.LOGINFO,
    )
    return channels


def main_menu():
    """Render the main menu with Mega Search, LiveTV Romania, World, Sport, Filme, Seriale, Favorites, and Server Check."""
    items = [
        (
            "[COLOR gold]Mega Cautare[/COLOR]",
            "mega_search_menu",
            "DefaultAddonsSearch.png",
        ),
        ("LiveTV Romania", "romania", "DefaultTVShows.png"),
        ("LiveTV World", "world", "DefaultAddonPVRClient.png"),
        ("LiveTV Sport", "sport", "DefaultAddonGame.png"),
        ("Filme", "vod", "DefaultMovies.png"),
        ("Seriale", "series", "DefaultTVShows.png"),
        ("[COLOR gold]Favorite[/COLOR]", "global_favorites", "DefaultFavourites.png"),
        ("[COLOR yellow]Verificare Servere[/COLOR]", "check", "DefaultNetwork.png"),
        ("[COLOR cyan]Setari[/COLOR]", "settings_menu", "DefaultAddonService.png"),
    ]

    for label, main_mode, icon in items:
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": icon, "thumb": icon})

        if main_mode == "check":
            url = (
                f"{_BASE_URL}?mode=select_server&main_mode=verificare&force_check=true"
            )
        elif main_mode == "settings_menu":
            url = f"{_BASE_URL}?mode=settings_menu&is_main=true"
        elif main_mode == "mega_search_menu":
            url = f"{_BASE_URL}?mode=mega_search_menu"
        elif main_mode == "global_favorites":
            url = f"{_BASE_URL}?mode=global_favorites"
        else:
            url = f"{_BASE_URL}?mode=select_server&main_mode={main_mode}"

        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def mega_search_menu():
    """Render the Mega Search submenu."""
    items = [
        ("Cauta Live", "live", "DefaultAddonPVRClient.png"),
        ("Cauta Filme", "vod", "DefaultMovies.png"),
        ("Cauta Seriale", "series", "DefaultTVShows.png"),
    ]

    for label, search_type, icon in items:
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": icon, "thumb": icon})
        url = f"{_BASE_URL}?mode=mega_search_input&search_type={search_type}"
        # isFolder=False to prevent history stack issues
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def get_session_server_statuses():
    """Get server statuses from Kodi window property (session cache)."""
    try:
        window = xbmcgui.Window(10000)
        data = window.getProperty("hublive_server_statuses")
        if data:
            return json_loads(data)
    except:
        pass
    return None


def set_session_server_statuses(statuses):
    """Save server statuses to Kodi window property."""
    try:
        window = xbmcgui.Window(10000)
        window.setProperty("hublive_server_statuses", json_dumps(statuses))
    except:
        pass


def select_server_dialog(main_mode, force_check=False):
    """Show a dialog to select a server and return the selected server ID.
    Uses session cache for statuses unless force_check is True.
    """
    servers_config = reload_servers_config()
    available_servers = servers_config.get("servers", [])

    if not available_servers:
        xbmcgui.Dialog().ok("Error", "No servers configured in servers.json")
        return None

    # Try to get statuses from session cache
    server_statuses = get_session_server_statuses()

    # Determine if we need to perform a check
    should_check = force_check or (
        is_server_check_enabled() and server_statuses is None
    )

    if should_check:
        # Perform parallel check
        server_statuses = _check_all_servers_online(available_servers)
        # Update session cache
        set_session_server_statuses(server_statuses)

    # Safe capitalize for title
    title_suffix = main_mode.capitalize() if main_mode else "Verificare"

    labels = []
    for srv in available_servers:
        srv_name = srv.get("name", srv.get("id", "Unknown"))
        srv_id = srv.get("id")

        if server_statuses is not None:
            is_online = server_statuses.get(srv_id, False)
            status = (
                "[COLOR green]● ON[/COLOR]" if is_online else "[COLOR red]● OFF[/COLOR]"
            )
            labels.append(f"{srv_name}  {status}")
        else:
            labels.append(srv_name)

    selection = xbmcgui.Dialog().select(f"Alege Server - {title_suffix}", labels)

    if selection >= 0:
        return available_servers[selection].get("id")

    return None


def fetch_stalker_paginated(type_param, category_id, server="server1"):
    """Helper to fetch all pages for a given Stalker category."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    base_url = f"{portal_url}/portal.php"
    param_key = "category" if type_param in ["vod", "series"] else "genre"

    all_items = []
    current_page = 1
    total_pages = 1

    while current_page <= total_pages:
        params = {
            "type": type_param,
            "action": "get_ordered_list",
            param_key: category_id,
            "JsHttpRequest": "1-xml",
            "p": current_page,
        }

        try:
            response = get_session().get(
                base_url,
                params=params,
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["channels"],
            )
            response.raise_for_status()
            data = response.json()
            js_data = data.get("js", {})

            # Update total pages on first request
            if current_page == 1:
                total_items = int(js_data.get("total_items", 0))
                items_first_page = js_data.get("data", [])
                if not items_first_page:
                    break

                items_per_page = len(items_first_page)
                if items_per_page > 0:
                    total_pages = (total_items + items_per_page - 1) // items_per_page

                xbmc.log(
                    f"[Stalker] Total items: {total_items}, Pages: {total_pages} for {type_param} cat {category_id}",
                    level=xbmc.LOGINFO,
                )

            page_items = js_data.get("data", [])
            if not page_items:
                break

            all_items.extend(page_items)
            current_page += 1

            # Safety break to avoid infinite loops if server misbehaves
            if current_page > 100:
                break

        except Exception as e:
            xbmc.log(
                f"[Stalker] Pagination error at page {current_page}: {e}",
                level=xbmc.LOGERROR,
            )
            break

    return all_items


def fetch_vod_items(category_id, server="server1"):
    """Fetch VOD items for a specific category from server using pagination."""
    return fetch_stalker_paginated("vod", category_id, server)


def fetch_series_items(category_id, server="server1"):
    """Fetch Series items for a specific category from server using pagination."""
    return fetch_stalker_paginated("series", category_id, server)


def list_vod_items(category_id, server="server1"):
    """List VOD items for a specific category."""
    items = fetch_vod_items(category_id, server)
    if not items:
        xbmcgui.Dialog().notification("Info", "No VOD items found in this category.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    for item in items:
        name = item.get("name", "Unknown")
        movie_id = item.get("id")
        li = xbmcgui.ListItem(label=name)
        li.setInfo(
            "video",
            {"title": name, "plot": item.get("description"), "year": item.get("year")},
        )
        li.setProperty("IsPlayable", "true")
        url = f"{_BASE_URL}?mode=play_vod&movie_id={movie_id}&server={server}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_series_items(category_id, server="server1"):
    """List Series items for a specific category."""
    items = fetch_series_items(category_id, server)
    if not items:
        xbmcgui.Dialog().notification("Info", "No series found in this category.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    for item in items:
        name = item.get("name", "Unknown")
        series_id = item.get("id")
        li = xbmcgui.ListItem(label=name)
        li.setInfo(
            "video",
            {"title": name, "plot": item.get("description"), "year": item.get("year")},
        )
        # For series, clicking an item should lead to seasons
        # series_id might need splitting if it contains colons like in stalker_kodi.py
        movie_id = str(series_id).split(":")[0]
        url = f"{_BASE_URL}?mode=list_seasons&movie_id={movie_id}&server={server}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def fetch_seasons(movie_id, server="server1"):
    """Fetch seasons for a series."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    url = f"{portal_url}/portal.php?type=series&action=get_ordered_list&movie_id={movie_id}&JsHttpRequest=1-xml"
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["channels"]
        )
        response.raise_for_status()
        data = response.json()
        return data.get("js", {}).get("data", [])
    except Exception as e:
        xbmc.log(f"[Series] Failed to fetch seasons: {e}", level=xbmc.LOGERROR)
        return []


def list_seasons(movie_id, server="server1"):
    """List seasons for a series."""
    seasons = fetch_seasons(movie_id, server)
    if not seasons:
        xbmcgui.Dialog().notification("Info", "No seasons found for this series.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    for season in seasons:
        li = xbmcgui.ListItem(label=season.get("name", "Unknown Season"))
        url = f"{_BASE_URL}?mode=list_episodes&movie_id={movie_id}&season_id={season.get('id')}&server={server}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def fetch_episodes(movie_id, season_id, server="server1"):
    """Fetch episodes for a season."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return []

    url = f"{portal_url}/portal.php?type=series&action=get_ordered_list&movie_id={movie_id}&season_id={season_id}&JsHttpRequest=1-xml"
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["channels"]
        )
        response.raise_for_status()
        data = response.json()
        return data.get("js", {}).get("data", [])
    except Exception as e:
        xbmc.log(f"[Series] Failed to fetch episodes: {e}", level=xbmc.LOGERROR)
        return []


def list_episodes(movie_id, season_id, server="server1"):
    """List episodes for a season."""
    episodes_data = fetch_episodes(movie_id, season_id, server)
    if not episodes_data or not isinstance(episodes_data, list):
        xbmcgui.Dialog().notification("Info", "No episodes found for this season.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    # In Stalker, episodes_data[0]['series'] is usually a list of episode numbers
    # and episodes_data[0]['cmd'] is the base command for the season.
    if len(episodes_data) > 0:
        season_info = episodes_data[0]
        episodes_list = season_info.get("series", [])
        season_cmd = season_info.get("cmd")

        for ep_num in episodes_list:
            label = f"Episodul {ep_num}"
            li = xbmcgui.ListItem(label=label)
            li.setProperty("IsPlayable", "true")
            url = f"{_BASE_URL}?mode=play_series&cmd={quote_plus(str(season_cmd))}&episode={ep_num}&server={server}"
            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=url, listitem=li, isFolder=False
            )

    xbmcplugin.endOfDirectory(_HANDLE)


def play_vod(movie_id, server="server1"):
    """Play a VOD movie."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return

    cmd = f"movie {movie_id}"
    url = f"{portal_url}/portal.php?type=vod&action=create_link&cmd={quote_plus(cmd)}&JsHttpRequest=1-xml"
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["play"]
        )
        response.raise_for_status()
        data = response.json()
        returned_url = data.get("js", {}).get("cmd")

        if returned_url:
            final_url = returned_url
            if "play_token=" in returned_url:
                try:
                    play_token = returned_url.split("play_token=")[1].split("&")[0]
                    mac = cookies.get("mac", "")
                    # Ensure mac is available
                    if not mac:
                        # Try to get mac from settings/config if not in cookies
                        servers_config = reload_servers_config()
                        for s in servers_config.get("servers", []):
                            if s.get("id") == server and s.get("macs"):
                                mac = s["macs"][0]
                                break

                    final_url = f"{portal_url}/play/movie.php?mac={mac}&stream={movie_id}.mkv&play_token={play_token}&type=movie"
                except IndexError:
                    pass

            xbmc.log(f"[VOD] Playing URL: {final_url}", level=xbmc.LOGINFO)
            li = xbmcgui.ListItem(path=final_url)
            xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=li)
        else:
            xbmcgui.Dialog().notification(
                "Eroare", "Nu s-a putut genera link-ul de redare."
            )
    except Exception as e:
        xbmc.log(f"[VOD] Play failed: {e}", level=xbmc.LOGERROR)


def play_series(cmd, episode_num, server="server1"):
    """Play a series episode."""
    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        return

    # cmd for series is usually like "movie 1234"
    url = f"{portal_url}/portal.php?type=vod&action=create_link&cmd={quote_plus(str(cmd))}&series={episode_num}&JsHttpRequest=1-xml"
    try:
        response = get_session().get(
            url, headers=headers, cookies=cookies, timeout=TIMEOUTS["play"]
        )
        response.raise_for_status()
        data = response.json()
        stream_url = data.get("js", {}).get("cmd")

        if stream_url:
            if stream_url.startswith("ffmpeg "):
                stream_url = stream_url.split(" ", 1)[1]

            xbmc.log(f"[Series] Playing URL: {stream_url}", level=xbmc.LOGINFO)
            li = xbmcgui.ListItem(path=stream_url)
            xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=li)
        else:
            xbmcgui.Dialog().notification(
                "Eroare", "Nu s-a putut genera link-ul de redare."
            )
    except Exception as e:
        xbmc.log(f"[Series] Play failed: {e}", level=xbmc.LOGERROR)


def list_vod_categories(server="server1"):
    """List VOD categories from server."""
    categories = fetch_vod_categories(server)
    if not categories:
        xbmcgui.Dialog().notification("Info", "No VOD categories found.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    # Set plugin category and content
    xbmcplugin.setPluginCategory(_HANDLE, "Filme")
    xbmcplugin.setContent(_HANDLE, "videos")

    # Add "Search" button at the top - Action item, not a folder to prevent history stack issues
    search_button = xbmcgui.ListItem(label="[COLOR yellow]Cauta Film[/COLOR]")
    search_button.setArt(
        {"thumb": "DefaultAddonsSearch.png", "icon": "DefaultAddonsSearch.png"}
    )
    search_button.setProperty("IsPlayable", "false")
    search_button_url = f"{_BASE_URL}?mode=search_input_vod&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=search_button_url, listitem=search_button, isFolder=False
    )

    for cat in categories:
        li = xbmcgui.ListItem(label=cat.get("title", "Unknown"))
        url = f"{_BASE_URL}?mode=list_vod_items&category_id={cat.get('id')}&server={server}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def list_series_categories(server="server1"):
    """List Series categories from server."""
    categories = fetch_series_categories(server)
    if not categories:
        xbmcgui.Dialog().notification("Info", "No Series categories found.")
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    # Set plugin category and content
    xbmcplugin.setPluginCategory(_HANDLE, "Seriale")
    xbmcplugin.setContent(_HANDLE, "videos")

    # Add "Search" button at the top - Action item, not a folder
    search_button = xbmcgui.ListItem(label="[COLOR yellow]Cauta Serial[/COLOR]")
    search_button.setArt(
        {"thumb": "DefaultAddonsSearch.png", "icon": "DefaultAddonsSearch.png"}
    )
    search_button.setProperty("IsPlayable", "false")
    search_button_url = f"{_BASE_URL}?mode=search_input_series&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=search_button_url, listitem=search_button, isFolder=False
    )

    for cat in categories:
        li = xbmcgui.ListItem(label=cat.get("title", "Unknown"))
        url = f"{_BASE_URL}?mode=list_series_items&category_id={cat.get('id')}&server={server}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def list_channels(
    server="server1",
    category=None,
    category_id=None,
    from_server=False,
    main_mode=None,
):
    """List channel categories from server."""
    # Check if portal URL exists
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        xbmc.log(f"[List] No portal URL configured for {server}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Error",
            f"No portal URL configured for {server}",
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    # Get params for backward compatibility
    params = get_params()
    if category is None:
        category = params.get("category")
    if category_id is None:
        category_id = params.get("cat_id")
    if not from_server:
        from_server = params.get("from_server") == "true"
    if main_mode is None:
        main_mode = params.get("main_mode")

    xbmc.log(
        f"[List] Listing channels for server={server}, main_mode={main_mode}",
        level=xbmc.LOGINFO,
    )

    # If a category is selected, list channels in that category
    if category:
        list_channels_in_category(
            [],
            category,
            server=server,
            category_id=category_id,
            from_server=from_server,
            main_mode=main_mode,
        )
    else:
        # List all available categories
        list_categories([], server=server, main_mode=main_mode)


def list_categories(channels, server="server1", main_mode=None):
    """List all available channel categories with Get Full EPG button."""
    # Add "Search" button at the top - Action item, not a folder
    search_button = xbmcgui.ListItem(label="[COLOR yellow]Cauta[/COLOR]")
    search_button.setArt(
        {"icon": "DefaultAddonsSearch.png", "thumb": "DefaultAddonsSearch.png"}
    )
    search_button.setProperty("IsPlayable", "false")
    search_button_url = f"{_BASE_URL}?mode=search_input&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=search_button_url, listitem=search_button, isFolder=False
    )

    # Add "Favorites" button at the top
    favorites_button = xbmcgui.ListItem(label="[COLOR gold]Favorite[/COLOR]")
    favorites_button.setArt(
        {"icon": "DefaultFavourites.png", "thumb": "DefaultFavourites.png"}
    )
    favorites_button_url = f"{_BASE_URL}?mode=favorites&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=favorites_button_url,
        listitem=favorites_button,
        isFolder=True,
    )

    # Get server type
    server_type = get_server_type(server)

    # Add "Get Full EPG" button (only if EPG is enabled and server type supports it)
    if is_epg_enabled() and server_type in ["stalker", "stalker_v2"]:
        epg_button = xbmcgui.ListItem(label="[COLOR yellow]Get Full EPG[/COLOR]")
        epg_button.setArt(
            {"icon": "DefaultAddonPVRClient.png", "thumb": "DefaultAddonPVRClient.png"}
        )
        epg_button_url = f"{_BASE_URL}?mode=get_full_epg&server={server}&main_mode={main_mode if main_mode else ''}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=epg_button_url, listitem=epg_button, isFolder=True
        )

    # Always use server categories (mandatory with JSON config)
    server_cat_list = []

    # Try to fetch categories from server (works for stalker, stalker_v2 types)
    if server_type in ["stalker", "stalker_v2"]:
        all_server_cats = fetch_server_categories(server)
        if all_server_cats:
            if main_mode == "world":
                server_cat_list = all_server_cats
            elif main_mode == "sport":
                server_cat_list = get_sport_categories(all_server_cats)
            else:
                server_cat_list = get_romanian_categories(all_server_cats)

            xbmc.log(
                f"[Categories] Using server categories for {server}: {len(server_cat_list)} found (mode: {main_mode})",
                level=xbmc.LOGINFO,
            )

    # Determine which categories to display
    if server_cat_list:
        # If only one category, show channels directly
        if len(server_cat_list) == 1:
            cat = server_cat_list[0]
            xbmc.log(
                f"[Categories] Single category detected: {cat['title']}, showing channels directly",
                level=xbmc.LOGINFO,
            )
            list_channels_in_category(
                [],
                cat["title"],
                server=server,
                category_id=cat["id"],
                from_server=True,
                main_mode=main_mode,
            )
            return

        # Multiple categories - show the list
        categories_to_show = []
        for cat in server_cat_list:
            display_name = clean_category_title(cat["title"])
            # Map to our display format if possible
            mapped = map_category_name(display_name)
            categories_to_show.append(
                {"display": mapped, "original": display_name, "id": cat["id"]}
            )

        # Sort by custom order
        if main_mode != "world":
            categories_to_show.sort(key=lambda x: get_category_sort_key(x["display"]))
        else:
            categories_to_show.sort(key=lambda x: x["display"])

        for cat_info in categories_to_show:
            li = xbmcgui.ListItem(label=cat_info["display"])
            icon = get_category_icon(cat_info["display"])
            li.setArt({"icon": icon, "thumb": icon})

            # Use original category name for server query
            category_url = f"{_BASE_URL}?category={quote_plus(cat_info['original'])}&server={server}&cat_id={cat_info['id']}&from_server=true&main_mode={main_mode if main_mode else ''}"

            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=category_url, listitem=li, isFolder=True
            )
    else:
        # No categories from server - show error
        xbmc.log(f"[Categories] No categories found for {server}", level=xbmc.LOGERROR)
        li = xbmcgui.ListItem(label="[COLOR red]Error: Cannot load categories[/COLOR]")
        li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

        li2 = xbmcgui.ListItem(
            label="[COLOR yellow]Check server URL or internet connection[/COLOR]"
        )
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url="", listitem=li2, isFolder=False
        )

    # Add Settings folder at the end
    settings_folder = xbmcgui.ListItem(label="[COLOR cyan]Setari[/COLOR]")
    settings_folder.setArt(
        {"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"}
    )
    settings_folder_url = f"{_BASE_URL}?mode=settings_menu&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=settings_folder_url, listitem=settings_folder, isFolder=True
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_channels_in_category(
    all_channels,
    selected_category,
    server="server1",
    category_id=None,
    from_server=False,
    main_mode=None,
):
    """List channels within a specific category."""
    favorites_file = FAVORITES_FILE.format(server=server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as f:
            favorites = json_loads(f)
    except (FileNotFoundError, json.JSONDecodeError):
        favorites = []
    favorite_stream_ids = {fav["stream_id"] for fav in favorites}

    # Handle server categories
    if from_server and category_id:
        # Fetch channels from server by category
        xbmc.log(
            f"[Categories] Fetching channels for category ID: {category_id} (mode: {main_mode})",
            level=xbmc.LOGINFO,
        )
        server_channels = fetch_channels_by_category_from_server(category_id, server)

        if server_channels:
            # Convert server channels to our format
            channels_in_category = []
            for idx, ch in enumerate(server_channels):
                name = clean_category_title(
                    ch.get("name") or ch.get("title") or "Unknown"
                )
                cmd = ch.get("cmd") or ch.get("stream_url") or ""
                logo = ch.get("logo") or ""
                if logo and RE_BOX_CHARS.search(logo):
                    logo = ""

                stream_id_match = RE_STREAM_ID.search(cmd)
                if stream_id_match:
                    stream_id = stream_id_match.group(1)
                else:
                    # Fallback 1: Use direct 'id' field if numeric
                    srv_id_field = str(ch.get("id", ""))
                    if srv_id_field and srv_id_field.isdigit():
                        stream_id = srv_id_field
                    else:
                        # Fallback 2: Try to find ANY number in the cmd
                        any_digit_match = re.search(r"(\d+)", cmd)
                        stream_id = any_digit_match.group(1) if any_digit_match else f"unknown_{idx}"

                channels_in_category.append(
                    {
                        "name": name,
                        "group": selected_category,
                        "logo": logo,
                        "stream_id": stream_id,
                        "url": cmd,
                    }
                )
            xbmc.log(
                f"[Categories] Got {len(channels_in_category)} channels from server",
                level=xbmc.LOGINFO,
            )
        else:
            channels_in_category = []
    else:
        # Filter channels by the selected category from M3U
        channels_in_category = [
            ch for ch in all_channels if ch["group"] == selected_category
        ]

    # Add "Change MAC" button at the top
    change_mac_button = xbmcgui.ListItem(
        label="[COLOR orange]Change MAC Address[/COLOR]"
    )
    change_mac_button.setArt(
        {"icon": "DefaultIconInfo.png", "thumb": "DefaultIconInfo.png"}
    )
    change_mac_url = f"{_BASE_URL}?mode=change_mac&category={quote_plus(selected_category)}&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=change_mac_url, listitem=change_mac_button, isFolder=False
    )

    # Only load and request EPG if enabled
    if is_epg_enabled() and epg_manager:
        # Set current server for EPG operations
        global _epg_current_server
        _epg_current_server = server

        # Reconfigure EPG manager for the current server
        portal_url = get_portal_url_for_server(server)
        if portal_url:
            epg_manager.reconfigure(base_url=portal_url)

        # Load EPG cache first
        load_epg_cache()

        xbmc.log(
            f"[EPG] Category '{selected_category}' has {len(channels_in_category)} channels",
            level=xbmc.LOGINFO,
        )

        # Count how many channels already have EPG from cache
        channels_with_cached_epg = sum(
            1 for ch in channels_in_category if ch["stream_id"] in epg_data
        )
        xbmc.log(
            f"[EPG] {channels_with_cached_epg}/{len(channels_in_category)} channels have cached EPG",
            level=xbmc.LOGINFO,
        )

        # Request EPG data for ALL channels in the category
        for channel in channels_in_category:
            epg_manager.request(channel, size=10)

        # Calculate adaptive timeout based on number of channels and cache coverage
        num_channels = len(channels_in_category)
        cache_coverage = (
            channels_with_cached_epg / num_channels if num_channels > 0 else 0
        )

        if cache_coverage >= 0.8:
            # Good cache — wait at most 3 s (50 ms per channel)
            max_wait_time = min(3000, num_channels * 50)
            xbmc.log(
                f"[EPG] Good cache coverage ({cache_coverage:.0%}), waiting up to {max_wait_time}ms",
                level=xbmc.LOGINFO,
            )
        else:
            # Fresh fetch needed — wait at most 15 s (200 ms per channel)
            max_wait_time = min(15000, num_channels * 200)
            xbmc.log(
                f"[EPG] Fetching fresh EPG, waiting up to {max_wait_time}ms",
                level=xbmc.LOGINFO,
            )

        wait_interval = 100  # Poll every 100 ms (was 300 ms)
        waited = 0
        last_count = channels_with_cached_epg
        no_progress_since = 0  # ms since last new EPG arrived

        while waited < max_wait_time:
            xbmc.sleep(wait_interval)
            waited += wait_interval

            channels_with_epg = sum(
                1 for ch in channels_in_category if ch["stream_id"] in epg_data
            )

            if channels_with_epg != last_count:
                xbmc.log(
                    f"[EPG] Progress: {channels_with_epg}/{num_channels} ({waited}ms)",
                    level=xbmc.LOGDEBUG,
                )
                last_count = channels_with_epg
                no_progress_since = 0
            else:
                no_progress_since += wait_interval

            # All channels have EPG — no need to wait further
            if channels_with_epg >= num_channels:
                xbmc.log(
                    "[EPG] All channels have EPG, proceeding early", level=xbmc.LOGDEBUG
                )
                break

            # No new EPG for 2 s — give up waiting
            if no_progress_since >= 2000:
                xbmc.log(
                    f"[EPG] No new EPG for 2s, proceeding with {channels_with_epg}/{num_channels}",
                    level=xbmc.LOGDEBUG,
                )
                break

        # Final count
        final_count = sum(
            1 for ch in channels_in_category if ch["stream_id"] in epg_data
        )
        final_coverage = final_count / num_channels if num_channels > 0 else 0
        xbmc.log(
            f"[EPG] Final: {final_count}/{num_channels} channels ({final_coverage:.0%}) have EPG",
            level=xbmc.LOGINFO,
        )

        # Save updated EPG to cache
        save_epg_cache()

    # Create list items with EPG data
    for channel in channels_in_category:
        # Build channel label with current program
        channel_label = channel["name"]

        # Add current program to label if EPG available and enabled
        if is_epg_enabled() and channel["stream_id"] in epg_data:
            epg_items = epg_data[channel["stream_id"]]
            current_prog = get_current_program(epg_items)
            if current_prog:
                channel_label = f"{channel['name']} - {current_prog}"

        li = xbmcgui.ListItem(label=channel_label)

        # Set thumbnail from tvg-logo if available
        if channel["logo"]:
            li.setArt({"thumb": channel["logo"], "icon": channel["logo"]})

        li.setProperty("IsPlayable", "true")

        # Set EPG data if available and enabled
        if is_epg_enabled() and channel["stream_id"] in epg_data:
            epg_items = epg_data[channel["stream_id"]]
            plot = format_epg_tooltip(epg_items)
            li.setInfo("video", {"plot": plot})

        # Create URL to play this specific channel
        url = f"{_BASE_URL}?mode=play&stream_id={channel['stream_id']}&name={quote_plus(channel['name'])}&server={server}"
        if server == "server2" and channel.get("url"):
            url += f"&url_template={quote_plus(channel['url'])}"

        # Add context menu for favorites
        context_menu = []
        if channel["stream_id"] in favorite_stream_ids:
            context_menu.append(
                (
                    "Remove from Favorites",
                    f"RunPlugin({_BASE_URL}?mode=remove_from_favorites&stream_id={channel['stream_id']}&server={server})",
                )
            )
        else:
            add_fav_url = f"{_BASE_URL}?mode=add_to_favorites&stream_id={channel['stream_id']}&name={quote_plus(channel['name'])}&logo={quote_plus(channel['logo'])}&server={server}"
            if server == "server2" and channel.get("url"):
                add_fav_url += f"&url_template={quote_plus(channel['url'])}"
            context_menu.append(("Add to Favorites", f"RunPlugin({add_fav_url})"))
        li.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def get_full_epg():
    """Fetch EPG for ALL channels from server."""
    if not is_epg_enabled() or not epg_manager:
        xbmcgui.Dialog().notification(
            "EPG Disabled", "Enable EPG in addon settings", xbmcgui.NOTIFICATION_INFO
        )
        return

    # Get server from params
    params = get_params()
    server = params.get("server", "server1")

    # Get all channels from server
    xbmc.log(f"[EPG] Fetching all channels from {server}", level=xbmc.LOGINFO)

    # Fetch all channels from server
    all_channels = []
    server_cats = fetch_server_categories(server)

    if not server_cats:
        xbmcgui.Dialog().notification(
            "EPG", "Could not fetch categories", xbmcgui.NOTIFICATION_WARNING
        )
        return

    # Fetch channels for each category
    for cat in server_cats[:5]:  # Limit to first 5 categories to avoid long loading
        cat_id = cat.get("id")
        channels = fetch_channels_by_category_from_server(cat_id, server)
        all_channels.extend(channels)
        xbmc.log(
            f"[EPG] Got {len(channels)} channels from category {cat.get('title')}",
            level=xbmc.LOGDEBUG,
        )

    if not all_channels:
        xbmcgui.Dialog().notification(
            "EPG", "No channels found", xbmcgui.NOTIFICATION_WARNING
        )
        return

    total_channels = len(all_channels)
    xbmc.log(f"[EPG] Get Full EPG: Found {total_channels} channels", level=xbmc.LOGINFO)

    # Count how many already cached
    load_epg_cache()
    channels_with_cached_epg = sum(
        1
        for ch in all_channels
        if str(ch.get("id")) in epg_data or str(ch.get("tv_genre_id")) in epg_data
    )
    xbmc.log(
        f"[EPG] {channels_with_cached_epg}/{total_channels} channels already have cached EPG",
        level=xbmc.LOGDEBUG,
    )

    # Create progress dialog
    progress = xbmcgui.DialogProgress()
    progress.create(
        "Fetching Full EPG", f"Requesting EPG for {total_channels} channels..."
    )

    # Request EPG for all channels
    for idx, channel in enumerate(all_channels):
        if progress.iscanceled():
            xbmc.log("[EPG] User cancelled full EPG fetch", level=xbmc.LOGDEBUG)
            progress.close()
            return

        epg_manager.request(channel, size=10)

        # Update progress every 10 channels
        if (idx + 1) % 10 == 0:
            percent = int(((idx + 1) / total_channels) * 30)
            progress.update(
                percent, f"Requested EPG for {idx + 1}/{total_channels} channels..."
            )

    progress.update(30, f"Waiting for EPG data from server...")

    # Calculate timeout based on total channels
    max_wait_time = min(300000, total_channels * 400)
    wait_interval = 500  # Check every 500ms
    waited = 0
    last_count = channels_with_cached_epg

    xbmc.log(
        f"[EPG] Waiting up to {max_wait_time}ms for {total_channels} channels",
        level=xbmc.LOGDEBUG,
    )

    while waited < max_wait_time:
        if progress.iscanceled():
            xbmc.log(
                "[EPG] User cancelled full EPG fetch during wait", level=xbmc.LOGDEBUG
            )
            progress.close()
            save_epg_cache()
            return

        xbmc.sleep(wait_interval)
        waited += wait_interval

        # Check progress
        channels_with_epg = sum(1 for ch in channels if ch["stream_id"] in epg_data)

        # Update progress dialog (30% to 95%)
        progress_percent = 30 + int(((channels_with_epg / total_channels) * 65))
        coverage_percent = int((channels_with_epg / total_channels) * 100)
        progress.update(
            progress_percent,
            f"Received EPG for {channels_with_epg}/{total_channels} channels ({coverage_percent}%)\nElapsed: {waited // 1000}s / {max_wait_time // 1000}s",
        )

        # Log progress if changed
        if channels_with_epg != last_count:
            xbmc.log(
                f"[EPG] Full EPG Progress: {channels_with_epg}/{total_channels} ({coverage_percent}%) - {waited}ms elapsed",
                level=xbmc.LOGDEBUG,
            )
            last_count = channels_with_epg

        # Exit only if no progress for 10 seconds
        if waited >= 10000 and channels_with_epg == channels_with_cached_epg:
            xbmc.log(
                f"[EPG] No new EPG after 10s, finishing with {channels_with_epg}/{total_channels}",
                level=xbmc.LOGDEBUG,
            )
            break

    # Final save
    progress.update(95, "Saving EPG to cache...")
    save_epg_cache()

    # Final stats
    final_count = sum(1 for ch in channels if ch["stream_id"] in epg_data)
    final_coverage = int((final_count / total_channels) * 100)

    progress.update(
        100,
        f"Complete! EPG for {final_count}/{total_channels} channels ({final_coverage}%)",
    )
    xbmc.sleep(1500)  # Show final message for 1.5 seconds
    progress.close()

    xbmc.log(
        f"[EPG] Full EPG fetch complete: {final_count}/{total_channels} ({final_coverage}%)",
        level=xbmc.LOGDEBUG,
    )
    xbmcgui.Dialog().notification(
        "EPG Complete",
        f"Got EPG for {final_count}/{total_channels} channels ({final_coverage}%)",
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )


def generate_random_mac():
    """Generate a random MAC address in the format 00:1A:79:XX:XX:XX"""
    # Using the same manufacturer prefix as existing MACs in the file
    prefix = "00:1A:79"
    # Generate 3 random bytes for the last part
    suffix = ":".join([f"{random.randint(0, 255):02X}" for _ in range(3)])
    return f"{prefix}:{suffix}"


def change_mac(category=None, server="server1"):
    """Change to a new random MAC address and clear token cache."""
    global _token_cache

    # Get a new random MAC from file
    new_mac = get_random_mac_from_file(server)
    if not new_mac:
        xbmcgui.Dialog().notification(
            "Error", "Failed to get new MAC address", xbmcgui.NOTIFICATION_ERROR
        )
        return

    # Clear token cache to force new handshake with new MAC
    _token_cache["token"] = None
    _token_cache["mac"] = None
    _token_cache["timestamp"] = 0

    xbmc.log(f"[MAC] Changed to new MAC: {new_mac}", level=xbmc.LOGDEBUG)
    xbmcgui.Dialog().notification(
        "MAC Changed", f"New MAC: {new_mac}", xbmcgui.NOTIFICATION_INFO, 3000
    )

    # Refresh the category view if we came from a category
    if category:
        xbmc.executebuiltin(f"Container.Refresh")


def play_stream(stream_id, name, server="server1", url_template=None):
    """Get the token and MAC dynamically and resolve the URL for a single stream."""
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        xbmcgui.Dialog().notification(
            "Error", "Portal URL is not set in settings.", xbmcgui.NOTIFICATION_ERROR
        )
        return

    # Check if this is a Server 2 stream (stream_id starts with s2_)
    if stream_id.startswith("s2_"):
        xbmc.log(f"--- SERVER 2 PLAYBACK START: {name} ---", level=xbmc.LOGDEBUG)

        url_line = url_template
        # Fallback if url_template was not provided (e.g., from old favorites)
        if not url_line:
            addon_path = _ADDON.getAddonInfo("path")
            m3u_file = os.path.join(addon_path, "mag.txt")
            xbmc.log(
                f"[Server 2] Falling back to read M3U file from {m3u_file}",
                level=xbmc.LOGDEBUG,
            )

            try:
                with open(m3u_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                channel_index = int(stream_id.split("_")[1])
                channel_count = 0

                for i, line in enumerate(lines):
                    line = line.strip()
                    if line.startswith("#EXTINF:") or "#EXTINF:" in line.upper():
                        if i + 1 < len(lines):
                            pot_url = lines[i + 1].strip()
                            if (
                                pot_url
                                and not pot_url.startswith("#")
                                and "MACPH" in pot_url
                                and "TOKENPH" in pot_url
                            ):
                                if channel_count == channel_index:
                                    url_line = pot_url
                                    break
                                channel_count += 1
            except Exception as e:
                xbmcgui.Dialog().notification(
                    "Error", f"Failed to load mag.txt: {e}", xbmcgui.NOTIFICATION_ERROR
                )
                return

        if not url_line:
            xbmcgui.Dialog().notification(
                "Error",
                "Channel not found or URL template missing",
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

        # Found our channel! Extract stream ID from URL
        stream_id_match = RE_STREAM_ID.search(url_line)
        if stream_id_match:
            actual_stream_id = stream_id_match.group(1)

            # Perform handshake to get token
            # Extract portal URL from the URL template
            portal_match = re.match(r"(https?://[^/]+)", url_line)
            if portal_match:
                server2_portal_url = portal_match.group(1)

                # Try up to 3 different MACs with loading dialog
                dp = xbmcgui.DialogProgress()
                dp.create("Se caută stream valid...", "Se testează streamul...")
                dp.update(0)

                for mac_attempt in range(3):
                    if dp.iscanceled():
                        dp.close()
                        return

                    dp.update(
                        int((mac_attempt / 3) * 100), f"Se încearcă conectarea..."
                    )

                    random_mac = get_random_mac_from_file(server)
                    if not random_mac:
                        return

                    # Get session token via handshake
                    session_token = handshake(
                        server2_portal_url, random_mac, server="server2"
                    )
                    if not session_token:
                        continue

                    # Create link to get play token
                    headers = {
                        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
                        "X-User-Agent": "Model: MAG250; Link: WiFi",
                    }
                    create_link_url = f"{server2_portal_url}/portal.php?action=create_link&type=itv&cmd={actual_stream_id}&JsHttpRequest=1-xml"
                    cookies = {"mac": random_mac, "token": session_token}

                    try:
                        response = get_session().get(
                            create_link_url,
                            headers=headers,
                            cookies=cookies,
                            timeout=TIMEOUTS["playlink"],
                        )
                        response.raise_for_status()
                        link_data = response.json()

                        js_data = link_data.get("js", {})
                        returned_cmd = js_data.get("cmd")

                        if returned_cmd:
                            play_token_match = re.search(
                                r"play_token=([a-zA-Z0-9]+)", returned_cmd
                            )
                            if play_token_match:
                                play_token = play_token_match.group(1)

                                # Replace placeholders in the original URL from template
                                final_url = url_line.replace(
                                    "MACPH", random_mac
                                ).replace("TOKENPH", play_token)

                                # Add User-Agent to the final URL to prevent 405 errors
                                final_url_with_ua = f"{final_url}|User-Agent={quote_plus(headers['User-Agent'])}"

                                dp.close()
                                play_item = xbmcgui.ListItem(path=final_url_with_ua)
                                xbmcplugin.setResolvedUrl(
                                    _HANDLE, True, listitem=play_item
                                )
                                return  # SUCCESS!
                    except requests.exceptions.RequestException as e:
                        continue  # Try next MAC
                    except Exception as e:
                        continue  # Try next MAC

                # All MAC attempts failed
                dp.close()
                xbmcgui.Dialog().notification(
                    "Eroare",
                    "Niciun stream valid găsit. Încearcă din nou.",
                    xbmcgui.NOTIFICATION_ERROR,
                )
                return
            else:
                xbmcgui.Dialog().notification(
                    "Error",
                    "Could not extract portal URL from template",
                    xbmcgui.NOTIFICATION_ERROR,
                )
                return
        else:
            xbmcgui.Dialog().notification(
                "Error",
                "Could not extract stream ID from URL",
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

    # Server 1: Try up to 3 MACs with loading dialog
    dp = xbmcgui.DialogProgress()
    dp.create("Se caută stream valid...", "Se testează streamul...")
    dp.update(0)

    for mac_attempt in range(3):
        if dp.iscanceled():
            dp.close()
            return

        dp.update(int((mac_attempt / 3) * 100), f"Se încearcă conectarea...")

        random_mac = get_random_mac_from_file(server)
        if not random_mac:
            return

        xbmc.log(
            f"[Server1] Attempt {mac_attempt + 1}/3 with MAC: {random_mac}",
            level=xbmc.LOGINFO,
        )

        # Perform handshake to get a fresh token from the server for each request
        session_token = handshake(portal_url, random_mac, server=server)
        if not session_token:
            xbmc.log(
                f"[Server1] Handshake failed for MAC {random_mac}, trying another...",
                level=xbmc.LOGWARNING,
            )
            continue

        headers = {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
            "X-User-Agent": "Model: MAG250; Link: WiFi",
        }
        create_link_url = f"{portal_url}/portal.php?type=itv&action=create_link&cmd={stream_id}&JsHttpRequest=1-xml"
        cookies = {"mac": random_mac, "token": session_token}

        try:
            response = get_session().get(
                create_link_url,
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["playlink"],
            )
            response.raise_for_status()
            link_data = response.json()

            # Check if response is a dict (expected) or list (error)
            if isinstance(link_data, dict):
                js_data = link_data.get("js", {})
                if isinstance(js_data, dict):
                    returned_cmd = js_data.get("cmd")
                elif isinstance(js_data, list):
                    xbmc.log(
                        f"[Server1] MAC {random_mac} rejected (empty list), trying another...",
                        level=xbmc.LOGWARNING,
                    )
                    continue  # Try next MAC
                else:
                    xbmc.log(
                        f"[Server1] Unexpected js data type: {type(js_data)}",
                        level=xbmc.LOGWARNING,
                    )
                    continue  # Try next MAC
            elif isinstance(link_data, list):
                xbmc.log(
                    f"[Server1] MAC {random_mac} rejected (root level list), trying another...",
                    level=xbmc.LOGWARNING,
                )
                continue  # Try next MAC
            else:
                xbmc.log(
                    f"[Server1] Unexpected response type: {type(link_data)}",
                    level=xbmc.LOGWARNING,
                )
                continue  # Try next MAC

            if returned_cmd:
                play_token_match = re.search(r"play_token=([a-zA-Z0-9]+)", returned_cmd)
                if play_token_match:
                    play_token = play_token_match.group(1)
                    final_url = f"{portal_url}/play/live.php?mac={random_mac}&stream={stream_id}&extension=ts&play_token={play_token}"
                    xbmc.log(
                        f"[Server1] Successfully playing with MAC: {random_mac}",
                        level=xbmc.LOGINFO,
                    )
                    dp.close()
                    play_item = xbmcgui.ListItem(path=final_url)
                    xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=play_item)
                    return  # SUCCESS!
                else:
                    xbmc.log(
                        f"[Server1] No play_token in response, trying another MAC...",
                        level=xbmc.LOGWARNING,
                    )
                    continue  # Try next MAC
            else:
                xbmc.log(
                    f"[Server1] No cmd in response, trying another MAC...",
                    level=xbmc.LOGWARNING,
                )
                continue  # Try next MAC

        except requests.exceptions.RequestException as e:
            xbmc.log(
                f"[Server1] Request failed: {e}, trying another MAC...",
                level=xbmc.LOGWARNING,
            )
            continue  # Try next MAC

    # All MAC attempts failed
    dp.close()
    xbmcgui.Dialog().notification(
        "Eroare",
        "Niciun stream valid găsit. Încearcă din nou.",
        xbmcgui.NOTIFICATION_ERROR,
    )


def show_settings_menu(server="server1", is_main=False):
    """Show settings submenu."""
    # Setari addon
    settings_item = xbmcgui.ListItem(label="Setari addon")
    settings_item.setArt(
        {"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"}
    )
    settings_url = f"{_BASE_URL}?mode=settings&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=settings_url, listitem=settings_item, isFolder=False
    )

    if not is_main:
        # Sterge cache (pt. acest server)
        clear_cache_item = xbmcgui.ListItem(label="Sterge cache (pt. acest server)")
        clear_cache_item.setArt(
            {
                "icon": "DefaultAddonRepository.png",
                "thumb": "DefaultAddonRepository.png",
            }
        )
        clear_cache_url = f"{_BASE_URL}?mode=clear_cache&server={server}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE,
            url=clear_cache_url,
            listitem=clear_cache_item,
            isFolder=False,
        )

    # Sterge tot cache (Clear Cache)
    label_clear = "Sterge tot cache" if not is_main else "Clear Cache"
    clear_all_cache_item = xbmcgui.ListItem(label=label_clear)
    clear_all_cache_item.setArt(
        {"icon": "DefaultAddonRepository.png", "thumb": "DefaultAddonRepository.png"}
    )
    clear_all_cache_url = f"{_BASE_URL}?mode=clear_all_cache"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=clear_all_cache_url,
        listitem=clear_all_cache_item,
        isFolder=False,
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def _list_servers_page(available_servers, server_statuses=None):
    """Render the server selection directory page.

    Args:
        available_servers: list of server dicts from servers.json
        server_statuses:   dict {srv_id: bool} or None.
                           When None, no ON/OFF badge is shown (fast path).
    Always appends an on-demand 'Verificare servere' button at the bottom.
    """
    for srv in available_servers:
        srv_name = srv.get("name", srv.get("id", "Unknown"))
        srv_id = srv.get("id", "server1")

        if server_statuses is not None:
            is_online = server_statuses.get(srv_id, False)
            status = (
                "[COLOR green]● ON[/COLOR]" if is_online else "[COLOR red]● OFF[/COLOR]"
            )
            label = f"{srv_name}  {status}"
        else:
            label = srv_name

        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": "DefaultNetwork.png", "thumb": "DefaultNetwork.png"})
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE,
            url=f"{_BASE_URL}?server={srv_id}",
            listitem=li,
            isFolder=True,
        )

    # On-demand check button — always visible regardless of the auto-check setting
    check_btn = xbmcgui.ListItem(label="[COLOR cyan]>> Verificare servere[/COLOR]")
    check_btn.setArt(
        {"icon": "DefaultAddonRepository.png", "thumb": "DefaultAddonRepository.png"}
    )
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?mode=check_servers",
        listitem=check_btn,
        isFolder=True,
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def _get_probe_session():
    """Return a shared lightweight session used only for server status probes.

    A single session is reused across all parallel server checks to avoid the
    overhead of creating connection pools for each server individually.
    Thread-safe: requests.Session is safe for concurrent use.
    """
    global _probe_session
    if _probe_session is None:
        _probe_session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        _probe_session.mount("http://", adapter)
        _probe_session.mount("https://", adapter)
    return _probe_session


def check_server_online(portal_url, timeout=3):
    """Improved connectivity check for Stalker portal URLs.

    Uses a dedicated no-retry session to avoid false negatives caused by the
    global session's max_retries=3 adapter blocking on connection failures.

    Strategy:
      1. Try /portal.php with MAG headers — the actual Stalker API endpoint.
         Many portals don't serve anything at '/' but do respond on portal.php.
      2. Fall back to the root URL in case the server has a custom layout.
    Any HTTP response (even 4xx/5xx) is treated as ON — the server is reachable.
    Only a connection error or timeout on BOTH attempts means OFF.
    """
    if not portal_url:
        return False

    portal_url = portal_url.rstrip("/")

    probe_session = _get_probe_session()
    mag_headers = {
        "User-Agent": (
            "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
            "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
        ),
        "X-User-Agent": "Model: MAG250; Link: WiFi",
    }

    # 1. Try /portal.php — the real Stalker API endpoint
    try:
        probe_session.get(
            f"{portal_url}/portal.php",
            headers=mag_headers,
            timeout=timeout,
            allow_redirects=True,
        )
        return True
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        pass
    except Exception:
        pass

    # 2. Fall back to root URL
    try:
        probe_session.get(
            portal_url,
            headers=mag_headers,
            timeout=timeout,
            allow_redirects=True,
        )
        return True
    except Exception:
        pass

    return False


def _check_all_servers_online(servers_list):
    """Check all servers online status in parallel. Returns dict {srv_id: bool}.

    Uses a manual executor (no 'with' block) so we can shutdown(wait=False)
    when the 8-second wall-clock timeout fires, preventing a crash/hang on
    the main page when one server is unreachable.

    Per-server timeout is 3 s × 2 attempts = 6 s max, safely under 8 s global.
    """

    def _check(srv):
        srv_id = srv.get("id", "")
        portal_url = srv.get("portal_url", "")
        return srv_id, check_server_online(portal_url)

    statuses = {srv.get("id", ""): False for srv in servers_list}
    executor = ThreadPoolExecutor(max_workers=min(len(servers_list), 10))
    try:
        futures = {executor.submit(_check, srv): srv for srv in servers_list}
        try:
            for future in as_completed(futures, timeout=8):
                try:
                    srv_id, is_online = future.result()
                    statuses[srv_id] = is_online
                except Exception as exc:
                    srv = futures[future]
                    xbmc.log(
                        f"[ServerCheck] {srv.get('id', '?')} probe error: {exc}",
                        level=xbmc.LOGWARNING,
                    )
        except Exception:
            # as_completed raises TimeoutError when the wall-clock expires;
            # remaining servers keep their pre-initialised False status.
            xbmc.log(
                "[ServerCheck] 8s global timeout reached; slow servers marked offline",
                level=xbmc.LOGWARNING,
            )
    finally:
        # Do NOT wait for lingering threads — let them finish in the background
        # so the main page is never blocked by a slow/dead server.
        executor.shutdown(wait=False)
    return statuses


def router(params):
    """Router function with global error handling"""
    try:
        xbmc.log(f"[Router] params: {params}", level=xbmc.LOGDEBUG)
        server = params.get("server")
        mode = params.get("mode")

        # If no server specified and no mode, show main menu
        if server is None and mode is None:
            main_menu()
            return

        # Always reload servers from JSON config (fresh on each request)
        servers_config = reload_servers_config()
        available_servers = servers_config.get("servers", [])

        # Handle clear_all_cache mode early (doesn't require server)
        if mode == "clear_all_cache":
            xbmc.log("[Router] Processing clear_all_cache mode", level=xbmc.LOGINFO)
            clear_all_cache_for_all_servers()
            xbmc.executebuiltin("Container.Refresh")
            return

        # Handle select_server mode
        if mode == "select_server":
            main_mode = params.get("main_mode")
            force_check = params.get("force_check") == "true"
            selected_server = select_server_dialog(main_mode, force_check=force_check)

            if selected_server:
                if main_mode == "vod":
                    list_vod_categories(server=selected_server)
                elif main_mode == "series":
                    list_series_categories(server=selected_server)
                else:
                    list_channels(server=selected_server, main_mode=main_mode)
            else:
                # If user cancelled dialog, we must end the directory listing to stop the spinner
                xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
            return

        # Handle VOD and Series specific modes
        if mode == "list_vod_items":
            list_vod_items(params.get("category_id"), server=server)
            return
        elif mode == "list_series_items":
            list_series_items(params.get("category_id"), server=server)
            return
        elif mode == "list_seasons":
            list_seasons(params.get("movie_id"), server=server)
            return
        elif mode == "list_episodes":
            list_episodes(
                params.get("movie_id"), params.get("season_id"), server=server
            )
            return
        elif mode == "play_vod":
            play_vod(params.get("movie_id"), server=server)
            return
        elif mode == "play_series":
            play_series(params.get("cmd"), params.get("episode"), server=server)
            return

        # Handle modes that don't strictly require a pre-selected server or handle it themselves
        if mode == "settings_menu":
            is_main = params.get("is_main") == "true"
            show_settings_menu(server=server if server else "server1", is_main=is_main)
            return
        elif mode == "settings":
            _ADDON.openSettings()
            xbmc.executebuiltin("Container.Refresh")
            return
        elif mode == "favorites":
            list_favorites(server=server if server else "server1")
            return
        elif mode == "mega_search_menu":
            mega_search_menu()
            return
        elif mode == "mega_search_input":
            mega_search_input(params.get("search_type"))
            return
        elif mode == "mega_search_results":
            show_mega_search_results(params.get("query"), params.get("search_type"))
            return
        elif mode == "global_favorites":
            list_global_favorites()
            return
        elif mode == "search_input":
            search_input_dialog(server=server, main_mode=params.get("main_mode"))
            return
        elif mode == "search_results":
            # Display search results (can be called with query or search_query param)
            query = params.get("query") or params.get("search_query")
            if query:
                show_search_results(query, server=server)
            else:
                # No query, show search input dialog
                search_input_dialog(server=server)
            return
        elif mode == "search_input_vod":
            search_input_dialog_vod(server=server)
            return
        elif mode == "search_results_vod":
            # Display VOD search results
            query = params.get("query") or params.get("search_query")
            if query:
                show_vod_search_results(query, server=server)
            else:
                search_input_dialog_vod(server=server)
            return
        elif mode == "search_input_series":
            search_input_dialog_series(server=server)
            return
        elif mode == "search_results_series":
            # Display Series search results
            query = params.get("query") or params.get("search_query")
            if query:
                show_series_search_results(query, server=server)
            else:
                search_input_dialog_series(server=server)
            return

        # On-demand server check (triggered by the 'Verificare servere' button)
        if mode == "check_servers":
            xbmc.log("[Router] On-demand server check triggered", level=xbmc.LOGINFO)
            server_statuses = _check_all_servers_online(available_servers)
            xbmc.log(
                f"[Router] On-demand statuses: {server_statuses}", level=xbmc.LOGINFO
            )
            _list_servers_page(available_servers, server_statuses)
            return

        # If no server specified, fallback to first server or list servers page
        if server is None:
            if len(available_servers) > 1:
                if is_server_check_enabled():
                    xbmc.log(
                        "[Router] Auto server check enabled, checking status...",
                        level=xbmc.LOGINFO,
                    )
                    server_statuses = _check_all_servers_online(available_servers)
                    xbmc.log(
                        f"[Router] Server statuses: {server_statuses}",
                        level=xbmc.LOGINFO,
                    )
                else:
                    server_statuses = None
                _list_servers_page(available_servers, server_statuses)
                return
            elif len(available_servers) == 1:
                server = available_servers[0].get("id", "server1")
            else:
                # Fallback to default
                server = "server1"

        params["server"] = server

        mode = params.get("mode")

        xbmc.log(f"[Router] params: {params}", level=xbmc.LOGDEBUG)
        xbmc.log(f"[Router] mode: {mode}", level=xbmc.LOGDEBUG)

        if mode in (
            "play",
            "add_to_favorites",
            "remove_from_favorites",
        ):
            if "stream_id" not in params:
                xbmc.log(
                    f"[Router] Missing stream_id for mode: {mode}", level=xbmc.LOGERROR
                )
                xbmcgui.Dialog().notification(
                    "Error", "Missing stream ID", xbmcgui.NOTIFICATION_ERROR
                )
                return

        if mode == "play":
            play_stream(
                params.get("stream_id"),
                params.get("name", "Unknown"),
                server=server,
                url_template=params.get("url_template"),
            )
        elif mode == "add_to_favorites":
            add_to_favorites(
                params.get("stream_id"),
                params.get("name", "Unknown"),
                params.get("logo", ""),
                server=server,
                url_template=params.get("url_template"),
            )
        elif mode == "remove_from_favorites":
            remove_from_favorites(params.get("stream_id"), server=server)

        if server == "both" and mode is None:
            if is_server_check_enabled():
                server_statuses = _check_all_servers_online(available_servers)
            else:
                server_statuses = None
            _list_servers_page(available_servers, server_statuses)
            return

        if mode is None or mode == "list_channels":
            list_channels(
                server=server,
                category=params.get("category"),
                category_id=params.get("cat_id"),
                from_server=params.get("from_server") == "true",
                main_mode=params.get("main_mode"),
            )
        elif mode == "get_full_epg":
            get_full_epg()
        elif mode == "change_mac":
            change_mac(params.get("category"), server=server)
        elif mode == "clear_cache":
            clear_all_cache(server=server if server else "server1")
            xbmc.executebuiltin("Container.Refresh")
        elif mode == "clear_all_cache":
            xbmc.log("[Router] Processing clear_all_cache mode", level=xbmc.LOGINFO)
            clear_all_cache_for_all_servers()
            xbmc.executebuiltin("Container.Refresh")
        elif mode == "favorites":
            list_favorites(server=server if server else "server1")

    except KeyError as e:
        xbmc.log(
            f"[Router] KeyError: {e}, mode: {params.get('mode')}, params: {params}",
            level=xbmc.LOGERROR,
        )
        xbmcgui.Dialog().notification(
            "Error", f"Missing parameter: {e}", xbmcgui.NOTIFICATION_ERROR
        )
    except Exception as e:
        xbmc.log(
            f"[Router] Unexpected error: {type(e).__name__}: {e}", level=xbmc.LOGERROR
        )
        xbmcgui.Dialog().notification(
            "Error",
            f"An unexpected error occurred: {type(e).__name__}",
            xbmcgui.NOTIFICATION_ERROR,
        )
    finally:
        # Only stop epg_manager if it exists
        if epg_manager:
            epg_manager.stop()


def mega_search_input(search_type):
    """Show keyboard for mega search and then update to results."""
    xbmc.executebuiltin("Dialog.Close(all,true)")
    labels = {"live": "Canal Live", "vod": "Film", "series": "Serial"}
    search_term = xbmcgui.Dialog().input(
        f"Mega Cautare {labels.get(search_type)}", type=xbmcgui.INPUT_ALPHANUM
    )

    if search_term:
        url = f"{_BASE_URL}?mode=mega_search_results&query={quote_plus(search_term)}&search_type={search_type}"
        xbmc.executebuiltin(f"Container.Update({url})")


def show_mega_search_results(query, search_type):
    """Search on all servers concurrently and display unified results."""
    xbmc.log(
        f"[MegaSearch] Starting with query='{query}', search_type='{search_type}'",
        level=xbmc.LOGINFO,
    )

    if not query:
        xbmc.log("[MegaSearch] No query provided, exiting", level=xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    servers_config = reload_servers_config()
    available_servers = servers_config.get("servers", [])
    xbmc.log(
        f"[MegaSearch] Found {len(available_servers)} servers: {[s.get('id') for s in available_servers]}",
        level=xbmc.LOGINFO,
    )

    if not available_servers:
        xbmcgui.Dialog().notification(
            "Eroare", "Niciun server configurat.", xbmcgui.NOTIFICATION_ERROR
        )
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    # Set content type
    content_map = {"live": "videos", "vod": "movies", "series": "tvshows"}
    xbmcplugin.setContent(_HANDLE, content_map.get(search_type, "videos"))
    xbmcplugin.setPluginCategory(_HANDLE, f"Mega Cautare: {query}")

    dp = xbmcgui.DialogProgress()
    dp.create(
        "Mega Cautare",
        f"Se cauta pe [COLOR yellow]{len(available_servers)}[/COLOR] servere...",
    )

    all_results = []
    type_param_map = {"live": "itv", "vod": "vod", "series": "series"}
    stalker_type = type_param_map.get(search_type, "itv")

    def worker(srv):
        srv_name = srv.get("name", srv.get("id"))
        srv_id = srv.get("id")
        xbmc.log(
            f"[MegaSearch] Searching '{query}' on {srv_id} (type={stalker_type})",
            level=xbmc.LOGINFO,
        )
        try:
            results = fetch_stalker_search(stalker_type, query, server=srv_id)
            xbmc.log(
                f"[MegaSearch] Got {len(results) if results else 0} results from {srv_id}",
                level=xbmc.LOGINFO,
            )
            if results:
                for item in results:
                    item["_server_name"] = srv_name
                    item["_server_id"] = srv_id
                return results
        except Exception as e:
            xbmc.log(
                f"[MegaSearch] Worker failed for {srv_id}: {e}", level=xbmc.LOGWARNING
            )
        return []

    # Run searches in parallel
    with ThreadPoolExecutor(max_workers=min(len(available_servers), 10)) as executor:
        future_to_srv = {executor.submit(worker, srv): srv for srv in available_servers}

        completed = 0
        total = len(available_servers)

        for future in as_completed(future_to_srv):
            if dp.iscanceled():
                break

            res = future.result()
            if res:
                all_results.extend(res)

            completed += 1
            progress = int((completed / total) * 100)
            srv = future_to_srv[future]
            dp.update(
                progress,
                f"Finalizat: [COLOR yellow]{srv.get('name')}[/COLOR] ({completed}/{total})",
            )

    dp.close()

    # Fallback to local search for live channels if no results from API
    if not all_results and search_type == "live":
        xbmc.log(
            f"[MegaSearch] No results from API, trying local search for live",
            level=xbmc.LOGINFO,
        )
        search_term_lower = query.lower()
        for srv in available_servers:
            srv_id = srv.get("id")
            srv_name = srv.get("name", srv_id)
            try:
                all_channels = fetch_channels_by_category_from_server(None, srv_id)
                if all_channels:
                    for item in all_channels:
                        name = item.get("name", "")
                        if name and search_term_lower in name.lower():
                            item["_server_name"] = srv_name
                            item["_server_id"] = srv_id
                            all_results.append(item)
            except Exception as e:
                xbmc.log(
                    f"[MegaSearch] Local search failed for {srv_id}: {e}",
                    level=xbmc.LOGWARNING,
                )

    if not all_results:
        xbmc.log(f"[MegaSearch] No results found for '{query}'", level=xbmc.LOGINFO)
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu s-a gasit nimic pentru "{query}" pe niciun server.[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    # Process results
    for item in all_results:
        name = item.get("name", "Unknown")
        srv_name = item.get("_server_name")
        srv_id = item.get("_server_id")

        display_label = f"{name} - [COLOR cyan]{srv_name}[/COLOR]"
        li = xbmcgui.ListItem(label=display_label)

        # Art and Info
        logo = item.get("logo") or ""
        if logo:
            li.setArt({"thumb": logo, "icon": logo})

        desc = item.get("description", "")
        year = item.get("year", "")

        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(desc)
        if year and year.isdigit():
            video_info.setYear(int(year))

        # URL Construction based on type
        if search_type == "live":
            cmd = item.get("cmd", "")
            # Try to get stream_id from cmd first (reliable for Stalker)
            stream_id_match = RE_STREAM_ID.search(cmd)
            if stream_id_match:
                stream_id = stream_id_match.group(1)
            else:
                # Fallback to direct id
                stream_id = item.get("id")

            if not stream_id:
                continue

            url = f"{_BASE_URL}?mode=play&stream_id={stream_id}&name={quote_plus(name)}&server={srv_id}"
            li.setProperty("IsPlayable", "true")
            is_folder = False
        elif search_type == "vod":
            movie_id = item.get("id")
            url = f"{_BASE_URL}?mode=play_vod&movie_id={movie_id}&server={srv_id}"
            li.setProperty("IsPlayable", "true")
            is_folder = False
        else:  # series
            series_id = item.get("id")
            movie_id = str(series_id).split(":")[0] if series_id else ""
            url = f"{_BASE_URL}?mode=list_seasons&movie_id={movie_id}&server={srv_id}"
            is_folder = True

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=is_folder
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def search_input_dialog(server="server1", main_mode=None):
    """Show keyboard and display search results directly."""
    # Close any open dialogs first
    xbmc.executebuiltin("Dialog.Close(all,true)")

    search_term = xbmcgui.Dialog().input("Cauta canal", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        # End current directory first
        xbmcplugin.endOfDirectory(_HANDLE)
        xbmc.sleep(200)
        # Use Container.Update to replace current directory with search results
        search_url = f"{_BASE_URL}?mode=search_results&query={quote_plus(search_term)}&server={server}"
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)


def search_input_dialog_vod(server="server1"):
    """Show keyboard and display VOD search results directly."""
    xbmc.executebuiltin("Dialog.Close(all,true)")
    search_term = xbmcgui.Dialog().input("Cauta film", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        xbmcplugin.endOfDirectory(_HANDLE)
        xbmc.sleep(200)
        search_url = f"{_BASE_URL}?mode=search_results_vod&query={quote_plus(search_term)}&server={server}"
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)


def search_input_dialog_series(server="server1"):
    """Show keyboard and display Series search results directly."""
    xbmc.executebuiltin("Dialog.Close(all,true)")
    search_term = xbmcgui.Dialog().input("Cauta serial", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        xbmcplugin.endOfDirectory(_HANDLE)
        xbmc.sleep(200)
        search_url = f"{_BASE_URL}?mode=search_results_series&query={quote_plus(search_term)}&server={server}"
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)


def fetch_stalker_search(type_param, query, server="server1"):
    """Fetch search results directly from Stalker server with robustness."""
    xbmc.log(
        f"[Stalker] Search request: server={server}, type={type_param}, query={query}",
        level=xbmc.LOGINFO,
    )

    token, headers, cookies, portal_url = get_server_auth(server)
    if not token or not portal_url:
        xbmc.log(
            f"[Stalker] No auth for {server}, returning empty", level=xbmc.LOGWARNING
        )
        return []

    # Use params for robust URL construction
    url = f"{portal_url}/portal.php"
    params = {
        "type": type_param,
        "action": "search",
        "q": query,
        "token": token,
        "JsHttpRequest": "1-xml",
    }

    try:
        session = get_session()
        # Clear existing cookies since threads are reused in ThreadPoolExecutor
        session.cookies.clear()

        response = session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=TIMEOUTS["channels"],
        )

        if response.status_code != 200:
            xbmc.log(
                f"[Stalker] Server {server} returned status {response.status_code} for {type_param} search",
                level=xbmc.LOGWARNING,
            )
            return []

        raw_text = response.text
        if not raw_text or len(raw_text.strip()) < 5:
            xbmc.log(f"[Stalker] Response too short from {server} for {type_param}: '{raw_text[:100] if raw_text else 'empty'}'", level=xbmc.LOGWARNING)
            
            # Fallback for VOD/Series: try get_ordered_list with search param
            if type_param in ["vod", "series"]:
                xbmc.log(f"[Stalker] Trying fallback get_ordered_list search for {type_param} on {server}", level=xbmc.LOGINFO)
                fallback_params = {
                    "type": type_param,
                    "action": "get_ordered_list",
                    "search": query,
                    "token": token,
                    "JsHttpRequest": "1-xml"
                }
                try:
                    response = session.get(url, params=fallback_params, headers=headers, cookies=cookies, timeout=TIMEOUTS["channels"])
                    if response.status_code == 200 and response.text and len(response.text.strip()) >= 5:
                        raw_text = response.text
                        xbmc.log(f"[Stalker] Fallback search successful for {server}", level=xbmc.LOGINFO)
                    else:
                        return []
                except:
                    return []
            else:
                return []

        xbmc.log(
            f"[Stalker] Raw response from {server}: {raw_text[:200]}",
            level=xbmc.LOGINFO,
        )

        # Stalker portals often return garbage text before/after the JSON object
        if "{" in raw_text:
            raw_text = raw_text[raw_text.find("{") :]
        if "}" in raw_text:
            raw_text = raw_text[: raw_text.rfind("}") + 1]
            
        try:
            data = json_loads(raw_text)

            results = []
            if isinstance(data, dict):
                js_data = data.get("js", {})
                if isinstance(js_data, dict):
                    # Try js -> data (standard) or js -> data -> data (paginated)
                    res_data = js_data.get("data", [])
                    if isinstance(res_data, dict):
                        results = res_data.get("data", [])
                    else:
                        results = res_data
                elif isinstance(js_data, list):
                    results = js_data
            elif isinstance(data, list):
                results = data

            if not isinstance(results, list):
                results = []

            return results
        except ValueError as e:
            xbmc.log(f"[Stalker] JSON decode failed for {server}: {e}", level=xbmc.LOGERROR)
            return []

    except Exception as e:
        xbmc.log(
            f"[Stalker] Search failed for {server} ({type_param}): {e}",
            level=xbmc.LOGWARNING,
        )
        return []


def show_search_results(query, server="server1"):
    """Display search results for channels using direct server search."""
    if not query:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    # Use direct server search
    matching_channels = fetch_stalker_search("itv", query, server)

    if not matching_channels:
        # Fallback to local search if direct search returns nothing (some portals are picky)
        all_channels = fetch_channels_by_category_from_server(None, server)
        search_term_lower = query.lower()
        matching_channels = [
            ch for ch in all_channels if search_term_lower in ch.get("name", "").lower()
        ]

    # Set plugin category and content
    xbmcplugin.setPluginCategory(_HANDLE, f"Cautare: {query}")
    xbmcplugin.setContent(_HANDLE, "videos")

    # Load favorites
    favorites_file = FAVORITES_FILE.format(server=server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as f:
            favorites = json_loads(f)
    except:
        favorites = []
    favorite_stream_ids = {fav["stream_id"] for fav in favorites}

    for ch in matching_channels:
        name = ch.get("name", "Unknown")
        logo = ch.get("logo") or ""
        cmd = ch.get("cmd", "")

        stream_id_match = RE_STREAM_ID.search(cmd)
        stream_id = stream_id_match.group(1) if stream_id_match else ch.get("id")

        if not stream_id:
            continue

        channel_label = name
        plot = ""
        if is_epg_enabled() and stream_id in epg_data:
            epg_items = epg_data[stream_id]
            current_prog = get_current_program(epg_items)
            if current_prog:
                channel_label = f"{name} - {current_prog}"
            plot = format_epg_tooltip(epg_items)

        li = xbmcgui.ListItem(label=channel_label)
        if logo:
            li.setArt({"thumb": logo, "icon": logo})

        li.setProperty("IsPlayable", "true")

        # Kodi 21 InfoTags
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(plot)

        url = f"{_BASE_URL}?mode=play&stream_id={stream_id}&name={quote_plus(name)}&server={server}&search_query={quote_plus(query)}"

        # Context menu
        context_menu = []
        if stream_id in favorite_stream_ids:
            context_menu.append(
                (
                    "Remove from Favorites",
                    f"RunPlugin({_BASE_URL}?mode=remove_from_favorites&stream_id={stream_id}&server={server})",
                )
            )
        else:
            add_fav_url = f"{_BASE_URL}?mode=add_to_favorites&stream_id={stream_id}&name={quote_plus(name)}&logo={quote_plus(logo)}&server={server}"
            context_menu.append(("Add to Favorites", f"RunPlugin({add_fav_url})"))
        li.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    if not matching_channels:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun canal pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(_HANDLE)


def show_vod_search_results(query, server="server1"):
    """Display VOD search results using direct server search."""
    if not query:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    matching_items = fetch_stalker_search("vod", query, server)

    # Set plugin category and content
    xbmcplugin.setPluginCategory(_HANDLE, f"Cautare Filme: {query}")
    xbmcplugin.setContent(_HANDLE, "movies")

    for item in matching_items:
        name = item.get("name", "Unknown")
        movie_id = item.get("id")
        year = item.get("year", "")
        description = item.get("description", "")

        li = xbmcgui.ListItem(label=f"{name} ({year})")
        li.setProperty("IsPlayable", "true")

        # Kodi 21 InfoTags
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(description)
        video_info.setYear(int(year) if year and year.isdigit() else 0)

        url = f"{_BASE_URL}?mode=play_vod&movie_id={movie_id}&server={server}&search_query={quote_plus(query)}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    if not matching_items:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun film pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(_HANDLE)


def show_series_search_results(query, server="server1"):
    """Display Series search results using direct server search."""
    if not query:
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return

    matching_items = fetch_stalker_search("series", query, server)

    # Set plugin category and content
    xbmcplugin.setPluginCategory(_HANDLE, f"Cautare Seriale: {query}")
    xbmcplugin.setContent(_HANDLE, "tvshows")

    for item in matching_items:
        name = item.get("name", "Unknown")
        series_id = item.get("id")
        year = item.get("year", "")
        description = item.get("description", "")

        li = xbmcgui.ListItem(label=f"{name} ({year})")

        # Kodi 21 InfoTags
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(description)
        video_info.setYear(int(year) if year and year.isdigit() else 0)

        # For series, clicking an item should lead to seasons
        movie_id = str(series_id).split(":")[0] if series_id else ""
        url = f"{_BASE_URL}?mode=list_seasons&movie_id={movie_id}&server={server}&search_query={quote_plus(query)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    if not matching_items:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun serial pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(_HANDLE)


if __name__ == "__main__":
    check_version_compatibility()
    router(get_params())
