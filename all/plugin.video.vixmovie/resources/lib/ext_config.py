# -*- coding: utf-8 -*-
"""
Standalone config for extended resolvers in VixMovie.
All HTTP providers are force-enabled. No dependency on tmdbmovies addon settings.
"""
import xbmcaddon
import xbmcvfs
import os
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =============================================================================
# ADDON WRAPPER - Forces all providers enabled
# =============================================================================

class _ForceEnabledAddon:
    """Fake ADDON object that returns 'true' for all provider settings."""
    
    _force_true_keys = {
        'enable_http_scrapers', 'use_sooti', 'use_nuviostreams', 'use_webstreamr',
        'use_streamvix', 'use_vixsrc', 'use_meowtv', 'use_dooflix', 'use_vidlink',
        'use_vaplayer', 'use_vsembed', 'use_videasy', 'use_netmirror', 'use_castle',
        'use_vidmody', 'use_movieblast', 'use_moviebox', 'use_lamovie',
        'use_yflix', 'use_primesrc', 'use_primesrcme', 'use_onlykdrama',
        'use_hdhub4u', 'use_mkvcinemas', 'use_moviesdrive', 'use_hdhub',
        'filter_duplicate_urls',
    }
    
    def __init__(self):
        try:
            self._real = xbmcaddon.Addon('plugin.video.vixmovie')
        except Exception:
            self._real = None
    
    def getSetting(self, key):
        if key in self._force_true_keys:
            return 'true'
        if key == 'scraper_timeout':
            return '25'
        if self._real:
            try:
                return self._real.getSetting(key)
            except Exception:
                pass
        return ''
    
    def setSetting(self, key, value):
        pass  # No-op
    
    def getAddonInfo(self, info_id):
        if self._real:
            return self._real.getAddonInfo(info_id)
        return ''


ADDON = _ForceEnabledAddon()

try:
    HANDLE = int(sys.argv[1])
except Exception:
    HANDLE = -1

PAGE_LIMIT = 21
LANG = 'en-US'

# Paths
try:
    ADDON_PATH = xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.vixmovie').getAddonInfo('path'))
    ADDON_DATA_DIR = xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.vixmovie').getAddonInfo('profile'))
except Exception:
    ADDON_PATH = ''
    ADDON_DATA_DIR = ''

FAVORITES_FILE = os.path.join(ADDON_DATA_DIR, 'favorites.json')
TRAKT_TOKEN_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_token.json')
TRAKT_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_history.json')
TMDB_SESSION_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_session.json')
TMDB_LISTS_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_lists_cache.json')
TRAKT_LISTS_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'trakt_lists_cache.json')
TMDB_V4_TOKEN_FILE = os.path.join(ADDON_DATA_DIR, 'tmdb_v4_token.json')
LISTS_CACHE_TTL = 3600

# URLs & API Keys
BASE_URL = "https://api.themoviedb.org/3"
TMDB_V4_BASE_URL = "https://api.themoviedb.org/4"
API_KEY = "28af5f8c53c4bd145a3a39525ccbf764"
TRAKT_CLIENT_ID = "67149cca60e6dd23f9f56ba45e1187ce0f9cb9c73363364eb24560c7627c3daf"
TRAKT_CLIENT_SECRET = '7a237effa309ecb580cc167985b5df05f04b1dc163edfd6d2000b8536fc44a92'
TRAKT_API_URL = "https://api.trakt.tv"
TRAKT_SYNC_INTERVAL = 300
TMDB_V4_READ_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIyOGFmNWY4YzUzYzRiZDE0NWEzYTM5NTI1Y2NiZjc2NCIsIm5iZiI6MTU1NzQwMzU0NC42NTIsInN1YiI6IjVjZDQxNzk4OTI1MTQxMDMyNjNiNWU2YiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.i065NOMgVeRfJ5nLLUlPRSssh8DXNnz93VnBQDsD4sU"

# Images
IMG_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/%s%s"
IMAGE_RESOLUTION = {
    'poster': 'w500',
    'fanart': 'w1280',
    'backdrop': 'original',
    'still': 'w300'
}

# Session
SESSION = requests.Session()
retries = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
SESSION.mount('https://api.themoviedb.org', HTTPAdapter(pool_maxsize=100, max_retries=retries, pool_block=False))

# Cache
TV_META_CACHE = {}

# User Agents
_USER_AGENTS = None
_CURRENT_SESSION_UA = None

def _init_user_agents():
    global _USER_AGENTS
    if _USER_AGENTS is None:
        _USER_AGENTS = [
            'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
            'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
        ]
    return _USER_AGENTS

def get_random_ua():
    global _CURRENT_SESSION_UA
    if _CURRENT_SESSION_UA is None:
        import random
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
        'Connection': 'keep-alive',
    }
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            headers['Referer'] = f"{parsed.scheme}://{parsed.netloc}/"
            headers['Origin'] = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass
    return headers

# Genre Map
GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance", 878: "Sci-Fi",
    53: "Thriller", 10752: "War", 37: "Western",
}

def get_plot_language():
    return 'en-US'
