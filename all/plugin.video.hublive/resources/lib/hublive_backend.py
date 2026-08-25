import hashlib
import json
import os
import random
import re
import threading
import time

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass
except Exception:
    pass
from collections import OrderedDict
from functools import lru_cache

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from epg import EpgManager

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


RE_BOX_CHARS = re.compile(r"[\u2500-\u259F\u2500-\u257F]")
RE_CATEGORY_PREFIX = re.compile(r"^[\|\-\s]+ro[\|\s\:\-\[\(]?", re.IGNORECASE)

_ADDON = xbmcaddon.Addon()
_session_storage = threading.local()


def get_session():
    """Get or create a thread-safe HTTP session."""
    if not hasattr(_session_storage, "session") or _session_storage.session is None:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=20, pool_maxsize=30, max_retries=3, pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
                "Connection": "keep-alive",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        _session_storage.session = session
    return _session_storage.session


TIMEOUTS = {
    "handshake": 10,
    "categories": 10,
    "channels": 20,
    "epg": 15,
    "playlink": 8,
    "playprobe": 6,
    "play": 15,
}


def _append_kodi_headers(url, mac=None, token=None, portal_url=None, random_val="0"):
    """
    Append MAG headers and cookies to the URL for Kodi's player.
    Kodi uses the '|' separator for headers. Values MUST be URL-encoded.
    
    For servers that use /play/live.php with play_token parameter,
    no additional headers are needed as authentication is in the URL.
    """
    if not url:
        return url
    
    # Strip existing options if any
    clean_url = url.split("|")[0]
    
    # Check if URL already contains play_token parameter
    # If so, the server handles authentication via URL params, not headers
    if "/play/live.php" in clean_url and "play_token=" in clean_url:
        xbmc.log(f"[Headers] URL contains play_token, returning clean URL without headers: {clean_url}", level=xbmc.LOGINFO)
        return clean_url
    
    # Standard MAG User-Agent (matches tester script)
    ua = "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
    
    from urllib.parse import quote
    
    # We use quote with no safe characters for maximum compatibility in header values
    # Kodi's player requires spaces as %20 to avoid splitting the option string incorrectly.
    headers = [f"User-Agent={quote(ua, safe='')}"]
    
    if token:
        headers.append(f"Authorization={quote('Bearer ' + token, safe='')}")
        
    if random_val and str(random_val) != "0":
        headers.append(f"X-Random={quote(str(random_val), safe='')}")
    
    cookies = []
    if mac:
        cookies.append(f"mac={mac}")
    if token:
        cookies.append(f"token={token}")
        
    if cookies:
        cookie_str = "; ".join(cookies)
        headers.append(f"Cookie={quote(cookie_str, safe='')}")
        
    if portal_url:
        referer = f"{portal_url.rstrip('/')}/stalker_portal/c/index.html"
        headers.append(f"Referer={quote(referer, safe='')}")
        
    res = f"{clean_url}|{'&'.join(headers)}"
    xbmc.log(f"[Headers] Final URL for Kodi: {res[:120]}...", level=xbmc.LOGDEBUG)
    return res


def is_epg_enabled():
    return _ADDON.getSetting("epg_enabled") == "true"


epg_data = OrderedDict()
EPG_CACHE_FILE = None
DEFAULT_EPG_CACHE_TTL = 1800
MAX_EPG_CHANNELS = 2000
_epg_lock = threading.RLock()


def get_epg_cache_ttl():
    try:
        value = int((_ADDON.getSetting("epg_cache_duration") or "").strip())
        return max(1, value) * 60
    except (TypeError, ValueError):
        return DEFAULT_EPG_CACHE_TTL


def get_epg_cache_file():
    global EPG_CACHE_FILE
    if EPG_CACHE_FILE is None:
        addon_profile_path = xbmcaddon.Addon().getAddonInfo("profile")
        try:
            addon_path = xbmcvfs.translatePath(addon_profile_path)
        except Exception:
            addon_path = xbmc.translatePath(addon_profile_path)

        if not os.path.exists(addon_path):
            os.makedirs(addon_path)
        EPG_CACHE_FILE = os.path.join(addon_path, "epg_cache.json")
    return EPG_CACHE_FILE


def load_epg_cache():
    cache_file = get_epg_cache_file()
    cache_ttl = get_epg_cache_ttl()
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as handle:
                cache_data = json_loads(handle)
                current_time = time.time()

                loaded_count = 0
                for stream_id, cache_entry in cache_data.items():
                    timestamp = cache_entry.get("timestamp", 0)
                    if current_time - timestamp < cache_ttl:
                        items = cache_entry.get("items", [])
                        for item in items:
                            if item.get("start_dt"):
                                from datetime import datetime

                                item["start_dt"] = datetime.fromisoformat(
                                    item["start_dt"]
                                )
                            if item.get("end_dt"):
                                from datetime import datetime

                                item["end_dt"] = datetime.fromisoformat(
                                    item["end_dt"]
                                )
                        _set_epg_items(stream_id, items)
                        loaded_count += 1

                xbmc.log(
                    f"[EPG] Loaded {loaded_count} channels from cache",
                    level=xbmc.LOGDEBUG,
                )
    except Exception as exc:
        xbmc.log(f"[EPG] Failed to load cache: {exc}", level=xbmc.LOGWARNING)


