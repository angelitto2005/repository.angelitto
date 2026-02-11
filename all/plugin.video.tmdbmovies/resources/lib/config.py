import xbmcaddon
import xbmcvfs
import os
import sys

# =============================================================================
# CONFIGURAȚIE DE BAZĂ (ULTRA-LIGHT)
# =============================================================================

try:
    # Încercăm detectarea automată
    ADDON = xbmcaddon.Addon()
except RuntimeError:
    # Dacă eșuează (cazul RunScript din Context Menu), specificăm ID-ul manual
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')

try:
    HANDLE = int(sys.argv[1])
except:
    HANDLE = -1

PAGE_LIMIT = 21

# Limba
LANG = 'en-US'

# Căi
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
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
TRAKT_CLIENT_ID = "67149cca60e6dd23f9f56ba45e1187ce0f9cb9c73363364eb24560c7627c3daf"
TRAKT_API_URL = "https://api.trakt.tv"
TRAKT_SYNC_INTERVAL = 300

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



# --- MODIFICARE: ADĂUGARE SESIUNE PERSISTENTĂ (CA ÎN POV) ---
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SESSION = requests.Session()
retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
SESSION.mount('https://api.themoviedb.org', HTTPAdapter(pool_maxsize=100, max_retries=retries, pool_block=False))
# -----------------------------------------------------------


# Cache RAM pentru TV Meta
TV_META_CACHE = {}

# =============================================================================
# USER AGENTS - LAZY
# =============================================================================
_USER_AGENTS = None
_CURRENT_SESSION_UA = None  # Variabila globala pentru a tine minte UA-ul

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
        # Generam unul si il salvam
        _CURRENT_SESSION_UA = random.choice(_init_user_agents())
    return _CURRENT_SESSION_UA

def get_headers():
    return {
        'User-Agent': get_random_ua(),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
    }

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
# PLOT LANGUAGE HELPER
# =============================================================================
def get_plot_language():
    """Returnează codul de limbă pentru plot bazat pe setare."""
    try:
        setting = ADDON.getSetting('plot_language')
        if setting == '1':  # Română
            return 'ro-RO'
        return 'en-US'  # Default English
    except:
        return 'en-US'