import sys
import os
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
import time
import threading
import requests
import json
import datetime
from urllib.parse import urlencode

from resources.lib.config import (
    TRAKT_API_URL, TRAKT_CLIENT_ID, TRAKT_TOKEN_FILE, TRAKT_CACHE_FILE,
    HANDLE, ADDON, IMG_BASE, BACKDROP_BASE, BASE_URL, API_KEY
)
from resources.lib.utils import read_json, write_json, log, get_json, get_language, paginate_list
from resources.lib.cache import cache_object, MainCache

from resources.lib import trakt_sync
from resources.lib.config import PAGE_LIMIT # Importam limita de 21

LANG = get_language()

# ADĂUGAT: Cale pentru icon Trakt
ADDON_PATH = ADDON.getAddonInfo('path')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')


# ===================== TRAKT AUTH =====================

def get_trakt_headers(token=None):
    h = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID
    }
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h

def get_trakt_token():
    token_data = read_json(TRAKT_TOKEN_FILE)
    return token_data.get('access_token') if token_data else None

def get_trakt_username(token=None):
    if not token:
        token = get_trakt_token()
    if not token: return None

    try:
        headers = get_trakt_headers(token)
        r = requests.get(f"{TRAKT_API_URL}/users/me", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('username')
    except:
        pass
    return "User"

def trakt_auth():
    try:
        r = requests.post(f"{TRAKT_API_URL}/oauth/device/code", json={'client_id': TRAKT_CLIENT_ID}, headers=get_trakt_headers(), timeout=10)
        data = r.json()
        user_code = data['user_code']
        device_code = data['device_code']
        verification_url = data['verification_url']
        interval = data['interval']
        expires_in = data['expires_in']
    except:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Eroare conexiune", xbmcgui.NOTIFICATION_ERROR)
        return

    pdialog = xbmcgui.DialogProgress()
    msg = (f"Mergi la: [B]{verification_url}[/B]\n\n"
           f"Introdu codul: [B][COLOR yellow]{user_code}[/COLOR][/B]")
    pdialog.create('Autentificare Trakt', msg)

    start_time = time.time()
    while not pdialog.iscanceled():
        elapsed = time.time() - start_time
        if elapsed > expires_in:
            pdialog.close()
            break

        percent = max(0, int(100 - (elapsed / expires_in * 100)))
        pdialog.update(percent, msg)
        time.sleep(interval)

        try:
            poll = requests.post(f"{TRAKT_API_URL}/oauth/device/token", json={'code': device_code, 'client_id': TRAKT_CLIENT_ID, 'client_secret': ''}, headers=get_trakt_headers(), timeout=10)
            if poll.status_code == 200:
                token_data = poll.json()
                write_json(TRAKT_TOKEN_FILE, token_data)
                user = get_trakt_username(token_data.get('access_token'))
                ADDON.setSetting('trakt_status', f"Conectat: {user}")
                pdialog.close()
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Conectat cu succes!", TRAKT_ICON, 3000, False)
                xbmc.executebuiltin("Container.Refresh")
                return
            elif poll.status_code == 410:
                break
            elif poll.status_code == 429:
                interval += 1
        except:
            pass
    pdialog.close()

def trakt_revoke():
    if xbmcvfs.exists(TRAKT_TOKEN_FILE):
        xbmcvfs.delete(TRAKT_TOKEN_FILE)

    if xbmcvfs.exists(TRAKT_CACHE_FILE):
        xbmcvfs.delete(TRAKT_CACHE_FILE)
    ADDON.setSetting('trakt_status', "Neconectat")
    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Deconectat.", TRAKT_ICON, 3000, False)
    xbmc.executebuiltin("Container.Refresh")


# ===================== TRAKT API REQUEST =====================

def trakt_api_request(endpoint, method='GET', data=None, params=None):

    token = get_trakt_token()
    headers = get_trakt_headers(token)
    url = f"{TRAKT_API_URL}{endpoint}"

    try:
        if method == 'GET':
            r = requests.get(url, headers=headers, params=params, timeout=15)
        elif method == 'POST':
            r = requests.post(url, headers=headers, json=data, timeout=15)
        elif method == 'DELETE':
            r = requests.delete(url, headers=headers, json=data, timeout=15)
        else:
            return None

        if r.status_code in [200, 201, 204]:
            if r.content:
                return r.json()
            return True
        return None
    except Exception as e:
        log(f"[TRAKT] API Error: {e}", xbmc.LOGERROR)
        return None


# ===================== TRAKT DATA HELPERS =====================

def get_trakt_request_worker(endpoint, params=None):
    token = get_trakt_token()
    headers = get_trakt_headers(token)
    url = f"{TRAKT_API_URL}{endpoint}"
    return requests.get(url, headers=headers, params=params, timeout=15)

def get_trakt_data(endpoint, params=None, expiration=48):
    string = f"trakt_{endpoint}_{str(params)}"
    return cache_object(get_trakt_request_worker, string, [endpoint, params], expiration=expiration)


# ===================== TMDB ID HELPERS =====================

def get_tmdb_id_from_trakt(trakt_item, media_type):

    if media_type == 'movie':
        return str(trakt_item.get('movie', trakt_item).get('ids', {}).get('tmdb', ''))
    elif media_type == 'show':
        return str(trakt_item.get('show', trakt_item).get('ids', {}).get('tmdb', ''))
    return ''

def get_tmdb_details(tmdb_id, media_type):

    if not tmdb_id or tmdb_id == 'None':
        return None
    endpoint = 'movie' if media_type in ['movie', 'movies'] else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
    try:
        return get_json(url)
    except:
        return None


# ===================== TRAKT WATCHLIST =====================

def get_trakt_watchlist(media_type='movies'):

    return trakt_api_request(f"/sync/watchlist/{media_type}", params={'extended': 'full'})

def add_to_trakt_watchlist(tmdb_id, media_type):

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request("/sync/watchlist", method='POST', data=data)
    if result:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Adăugat în [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        return True
    return False

def remove_from_trakt_watchlist(tmdb_id, media_type):

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request("/sync/watchlist/remove", method='POST', data=data)
    if result:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Șters din [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def is_in_trakt_watchlist(tmdb_id, media_type):

    watchlist = get_trakt_watchlist('movies' if media_type == 'movie' else 'shows')
    if not watchlist:
        return False
    for item in watchlist:
        item_id = get_tmdb_id_from_trakt(item, 'movie' if media_type == 'movie' else 'show')
        if str(item_id) == str(tmdb_id):
            return True
    return False


# ===================== TRAKT COLLECTION =====================

def get_trakt_collection(media_type='movies'):

    return trakt_api_request(f"/sync/collection/{media_type}", params={'extended': 'full'})

def add_to_trakt_collection(tmdb_id, media_type):

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request("/sync/collection", method='POST', data=data)
    if result:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Adăugat în [B][COLOR pink]Colecție[/COLOR][/B]", TRAKT_ICON, 3000, False)
        return True
    return False

def remove_from_trakt_collection(tmdb_id, media_type):

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request("/sync/collection/remove", method='POST', data=data)
    if result:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Șters din [B][COLOR pink]Colecție[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def is_in_trakt_collection(tmdb_id, media_type):

    collection = get_trakt_collection('movies' if media_type == 'movie' else 'shows')
    if not collection:
        return False
    for item in collection:
        item_id = get_tmdb_id_from_trakt(item, 'movie' if media_type == 'movie' else 'show')
        if str(item_id) == str(tmdb_id):
            return True
    return False


# ===================== TRAKT USER LISTS =====================

def get_trakt_user_lists():

    username = get_trakt_username()
    if not username:
        return []
    return trakt_api_request(f"/users/{username}/lists") or []

def get_trakt_list_items(list_slug, username=None):

    if not username:
        username = get_trakt_username()
    if not username:
        return []
    return trakt_api_request(f"/users/{username}/lists/{list_slug}/items", params={'extended': 'full'}) or []

def add_to_trakt_list(list_slug, tmdb_id, media_type):

    username = get_trakt_username()
    if not username:
        return False

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request(f"/users/{username}/lists/{list_slug}/items", method='POST', data=data)
    
    if result:
        # Am șters notificarea de aici. 
        # Returnăm True, iar funcția 'show_trakt_add_to_list_dialog' va afișa notificarea detaliată cu titlul filmului.
        return True
        
    return False

def remove_from_trakt_list(list_slug, tmdb_id, media_type):

    username = get_trakt_username()
    if not username:
        return False

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request(f"/users/{username}/lists/{list_slug}/items/remove", method='POST', data=data)
    if result:
        return True
    return False

def is_in_trakt_list(list_slug, tmdb_id, media_type):

    items = get_trakt_list_items(list_slug)
    if not items:
        return False
    for item in items:
        item_type = item.get('type', '')
        if item_type == 'movie' and media_type == 'movie':
            item_id = get_tmdb_id_from_trakt(item, 'movie')
        elif item_type == 'show' and media_type in ['tv', 'show']:
            item_id = get_tmdb_id_from_trakt(item, 'show')
        else:
            continue
        if str(item_id) == str(tmdb_id):
            return True
    return False


# ===================== TRAKT HISTORY =====================

def get_trakt_history(media_type='movies', limit=50, page=1):

    return trakt_api_request(f"/sync/history/{media_type}", params={'limit': limit, 'page': page, 'extended': 'full'})

def get_trakt_watched(media_type='movies'):

    return trakt_api_request(f"/sync/watched/{media_type}", params={'extended': 'full'})

def get_trakt_playback_progress():

    return trakt_api_request("/sync/playback", params={'extended': 'full'})


# ===================== TRAKT DISCOVER =====================

def get_trakt_trending(media_type='movies', limit=40):

    return trakt_api_request(f"/{media_type}/trending", params={'limit': limit, 'extended': 'full'})

def get_trakt_popular(media_type='movies', limit=40):

    return trakt_api_request(f"/{media_type}/popular", params={'limit': limit, 'extended': 'full'})

def get_trakt_most_watched(media_type='movies', period='weekly', limit=40):

    return trakt_api_request(f"/{media_type}/watched/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_most_favorited(media_type='movies', period='weekly', limit=40):

    return trakt_api_request(f"/{media_type}/favorited/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_anticipated(media_type='movies', limit=40):

    return trakt_api_request(f"/{media_type}/anticipated", params={'limit': limit, 'extended': 'full'})

def get_trakt_box_office():

    return trakt_api_request("/movies/boxoffice", params={'extended': 'full'})

def get_trakt_recommendations(media_type='movies', limit=40):

    return trakt_api_request(f"/recommendations/{media_type}", params={'limit': limit, 'extended': 'full'})


# ===================== TRAKT CALENDAR =====================

def get_trakt_calendar_shows(start_date=None, days=14):

    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    return trakt_api_request(f"/calendars/my/shows/{start_date}/{days}", params={'extended': 'full'})

def get_trakt_calendar_movies(start_date=None, days=30):

    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    return trakt_api_request(f"/calendars/my/movies/{start_date}/{days}", params={'extended': 'full'})

def get_trakt_calendar_premieres(start_date=None, days=30):

    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    return trakt_api_request(f"/calendars/all/shows/premieres/{start_date}/{days}", params={'extended': 'full'})

def get_trakt_calendar_new_shows(start_date=None, days=30):

    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    return trakt_api_request(f"/calendars/all/shows/new/{start_date}/{days}", params={'extended': 'full'})


# ===================== TRAKT GENRES =====================

def get_trakt_genres(media_type='movies'):

    return trakt_api_request(f"/genres/{media_type}")

def get_trakt_by_genre(media_type, genre_slug, limit=40):

    return None


# ===================== TRAKT PUBLIC LISTS =====================

def get_trakt_trending_lists(limit=20):

    return trakt_api_request("/lists/trending", params={'limit': limit})

def get_trakt_popular_lists(limit=20):

    return trakt_api_request("/lists/popular", params={'limit': limit})

def get_liked_lists():

    return trakt_api_request("/users/likes/lists", params={'limit': 50})


# ===================== TRAKT SYNC =====================

def perform_trakt_sync(force=False, silent=False):
    """Sync Trakt - totul e în SQL."""
    trakt_sync.sync_full_library(silent=silent, force=force)
    return True

def rebuild_watched_cache():
    """Reconstruiește cache-ul watched din baza SQL Trakt."""
    import time
    from resources.lib import trakt_sync
    from resources.lib.utils import write_json
    
    log("[SYNC] Rebuilding watched cache from SQL...")
    
    cache = {'movies': [], 'shows': {}, 'last_update': int(time.time())}
    
    conn = trakt_sync.get_connection()
    c = conn.cursor()
    
    # 1. FILME VIZIONATE
    try:
        c.execute("SELECT tmdb_id FROM trakt_watched_movies")
        for row in c.fetchall():
            tid = str(row[0] if isinstance(row, tuple) else row['tmdb_id'])
            if tid and tid != 'None':
                cache['movies'].append(tid)
    except Exception as e:
        log(f"[SYNC] Error reading watched movies: {e}", xbmc.LOGERROR)
    
    # 2. EPISOADE VIZIONATE
    try:
        c.execute("SELECT tmdb_id, season, episode FROM trakt_watched_episodes")
        for row in c.fetchall():
            if isinstance(row, tuple):
                tid, s, e = str(row[0]), row[1], row[2]
            else:
                tid = str(row['tmdb_id'])
                s = row['season']
                e = row['episode']
            
            if tid and tid != 'None':
                if tid not in cache['shows']:
                    cache['shows'][tid] = []
                ep_key = f"{s}x{e}"
                if ep_key not in cache['shows'][tid]:
                    cache['shows'][tid].append(ep_key)
    except Exception as e:
        log(f"[SYNC] Error reading watched episodes: {e}", xbmc.LOGERROR)
    
    conn.close()
    
    # Salvăm cache-ul
    write_json(TRAKT_CACHE_FILE, cache)
    
    log(f"[SYNC] Watched cache rebuilt: {len(cache['movies'])} movies, {len(cache['shows'])} shows")


def check_auto_sync():
    """
    Verifică dacă e nevoie de sincronizare și o rulează în fundal (thread separat)
    folosind noul sistem Smart Sync din trakt_sync.
    """
    token = get_trakt_token()
    if not token:
        return

    # Pornim direct sync_full_library într-un thread.
    # Aceasta va verifica intern (needs_sync) dacă chiar e nevoie de update.
    t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': True})
    t.daemon = True
    t.start()

def get_watched_counts(tmdb_id, content_type, season_num=None):
    """
    Returnează numărul de vizionări DIRECT din baza de date SQL.
    - movie: 1 dacă e vizionat, 0 altfel
    - tv: numărul total de episoade vizionate
    - season: numărul de episoade vizionate din sezonul specificat
    """
    from resources.lib import trakt_sync
    
    str_id = str(tmdb_id)
    
    # Verifică dacă DB există
    if not os.path.exists(trakt_sync.DB_PATH):
        return 0
    
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        
        if content_type == 'movie':
            c.execute("SELECT 1 FROM trakt_watched_movies WHERE tmdb_id=?", (str_id,))
            found = c.fetchone()
            conn.close()
            return 1 if found else 0
            
        elif content_type == 'tv':
            c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (str_id,))
            row = c.fetchone()
            conn.close()
            return row[0] if row else 0
            
        elif content_type == 'season' and season_num is not None:
            c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=? AND season=?", 
                      (str_id, int(season_num)))
            row = c.fetchone()
            conn.close()
            return row[0] if row else 0
        else:
            conn.close()
            return 0
            
    except Exception as e:
        log(f"[WATCHED] SQL Error: {e}", xbmc.LOGERROR)
        return 0


def check_episode_watched(tmdb_id, season_num, episode_num):
    """Verifică dacă un episod specific e vizionat - DIRECT din SQL."""
    from resources.lib import trakt_sync
    
    if not os.path.exists(trakt_sync.DB_PATH):
        return False
    
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", 
                  (str(tmdb_id), int(season_num), int(episode_num)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except Exception as e:
        log(f"[WATCHED] Episode check error: {e}", xbmc.LOGERROR)
        return False


def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_trakt=True):
    """Marchează ca vizionat - actualizează SQL-ul local + Trakt."""
    from resources.lib import trakt_sync
    import datetime
    
    tid = str(tmdb_id)
    
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        
        if content_type == 'movie':
            # Verifică dacă există deja
            c.execute("SELECT 1 FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            if c.fetchone():
                conn.close()
                if notify:
                    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Deja vizionat", TRAKT_ICON, 2000, False)
                return
            
            # Adaugă în SQL
            c.execute("INSERT OR REPLACE INTO trakt_watched_movies (tmdb_id, title, year, last_watched_at, poster, backdrop, overview) VALUES (?,?,?,?,?,?,?)",
                      (tid, '', '', now, '', '', ''))
            log(f"[WATCHED] Film {tid} marcat ca vizionat în SQL")
        else:
            # Episod
            if not season or not episode:
                conn.close()
                return
                
            c.execute("SELECT 1 FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
            if c.fetchone():
                conn.close()
                if notify:
                    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Deja vizionat", TRAKT_ICON, 2000, False)
                return
            
            c.execute("INSERT OR REPLACE INTO trakt_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)",
                      (tid, int(season), int(episode), '', now))
            log(f"[WATCHED] Episod {tid} S{season}E{episode} marcat ca vizionat în SQL")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        log(f"[WATCHED] Error marking as watched: {e}", xbmc.LOGERROR)
        return

    # Sync cu Trakt
    if sync_trakt:
        sync_single_watched_to_trakt(tmdb_id, content_type, season, episode)

    if notify:
        msg = "Film marcat vizionat" if content_type == 'movie' else f"S{season}E{episode} vizionat"
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", msg, TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")


def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, sync_trakt=True):
    """Marchează ca nevizionat - șterge din SQL-ul local + Trakt."""
    from resources.lib import trakt_sync
    
    tid = str(tmdb_id)
    removed = False
    
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        
        if content_type == 'movie':
            c.execute("DELETE FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            removed = c.rowcount > 0
            if removed:
                log(f"[WATCHED] Film {tid} șters din SQL")
        else:
            if season and episode:
                c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                          (tid, int(season), int(episode)))
                removed = c.rowcount > 0
                if removed:
                    log(f"[WATCHED] Episod {tid} S{season}E{episode} șters din SQL")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        log(f"[WATCHED] Error marking as unwatched: {e}", xbmc.LOGERROR)
        return

    if sync_trakt and removed:
        sync_single_unwatched_to_trakt(tmdb_id, content_type, season, episode)

    if removed:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Marcat ca nevizionat", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")

def sync_single_watched_to_trakt(tmdb_id, content_type, season=None, episode=None):

    token = get_trakt_token()
    if not token:
        return

    if content_type == 'movie':
        payload = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        payload = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}

    trakt_api_request("/sync/history", method='POST', data=payload)

def sync_single_unwatched_to_trakt(tmdb_id, content_type, season=None, episode=None):

    token = get_trakt_token()
    if not token:
        return

    if content_type == 'movie':
        payload = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        payload = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}

    trakt_api_request("/sync/history/remove", method='POST', data=payload)


def remove_from_progress(tmdb_id, content_type, season=None, episode=None):
    """
    Șterge din In Progress folosind metoda SCROBBLE 100% (Cea mai sigură).
    1. Delete Local.
    2. Try Remove Playback API.
    3. Fallback: Scrobble 100% (Clear Resume) -> Remove History (dacă e cazul).
    """
    from resources.lib import trakt_sync
    import xbmc
    import xbmcgui
    import time
    
    # --- PAS 1: Verificăm starea anterioară (pentru a proteja istoricul la rewatch) ---
    was_watched_before = False
    try:
        if content_type == 'movie':
            was_watched_before = trakt_sync.is_movie_watched(tmdb_id)
        elif season and episode:
            was_watched_before = trakt_sync.is_episode_watched(tmdb_id, season, episode)
    except: pass

    # --- PAS 2: Ștergere Locală (Instant UI) ---
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        if content_type == 'movie':
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(tmdb_id),))
        else:
            if season and episode:
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=? AND media_type='episode'", 
                          (str(tmdb_id), int(season), int(episode)))
        conn.commit()
        conn.close()
        log(f"[REMOVE] Local delete for {tmdb_id} done.")
    except Exception as e:
        log(f"[REMOVE] Local SQL Error: {e}", xbmc.LOGERROR)

    # --- PAS 3: Execuție API Trakt ---
    
    # Pregătire date
    ids = {'tmdb': int(tmdb_id)}
    payload_remove = {} # Pentru sync/playback/remove
    payload_scrobble = {'progress': 100, 'app_version': '1.0'} # Pentru scrobble
    
    if content_type == 'movie':
        payload_remove = {'movies': [{'ids': ids}]}
        payload_scrobble['movie'] = {'ids': ids}
    elif season and episode:
        payload_remove = {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}
        payload_scrobble['episode'] = {'season': int(season), 'number': int(episode), 'ids': ids} # Scrobble vrea structura asta la episod (simplificat)
        # Nota: La scrobble episode, structura e un pic diferita, dar incercam cu show/episode standard
        payload_scrobble['show'] = {'ids': ids}

    # A. Încercare Standard (/sync/playback/remove)
    log(f"[REMOVE] Method A: Standard Remove for {tmdb_id}...")
    res_std = trakt_api_request("/sync/playback/remove", method='POST', data=payload_remove)
    
    # B. Încercare Scrobble (Force Completion)
    # Executăm asta dacă A eșuează SAU preventiv, pentru că A nu garantează mereu.
    # Dacă API-ul standard a dat fail, trecem la planul B.
    if not res_std:
        log("[REMOVE] Method A failed. Starting Method B (Scrobble 100%)...", xbmc.LOGWARNING)
        
        # Scrobble STOP la 100% -> Asta distruge resume point-ul garantat
        res_scrobble = trakt_api_request("/scrobble/stop", method='POST', data=payload_scrobble)
        
        if res_scrobble:
            log("[REMOVE] Method B: Scrobble 100% success. Resume cleared.")
            
            # Acum, dacă NU trebuia să fie vizionat, ștergem intrarea din istoric pe care tocmai am creat-o
            if not was_watched_before:
                log("[REMOVE] Item was not watched before. Cleaning up history...")
                time.sleep(2.0) # Trakt are nevoie de timp să proceseze scrobble-ul
                
                # Folosim payload_remove care e compatibil și cu history/remove
                res_hist = trakt_api_request("/sync/history/remove", method='POST', data=payload_remove)
                if res_hist:
                    log("[REMOVE] History cleanup success.")
                    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Resume & History Șterse", TRAKT_ICON, 2000, False)
                else:
                    log("[REMOVE] History cleanup failed.", xbmc.LOGERROR)
            else:
                log("[REMOVE] Item was already watched. Leaving in history, resume cleared.")
                xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Resume Șters (Rămas Vizionat)", TRAKT_ICON, 2000, False)
        else:
            log("[REMOVE] Method B (Scrobble) failed.", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Eroare Comunicare Trakt", xbmcgui.NOTIFICATION_ERROR)
    else:
        log("[REMOVE] Method A Success.")
        xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Eliminat din Progres", TRAKT_ICON, 2000, False)

    xbmc.executebuiltin("Container.Refresh")

# ===================== CONTEXT MENUS =====================

def get_watched_context_menu(tmdb_id, content_type, season=None, episode=None):

    cm = []
    base_params = {'tmdb_id': tmdb_id, 'type': content_type}

    if season:
        base_params['season'] = season
    if episode:
        base_params['episode'] = episode

    watched_params = {'mode': 'mark_watched', **base_params}
    unwatched_params = {'mode': 'mark_unwatched', **base_params}

    cm.append(('Mark as [B][COLOR pink]Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(watched_params)})"))
    cm.append(('Mark as [B][COLOR pink]Unwatched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(unwatched_params)})"))

    return cm

def show_trakt_context_menu(tmdb_id, content_type, title=''):
    token = get_trakt_token()
    if not token:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Nu ești conectat", xbmcgui.NOTIFICATION_WARNING)
        return

    options = []
    
    # 1 & 2. Mark as Watched / Unwatched
    options.append(('Mark as [B][COLOR pink]Watched[/COLOR][/B]', 'mark_watched'))
    options.append(('Mark as [B][COLOR pink]Unwatched[/COLOR][/B]', 'mark_unwatched'))

    # 3 & 4. Lists Manager
    options.append(('Add to [B][COLOR pink]My Lists[/COLOR][/B]', 'add_to_list'))
    options.append(('Remove from [B][COLOR pink] My Lists[/COLOR][/B]', 'remove_from_list'))

    # 5. Watchlist Toggle (Dinamic)
    in_watchlist = is_in_trakt_watchlist(tmdb_id, content_type)
    if in_watchlist:
        options.append(('Remove from [B][COLOR pink]Watchlist[/COLOR][/B]', 'remove_watchlist'))
    else:
        options.append(('Add to [B][COLOR pink]Watchlist[/COLOR][/B]', 'add_watchlist'))

    # 6. Collection Toggle (Dinamic)
    in_collection = is_in_trakt_collection(tmdb_id, content_type)
    if in_collection:
        options.append(('Remove from [B][COLOR pink]Collection[/COLOR][/B]', 'remove_collection'))
    else:
        options.append(('Add to [B][COLOR pink]Collection[/COLOR][/B]', 'add_collection'))
    
    # 7. Add Rating
    options.append(('Add [B][COLOR pink]Rating[/COLOR][/B]', 'add_rating'))

    # Folosim contextmenu pentru a afisa meniul mic
    dialog = xbmcgui.Dialog()
    display_options = [opt[0] for opt in options]
    
    # contextmenu returneaza indexul selectat
    ret = dialog.contextmenu(display_options)

    if ret < 0:
        return

    action = options[ret][1]

    if action == 'add_watchlist':
        if add_to_trakt_watchlist(tmdb_id, content_type):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'remove_watchlist':
        if remove_from_trakt_watchlist(tmdb_id, content_type):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'add_collection':
        if add_to_trakt_collection(tmdb_id, content_type):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'remove_collection':
        if remove_from_trakt_collection(tmdb_id, content_type):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'add_to_list':
        show_trakt_add_to_list_dialog(tmdb_id, content_type, title)
    elif action == 'remove_from_list':
        show_trakt_remove_from_list_dialog(tmdb_id, content_type, title)
    elif action == 'mark_watched':
        mark_as_watched_internal(tmdb_id, content_type, sync_trakt=True, notify=True)
        # Refresh-ul e acum in mark_as_watched_internal (daca ai facut pasul anterior)
    elif action == 'mark_unwatched':
        mark_as_unwatched_internal(tmdb_id, content_type, sync_trakt=True)
    elif action == 'add_rating':
        rate_trakt_item(tmdb_id, content_type)

def show_trakt_add_to_list_dialog(tmdb_id, content_type, title=''):
    lists = get_trakt_user_lists()
    if not lists:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Nu ai liste create", TRAKT_ICON, 3000, False)
        return

    display_items = []
    
    for lst in lists:
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        
        formatted_item = f"[B][COLOR pink]{name}[/COLOR][/B] [B][COLOR FF00FA9A]({count})[/COLOR][/B]"
        
        display_items.append(formatted_item)

    dialog = xbmcgui.Dialog()
    
    # Afișăm meniul mic
    ret = dialog.contextmenu(display_items)

    if ret >= 0:
        # Folosim indexul returnat (ret) pentru a lua obiectul original din lista 'lists'
        selected_list = lists[ret]
        list_slug = selected_list.get('ids', {}).get('slug', '')
        list_name = selected_list.get('name', '')
        
        if list_slug:
            if add_to_trakt_list(list_slug, tmdb_id, content_type):
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] adăugat în [B][COLOR yellow]{list_name}[/COLOR][/B]", TRAKT_ICON, 3000, False)

def show_trakt_remove_from_list_dialog(tmdb_id, content_type, title=''):
    lists = get_trakt_user_lists()
    if not lists:
        return

    # Filtram doar listele care contin elementul
    lists_with_item = []
    for lst in lists:
        list_slug = lst.get('ids', {}).get('slug', '')
        if is_in_trakt_list(list_slug, tmdb_id, content_type):
            lists_with_item.append(lst)

    if not lists_with_item:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Nu este în nicio listă", TRAKT_ICON, 3000, False)
        return

    display_items = []
    for lst in lists_with_item:
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        display_items.append(f"[B][COLOR pink]{name}[/COLOR][/B] [B][COLOR FF00FA9A]({count})[/COLOR][/B]")

    dialog = xbmcgui.Dialog()
    # Folosim contextmenu
    ret = dialog.contextmenu(display_items)

    if ret >= 0:
        selected_list = lists_with_item[ret]
        list_slug = selected_list.get('ids', {}).get('slug', '')
        list_name = selected_list.get('name', '')
        
        if list_slug:
            if remove_from_trakt_list(list_slug, tmdb_id, content_type):
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] scos din [B][COLOR yellow]{list_name}[/COLOR][/B]", TRAKT_ICON, 3000, False)


def rate_trakt_item(tmdb_id, content_type):
    # Generam lista de note 1-10
    ratings = [f"{i}" for i in range(1, 11)]
    # Le afisam invers (10 sus, 1 jos) sau normal. Aici le pun normal 1-10.
    
    dialog = xbmcgui.Dialog()
    ret = dialog.contextmenu(ratings)

    if ret >= 0:
        # ret 0 este nota 1, ret 9 este nota 10
        rating_val = int(ratings[ret])
        
        # Pregatim payload-ul API
        if content_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}, 'rating': rating_val}]}
        else:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'rating': rating_val}]}

        # Trimitem la Trakt
        res = trakt_api_request("/sync/ratings", method='POST', data=data)
        
        if res:
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"Ai acordat nota [B][COLOR lime]{rating_val}[/COLOR][/B]", TRAKT_ICON, 3000, False)