def save_epg_cache():
    cache_file = get_epg_cache_file()
    try:
        cache_data = {}
        current_time = time.time()

        with _epg_lock:
            epg_snapshot = list(epg_data.items())

        for stream_id, items in epg_snapshot:
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

        with open(cache_file, "w", encoding="utf-8") as handle:
            json_dumps(cache_data, handle)

        xbmc.log(f"[EPG] Saved {len(cache_data)} channels to cache", level=xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log(f"[EPG] Failed to save cache: {exc}", level=xbmc.LOGWARNING)


def get_current_program(epg_items):
    if not epg_items:
        return None

    from datetime import datetime

    now = datetime.now()

    for item in epg_items:
        start_dt = item.get("start_dt")
        end_dt = item.get("end_dt")
        if start_dt and end_dt and start_dt <= now < end_dt:
            name = item.get("name") or item.get("title") or ""
            return name.strip()

    for item in epg_items:
        start_dt = item.get("start_dt")
        if start_dt and now < start_dt:
            name = item.get("name") or item.get("title") or ""
            return f"Urmează: {name.strip()}"

    return None


def _evict_epg_if_needed():
    while len(epg_data) > MAX_EPG_CHANNELS:
        epg_data.popitem(last=False)


def _get_epg_storage_key(channel_key, server=None):
    if channel_key is None or channel_key == "":
        return None
    server_id = (server or _epg_current_server or "").strip()
    key = str(channel_key).strip()
    if not server_id:
        return key
    return f"{server_id}:{key}"


def _set_epg_items(channel_key, items):
    storage_key = _get_epg_storage_key(channel_key)
    if not storage_key:
        return
    with _epg_lock:
        epg_data[storage_key] = items
        epg_data.move_to_end(storage_key)
        _evict_epg_if_needed()


def epg_contains(channel_key):
    storage_key = _get_epg_storage_key(channel_key)
    if not storage_key:
        return False
    with _epg_lock:
        return storage_key in epg_data


def epg_contains_any(*channel_keys):
    storage_keys = [_get_epg_storage_key(key) for key in channel_keys if key is not None]
    with _epg_lock:
        return any(key in epg_data for key in storage_keys if key is not None)


def get_epg_items(channel_key):
    storage_key = _get_epg_storage_key(channel_key)
    if not storage_key:
        return []
    with _epg_lock:
        items = epg_data.get(storage_key, [])
        return list(items) if items else []


def set_server_auth(server, token, mac, random_value="0", timestamp=None):
    with _cache_lock:
        _auth_cache[server] = {
            "token": token,
            "mac": mac,
            "random": random_value,
            "timestamp": timestamp if timestamp is not None else time.time(),
        }
        _auth_failure_cache.pop(server, None)


def clear_token_cache():
    with _cache_lock:
        _token_cache["token"] = None
        _token_cache["mac"] = None
        _token_cache["timestamp"] = 0


def epg_callback(channel_key, items):
    xbmc.log(
        f"[DEBUG] EPG callback for channel {channel_key} with {len(items)} items. Data: {items}",
        level=xbmc.LOGDEBUG,
    )
    _set_epg_items(channel_key, items)


_servers_config = None
_servers_config_timestamp = 0
_SERVERS_CONFIG_TTL = 300


def load_servers_config(force_refresh=False):
    global _servers_config, _servers_config_timestamp
    if (
        not force_refresh
        and _servers_config is not None
        and (time.time() - _servers_config_timestamp) < _SERVERS_CONFIG_TTL
    ):
        xbmc.log("[Config] Using cached servers.json", level=xbmc.LOGDEBUG)
        return _servers_config
    return _load_servers_config_internal(force_refresh=force_refresh)


def reload_servers_config():
    global _servers_config, _servers_config_timestamp
    _servers_config = None
    _servers_config_timestamp = 0
    get_server_config.cache_clear()
    get_portal_url_for_server.cache_clear()
    get_macs_for_server.cache_clear()
    get_server_type.cache_clear()
    return load_servers_config(force_refresh=True)


def _get_servers_config_cache_file():
    addon_profile_path = xbmcaddon.Addon().getAddonInfo("profile")
    try:
        addon_path = xbmcvfs.translatePath(addon_profile_path)
    except Exception:
        addon_path = xbmc.translatePath(addon_profile_path)

    if not os.path.exists(addon_path):
        os.makedirs(addon_path)
    return os.path.join(addon_path, "servers.remote.cache.json")


def _load_cached_servers_config():
    cache_file = _get_servers_config_cache_file()
    try:
        if not os.path.exists(cache_file):
            return None, 0
        with open(cache_file, "r", encoding="utf-8") as handle:
            payload = json_loads(handle)
        if not isinstance(payload, dict):
            return None, 0
        config = payload.get("config")
        timestamp = float(payload.get("timestamp", 0) or 0)
        if not isinstance(config, dict):
            return None, 0
        return config, timestamp
    except Exception as exc:
        xbmc.log(f"[Config] Failed to read cached servers.json: {exc}", level=xbmc.LOGWARNING)
        return None, 0


def _save_cached_servers_config(config):
    cache_file = _get_servers_config_cache_file()
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json_dumps({"timestamp": time.time(), "config": config}, handle)
    except Exception as exc:
        xbmc.log(f"[Config] Failed to write cached servers.json: {exc}", level=xbmc.LOGWARNING)


def _load_servers_config_internal(force_refresh=False):
    global _servers_config, _servers_config_timestamp
    _servers_config = {"servers": []}

    if not force_refresh:
        cached_config, cached_timestamp = _load_cached_servers_config()
        if cached_config and (time.time() - cached_timestamp) < _SERVERS_CONFIG_TTL:
            _servers_config = cached_config
            _servers_config_timestamp = cached_timestamp
            xbmc.log("[Config] Loaded servers.json from disk cache", level=xbmc.LOGINFO)
            return _servers_config

    json_url = _ADDON.getSetting("servers_json_url")
    if json_url and json_url.strip():
        try:
            xbmc.log(
                f"[Config] Fetching servers.json from URL: {json_url}",
                level=xbmc.LOGINFO,
            )
            response = get_session().get(json_url.strip(), timeout=15, verify=False)
            response.raise_for_status()
            fetched_config = response.json()
            if fetched_config:
                if isinstance(fetched_config, list):
                    fetched_config = {"servers": fetched_config}
                
                if isinstance(fetched_config, dict):
                    _servers_config = fetched_config
                    _servers_config_timestamp = time.time()
                    _save_cached_servers_config(_servers_config)
                    xbmc.log("[Config] Loaded servers.json from remote URL", level=xbmc.LOGINFO)
                    return _servers_config
        except Exception as exc:
            xbmc.log(f"[Config] Failed to load from URL: {exc}", level=xbmc.LOGWARNING)

    cached_config, cached_timestamp = _load_cached_servers_config()
    if cached_config:
        _servers_config = cached_config
        _servers_config_timestamp = cached_timestamp or time.time()
        xbmc.log(f"[Config] Falling back to cached remote servers.json ({len(_servers_config.get('servers', []))} servers)", level=xbmc.LOGINFO)
        return _servers_config

    addon_path = _ADDON.getAddonInfo("path")
    servers_file = os.path.join(addon_path, "servers.json")
    xbmc.log(f"[Config] Attempting to load local servers.json from {servers_file}", level=xbmc.LOGINFO)

    try:
        if os.path.exists(servers_file):
            with open(servers_file, "r", encoding="utf-8") as handle:
                local_config = json_loads(handle)
                if local_config:
                    if isinstance(local_config, list):
                        local_config = {"servers": local_config}
                    _servers_config = local_config
                    _servers_config_timestamp = time.time()
                    xbmc.log(f"[Config] Loaded servers.json from local file ({len(_servers_config.get('servers', []))} servers)", level=xbmc.LOGINFO)
                    return _servers_config
        else:
            xbmc.log(f"[Config] local servers.json NOT FOUND at {servers_file}", level=xbmc.LOGWARNING)
    except Exception as exc:
        xbmc.log(f"[Config] Error loading local servers.json: {exc}", level=xbmc.LOGERROR)

    xbmc.log(f"[Config] Returning empty server list (final fallback)", level=xbmc.LOGWARNING)
    return _servers_config


@lru_cache(maxsize=8)
def get_server_config(server_id):
    config = load_servers_config()
    for server in config.get("servers", []):
        if server.get("id") == server_id:
            return server
    return None


@lru_cache(maxsize=8)
def get_portal_url_for_server(server_id):
    server = get_server_config(server_id)
    if server and server.get("portal_url"):
        return server["portal_url"]
    return None


@lru_cache(maxsize=8)
def get_macs_for_server(server_id):
    server = get_server_config(server_id)
    if server and server.get("macs"):
        return server["macs"]
    return None


@lru_cache(maxsize=8)
def get_server_type(server_id):
    server = get_server_config(server_id)
    if server:
        return server.get("type", "stalker")
    return "stalker"


_mac_list_cache = {}
_MAC_CACHE_TTL = 7200
_failed_mac_cache = {}
_FAILED_MAC_TTL = 900
_fetch_status = {}
_selected_mac_override = {}
_token_cache = {"token": None, "mac": None, "timestamp": 0}
_epg_current_server = "server1"
_categories_cache = {}
_CATEGORIES_CACHE_TTL = 86400
_CHANNELS_CACHE_TTL = 1800
_PORTAL_ONLINE_CACHE_TTL = 20
_AUTH_FAILURE_COOLDOWN = 45
_server_cache_folder_path = None
_auth_cache = {}
_auth_failure_cache = {}
_AUTH_TOKEN_TTL = 3600
_channels_memory_cache = {}
_category_channels_memory_cache = {}
_portal_online_cache = {}
_cache_lock = threading.RLock()
epg_manager = None


def set_epg_current_server(server):
    global _epg_current_server
    _epg_current_server = server or "server1"


def _normalize_mac(mac):
    return (mac or "").strip().upper()


def set_fetch_status(
    scope,
    server,
    status="idle",
    message="",
    portal_online=None,
    attempts=0,
    used_cache=False,
    stale_cache=False,
    item_count=0,
):
    _fetch_status[(scope, server)] = {
        "status": status,
        "message": message,
        "portal_online": portal_online,
        "attempts": attempts,
        "used_cache": used_cache,
        "stale_cache": stale_cache,
        "item_count": item_count,
        "timestamp": time.time(),
    }


def get_fetch_status(scope, server):
    return _fetch_status.get(
        (scope, server),
        {
            "status": "unknown",
            "message": "",
            "portal_online": None,
            "attempts": 0,
            "used_cache": False,
            "stale_cache": False,
            "item_count": 0,
            "timestamp": 0,
        },
    )


def _get_auth_failure_entry(server):
    with _cache_lock:
        entry = dict(_auth_failure_cache.get(server, {}))
    if not entry:
        return {}

    timestamp = float(entry.get("timestamp", 0) or 0)
    cooldown = int(entry.get("cooldown") or _AUTH_FAILURE_COOLDOWN)
    if not timestamp or (time.time() - timestamp) >= cooldown:
        with _cache_lock:
            _auth_failure_cache.pop(server, None)
        return {}
    return entry


def _note_auth_failure(server, portal_url=None, reason="", cooldown=None):
    with _cache_lock:
        _auth_failure_cache[server] = {
            "portal_url": (portal_url or "").rstrip("/"),
            "reason": reason or "",
            "timestamp": time.time(),
            "cooldown": int(cooldown or _AUTH_FAILURE_COOLDOWN),
        }


def _clear_auth_failure(server):
    with _cache_lock:
        _auth_failure_cache.pop(server, None)


def get_auth_max_attempts():
    try:
        value = int((_ADDON.getSetting("auth_max_attempts") or "").strip())
    except (TypeError, ValueError):
        value = 6
    return max(1, min(value, 12))


def get_mac_pool(server="server1"):
    global _mac_list_cache
    current_time = time.time()
    cached = _mac_list_cache.get(server, {})
    if cached.get("macs") and (current_time - cached.get("timestamp", 0)) < _MAC_CACHE_TTL:
        return list(cached["macs"])

    json_macs = get_macs_for_server(server) or []
    if json_macs:
        _mac_list_cache[server] = {
            "macs": list(json_macs),
            "timestamp": current_time,
        }
        return list(json_macs)
    return []


def get_recent_failed_macs(server="server1"):
    with _cache_lock:
        entries = dict(_failed_mac_cache.get(server, {}))
    if not entries:
        return set()

    now = time.time()
    fresh_entries = {mac: ts for mac, ts in entries.items() if (now - ts) < _FAILED_MAC_TTL}
    with _cache_lock:
        if fresh_entries:
            _failed_mac_cache[server] = fresh_entries
        else:
            _failed_mac_cache.pop(server, None)
    return set(fresh_entries.keys())


def note_failed_mac(server, mac):
    norm_mac = _normalize_mac(mac)
    if not norm_mac:
        return
    with _cache_lock:
        _failed_mac_cache.setdefault(server, {})[norm_mac] = time.time()


def clear_failed_mac(server, mac):
    norm_mac = _normalize_mac(mac)
    if not norm_mac:
        return
    with _cache_lock:
        server_failures = _failed_mac_cache.get(server)
        if not server_failures:
            return
        server_failures.pop(norm_mac, None)
        if not server_failures:
            _failed_mac_cache.pop(server, None)


def get_candidate_macs(server="server1", exclude_macs=None, limit=None):
    mac_pool = get_mac_pool(server)
    if not mac_pool:
        return []

    excluded = {
        _normalize_mac(mac)
        for mac in (exclude_macs or [])
        if _normalize_mac(mac)
    }
    recent_failed = get_recent_failed_macs(server)

    preferred = []
    fallback = []
    seen = set()
    for mac in mac_pool:
        norm_mac = _normalize_mac(mac)
        if not norm_mac or norm_mac in seen or norm_mac in excluded:
            continue
        seen.add(norm_mac)
        if norm_mac in recent_failed:
            fallback.append(mac)
        else:
            preferred.append(mac)

    random.shuffle(preferred)
    random.shuffle(fallback)
    candidates = preferred + fallback
    preferred_override = _selected_mac_override.get(server)
    if preferred_override:
        preferred_norm = _normalize_mac(preferred_override)
        for index, mac in enumerate(candidates):
            if _normalize_mac(mac) == preferred_norm:
                candidates.insert(0, candidates.pop(index))
                break
    if limit is not None:
        return candidates[:limit]
    return candidates


def get_random_mac_from_file(server="server1", exclude_macs=None):
    candidates = get_candidate_macs(server, exclude_macs=exclude_macs, limit=1)
    if candidates:
        return candidates[0]

    xbmcgui.Dialog().notification(
        "Eroare",
        f"Nu există adrese MAC pentru {server} în servers.json",
        xbmcgui.NOTIFICATION_ERROR,
    )
    return None


def _build_device_identity(mac):
    """Build device identity from MAC address (like reference script)."""
    mac_upper = (mac or "").strip().upper()
    serialnumber = hashlib.md5(mac_upper.encode()).hexdigest().upper()
    sn = serialnumber[0:13]
    device_id = hashlib.sha256(sn.encode()).hexdigest().upper()
    device_id2 = hashlib.sha256(mac_upper.encode()).hexdigest().upper()
    hw_version_2 = hashlib.sha1(mac_upper.encode()).hexdigest()

    return {
        "sn": sn,
        "device_id": device_id,
        "device_id2": device_id2,
        "adid": hw_version_2,
    }


def _activate_session(portal_url, mac, token, random_value, server="server1"):
    """
    Activate the session by requesting the profile. 
    Some portals require this step to fully authorize the token.
    """
    mac_upper = (mac or "").strip().upper()
    identity = _build_device_identity(mac_upper)
    sig = hashlib.sha256(str(random_value).encode()).hexdigest().upper()
    
    headers, cookies = _build_auth_headers_and_cookies(portal_url, mac_upper, token, random_value)

    params = {
        "type": "stb",
        "action": "get_profile",
        "hd": "1",
        "ver": "ImageDescription: 0.2.18-r23-250; ImageDate: Wed Aug 29 10:49:53 EEST 2018; PORTAL version: 5.3.1; API Version: JS API version: 343; STB API version: 146; Player Engine version: 0x58c",
        "num_banks": "2",
        "sn": identity["sn"],
        "stb_type": "MAG250",
        "client_type": "STB",
        "image_version": "218",
        "video_out": "hdmi",
        "device_id": identity["device_id2"],
        "device_id2": identity["device_id2"],
        "sig": sig,
        "auth_second_step": "1",
        "hw_version": "1.7-BD-00",
        "not_valid_token": "0",
        "timestamp": str(round(time.time())),
        "api_sig": "262",
        "prehash": "0",
        "JsHttpRequest": "1-xml",
    }

    try:
        response = get_session().get(
            f"{portal_url}/portal.php",
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=TIMEOUTS["handshake"],
            verify=False,
        )
        response.raise_for_status()
        xbmc.log(f"[Auth] Session activated for {server} ({portal_url})", level=xbmc.LOGINFO)
        return True
    except Exception as exc:
        xbmc.log(f"[Auth] Session activation failed for {server}: {exc}", level=xbmc.LOGWARNING)
        return False


def handshake(portal_url, mac, server="server1"):
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.cookies.clear()

    mac_upper = _normalize_mac(mac)
    xbmc.log(f"[Handshake] Testing MAC {mac_upper} for {portal_url}", level=xbmc.LOGINFO)
    
    from urllib.parse import urlparse
    parsed_url = urlparse(portal_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
        "Host": parsed_url.netloc,
    }

    identity = _build_device_identity(mac_upper)
    cookies = {
        "mac": mac_upper,
        "stb_lang": "en",
        "timezone": "America/Los_Angeles",
        "sn": identity["sn"],
        "device_id": identity["device_id"],
        "device_id2": identity["device_id2"],
        "adid": identity["adid"],
        "hw_version": "1.7-BD-00",
    }

    # Use fixed URL string to ensure parameter order, matching tester script
    url = f"{portal_url.rstrip('/')}/portal.php?type=stb&action=handshake&JsHttpRequest=1-xml"
    params = {"token": ""}

    try:
        response = session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=TIMEOUTS["handshake"],
            verify=False,
            allow_redirects=True,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except Exception as json_exc:
            xbmc.log(
                f"[Handshake] Failed to parse JSON response for {portal_url}. Status: {response.status_code}, Body: {response.text[:200]}",
                level=xbmc.LOGWARNING,
            )
            return None, "0"

        if isinstance(data, dict):
            js_data = data.get("js", {})
            if isinstance(js_data, dict):
                token = js_data.get("token")
                random_value = js_data.get("random") or "0"
                if token:
                    # After handshake, we MUST activate the session with get_profile
                    _activate_session(portal_url, mac_upper, token, random_value, server)
                    return token, random_value
                xbmc.log(
                    f"[Handshake] No token in response for {portal_url}. js data: {js_data}",
                    level=xbmc.LOGWARNING,
                )
                return None, "0"
            if isinstance(js_data, list):
                xbmc.log(
                    f"[Handshake] Server returned error list: {js_data}",
                    level=xbmc.LOGWARNING,
                )
                return None, "0"
            xbmc.log(
                f"[Handshake] Unexpected js data type: {type(js_data)}",
                level=xbmc.LOGWARNING,
            )
            _note_auth_failure(
                server, portal_url, f"unexpected_js_type:{type(js_data).__name__}"
            )
            return None, "0"
        if isinstance(data, list):
            xbmc.log(
                f"[Handshake] Server returned error list at root level: {data}",
                level=xbmc.LOGWARNING,
            )
            _note_auth_failure(server, portal_url, "root_error_list")
            return None, "0"
        xbmc.log(
            f"[Handshake] Unexpected response format: {type(data)}",
            level=xbmc.LOGWARNING,
        )
        _note_auth_failure(
            server, portal_url, f"unexpected_response_type:{type(data).__name__}"
        )
        return None, "0"
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        # Don't note permanent auth failure for connection resets or timeouts
        # This allows the iterator to try other MACs
        xbmc.log(f"[Handshake] Connection failed for {mac_upper}: {exc}", level=xbmc.LOGWARNING)
        return None, "0"
    except requests.exceptions.RequestException as exc:
        _note_auth_failure(server, portal_url, type(exc).__name__)
        with _cache_lock:
            _portal_online_cache[portal_url.rstrip("/")] = {
                "online": False,
                "timestamp": time.time(),
            }
        xbmc.log(f"[Handshake] Request failed: {exc}", level=xbmc.LOGERROR)
        return None, "0"
    except Exception as exc:
        _note_auth_failure(server, portal_url, type(exc).__name__)
        xbmc.log(f"[Handshake] Error: {exc}", level=xbmc.LOGERROR)
        return None, "0"
    finally:
        session.close()


def _build_auth_headers_and_cookies(portal_url, mac, token, random_value="0"):
    from urllib.parse import urlparse
    parsed_url = urlparse(portal_url)
    
    mac_upper = (mac or "").strip().upper()
    identity = _build_device_identity(mac_upper)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
            "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
        ),
        "Authorization": f"Bearer {token}",
        "Referer": f"{portal_url.rstrip('/')}/stalker_portal/c/index.html",
        "Host": parsed_url.netloc,
    }
    if random_value and str(random_value) != "0":
        headers["X-Random"] = str(random_value)

    cookies = {
        "mac": mac_upper,
        "token": token,
        "stb_lang": "en",
        "timezone": "America/Los_Angeles",
        "sn": identity["sn"],
        "device_id": identity["device_id"],
        "device_id2": identity["device_id2"],
        "adid": identity["adid"],
        "hw_version": "1.7-BD-00",
    }
    return headers, cookies


