import xbmcaddon
import xbmcvfs
import xbmc
import json
import os
import sys

# =============================================================================
# BASIC CONFIGURATION (ULTRA-LIGHT)
# =============================================================================

_SETTINGS_CACHE_KEY = 'tmdbm_settings'
_SETTINGS_DICT = None  # Python-level cache (RLI-safe, per-process)
_SETTINGS_MTIME = 0    # mtime-ul fișierului la ultimul parse
_WINDOW = None  # lazy init

def _get_window():
    global _WINDOW
    if _WINDOW is None:
        import xbmcgui
        _WINDOW = xbmcgui.Window(10000)
    return _WINDOW

def _get_settings_xml_path():
    _a = xbmcaddon.Addon()
    _profile = xbmcvfs.translatePath(_a.getAddonInfo('profile'))
    return os.path.join(_profile, 'settings.xml')

def _load_settings_dict():
    global _SETTINGS_DICT, _SETTINGS_MTIME
    try:
        import xml.etree.ElementTree as ET
        _path = _get_settings_xml_path()
        _mtime = os.path.getmtime(_path)
        with xbmcvfs.File(_path, 'rb') as _f:
            _raw = _f.read()
        _root = ET.fromstring(_raw)
        _d = {}
        for _el in _root.iter('setting'):
            _id = _el.get('id')
            if _id:
                _d[_id] = (_el.text or '')
        _SETTINGS_DICT = _d
        _SETTINGS_MTIME = _mtime
        _get_window().setProperty(_SETTINGS_CACHE_KEY, json.dumps(_d))
        # xbmc.log(f"[XML] Loaded {len(_d)} settings (mtime={_mtime})", xbmc.LOGINFO)  # DEBUG TIMING
        return _d
    except Exception as _e:
        xbmc.log(f"[XML] _load_settings_dict EXCEPTION: {_e}", xbmc.LOGINFO)
        return {}

def clear_settings_cache():
    """Invalidates Python + Window Property caches. Următorul getSetting() re-parsează."""
    global _SETTINGS_DICT
    _SETTINGS_DICT = None
    try:
        _get_window().clearProperty(_SETTINGS_CACHE_KEY)
    except:
        pass

def _get_settings_dict():
    """Python-level cache → mtime check → Window Property → XML parse."""
    global _SETTINGS_DICT, _SETTINGS_MTIME
    if _SETTINGS_DICT is not None:
        try:
            _mtime = os.path.getmtime(_get_settings_xml_path())
            if _mtime != _SETTINGS_MTIME:
                _SETTINGS_DICT = None
        except:
            pass
    if _SETTINGS_DICT is not None:
        return _SETTINGS_DICT
    try:
        _raw = _get_window().getProperty(_SETTINGS_CACHE_KEY)
        if _raw:
            _d = json.loads(_raw)
            if _d:
                # Check if file mtime matches Window Property cache
                try:
                    _mtime = os.path.getmtime(_get_settings_xml_path())
                    _SETTINGS_MTIME = _mtime
                except:
                    pass
                _SETTINGS_DICT = _d
                return _SETTINGS_DICT
    except:
        pass
    return _load_settings_dict()

# Wrapper care intermediază ADDON.getSetting prin Window Property cache (bypass RLI stale cache).
# Citește direct din settings.xml pe disk — RLI nu poate cache-ui asta.
class _AddonProxy:
    def __init__(self, addon):
        self._addon = addon
    def getSetting(self, setting_id):
        _d = _get_settings_dict()
        _val = _d.get(setting_id)
        if _val is not None:
            return _val
        # xbmc.log(f"[XML] getSetting({setting_id}) not in XML, FALLBACK to C++", xbmc.LOGINFO)  # DEBUG TIMING
        _fallback = self._addon.getSetting(setting_id)
        # xbmc.log(f"[XML] getSetting({setting_id}) FALLBACK: {_fallback}", xbmc.LOGINFO)  # DEBUG TIMING
        return _fallback
    def setSetting(self, setting_id, value):
        """Write directly to settings.xml — bypass RLI cache dump that corrupts other settings."""
        import xml.etree.ElementTree as ET
        import xbmcvfs
        _path = _get_settings_xml_path()
        try:
            with xbmcvfs.File(_path, 'rb') as _f:
                _raw = _f.read()
            _root = ET.fromstring(_raw)
            _found = False
            for _el in _root.iter('setting'):
                if _el.get('id') == setting_id:
                    _el.text = str(value)
                    _found = True
                    break
            if not _found:
                ET.SubElement(_root, 'setting', {'id': setting_id}).text = str(value)
            _out = ET.tostring(_root, encoding='utf-8')
            if not _out.startswith(b'<?xml'):
                _out = b'<?xml version="1.0" encoding="utf-8"?>\n' + _out
            with xbmcvfs.File(_path, 'wb') as _f:
                _f.write(_out)
        except Exception as _e:
            xbmc.log(f"[AddonProxy] setSetting fallback C++: {_e}", xbmc.LOGINFO)
            self._addon.setSetting(setting_id, value)
        clear_settings_cache()
    def __getattr__(self, name):
        return getattr(self._addon, name)