# ===================== TRAKT MY LISTS - MODIFICAT COMPLET =====================

def trakt_my_lists():
    from resources.lib.tmdb_api import add_directory

    token = get_trakt_token()
    if not token:
        add_directory("[COLOR red]Conectare Trakt[/COLOR]", {'mode': 'trakt_auth'}, icon='DefaultUser.png', folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    username = get_trakt_username(token)

    # Acestea sunt statice, apar instant
    add_directory("Watchlist", {'mode': 'trakt_watchlist_menu'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Collection", {'mode': 'trakt_collection_menu'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("History", {'mode': 'trakt_history_menu'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    
    add_directory("[B][COLOR pink]--- Public Lists ---[/COLOR][/B]", {'mode': 'noop'}, folder=False)

    add_directory("Trakt Movies Lists", {'mode': 'trakt_movies_menu'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Trakt TV Shows Lists", {'mode': 'trakt_tv_menu'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)

    add_directory("Trending User Lists", {'mode': 'trakt_public_lists', 'list_type': 'trending'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Popular User Lists", {'mode': 'trakt_public_lists', 'list_type': 'popular'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Liked Lists", {'mode': 'trakt_liked_lists'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Search List", {'mode': 'trakt_search_list'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)

    # --- AICI E MODIFICAREA PENTRU VITEZĂ ---
    # Citim listele personale din baza de date SQL locală
    lists = trakt_sync.get_lists_from_db()
    
    # Fallback: Dacă DB e gol, le luăm de pe net (metoda veche)
    if not lists:
        lists = get_trakt_user_lists()

    if lists:
        add_directory("[B][COLOR pink]--- My Lists ---[/COLOR][/B]", {'mode': 'noop'}, folder=False)
        for lst in lists:
            # Suport atât pentru formatul SQL cât și API
            name = lst.get('name', 'Unknown')
            count = lst.get('item_count', 0)
            
            # Extragem slug corect
            ids = lst.get('ids', {})
            if isinstance(ids, str): # Uneori SQL returnează string json (rar), dar formatul curent e dict
                 try: ids = json.loads(ids)
                 except: pass
            slug = ids.get('slug', '')

            add_directory(
                f"{name} [COLOR gray]({count})[/COLOR]",
                {'mode': 'trakt_list_items', 'list_type': 'user_list', 'user': username, 'slug': slug},
                icon=TRAKT_ICON, thumb=TRAKT_ICON
            )

    xbmcplugin.endOfDirectory(HANDLE)


def trakt_movies_menu():
    """Submeniu pentru filme Trakt - citește din SQL."""
    from resources.lib.tmdb_api import add_directory
    
    ADDON_PATH = ADDON.getAddonInfo('path')
    TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
    
    add_directory("Trending Movies", {'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Popular Movies", {'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Anticipated Movies", {'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Top 10 Box Office", {'mode': 'trakt_discovery_list', 'list_type': 'boxoffice', 'media_type': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_tv_menu():
    """Submeniu pentru seriale Trakt - citește din SQL."""
    from resources.lib.tmdb_api import add_directory
    
    ADDON_PATH = ADDON.getAddonInfo('path')
    TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
    
    add_directory("Trending TV Shows", {'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Popular TV Shows", {'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("Anticipated TV Shows", {'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)

def trakt_discovery_list(params):
    from resources.lib.tmdb_api import add_directory, _process_movie_item, _process_tv_item
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    from resources.lib.utils import paginate_list

    list_type = params.get('list_type')
    media_type = params.get('media_type', 'movies')
    page = int(params.get('page', '1'))

    db_m_type = 'movie' if media_type == 'movies' else 'show'
    
    # 1. CITIRE DIN SQL
    data = trakt_sync.get_trakt_discovery_from_db(list_type, db_m_type)
    
    # 2. FALLBACK API (Dacă SQL e gol - ex: prima rulare)
    if not data:
        log(f"[TRAKT] Discovery SQL gol pentru {list_type}/{media_type}, folosim API...")
        limit_request = 40
        api_data = None
        
        if list_type == 'trending': 
            api_data = get_trakt_trending(media_type, limit_request)
        elif list_type == 'popular': 
            api_data = get_trakt_popular(media_type, limit_request)
        elif list_type == 'anticipated': 
            api_data = get_trakt_anticipated(media_type, limit_request)
        elif list_type == 'boxoffice': 
            api_data = get_trakt_box_office()
        
        if api_data:
            data = []
            for item in api_data:
                # Extrage metadata
                if 'movie' in item:
                    raw = item['movie']
                elif 'show' in item:
                    raw = item['show']
                else:
                    raw = item
                
                tmdb_id = str((raw.get('ids') or {}).get('tmdb', ''))
                if tmdb_id and tmdb_id != 'None':
                    title = raw.get('title') or raw.get('name', '')
                    year = str(raw.get('year', ''))
                    
                    data.append({
                        'tmdb_id': tmdb_id,
                        'title': title,
                        'year': year,
                        'overview': raw.get('overview', ''),
                        'poster_path': '',  # Va fi completat prin self-healing
                        'media_type': db_m_type
                    })

    if not data:
        add_directory("[COLOR gray]Lista se actualizează...[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # 3. PAGINARE
    paginated_items, total_pages = paginate_list(data, page, limit=PAGE_LIMIT)

    for item in paginated_items:
        # Convertim formatul SQL la format TMDb pentru procesare
        processed_item = {
            'id': item.get('tmdb_id') or item.get('id'),
            'title': item.get('title'),
            'name': item.get('title'),  # Pentru seriale
            'release_date': f"{item.get('year', '')}-01-01",
            'first_air_date': f"{item.get('year', '')}-01-01",
            'overview': item.get('overview', ''),
            'poster_path': item.get('poster_path', '')  # Poate fi gol, self-healing va completa
        }
        
        if media_type == 'movies':
            _process_movie_item(processed_item)
        else:
            _process_tv_item(processed_item)

    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {'mode': 'trakt_discovery_list', 'list_type': list_type, 'media_type': media_type, 'page': str(page + 1)},
            icon='DefaultFolder.png',
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)

# ADĂUGAT: Sub-meniuri pentru Trakt
def trakt_watchlist_menu():
    """Sub-meniu Trakt Watchlist: Movies și TV Shows"""
    from resources.lib.tmdb_api import add_directory
    
    add_directory("Movies Watchlist", {'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("TV Shows Watchlist", {'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_collection_menu():
    """Sub-meniu Trakt Collection: Movies și TV Shows"""
    from resources.lib.tmdb_api import add_directory
    
    add_directory("Movies Collection", {'mode': 'trakt_list_items', 'list_type': 'collection', 'media_filter': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("TV Shows Collection", {'mode': 'trakt_list_items', 'list_type': 'collection', 'media_filter': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_history_menu():
    """Sub-meniu Trakt History: Movies și TV Shows"""
    from resources.lib.tmdb_api import add_directory
    
    add_directory("Movies History", {'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'movies'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("TV Shows History", {'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'shows'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_public_lists(params):
    """Afișează liste publice Trakt (trending sau popular)"""
    from resources.lib.tmdb_api import add_directory
    
    list_type = params.get('list_type', 'trending')
    
    if list_type == 'trending':
        data = get_trakt_trending_lists(50)
    else:
        data = get_trakt_popular_lists(50)
    
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', item)
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_liked_lists(params=None):
    """Afișează listele apreciate de utilizator"""
    from resources.lib.tmdb_api import add_directory
    
    data = get_liked_lists()
    
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Nu ai liste apreciate", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', {})
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_search_list(params=None):
    """Caută liste pe Trakt"""
    from resources.lib.tmdb_api import add_directory
    
    dialog = xbmcgui.Dialog()
    query = dialog.input("Caută listă...", type=xbmcgui.INPUT_ALPHANUM)
    
    if not query:
        return
    
    data = trakt_api_request("/search/list", params={'query': query, 'limit': 50})
    
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Nicio listă găsită", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', {})
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


# ===================== TRAKT LIST CONTENT =====================

def trakt_list_content(params):
    """Afișează liste Trakt Discovery (trending, popular, etc.) din SQL CU POSTERE."""
    from resources.lib.tmdb_api import add_directory, _process_movie_item, _process_tv_item, IMG_BASE
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    from resources.lib.utils import paginate_list

    list_type = params.get('list_type')
    media_type = params.get('media_type', 'movies')
    page = int(params.get('new_page', '1'))

    data = None
    
    # 1. Citire din SQL
    db_m_type = 'movie' if media_type == 'movies' else 'show'
    
    # Mapare list_type pentru SQL
    sql_list_type = list_type
    if list_type == 'top10_boxoffice':
        sql_list_type = 'boxoffice'
    
    if list_type in ['trending', 'popular', 'anticipated', 'most_watched', 'most_favorited', 'top10_boxoffice', 'boxoffice']:
        data = trakt_sync.get_trakt_discovery_from_db(sql_list_type, db_m_type)
    
    # 2. Fallback API dacă SQL e gol
    if not data:
        limit_request = 100 
        if list_type == 'trending': 
            data = get_trakt_trending(media_type, limit_request)
        elif list_type == 'trending_recent': 
            data = get_trakt_trending(media_type, limit_request)
        elif list_type == 'popular': 
            data = get_trakt_popular(media_type, limit_request)
        elif list_type == 'most_watched': 
            data = get_trakt_most_watched(media_type, 'weekly', limit_request)
        elif list_type == 'most_favorited': 
            data = get_trakt_most_favorited(media_type, 'weekly', limit_request)
        elif list_type == 'anticipated': 
            data = get_trakt_anticipated(media_type, limit_request)
        elif list_type in ['top10_boxoffice', 'boxoffice']: 
            data = get_trakt_box_office()

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # 3. Paginare
    paginated_items, total_pages = paginate_list(data, page, limit=PAGE_LIMIT)

    for item in paginated_items:
        # Verificăm dacă datele vin din SQL (au poster_path) sau API
        if 'poster_path' in item:
            # Date din SQL - procesare directă
            if media_type == 'movies':
                _process_movie_item(item)
            else:
                _process_tv_item(item)
        else:
            # Date din API - extrage din structura Trakt
            if 'movie' in item: 
                raw = item['movie']
            elif 'show' in item: 
                raw = item['show']
            else: 
                raw = item

            tmdb_id = str(raw.get('ids', {}).get('tmdb', '') or raw.get('id', ''))
            title = raw.get('title', '') or raw.get('name', '')
            year_val = str(raw.get('year') or '')[:4]
            overview = raw.get('overview', '')

            if tmdb_id:
                fake_item = {
                    'id': tmdb_id,
                    'title': title if media_type == 'movies' else None,
                    'name': title if media_type != 'movies' else None,
                    'release_date': f"{year_val}-01-01",
                    'first_air_date': f"{year_val}-01-01",
                    'overview': overview,
                    'poster_path': ''  # API nu are poster direct
                }
                if media_type == 'movies': 
                    _process_movie_item(fake_item)
                else: 
                    _process_tv_item(fake_item)

    # Next Page
    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {
                'mode': 'build_movie_list' if media_type == 'movies' else 'build_tvshow_list',
                'action': f'trakt_{media_type.rstrip("s")}_{list_type}',
                'new_page': str(page + 1)
            },
            icon='DefaultFolder.png',
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_list_items(params):
    """Afișează conținutul listelor Trakt - CU POSTERE din SQL."""
    from resources.lib.tmdb_api import add_directory, _process_movie_item, _process_tv_item, IMG_BASE
    from resources.lib.utils import paginate_list

    list_type = params.get('list_type')
    user = params.get('user')
    slug = params.get('slug')
    media_filter = params.get('media_filter')  # 'movies' sau 'shows'
    page = int(params.get('new_page', '1'))

    data = None
    is_sql_data = False

    # =========================================================================
    # 1. ÎNCERCARE CITIRE DIN SQL (VITEZĂ MAXIMĂ)
    # =========================================================================
    if list_type == 'watchlist':
        db_type = 'movie' if media_filter == 'movies' else 'show'
        data = trakt_sync.get_trakt_list_from_db('watchlist', db_type)
        if data: is_sql_data = True
        
    elif list_type == 'collection':
        db_type = 'movie' if media_filter == 'movies' else 'show'
        data = trakt_sync.get_trakt_list_from_db('collection', db_type)
        if data: is_sql_data = True
        
    elif list_type == 'history':
        db_type = 'movie' if media_filter == 'movies' else 'show'
        data = trakt_sync.get_history_from_db(db_type)
        if data: is_sql_data = True
        
    elif list_type == 'user_list' and slug:
        # Liste personale Trakt
        data = trakt_sync.get_trakt_user_list_items_from_db(slug)
        if data: is_sql_data = True
        
    elif list_type == 'public_list' and slug and user:
        # Liste publice - fallback API (nu le salvăm în SQL momentan)
        data = trakt_api_request(f"/users/{user}/lists/{slug}/items", params={'extended': 'full'})

    # =========================================================================
    # 2. FALLBACK LA API dacă SQL e gol (doar dacă e absolut necesar)
    # =========================================================================
    if not data:
        if list_type == 'watchlist':
            if media_filter == 'movies':
                data = get_trakt_watchlist('movies')
            elif media_filter == 'shows':
                data = get_trakt_watchlist('shows')
                
        elif list_type == 'collection':
            if media_filter == 'movies':
                data = get_trakt_collection('movies')
            elif media_filter == 'shows':
                data = get_trakt_collection('shows')
                
        elif list_type == 'history':
            if media_filter == 'movies':
                data = get_trakt_history('movies', 100)
            elif media_filter == 'shows':
                episodes_data = get_trakt_history('episodes', 200)
                data = _extract_unique_shows_from_episodes(episodes_data)
                
        elif list_type == 'user_list' and slug:
            data = get_trakt_list_items(slug)

    if not data:
        add_directory("[COLOR gray]Lista este goală sau încă se sincronizează...[/COLOR]", {'mode': 'noop'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # =========================================================================
    # 3. PAGINARE ȘI AFIȘARE
    # =========================================================================
    paginated_items, total_pages = paginate_list(data, page, limit=PAGE_LIMIT)

    for item in paginated_items:
        if is_sql_data:
            # --- CALEA RAPIDĂ (SQL) ---
            tmdb_id = str(item.get('tmdb_id') or item.get('id', ''))
            title = item.get('title') or item.get('name', 'Unknown')
            year = item.get('year', '')
            poster_path = item.get('poster_path', '') # Imaginea e deja in SQL!
            media_type = item.get('media_type', 'movie' if media_filter == 'movies' else 'show')
            
            # Construim un obiect 'fake' care seamănă cu cel de la TMDb, 
            # dar are deja poster_path setat
            fake_item = {
                'id': tmdb_id,
                'title': title if media_type == 'movie' else None,
                'name': title if media_type != 'movie' else None,
                'poster_path': poster_path, # Cheia vitezei
                'release_date': f"{year}-01-01" if year else '',
                'first_air_date': f"{year}-01-01" if year else '',
                'overview': item.get('overview') or ''
            }
            
            if media_filter == 'movies' or media_type == 'movie':
                _process_movie_item(fake_item)
            else:
                _process_tv_item(fake_item)
                
        else:
            # --- CALEA LENTĂ (API FALLBACK) ---
            item_type = item.get('type', 'movie')
            
            if item_type == 'movie':
                media_data = item.get('movie', item)
                tmdb_id = str(media_data.get('ids', {}).get('tmdb', ''))
                if tmdb_id and tmdb_id != 'None':
                    _process_trakt_item_with_tmdb(tmdb_id, 'movie', media_data)
                    
            elif item_type == 'show':
                media_data = item.get('show', item)
                tmdb_id = str(media_data.get('ids', {}).get('tmdb', ''))
                if tmdb_id and tmdb_id != 'None':
                    _process_trakt_item_with_tmdb(tmdb_id, 'show', media_data)

    # Next Page
    if page < total_pages:
        next_params = {
            'mode': 'trakt_list_items', 
            'list_type': list_type, 
            'new_page': str(page + 1)
        }
        if user: next_params['user'] = user
        if slug: next_params['slug'] = slug
        if media_filter: next_params['media_filter'] = media_filter
            
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            next_params,
            icon='DefaultFolder.png',
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if media_filter == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)

def _extract_unique_shows_from_episodes(episodes_data):
    """Extrage serialele unice din lista de episoade vizionate"""
    if not episodes_data:
        return []
    
    seen_shows = {}
    
    for item in episodes_data:
        show_data = item.get('show', {})
        show_id = show_data.get('ids', {}).get('tmdb')
        
        if show_id and show_id not in seen_shows:
            # Creează un item în format show pentru procesare
            seen_shows[show_id] = {
                'type': 'show',
                'show': show_data
            }
    
    return list(seen_shows.values())


# ===================== PROCESS TRAKT ITEM - MODIFICAT CU WATCHED STATUS =====================

def _process_trakt_item_with_tmdb(tmdb_id, media_type, trakt_data):
    """Procesează un item Trakt și îl afișează cu metadate TMDb (Doar EN)."""
    from resources.lib.tmdb_api import add_directory, IMG_BASE, BACKDROP_BASE
    from resources.lib.cache import cache_object

    tmdb_endpoint = 'movie' if media_type == 'movie' else 'tv'

    def tmdb_worker(u):
        return requests.get(u, timeout=10)

    # Cerem datele în EN (LANG este 'en-US' din config)
    url = f"{BASE_URL}/{tmdb_endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
    tmdb_data = cache_object(tmdb_worker, f"meta_{media_type}_{tmdb_id}_{LANG}", url, expiration=168)

    # Titlul din Trakt ca bază
    title = trakt_data.get('title') or trakt_data.get('name', 'Unknown')
    year = str(trakt_data.get('year', ''))

    poster = ''
    backdrop = ''
    plot = ''
    
    # Variabile implicite
    rating = 0
    votes = 0
    premiered = ''
    studio = ''
    duration = 0

    if tmdb_data:
        if tmdb_data.get('poster_path'):
            poster = f"{IMG_BASE}{tmdb_data['poster_path']}"
        if tmdb_data.get('backdrop_path'):
            backdrop = f"{BACKDROP_BASE}{tmdb_data['backdrop_path']}"
        
        # MODIFICARE: Logica de Fallback RO -> EN a fost ștearsă complet.
        # Luăm direct titlul din TMDb. Acesta e garantat în engleză datorită parametrului URL.
        tmdb_title = tmdb_data.get('title') if media_type == 'movie' else tmdb_data.get('name')
        if tmdb_title:
            title = tmdb_title

        plot = tmdb_data.get('overview', '')
        
        # Extragem metadatele din răspunsul TMDb
        rating = tmdb_data.get('vote_average', 0)
        votes = tmdb_data.get('vote_count', 0)
        
        if media_type == 'movie':
            premiered = tmdb_data.get('release_date', '')
            dur_mins = tmdb_data.get('runtime', 0)
            if dur_mins: duration = int(dur_mins) * 60
            if tmdb_data.get('production_companies'):
                studio = tmdb_data['production_companies'][0].get('name', '')
        else:
            premiered = tmdb_data.get('first_air_date', '')
            runtimes = tmdb_data.get('episode_run_time', [])
            if runtimes: duration = int(runtimes[0]) * 60
            if tmdb_data.get('networks'):
                studio = tmdb_data['networks'][0].get('name', '')

        # --- SELF HEALING: SALVĂM IMAGINILE ÎN SQL PENTRU DATA VIITOARE ---
        if poster or backdrop:
            trakt_sync.update_item_images(tmdb_id, media_type, tmdb_data.get('poster_path', ''), tmdb_data.get('backdrop_path', ''))

    # Watched status
    if media_type == 'movie':
        is_watched = get_watched_counts(tmdb_id, 'movie') > 0
        watched_info = is_watched
    else:
        watched_count = get_watched_counts(tmdb_id, 'tv')
        total_eps = trakt_sync.get_tv_meta_from_db(str(tmdb_id))
        
        if not total_eps and tmdb_data:
            total_eps = tmdb_data.get('number_of_episodes', 0)
            if total_eps:
                trakt_sync.set_tv_meta_to_db(tmdb_id, total_eps)
        
        watched_info = {'watched': watched_count, 'total': total_eps}

    info = {
        'mediatype': 'movie' if media_type == 'movie' else 'tvshow',
        'title': title,
        'year': year,
        'plot': plot,
        'rating': rating,
        'votes': votes,
        'premiered': premiered,
        'studio': studio,
        'duration': duration
    }

    # Context menu
    cm = [
        ('[B][COLOR FFFDBD01]TMDB Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_info&tmdb_id={tmdb_id}&type={tmdb_endpoint})"),
        ('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=trakt_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})"),
        ('[B][COLOR FF00CED1]My TMDB[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=tmdb_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})")
    ]
    
    fav_params = urlencode({'mode': 'add_favorite', 'type': 'movie' if media_type == 'movie' else 'tv', 'tmdb_id': tmdb_id, 'title': title})
    cm.append(('[B][COLOR yellow]Add to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

    if media_type == 'movie':
        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
        is_folder = False
    else:
        url_params = {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': title}
        is_folder = True

    add_directory(
        f"{title} ({year})" if year else title, 
        url_params, 
        icon=poster, 
        thumb=poster, 
        fanart=backdrop, 
        info=info, 
        folder=is_folder, 
        cm=cm,
        watched_info=watched_info
    )

# ===================== TRAKT SCROBBLE (NOU) =====================
def send_trakt_scrobble(action, tmdb_id, content_type, season, episode, progress):
    """
    Trimite statusul redării către Trakt (start, pause, stop).
    action: 'start', 'pause', 'stop'
    """
    if not get_trakt_token():
        return

    # Endpoint-urile sunt /scrobble/start, /scrobble/pause, /scrobble/stop
    # Dacă action e 'scrobble', folosim 'start' pentru a menține activitatea (watching now)
    endpoint = 'start' if action == 'scrobble' else action
    
    url = f"/scrobble/{endpoint}"
    
    payload = {
        "progress": float(progress),
        "app_version": "1.0",
        "date": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    }

    # Identificare Video
    ids = {'tmdb': int(tmdb_id)}
    
    if content_type == 'movie':
        payload['movie'] = {'ids': ids}
    else:
        # Pentru episoade
        payload['episode'] = {'season': int(season), 'number': int(episode)}
        payload['show'] = {'ids': ids}

    try:
        # Folosim funcția existentă trakt_api_request
        trakt_api_request(url, method='POST', data=payload)
    except Exception as e:
        xbmc.log(f"[TRAKT] Scrobble error: {e}", xbmc.LOGERROR)