def invalidate_server_auth(server="server1", mac=None):
    with _cache_lock:
        cached = _auth_cache.get(server)

    if cached:
        with _cache_lock:
            if mac is None or _normalize_mac(cached.get("mac")) == _normalize_mac(mac):
                _auth_cache.pop(server, None)

    portal_url = get_portal_url_for_server(server)
    if portal_url:
        with _cache_lock:
            _portal_online_cache.pop(portal_url.rstrip("/"), None)
            _auth_failure_cache.pop(server, None)
    else:
        _clear_auth_failure(server)


def iter_server_auth_candidates(
    server="server1",
    use_cached=True,
    exclude_macs=None,
    max_attempts=None,
):
    if max_attempts is None:
        max_attempts = get_auth_max_attempts()
    portal_url = get_portal_url_for_server(server)
    if not portal_url or max_attempts <= 0:
        return

    excluded = {
        _normalize_mac(mac)
        for mac in (exclude_macs or [])
        if _normalize_mac(mac)
    }
    current_time = time.time()
    attempts_yielded = 0
    with _cache_lock:
        cached = dict(_auth_cache.get(server, {}))
    preferred_override = _selected_mac_override.get(server)
    preferred_norm = _normalize_mac(preferred_override)

    auth_failure_entry = _get_auth_failure_entry(server)
    if auth_failure_entry:
        xbmc.log(
            f"[Auth] Recent auth failure for {server}; reason={auth_failure_entry.get('reason')}. Reusing cache only.",
            level=xbmc.LOGINFO,
        )

    if (
        use_cached
        and cached.get("token")
        and cached.get("mac")
        and (current_time - cached.get("timestamp", 0)) < _AUTH_TOKEN_TTL
        and _normalize_mac(cached["mac"]) not in excluded
        and (not preferred_norm or _normalize_mac(cached["mac"]) == preferred_norm)
    ):
        headers, cookies = _build_auth_headers_and_cookies(
            portal_url, cached["mac"], cached["token"], cached.get("random", "0")
        )
        yield cached["token"], headers, cookies, portal_url, cached["mac"], cached.get("random", "0")
        attempts_yielded += 1
        excluded.add(_normalize_mac(cached["mac"]))

    if auth_failure_entry:
        return

    remaining_attempts = max_attempts - attempts_yielded
    if remaining_attempts <= 0:
        return

    for mac in get_candidate_macs(server, exclude_macs=excluded, limit=remaining_attempts):
        if attempts_yielded > 0:
            time.sleep(0.5)  # Gentle delay between handshakes
        
        token, random_val = handshake(portal_url, mac, server)
        if not token:
            note_failed_mac(server, mac)
            excluded.add(_normalize_mac(mac))
            if _get_auth_failure_entry(server):
                xbmc.log(
                    f"[Auth] Aborting further handshake attempts for {server} after portal-level auth failure.",
                    level=xbmc.LOGINFO,
                )
                return
            continue

        set_server_auth(server, token, mac, random_val)
        _clear_auth_failure(server)
        clear_failed_mac(server, mac)
        headers, cookies = _build_auth_headers_and_cookies(portal_url, mac, token, random_val)
        yield token, headers, cookies, portal_url, mac, random_val
        excluded.add(_normalize_mac(mac))
        attempts_yielded += 1
        if attempts_yielded >= max_attempts:
            return


