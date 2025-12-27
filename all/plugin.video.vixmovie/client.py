import requests
import re
import json
from urllib.parse import urlencode
import xbmcaddon
import xbmcvfs
import time



def get_lang():
    """Return the language code for TMDb requests.

    If the 'Show titles in English' toggle is ON, we force Romanian ('ro-RO') for plots.

    Otherwise, we use the addon setting 'tmdb_lang'.
    """

    try:
        show_titles_en = ADDON.getSettingBool('titles_english') if hasattr(ADDON, 'getSettingBool') else (ADDON.getSetting('titles_english') == 'true')
    except Exception:
        show_titles_en = True
    if show_titles_en:
        return 'ro-RO'
    try:
        return ADDON.getSetting('tmdb_lang') or 'ro-RO'
    except Exception:
        return 'ro-RO'

# Helper pentru logging, va scrie în kodi.log
def log(msg, level='info'):
    prefix = '[VIXMOVIE-CLIENT]'
    print(f"{prefix} [{level.upper()}]: {msg}")

# --- Setup Cache ---
ADDON = xbmcaddon.Addon()
ADDON_PROFILE_PATH = ADDON.getAddonInfo('profile')
CACHE_PATH = f"{ADDON_PROFILE_PATH}/cache.json"
CACHE_EXPIRY_DAYS = 7

def _load_cache():
    if not xbmcvfs.exists(ADDON_PROFILE_PATH):
        xbmcvfs.mkdirs(ADDON_PROFILE_PATH)
    if not xbmcvfs.exists(CACHE_PATH):
        return {}
    
    f = None
    try:
        f = xbmcvfs.File(CACHE_PATH, 'r')
        content = f.read()
        return json.loads(content)
    except Exception as e:
        log(f"Error loading cache file: {e}", level='error')
        return {}
    finally:
        if f:
            f.close()

def _save_cache(cache_data):
    f = None
    try:
        f = xbmcvfs.File(CACHE_PATH, 'w')
        content = json.dumps(cache_data, indent=4)
        f.write(content)
    except Exception as e:
        log(f"Error writing to cache file: {e}", level='error')
    finally:
        if f:
            f.close()