try:
    # Try automatic detection
    ADDON = _AddonProxy(xbmcaddon.Addon())
except RuntimeError:
    # If it fails (RunScript from Context Menu case), specify the ID manually
    ADDON = _AddonProxy(xbmcaddon.Addon('plugin.video.tmdbmovies'))

try:
    HANDLE = int(sys.argv[1])
except:
    HANDLE = -1

PAGE_LIMIT_OPTIONS = [20, 40, 60, 80, 100]

def _get_page_limit_idx():
    """Returnează indicele page_limit (0-4). ADDON.getSetting e deja patch-at să citească via JSON-RPC."""
    try:
        return int(ADDON.getSetting('page_limit'))
    except:
        return 0

def get_page_limit_index():
    """Returnează indicele page_limit ca string, pentru chei de cache."""
    return str(_get_page_limit_idx())

def get_page_limit_value():
    """Returnează valoarea numerică a page_limit."""
    return PAGE_LIMIT_OPTIONS[_get_page_limit_idx()]

def __getattr__(name):
    if name == 'PAGE_LIMIT':
        return get_page_limit_value()
    if name == 'SESSION':
        return get_session()
    raise AttributeError(name)

# Limba
LANG = 'en-US'

# Căi
ADDON_PATH = ADDON.getAddonInfo('path')
ADDON_DATA_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
FAVORITES_FILE = os.path.join(ADDON_DATA_DIR, 'favorites.json')
TRAKT_TOKEN_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_token.json')
TRAKT_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_history.json') 
TMDB_SESSION_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_session.json')
TMDB_LISTS_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_lists_cache.json')
TRAKT_LISTS_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_lists_cache.json')
TMDB_V4_TOKEN_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_v4_token.json')

LISTS_CACHE_TTL = 3600

# URLs
BASE_URL = "https://api.themoviedb.org/3"
TMDB_V4_BASE_URL = "https://api.themoviedb.org/4"
API_KEY = "28af5f8c53c4bd145a3a39525ccbf764"
TRAKT_CLIENT_ID = "67149cca60e6dd23f9f56ba45e1187ce0f9cb9c73363364eb24560c7627c3daf"
TRAKT_CLIENT_SECRET = '7a237effa309ecb580cc167985b5df05f04b1dc163edfd6d2000b8536fc44a92'
TRAKT_API_URL = "https://api.trakt.tv"
TRAKT_SYNC_INTERVAL = 300
# --- V4 API CONFIGURATION (TV SHOWS) ---
# Path where we save the user token (if it doesn't already exist, check line 35)
TMDB_V4_TOKEN_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_v4_token.json')

# App read token (Developer Read Token)
# This allows the addon to request user permissions.
# Copy the "API Read Access Token" from the TMDb website (Settings -> API)
TMDB_V4_READ_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIyOGFmNWY4YzUzYzRiZDE0NWEzYTM5NTI1Y2NiZjc2NCIsIm5iZiI6MTU1NzQwMzU0NC42NTIsInN1YiI6IjVjZDQxNzk4OTI1MTQxMDMyNjNiNWU2YiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.i065NOMgVeRfJ5nLLUlPRSssh8DXNnz93VnBQDsD4sU"



# Imagini
IMG_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/%s%s"
IMAGE_RESOLUTION = {
    'poster': 'w500',
    'fanart': 'w1280',
    'backdrop': 'original',
    'still': 'w300'
}



# Persistent HTTP session with retry (LAZY — se importă la primul API call)
_SESSION = None

def get_session():
    global _SESSION
    if _SESSION is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _SESSION = requests.Session()
        retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
        _SESSION.mount('https://api.themoviedb.org', HTTPAdapter(pool_maxsize=100, max_retries=retries, pool_block=False))
    return _SESSION
# -----------------------------------------------------------


# Cache RAM pentru TV Meta
TV_META_CACHE = {}

# =============================================================================
# USER AGENTS - LAZY
# =============================================================================
_USER_AGENTS = None
_CURRENT_SESSION_UA = None  # Global variable to remember the UA