def get_server_cache_folder():
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
    return os.path.join(get_server_cache_folder(), f"{server_id}_cache.json")


def get_categories_cache_file(server_id):
    return os.path.join(get_server_cache_folder(), f"{server_id}_categories.json")


def get_channels_cache_file(server_id):
    return os.path.join(get_server_cache_folder(), f"{server_id}_channels.json")


def get_category_channels_cache_file(server_id, category_id):
    safe_category_id = str(category_id).strip().replace(os.sep, "_")
    if os.altsep:
        safe_category_id = safe_category_id.replace(os.altsep, "_")
    # Sanitize invalid filename characters (Windows: < > : " / \ | ? *)
    for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        safe_category_id = safe_category_id.replace(char, "_")
    return os.path.join(
        get_server_cache_folder(), f"{server_id}_category_{safe_category_id}_channels.json"
    )


def load_categories_cache(server_id):
    cache_file = get_categories_cache_file(server_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as handle:
                content = handle.read()
                if not content:
                    xbmc.log(
                        f"[ServerCache] Categories cache file empty for {server_id}",
                        level=xbmc.LOGDEBUG,
                    )
                    return None
                data = json_loads(content)
            xbmc.log(
                f"[ServerCache] Loaded categories for {server_id}",
                level=xbmc.LOGDEBUG,
            )
            return data
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to load categories for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
    return None


def save_categories_cache(server_id, categories):
    cache_file = get_categories_cache_file(server_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json_dumps({"categories": categories, "timestamp": time.time()}, handle)
        xbmc.log(f"[ServerCache] Saved categories for {server_id}", level=xbmc.LOGDEBUG)
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to save categories for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )


def clear_all_cache(server="server1"):
    try:
        _categories_cache.pop(f"categories_{server}", None)
        _categories_cache.pop(f"timestamp_{server}", None)
        _channels_memory_cache.pop(server, None)
        for cache_key in list(_category_channels_memory_cache):
            if cache_key.startswith(f"{server}:"):
                _category_channels_memory_cache.pop(cache_key, None)
        portal_url = get_portal_url_for_server(server)
        if portal_url:
            with _cache_lock:
                _portal_online_cache.pop(portal_url.rstrip("/"), None)

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

        for cache_name in os.listdir(get_server_cache_folder()):
            if not cache_name.startswith(f"{server}_category_"):
                continue
            cache_path = os.path.join(get_server_cache_folder(), cache_name)
            if not os.path.isfile(cache_path):
                continue
            os.remove(cache_path)
            deleted_count += 1
            xbmc.log(f"[Cache] Deleted category channels cache: {cache_path}")

        if deleted_count > 0:
            xbmcgui.Dialog().notification(
                "Succes",
                f"Cache șters: {deleted_count} fișiere",
                xbmcgui.NOTIFICATION_INFO,
            )
        else:
            xbmcgui.Dialog().notification(
                "Informații",
                "Nu există cache de șters",
                xbmcgui.NOTIFICATION_INFO,
            )
    except Exception as exc:
        xbmc.log(f"[Cache] Error clearing cache: {exc}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Eroare",
            f"Nu s-a putut șterge cache-ul: {exc}",
            xbmcgui.NOTIFICATION_ERROR,
        )


def clear_all_cache_for_all_servers():
    xbmc.log("[Cache] Starting clear_all_cache_for_all_servers", level=xbmc.LOGINFO)
    try:
        servers_config = reload_servers_config()
        available_servers = servers_config.get("servers", [])
        xbmc.log(f"[Cache] Found {len(available_servers)} servers", level=xbmc.LOGINFO)

        if not available_servers:
            xbmcgui.Dialog().notification(
                "Informații",
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
                f"Se șterge cache-ul pentru {srv_name}...",
            )

            deleted_count = 0
            _categories_cache.pop(f"categories_{srv_id}", None)
            _categories_cache.pop(f"timestamp_{srv_id}", None)
            _channels_memory_cache.pop(srv_id, None)
            for cache_key in list(_category_channels_memory_cache):
                if cache_key.startswith(f"{srv_id}:"):
                    _category_channels_memory_cache.pop(cache_key, None)
            portal_url = get_portal_url_for_server(srv_id)
            if portal_url:
                with _cache_lock:
                    _portal_online_cache.pop(portal_url.rstrip("/"), None)

            categories_file = get_categories_cache_file(srv_id)
            channels_file = get_channels_cache_file(srv_id)

            if categories_file and os.path.exists(categories_file):
                os.remove(categories_file)
                deleted_count += 1

            if channels_file and os.path.exists(channels_file):
                os.remove(channels_file)
                deleted_count += 1

            for cache_name in os.listdir(get_server_cache_folder()):
                if not cache_name.startswith(f"{srv_id}_category_"):
                    continue
                cache_path = os.path.join(get_server_cache_folder(), cache_name)
                if not os.path.isfile(cache_path):
                    continue
                os.remove(cache_path)
                deleted_count += 1

            total_deleted += deleted_count
            xbmc.log(
                f"[Cache] Deleted {deleted_count} cache files for {srv_name}",
                level=xbmc.LOGINFO,
            )

        dp.close()
        xbmcgui.Dialog().notification(
            "Succes",
            f"Cache șters: {total_deleted} fișiere",
            xbmcgui.NOTIFICATION_INFO,
            3000,
        )
    except Exception as exc:
        xbmc.log(f"[Cache] Error clearing all cache: {exc}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Eroare",
            f"Nu s-a putut șterge cache-ul: {exc}",
            xbmcgui.NOTIFICATION_ERROR,
        )


def load_channels_cache(server_id):
    cache_file = get_channels_cache_file(server_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as handle:
                data = json_loads(handle)
            xbmc.log(
                f"[ServerCache] Loaded channels for {server_id}",
                level=xbmc.LOGDEBUG,
            )
            return data
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to load channels for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
    return None


def save_channels_cache(server_id, channels):
    cache_file = get_channels_cache_file(server_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json_dumps({"channels": channels, "timestamp": time.time()}, handle)
        xbmc.log(f"[ServerCache] Saved channels for {server_id}", level=xbmc.LOGDEBUG)
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to save channels for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )


def load_category_channels_cache(server_id, category_id):
    cache_file = get_category_channels_cache_file(server_id, category_id)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as handle:
                data = json_loads(handle)
            xbmc.log(
                f"[ServerCache] Loaded category channels for {server_id}/{category_id}",
                level=xbmc.LOGDEBUG,
            )
            return data
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to load category channels for {server_id}/{category_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
    return None


def save_category_channels_cache(server_id, category_id, channels):
    cache_file = get_category_channels_cache_file(server_id, category_id)
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json_dumps({"channels": channels, "timestamp": time.time()}, handle)
        xbmc.log(
            f"[ServerCache] Saved category channels for {server_id}/{category_id}",
            level=xbmc.LOGDEBUG,
        )
    except Exception as exc:
        xbmc.log(
            f"[ServerCache] Failed to save category channels for {server_id}/{category_id}: {exc}",
            level=xbmc.LOGWARNING,
        )


def load_cached_category_channels(server_id, allowed_category_ids=None, cache_ttl=None):
    cache_folder = get_server_cache_folder()
    if not os.path.isdir(cache_folder):
        return []

    ttl = float(cache_ttl if cache_ttl is not None else _CHANNELS_CACHE_TTL)
    allowed_ids = None
    if allowed_category_ids is not None:
        allowed_ids = {str(cat_id) for cat_id in allowed_category_ids}

    now = time.time()
    merged = []
    seen = set()
    prefix = f"{server_id}_category_"

    for cache_name in os.listdir(cache_folder):
        if not cache_name.startswith(prefix) or not cache_name.endswith("_channels.json"):
            continue

        category_id = cache_name[len(prefix) : -len("_channels.json")]
        if allowed_ids is not None and category_id not in allowed_ids:
            continue

        cache_path = os.path.join(cache_folder, cache_name)
        if not os.path.isfile(cache_path):
            continue

        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json_loads(handle)
        except Exception as exc:
            xbmc.log(
                f"[ServerCache] Failed to load merged category cache {cache_path}: {exc}",
                level=xbmc.LOGWARNING,
            )
            continue

        timestamp = float((payload or {}).get("timestamp", 0) or 0)
        if not timestamp or (now - timestamp) >= ttl:
            continue

        for channel in (payload or {}).get("channels") or []:
            item_id = channel.get("id") or channel.get("stream_id") or channel.get("cmd")
            dedupe_key = (str(category_id), str(item_id))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append(channel)

    if merged:
        xbmc.log(
            f"[ServerCache] Loaded {len(merged)} channels from category caches for {server_id}",
            level=xbmc.LOGDEBUG,
        )
    return merged


def get_server_auth(server="server1", force_refresh=False, exclude_macs=None, max_attempts=None):
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        return None, None, None, portal_url, "0"

    for token, headers, cookies, portal_url, mac, random_val in iter_server_auth_candidates(
        server=server,
        use_cached=not force_refresh,
        exclude_macs=exclude_macs,
        max_attempts=max_attempts,
    ):
        xbmc.log(f"[Auth] Using auth for {server} with MAC {mac}", level=xbmc.LOGDEBUG)
        return token, headers, cookies, portal_url, random_val

    return None, None, None, portal_url, "0"


def _fetch_stalker_list_with_retry(
    server,
    scope,
    request_name,
    request_fn,
    parse_fn,
    max_auth_attempts=None,
):
    if max_auth_attempts is None:
        max_auth_attempts = get_auth_max_attempts()
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        set_fetch_status(
            scope,
            server,
            status="no_portal",
            message="Portal URL is not configured.",
        )
        return None

    attempted_macs = set()
    attempts = 0
    portal_online = None
    last_error = f"Could not load {request_name}."

    for token, headers, cookies, portal_url, mac, random_val in iter_server_auth_candidates(
        server=server,
        use_cached=True,
        exclude_macs=attempted_macs,
        max_attempts=max_auth_attempts,
    ):
        attempts += 1
        norm_mac = _normalize_mac(mac)
        if norm_mac:
            attempted_macs.add(norm_mac)

        try:
            # Update request_fn call to pass random_val
            data = request_fn(token, headers, cookies, portal_url, random_val)
            items = parse_fn(data)
            if items:
                clear_failed_mac(server, mac)
                set_fetch_status(
                    scope,
                    server,
                    status="ok",
                    message=f"{request_name} loaded successfully.",
                    portal_online=True,
                    attempts=attempts,
                    used_cache=False,
                    stale_cache=False,
                    item_count=len(items),
                )
                return items

            last_error = f"{request_name} returned an empty list."
            xbmc.log(
                f"[Fetch:{scope}] Empty response for {server} with MAC {mac}",
                level=xbmc.LOGWARNING,
            )
        except Exception as exc:
            last_error = str(exc)
            xbmc.log(
                f"[Fetch:{scope}] Request failed for {server} with MAC {mac}: {exc}",
                level=xbmc.LOGWARNING,
            )

        if portal_online is None:
            portal_online = check_server_online(portal_url)
            xbmc.log(
                f"[Fetch:{scope}] Portal status for {server}: {portal_online}",
                level=xbmc.LOGINFO,
            )

        note_failed_mac(server, mac)
        invalidate_server_auth(server, mac=mac)

        if portal_online is False:
            set_fetch_status(
                scope,
                server,
                status="portal_off",
                message=f"{request_name} failed because the portal appears offline.",
                portal_online=False,
                attempts=attempts,
            )
            return None

    if portal_online is None:
        portal_online = check_server_online(portal_url)

    final_status = "auth_failed" if portal_online else "portal_off"
    final_message = last_error
    if portal_online is False:
        final_message = f"{request_name} failed because the portal appears offline."
    elif portal_online is True and attempts:
        final_message = f"{request_name} failed after trying {attempts} MAC address(es)."

    set_fetch_status(
        scope,
        server,
        status=final_status,
        message=final_message,
        portal_online=portal_online,
        attempts=attempts,
        used_cache=False,
        stale_cache=False,
        item_count=0,
    )
    return None


def _parse_live_categories_response(data):
    categories = []
    if isinstance(data, dict):
        js_data = data.get("js", {})
        raw_list = []
        if isinstance(js_data, list):
            raw_list = js_data
        elif isinstance(js_data, dict):
            raw_list = js_data.get("genres") or js_data.get("data") or js_data.get("items") or js_data.get("result") or []
        
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                cat_id = item.get("id") or item.get("genre_id")
                cat_title = item.get("title") or item.get("name") or item.get("genre_name", "")
                if cat_id is not None and cat_title:
                    categories.append(
                        {
                            "id": str(cat_id),
                            "title": str(cat_title).strip(),
                            "original_title": str(cat_title).strip(),
                        }
                    )
    return categories


def _request_live_categories(token, headers, cookies, portal_url, random_val="0"):
    headers, cookies = _build_auth_headers_and_cookies(portal_url, cookies.get("mac", ""), token, random_val)
    
    # Strategy 1: /portal.php (Standard)
    endpoints = [
        f"{portal_url.rstrip('/')}/portal.php",
        f"{portal_url.rstrip('/')}/server/load.php",
    ]
    
    last_response = None
    for url in endpoints:
        try:
            response = get_session().get(
                url,
                params={
                    "type": "itv",
                    "action": "get_genres",
                    "JsHttpRequest": "1-xml",
                },
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["categories"],
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            js_data = data.get("js", [])
            
            # If we got meaningful data, return it
            if js_data and (isinstance(js_data, list) or (isinstance(js_data, dict) and js_data)):
                xbmc.log(f"[Categories] Successfully fetched from {url}", level=xbmc.LOGDEBUG)
                return data
            
            last_response = data
            xbmc.log(f"[Categories] Empty response from {url}, trying next...", level=xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"[Categories] Failed to fetch from {url}: {exc}", level=xbmc.LOGDEBUG)
            continue
            
    return last_response or {"js": []}


def clean_category_title(title):
    if not title:
        return ""

    cleaned = RE_BOX_CHARS.sub("", str(title))
    cleaned = cleaned.replace("✰", "")
    cleaned = cleaned.strip(r"|-[]:() ")
    return cleaned.strip()


def _parse_all_channels_response(data):
    raw_channels = []
    if isinstance(data, dict):
        js_data = data.get("js", {})
        if isinstance(js_data, list):
            raw_channels = js_data
        elif isinstance(js_data, dict):
            raw_channels = js_data.get("data") or js_data.get("channels") or []
    elif isinstance(data, list):
        raw_channels = data

    channels = []
    for channel in raw_channels or []:
        logo = channel.get("logo") or ""
        if logo and RE_BOX_CHARS.search(logo):
            logo = ""
        channels.append(
            {
                "id": channel.get("id"),
                "name": clean_category_title(channel.get("name")),
                "cmd": channel.get("cmd"),
                "logo": logo,
                "tv_genre_id": channel.get("tv_genre_id"),
            }
        )
    return channels


def _request_all_channels(token, headers, cookies, portal_url, random_val="0"):
    headers, cookies = _build_auth_headers_and_cookies(portal_url, cookies.get("mac", ""), token, random_val)
    endpoints = [
        f"{portal_url.rstrip('/')}/portal.php",
        f"{portal_url.rstrip('/')}/server/load.php",
    ]
    
    last_response = None
    for url in endpoints:
        try:
            response = get_session().get(
                url,
                params={
                    "type": "itv",
                    "action": "get_all_channels",
                    "JsHttpRequest": "1-xml",
                },
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["channels"],
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            js_data = data.get("js", [])
            
            if js_data and (isinstance(js_data, list) or (isinstance(js_data, dict) and js_data)):
                xbmc.log(f"[Channels] Successfully fetched from {url}", level=xbmc.LOGDEBUG)
                return data
            
            last_response = data
            xbmc.log(f"[Channels] Empty response from {url}, trying next...", level=xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"[Channels] Failed to fetch from {url}: {exc}", level=xbmc.LOGDEBUG)
            continue
            
    return last_response or {"js": []}


def _request_channels_for_category(
    token, headers, cookies, portal_url, category_id, page_size_hint=0, random_val="0"
):
    all_items = []
    current_page = 1
    total_pages = 1
    
    endpoints = [
        f"{portal_url.rstrip('/')}/portal.php",
        f"{portal_url.rstrip('/')}/server/load.php",
    ]

    while current_page <= total_pages:
        # Re-build headers to ensure X-Random and other identity markers are fresh
        headers, cookies = _build_auth_headers_and_cookies(portal_url, cookies.get("mac", ""), token, random_val)
        
        page_items = []
        page_data = None
        
        for url in endpoints:
            try:
                response = get_session().get(
                    url,
                    params={
                        "type": "itv",
                        "action": "get_ordered_list",
                        "genre": category_id,
                        "p": current_page,
                        "JsHttpRequest": "1-xml",
                    },
                    headers=headers,
                    cookies=cookies,
                    timeout=TIMEOUTS["channels"],
                    verify=False,
                )
                response.raise_for_status()
                data = response.json()
                js_data = data.get("js", {})

                if isinstance(js_data, dict):
                    page_items = js_data.get("data") or js_data.get("channels") or js_data.get("items") or []
                    if page_items:
                        page_data = js_data
                        break
                elif isinstance(js_data, list) and js_data:
                    page_items = js_data
                    page_data = {"js": js_data, "total_items": len(js_data)}
                    break
                    
                xbmc.log(f"[Channels:Genre] Empty response from {url} for page {current_page}, trying next...", level=xbmc.LOGDEBUG)
            except Exception as exc:
                xbmc.log(f"[Channels:Genre] Failed to fetch from {url} for page {current_page}: {exc}", level=xbmc.LOGDEBUG)
                continue

        if not page_items:
            break

        if current_page == 1 and page_data:
            if isinstance(page_data, dict):
                total_items = int(page_data.get("total_items", 0) or 0)
                items_per_page = page_size_hint or len(page_items)
                if items_per_page > 0 and total_items > items_per_page:
                    total_pages = (total_items + items_per_page - 1) // items_per_page
            else:
                total_pages = 1

        all_items.extend(page_items)
        current_page += 1
        if current_page > 100:
            break

    return all_items


def _parse_simple_js_list_response(data):
    results = []
    if isinstance(data, dict):
        js_data = data.get("js", [])
        raw_list = []
        if isinstance(js_data, list):
            raw_list = js_data
        elif isinstance(js_data, dict):
            raw_list = js_data.get("data") or js_data.get("categories") or js_data.get("items") or js_data.get("result") or []
        
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                cat_id = item.get("id") or item.get("category_id")
                cat_title = item.get("title") or item.get("name") or item.get("category_name", "")
                if cat_id is not None and cat_title:
                    results.append(
                        {
                            "id": str(cat_id),
                            "title": str(cat_title).strip(),
                        }
                    )
    elif isinstance(data, list):
        # Handle root level list
        for item in data:
            if isinstance(item, dict):
                cat_id = item.get("id") or item.get("category_id")
                cat_title = item.get("title") or item.get("name") or ""
                if cat_id is not None and cat_title:
                    results.append({"id": str(cat_id), "title": str(cat_title).strip()})
    return results


def _request_vod_categories(token, headers, cookies, portal_url, random_val="0"):
    headers, cookies = _build_auth_headers_and_cookies(portal_url, cookies.get("mac", ""), token, random_val)
    endpoints = [
        f"{portal_url.rstrip('/')}/portal.php",
        f"{portal_url.rstrip('/')}/server/load.php",
    ]
    
    last_response = None
    for url in endpoints:
        try:
            response = get_session().get(
                url,
                params={
                    "type": "vod",
                    "action": "get_categories",
                    "JsHttpRequest": "1-xml",
                },
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["categories"],
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            js_data = data.get("js", [])
            
            if js_data and (isinstance(js_data, list) or (isinstance(js_data, dict) and js_data)):
                xbmc.log(f"[VOD:Categories] Successfully fetched from {url}", level=xbmc.LOGDEBUG)
                return data
            
            last_response = data
            xbmc.log(f"[VOD:Categories] Empty response from {url}, trying next...", level=xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"[VOD:Categories] Failed to fetch from {url}: {exc}", level=xbmc.LOGDEBUG)
            continue
            
    return last_response or {"js": []}


def _request_series_categories(token, headers, cookies, portal_url, random_val="0"):
    headers, cookies = _build_auth_headers_and_cookies(portal_url, cookies.get("mac", ""), token, random_val)
    endpoints = [
        f"{portal_url.rstrip('/')}/portal.php",
        f"{portal_url.rstrip('/')}/server/load.php",
    ]
    
    last_response = None
    for url in endpoints:
        try:
            response = get_session().get(
                url,
                params={
                    "type": "series",
                    "action": "get_categories",
                    "JsHttpRequest": "1-xml",
                },
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["categories"],
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            js_data = data.get("js", [])
            
            if js_data and (isinstance(js_data, list) or (isinstance(js_data, dict) and js_data)):
                xbmc.log(f"[Series:Categories] Successfully fetched from {url}", level=xbmc.LOGDEBUG)
                return data
            
            last_response = data
            xbmc.log(f"[Series:Categories] Empty response from {url}, trying next...", level=xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log(f"[Series:Categories] Failed to fetch from {url}: {exc}", level=xbmc.LOGDEBUG)
            continue
            
    return last_response or {"js": []}


def fetch_server_categories(server="server1", force_refresh=False):
    global _categories_cache

    current_time = time.time()
    cache_key = f"categories_{server}"

    if not _categories_cache.get(cache_key):
        file_cache = load_categories_cache(server)
        if file_cache and file_cache.get("categories"):
            _categories_cache[cache_key] = file_cache["categories"]
            _categories_cache[f"timestamp_{server}"] = file_cache.get("timestamp", 0)
            xbmc.log(
                f"[Categories] Loaded categories from file cache: {len(_categories_cache[cache_key])}",
                level=xbmc.LOGDEBUG,
            )

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
        set_fetch_status(
            "categories",
            server,
            status="ok",
            message="Using cached categories.",
            used_cache=True,
            stale_cache=False,
            item_count=len(_categories_cache[cache_key]),
        )
        return _categories_cache[cache_key]

    xbmc.log(f"[Categories] Fast fetch genres for {server}", level=xbmc.LOGINFO)
    dp = xbmcgui.DialogProgress()
    dp.create("HubLive", "Se descarcă categoriile...")
    try:
        categories = _fetch_stalker_list_with_retry(
            server,
            "categories",
            "live categories",
            _request_live_categories,
            _parse_live_categories_response,
        )
    finally:
        dp.close()
    if categories:
        save_categories_cache(server, categories)
        _categories_cache[cache_key] = categories
        _categories_cache[f"timestamp_{server}"] = current_time
        return categories

    stale_categories = _categories_cache.get(cache_key, [])
    if stale_categories:
        status = get_fetch_status("categories", server)
        set_fetch_status(
            "categories",
            server,
            status="stale_cache",
            message=status.get("message") or "Using stale cached categories.",
            portal_online=status.get("portal_online"),
            attempts=status.get("attempts", 0),
            used_cache=True,
            stale_cache=True,
            item_count=len(stale_categories),
        )
        xbmc.log(
            f"[Categories] Falling back to stale cache for {server}: {len(stale_categories)}",
            level=xbmc.LOGWARNING,
        )
        return stale_categories

    return []


def fetch_vod_categories(server="server1"):
    categories = _fetch_stalker_list_with_retry(
        server,
        "vod_categories",
        "VOD categories",
        _request_vod_categories,
        _parse_simple_js_list_response,
    )
    return categories or []


def fetch_series_categories(server="server1"):
    categories = _fetch_stalker_list_with_retry(
        server,
        "series_categories",
        "series categories",
        _request_series_categories,
        _parse_simple_js_list_response,
    )
    return categories or []


def get_sport_categories(server_categories):
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
    keywords_lower = [keyword.lower() for keyword in sport_keywords]
    for cat in server_categories:
        title = cat["title"].strip()
        title_lower = title.lower()
        if any(keyword in title_lower for keyword in keywords_lower):
            sport_cats.append(cat)
            xbmc.log(
                f"[Categories] Matched Sport category: {cat['title']}",
                level=xbmc.LOGDEBUG,
            )

    xbmc.log(
        f"[Categories] Found {len(sport_cats)} Sport categories",
        level=xbmc.LOGINFO,
    )
    return sport_cats


def get_romanian_categories(server_categories):
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
    prefixes_lower = [prefix.lower() for prefix in romanian_prefixes]
    for cat in server_categories:
        title = cat["title"].strip()
        title_lower = title.lower()

        is_romanian = False
        for prefix in prefixes_lower:
            if title_lower.startswith(prefix):
                is_romanian = True
                break

        if not is_romanian and RE_CATEGORY_PREFIX.match(title_lower):
            is_romanian = True

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
    global _channels_memory_cache, _category_channels_memory_cache

    current_time = time.time()
    category_cache_key = f"{server}:{category_id}"
    cached_category = _category_channels_memory_cache.get(category_cache_key)
    if (
        category_id is not None
        and cached_category
        and (current_time - cached_category.get("timestamp", 0)) < _CHANNELS_CACHE_TTL
    ):
        channels = cached_category.get("channels") or []
        set_fetch_status(
            "channels",
            server,
            status="ok",
            message="Using cached channel list for category.",
            used_cache=True,
            stale_cache=False,
            item_count=len(channels),
        )
        return channels

    cached_category_file = None
    if category_id is not None:
        cached_category_file = load_category_channels_cache(server, category_id)
        if (
            cached_category_file
            and cached_category_file.get("channels")
            and (current_time - cached_category_file.get("timestamp", 0)) < _CHANNELS_CACHE_TTL
        ):
            channels = cached_category_file.get("channels") or []
            _category_channels_memory_cache[category_cache_key] = {
                "channels": channels,
                "timestamp": cached_category_file.get("timestamp", current_time),
            }
            set_fetch_status(
                "channels",
                server,
                status="ok",
                message="Using cached channel list for category.",
                used_cache=True,
                stale_cache=False,
                item_count=len(channels),
            )
            return channels

    used_cache_source = False
    mem = _channels_memory_cache.get(server, {})
    if mem.get("channels") and (current_time - mem.get("timestamp", 0)) < _CHANNELS_CACHE_TTL:
        channels = mem["channels"]
        used_cache_source = True
        set_fetch_status(
            "channels",
            server,
            status="ok",
            message="Using cached channel list.",
            used_cache=True,
            stale_cache=False,
            item_count=len(channels),
        )
    else:
        file_cache = load_channels_cache(server)
        if (
            file_cache
            and file_cache.get("channels")
            and (current_time - file_cache.get("timestamp", 0)) < _CHANNELS_CACHE_TTL
        ):
            channels = file_cache["channels"]
            _channels_memory_cache[server] = {
                "channels": channels,
                "timestamp": file_cache["timestamp"],
            }
            used_cache_source = True
            set_fetch_status(
                "channels",
                server,
                status="ok",
                message="Using cached channel list.",
                used_cache=True,
                stale_cache=False,
                item_count=len(channels),
            )
        else:
            channels = None

    if category_id is not None and channels:
        filtered_channels = [
            ch for ch in channels if str(ch.get("tv_genre_id", "")) == str(category_id)
        ]
        _category_channels_memory_cache[category_cache_key] = {
            "channels": filtered_channels,
            "timestamp": current_time,
        }
        save_category_channels_cache(server, category_id, filtered_channels)
        set_fetch_status(
            "channels",
            server,
            status="ok",
            message="Using cached channel list for category.",
            used_cache=True,
            stale_cache=False,
            item_count=len(filtered_channels),
        )
        return filtered_channels

    if category_id is not None:
        dp = xbmcgui.DialogProgress()
        dp.create("HubLive", "Se descarcă lista de canale...")
        try:
            direct_channels = _fetch_stalker_list_with_retry(
                server,
                "channels",
                f"channel list for category {category_id}",
                lambda token, headers, cookies, portal_url, random_val: _request_channels_for_category(
                    token, headers, cookies, portal_url, category_id, random_val=random_val
                ),
                _parse_all_channels_response,
            )
        except Exception as exc:
            xbmc.log(
                f"[Channels] Direct category fetch failed for {server}/{category_id}: {exc}",
                level=xbmc.LOGWARNING,
            )
            direct_channels = None
        finally:
            dp.close()

        if direct_channels:
            _category_channels_memory_cache[category_cache_key] = {
                "channels": direct_channels,
                "timestamp": current_time,
            }
            save_category_channels_cache(server, category_id, direct_channels)
            set_fetch_status(
                "channels",
                server,
                status="ok",
                message="Loaded channel list directly for category.",
                used_cache=False,
                stale_cache=False,
                item_count=len(direct_channels),
            )
            return direct_channels

    if not channels:
        xbmc.log(f"[Channels] Lazy loading full channel list for {server}", level=xbmc.LOGINFO)
        dp = xbmcgui.DialogProgress()
        dp.create("HubLive", "Se descarcă grila de canale...")
        try:
            channels = _fetch_stalker_list_with_retry(
                server,
                "channels",
                "channel list",
                _request_all_channels,
                _parse_all_channels_response,
            )
            if channels:
                _channels_memory_cache[server] = {
                    "channels": channels,
                    "timestamp": current_time,
                }
                for cache_key in list(_category_channels_memory_cache):
                    if cache_key.startswith(f"{server}:"):
                        _category_channels_memory_cache.pop(cache_key, None)
                save_channels_cache(server, channels)
        finally:
            dp.close()

        if not channels:
            stale_channels = mem.get("channels") or []
            if not stale_channels:
                file_cache = load_channels_cache(server)
                if file_cache and file_cache.get("channels"):
                    stale_channels = file_cache["channels"]
                    _channels_memory_cache[server] = {
                        "channels": stale_channels,
                        "timestamp": file_cache.get("timestamp", current_time),
                    }

            if stale_channels:
                status = get_fetch_status("channels", server)
                set_fetch_status(
                    "channels",
                    server,
                    status="stale_cache",
                    message=status.get("message") or "Using stale cached channel list.",
                    portal_online=status.get("portal_online"),
                    attempts=status.get("attempts", 0),
                    used_cache=True,
                    stale_cache=True,
                    item_count=len(stale_channels),
                )
                xbmc.log(
                    f"[Channels] Falling back to stale cache for {server}: {len(stale_channels)}",
                    level=xbmc.LOGWARNING,
                )
                channels = stale_channels

    if not channels:
        return []
    if category_id is None:
        return channels
    filtered_channels = [
        ch for ch in channels if str(ch.get("tv_genre_id", "")) == str(category_id)
    ]
    _category_channels_memory_cache[category_cache_key] = {
        "channels": filtered_channels,
        "timestamp": current_time,
    }
    save_category_channels_cache(server, category_id, filtered_channels)
    if used_cache_source:
        set_fetch_status(
            "channels",
            server,
            status="ok",
            message="Using cached channel list for category.",
            used_cache=True,
            stale_cache=False,
            item_count=len(filtered_channels),
        )
    return filtered_channels


def epg_token_provider(server=None):
    if server is None:
        server = _epg_current_server

    token, headers, cookies, _, random_val = get_server_auth(server)
    if not token:
        xbmc.log("[EPG] Failed to get token via get_server_auth", level=xbmc.LOGWARNING)
        return None, {}, {}
    return token, headers, cookies


if is_epg_enabled():
    epg_portal_url = get_portal_url_for_server("server1")
    epg_manager = EpgManager(
        mode="stalker",
        base_url=epg_portal_url,
        callback=epg_callback,
        token_provider=epg_token_provider,
        connect_timeout=10.0,
        read_timeout=30.0,
        max_retries=3,
        backoff_factor=1.0,
        cache_ttl=float(get_epg_cache_ttl()),
        max_items_default=10,
        num_workers=10,
    )


def get_epg_manager():
    global epg_manager

    if not is_epg_enabled():
        # If EPG is disabled, stop any existing manager
        if epg_manager is not None:
            try:
                epg_manager.stop()
                xbmc.log("[EPG] Stopped EPG manager (EPG disabled)", level=xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log(f"[EPG] Error stopping manager: {exc}", level=xbmc.LOGWARNING)
            epg_manager = None
        return None

    if epg_manager is not None and not getattr(epg_manager, "_stop", False):
        return epg_manager

    epg_portal_url = get_portal_url_for_server(_epg_current_server or "server1")
    epg_manager = EpgManager(
        mode="stalker",
        base_url=epg_portal_url,
        callback=epg_callback,
        token_provider=epg_token_provider,
        connect_timeout=10.0,
        read_timeout=30.0,
        max_retries=3,
        backoff_factor=1.0,
        cache_ttl=float(get_epg_cache_ttl()),
        max_items_default=10,
        num_workers=10,
    )
    return epg_manager


def _get_probe_session():
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def check_server_online(portal_url, timeout=3):
    if not portal_url:
        return False

    portal_url = portal_url.rstrip("/")
    with _cache_lock:
        cached = dict(_portal_online_cache.get(portal_url, {}))
    current_time = time.time()
    if cached and (current_time - cached.get("timestamp", 0)) < _PORTAL_ONLINE_CACHE_TTL:
        xbmc.log(
            f"[ServerCheck] Using cached reachability for {portal_url}: {cached.get('online')}",
            level=xbmc.LOGDEBUG,
        )
        return bool(cached.get("online"))

    mag_headers = {
        "User-Agent": (
            "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
            "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
        ),
        "X-User-Agent": "Model: MAG250; Link: WiFi",
    }

    probe_session = _get_probe_session()
    try:
        try:
            probe_session.get(
                f"{portal_url}/portal.php",
                headers=mag_headers,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            with _cache_lock:
                _portal_online_cache[portal_url] = {
                    "online": True,
                    "timestamp": current_time,
                }
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            pass
        except Exception:
            pass

        try:
            probe_session.get(
                portal_url,
                headers=mag_headers,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            with _cache_lock:
                _portal_online_cache[portal_url] = {
                    "online": True,
                    "timestamp": current_time,
                }
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            with _cache_lock:
                _portal_online_cache[portal_url] = {
                    "online": False,
                    "timestamp": current_time,
                }
            return False
        except Exception:
            with _cache_lock:
                _portal_online_cache[portal_url] = {
                    "online": True,
                    "timestamp": current_time,
                }
            return True
    finally:
        probe_session.close()