def get_stream_url(tmdb_id, season=None, episode=None):
    """
    Obține link-ul de stream .m3u8 de pe VixSrc folosind ID-ul TMDb.
    Modificat pentru a gestiona atât filme, cât și seriale.
    """
    if not tmdb_id:
        log("ID-ul TMDb lipsește. Anulare.", level='error')
        return None

    try:
        if season and episode:
            # URL pentru seriale
            page_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}"
        else:
            # URL pentru filme
            page_url = f"https://vixsrc.to/movie/{tmdb_id}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Referer': 'https://vixsrc.to/'
        }
        response = requests.get(page_url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text

        script_pattern = re.compile(r'window\.masterPlaylist\s*=\s*({[^<]*)')
        match = script_pattern.search(html_content)

        if not match:
            log("EROARE: Nu am găsit 'window.masterPlaylist' în codul HTML.", level='error')
            return None
        
        playlist_data_str = match.group(1)
        playlist_data_str = re.sub(r'}\s*window.*', '}', playlist_data_str, flags=re.DOTALL)
        playlist_data_str = re.sub(r'([{,])\s*([a-zA-Z0-9_]+)\s*:', r'\1"\2":', playlist_data_str)
        playlist_data_str = playlist_data_str.replace("'", '"')
        playlist_data_str = re.sub(r',(\s*})', r'\1', playlist_data_str)
        
        try:
            playlist_data = json.loads(playlist_data_str)
        except (json.JSONDecodeError, ValueError) as e:
            log(f"EROARE la parsarea JSON: {e}", level='error')
            log(f"String JSON problematic: {playlist_data_str[:500]}...", level='debug')
            return None

        base_url = playlist_data.get('url')
        params = playlist_data.get('params', {})
        
        if not base_url:
            log("EROARE: URL-ul de bază lipsește.", level='error')
            return None
            
        params['h'] = '1'
        params['lang'] = 'en'

        separator = '&' if '?' in base_url else '?'
        final_url = f"{base_url}{separator}{urlencode(params)}"
        
        return final_url

    except requests.exceptions.RequestException as e:
        log(f"EROARE la request-ul paginii: {e}", level='error')
        return None
    except Exception as e:
        log(f"A apărut o eroare neașteptată în get_stream_url: {e}", level='error')
        return None

def get_api_key():
    return ADDON.getSetting('tmdb_api_key')

# --- Movie-Specific Functions ---
def get_source_movie_ids():
    url = "https://vixsrc.to/api/list/movie/?lang=en"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        id_set = {item['tmdb_id'] for item in data if item.get('tmdb_id')}
        log(f"Found {len(id_set)} valid movie IDs.")
        return id_set
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log(f"Failed to fetch or parse movie list from source: {e}", level='error')
        return set()

# --- TV Show-Specific Functions ---
def get_source_tv_ids():
    url = "https://vixsrc.to/api/list/tv?lang=en"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        id_set = {item['tmdb_id'] for item in data if item.get('tmdb_id')}
        log(f"Found {len(id_set)} valid TV show IDs.")
        return id_set
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log(f"Failed to fetch or parse TV show list from source: {e}", level='error')
        return set()

def get_source_episode_info():
    url = "https://vixsrc.to/api/list/episode?lang=en"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        episode_map = {}
        for item in data:
            tmdb_id = item.get('tmdb_id')
            season = item.get('s')
            episode = item.get('e')
            if tmdb_id and season is not None and episode is not None:
                if tmdb_id not in episode_map:
                    episode_map[tmdb_id] = {}
                if season not in episode_map[tmdb_id]:
                    episode_map[tmdb_id][season] = set()
                episode_map[tmdb_id][season].add(episode)
        
        log(f"Processed episode info for {len(episode_map)} TV shows.")
        return episode_map
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log(f"Failed to fetch or parse episode list from source: {e}", level='error')
        return {}

# --- TMDb API Calls ---
def _call_tmdb_api(endpoint, params=None):
    api_key = get_api_key()
    if not api_key:
        log("TMDb API key is not set.", level='error')
        return None
    
    base_url = "https://api.themoviedb.org/3"
    params = params or {}
    params['api_key'] = api_key
    
    try:
        response = requests.get(f"{base_url}/{endpoint}", params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log(f"TMDb API request failed: {e}", level='error')
        return None


# --- Trailer helpers ---
def _best_trailer_from_results(results, prefer_langs=('en','en-US','', 'es-ES','es','ro-RO')):
    if not results:
        return None
    def score(v):
        s = 0
        if (v.get('type') or '').lower() == 'trailer':
            s += 10
        if v.get('official'):
            s += 5
        if (v.get('site') or '').lower() == 'youtube':
            s += 3
        lang = v.get('iso_639_1') or ''
        try:
            s += 5 - prefer_langs.index(lang)
        except ValueError:
            pass
        if v.get('published_at'):
            s += 1
        return s
    best = max(results, key=score)
    if (best.get('site') or '').lower() == 'youtube' and best.get('key'):
        return f"plugin://plugin.video.youtube/?action=play_video&videoid={best['key']}"
    return None

def get_movie_trailer_url(tmdb_id, language='en-US'):
    data = _call_tmdb_api(f"movie/{tmdb_id}/videos", {'language': language if language else 'en-US', 'include_video_language': 'en,en-US,null'})
    results = (data or {}).get('results') or []
    url = _best_trailer_from_results(results)
    return url

def get_tv_trailer_url(tmdb_id, language='en-US'):
    data = _call_tmdb_api(f"tv/{tmdb_id}/videos", {'language': language if language else 'en-US', 'include_video_language': 'en,en-US,null'})
    results = (data or {}).get('results') or []
    url = _best_trailer_from_results(results)
    return url
# --- TMDb Movie Functions ---
def get_popular_tmdb(page=1):
    return _call_tmdb_api('movie/popular', {'page': page, 'language': 'ro-RO'})

def get_movies_by_year_tmdb(year, page=1):
    params = {'primary_release_year': year, 'sort_by': 'popularity.desc', 'page': page, 'language': 'ro-RO'}
    return _call_tmdb_api('discover/movie', params)

def get_genres_tmdb():
    return _call_tmdb_api('genre/movie/list', {'language': 'ro-RO'})

def get_movies_by_genre_tmdb(genre_id, page=1):
    params = {'with_genres': genre_id, 'sort_by': 'popularity.desc', 'page': page, 'language': 'ro-RO'}
    return _call_tmdb_api('discover/movie', params)

def search_tmdb(query, page=1):
    return _call_tmdb_api('search/movie', {'query': query, 'page': page, 'language': 'ro-RO'})

# --- TMDb TV Show Functions ---
def get_popular_tv_tmdb(page=1):
    return _call_tmdb_api('tv/popular', {'page': page, 'language': 'ro-RO'})

def get_tv_by_year_tmdb(year, page=1):
    params = {'first_air_date_year': year, 'sort_by': 'popularity.desc', 'page': page, 'language': 'ro-RO'}
    return _call_tmdb_api('discover/tv', params)

def get_tv_genres_tmdb():
    return _call_tmdb_api('genre/tv/list', {'language': 'ro-RO'})

def get_tv_by_genre_tmdb(genre_id, page=1):
    params = {'with_genres': genre_id, 'sort_by': 'popularity.desc', 'page': page, 'language': 'ro-RO'}
    return _call_tmdb_api('discover/tv', params)

def search_tv_tmdb(query, page=1):
    return _call_tmdb_api('search/tv', {'query': query, 'page': page, 'language': 'ro-RO'})

def get_tv_details_tmdb(tv_id):
    return _call_tmdb_api(f'tv/{tv_id}', {'language': 'ro-RO'})

def get_season_details_tmdb(tv_id, season_number):
    return _call_tmdb_api(f'tv/{tv_id}/season/{season_number}', {'language': 'ro-RO'})
def get_movie_credits_tmdb(movie_id):
    # language used to localize character names when possible
    return _call_tmdb_api(f'movie/{movie_id}/credits', {'language': 'ro-RO'})

def get_tv_credits_tmdb(tv_id):
    return _call_tmdb_api(f'tv/{tv_id}/credits', {'language': 'ro-RO'})


def get_movie_details_en(movie_id):
    """TMDb movie details in English."""
    return _call_tmdb_api(f'movie/{movie_id}', {'language': 'en-US'})



def get_tv_details_en(tv_id):
    """TMDb TV details in English."""
    return _call_tmdb_api(f'tv/{tv_id}', {'language': 'en-US'})


def get_season_details_en(tv_id, season_number):
    return _call_tmdb_api(f'tv/{tv_id}/season/{season_number}', {'language': 'en-US'})


def get_episode_details_en(tv_id, season_number, episode_number):
    return _call_tmdb_api(f'tv/{tv_id}/season/{season_number}/episode/{episode_number}', {'language': 'en-US'})