def _init_user_agents():
    global _USER_AGENTS
    if _USER_AGENTS is None:
        _USER_AGENTS = [
            'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 12; moto g(60)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 13; M2101K6G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        ]
    return _USER_AGENTS

def get_random_ua():
    global _CURRENT_SESSION_UA
    if _CURRENT_SESSION_UA is None:
        import random
        # Generate one and save it
        _CURRENT_SESSION_UA = random.choice(_init_user_agents())
    return _CURRENT_SESSION_UA

def get_headers():
    return {
        'User-Agent': get_random_ua(),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
    }

# =============================================================================
# TORRSERVER HELPERS
# =============================================================================

def get_torrserver_host():
    """Returnează URL-ul complet TorrServer bazat pe modul selectat (Local/Custom)."""
    try:
        mode = ADDON.getSetting('torrserver_mode') or '0'
        if mode == '1':  # Custom
            return ADDON.getSetting('torrserver_custom_url') or 'http://127.0.0.1:8090'
        else:  # Local
            host = ADDON.getSetting('torrserver_local_host') or '127.0.0.1'
            port = ADDON.getSetting('torrserver_local_port') or '8090'
            return 'http://{}:{}'.format(host, port)
    except:
        return 'http://127.0.0.1:8090'

def get_torrserver_credentials():
    """Returnează (username, password) pentru TorrServer."""
    try:
        user = ADDON.getSetting('torrserver_user') or ''
        pwd = ADDON.getSetting('torrserver_pass') or ''
        return (user, pwd)
    except:
        return ('', '')

def get_stream_headers(url=None):
    ua = get_random_ua()
    headers = {
        'User-Agent': ua,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity;q=1, *;q=0',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'video',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-CH-UA-Mobile': '?1',
        'Sec-CH-UA-Platform': '"Android"',
    }
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            headers['Referer'] = f"{parsed.scheme}://{parsed.netloc}/"
            headers['Origin'] = f"{parsed.scheme}://{parsed.netloc}"
        except:
            pass
    return headers

# =============================================================================
# GENRE MAP
# =============================================================================
GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
    18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
    10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
}

# =============================================================================
# LANGUAGE HELPERS
# =============================================================================
LANG_TO_TMDB = {
    'enro': 'en-US', 'ro': 'ro-RO', 'en': 'en-US', 'es': 'es-ES', 'fr': 'fr-FR',
    'de': 'de-DE', 'it': 'it-IT', 'hu': 'hu-HU', 'pt': 'pt-PT',
    'ru': 'ru-RU', 'tr': 'tr-TR', 'bg': 'bg-BG', 'el': 'el-GR',
    'pl': 'pl-PL', 'cs': 'cs-CZ', 'nl': 'nl-NL', 'ar': 'ar-SA',
    'zh': 'zh-CN', 'ja': 'ja-JP', 'ko': 'ko-KR', 'sv': 'sv-SE',
    'da': 'da-DK', 'fi': 'fi-FI', 'no': 'no-NO', 'hr': 'hr-HR',
    'sr': 'sr-RS', 'sk': 'sk-SK', 'uk': 'uk-UA', 'he': 'he-IL',
    'th': 'th-TH', 'vi': 'vi-VN', 'id': 'id-ID', 'ms': 'ms-MY',
    'hi': 'hi-IN', 'fa': 'fa-IR', 'ca': 'ca-ES', 'eu': 'eu-ES',
    'gl': 'gl-ES',
}

def get_plot_language_code():
    """Returns the 2-letter language code from plot_language setting."""
    try:
        code = ADDON.getSetting('plot_language')
        code = str(code).strip().lower()
        if code == 'roen':
            code = 'enro'
        if code in ('0', '1'):  # backward compat for old enum values
            return 'ro' if code == '1' else 'en'
        return code if code in LANG_TO_TMDB else 'en'
    except:
        return 'en'

def get_plot_language():
    """Returns the TMDB language code for plot based on setting."""
    code = get_plot_language_code()
    return LANG_TO_TMDB.get(code, 'en-US')

def get_trailer_mode():
    """Returns 'yt-dlp' or 'youtube_plugin' based on setting."""
    try:
        val = ADDON.getSetting('trailer_player')
        return 'yt-dlp' if val == '0' else 'youtube_plugin'
    except:
        return 'yt-dlp'

def get_trailer_url(video_id):
    mode = get_trailer_mode()
    if mode == 'youtube_plugin':
        return f"plugin://plugin.video.youtube/play/?video_id={video_id}"
    return f"plugin://tmdbm.trailers/play/?video_id={video_id}"

def get_plot_img_lang():
    """Returns include_image_language parameter for the plot language."""
    code = get_plot_language_code()
    if code in ('en', 'enro'):
        return 'en,null'
    return f'{code},en,null'
