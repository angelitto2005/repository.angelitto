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
from resources.lib.tmdb_api import prefetch_metadata_parallel, _process_movie_item, _process_tv_item, add_directory

try:
    from resources.lib.config import TRAKT_CLIENT_SECRET
except ImportError:
    TRAKT_CLIENT_SECRET = ''

LANG = get_language()
ADDON_PATH = ADDON.getAddonInfo('path')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
NEXT_PAGE_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'item_next.png')

_token_lock = threading.Lock()
_last_notify_time = 0

# --- ÎNCEPUT MODIFICARE: SESIUNE GLOBALĂ TRAKT (Ca în SALTS) ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Creăm o sesiune persistentă pentru Trakt, care refolosește conexiunile (mai rapid)
# și reîncearcă automat la anumite erori (ex: 502, 503, 504).
# NU punem retry automat pe 429 aici, pentru că vrem să-l controlăm manual 
# în `trakt_api_request` citind header-ul `Retry-After`.
TRAKT_SESSION = requests.Session()
_retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
TRAKT_SESSION.mount('https://api.trakt.tv', HTTPAdapter(pool_maxsize=50, max_retries=_retries))
# --- SFÂRȘIT MODIFICARE ---

def get_trakt_headers(token=None):
    h = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID
    }
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h

def _notify_reauth_needed():
    global _last_notify_time
    now = time.time()
    if now - _last_notify_time > 60:
        _last_notify_time = now
        try:
            xbmcgui.Dialog().notification(
                "[B][COLOR pink]Trakt[/COLOR][/B]",
                "Session expired! Re-authenticate in Settings.",
                TRAKT_ICON, 5000, False
            )
        except:
            pass


# ══════════════════════════════════════════════════════════
# ADĂUGAT: Funcție nouă — refresh automat al tokenului
# ══════════════════════════════════════════════════════════

def refresh_trakt_token():
    """
    Reînnoiește access_token folosind refresh_token.
    
    IMPORTANT:
      - refresh_token e SINGLE-USE (Trakt dă unul nou la fiecare refresh)
      - client_secret e OBLIGATORIU pentru /oauth/token
      - Thread-safe cu lock (previne refresh dublu simultan)
    """
    with _token_lock:
        # Re-citim fișierul DUPĂ lock — alt thread ar fi putut face refresh
        token_data = read_json(TRAKT_TOKEN_FILE)
        if not token_data:
            log("[TRAKT] refresh: No token file.", xbmc.LOGWARNING)
            return None

        # Verificăm dacă alt thread l-a reînnoit deja
        created_at = token_data.get('created_at', 0)
        expires_in = token_data.get('expires_in', 86400)
        time_left = (created_at + expires_in) - time.time()
        if time_left > 3600:
            log("[TRAKT] Token already renewed by another thread.")
            return token_data.get('access_token')

        refresh_token = token_data.get('refresh_token')
        if not refresh_token:
            log("[TRAKT] No refresh_token! Re-authentication required.",
                xbmc.LOGERROR)
            return None

        if not TRAKT_CLIENT_SECRET:
            log("[TRAKT] TRAKT_CLIENT_SECRET missing from config.py! "
                "Refresh will fail!", xbmc.LOGERROR)

        try:
            log("[TRAKT] Sending refresh token request...")
            r = requests.post(
                f"{TRAKT_API_URL}/oauth/token",
                json={
                    'refresh_token': refresh_token,
                    'client_id': TRAKT_CLIENT_ID,
                    'client_secret': TRAKT_CLIENT_SECRET,
                    'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
                    'grant_type': 'refresh_token'
                },
                headers={'Content-Type': 'application/json'},
                timeout=15
            )

            if r.status_code == 200:
                new_data = r.json()
                write_json(TRAKT_TOKEN_FILE, new_data)
                exp = new_data.get('expires_in', 0)
                log(f"[TRAKT] ✓ Token renewed! Expires in ~{exp // 3600}h")
                return new_data.get('access_token')
            else:
                log(f"[TRAKT] Refresh FAILED: HTTP {r.status_code}",
                    xbmc.LOGERROR)
                try:
                    log(f"[TRAKT] Response: {r.text[:300]}", xbmc.LOGWARNING)
                except:
                    pass
                return None

        except requests.exceptions.Timeout:
            log("[TRAKT] Refresh timeout.", xbmc.LOGWARNING)
            return None
        except Exception as e:
            log(f"[TRAKT] Error refresh: {e}", xbmc.LOGERROR)
            return None


# ══════════════════════════════════════════════════════════
# MODIFICAT: get_trakt_token — verifică expirarea + refresh
# ══════════════════════════════════════════════════════════

def get_trakt_token():
    """Returnează un token valid, cu refresh automat dacă expiră în < 1h."""
    token_data = read_json(TRAKT_TOKEN_FILE)
    if not token_data:
        return None

    access_token = token_data.get('access_token')
    if not access_token:
        return None

    # Calculăm timpul rămas
    created_at = token_data.get('created_at', 0)
    expires_in = token_data.get('expires_in', 86400)
    time_left = (created_at + expires_in) - time.time()

    # Token valid, nu expiră curând
    if time_left >= 3600:
        return access_token

    # Expiră în < 1 oră sau e deja expirat → refresh
    if time_left > 0:
        log(f"[TRAKT] Token expires in {int(time_left // 60)} min. Preventive refresh...")
    else:
        log(f"[TRAKT] Token EXPIRED {int(-time_left)}s ago!")

    refreshed = refresh_trakt_token()
    if refreshed:
        return refreshed

    # Refresh eșuat dar tokenul mai e valid tehnic
    if time_left > 0:
        log("[TRAKT] Refresh failed, but token is still temporarily valid.",
            xbmc.LOGWARNING)
        return access_token

    # Complet expirat + refresh eșuat
    log("[TRAKT] Token EXPIRED + refresh FAILED!", xbmc.LOGERROR)
    _notify_reauth_needed()
    return None
    

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

# ══════════════════════════════════════════════════════════
# MODIFICAT: trakt_auth — adăugat client_secret la device/token
# ══════════════════════════════════════════════════════════

def trakt_auth():
    try:
        r = requests.post(
            f"{TRAKT_API_URL}/oauth/device/code",
            json={'client_id': TRAKT_CLIENT_ID},
            headers=get_trakt_headers(),
            timeout=10
        )
        data = r.json()
        user_code = data['user_code']
        device_code = data['device_code']
        verification_url = data['verification_url']
        interval = data['interval']
        expires_in = data['expires_in']
    except:
        xbmcgui.Dialog().notification(
            "[B][COLOR pink]Trakt[/COLOR][/B]",
            "Connection error",
            xbmcgui.NOTIFICATION_ERROR
        )
        return

    pdialog = xbmcgui.DialogProgress()
    msg = (f"Mergi la: [B]{verification_url}[/B]\n\n"
           f"Introdu codul: [B][COLOR yellow]{user_code}[/COLOR][/B]")
    pdialog.create('Trakt Authentication', msg)

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
            poll = requests.post(
                f"{TRAKT_API_URL}/oauth/device/token",
                json={
                    'code': device_code,
                    'client_id': TRAKT_CLIENT_ID,
                    'client_secret': TRAKT_CLIENT_SECRET  # ← ADĂUGAT
                },
                headers=get_trakt_headers(),
                timeout=10
            )
            if poll.status_code == 200:
                token_data = poll.json()
                write_json(TRAKT_TOKEN_FILE, token_data)
                user = get_trakt_username(token_data.get('access_token'))
                ADDON.setSetting('trakt_status', f"Connected: {user}")
                pdialog.close()
                exp = token_data.get('expires_in', 0)
                log(f"[TRAKT] Authenticated! Token expires in ~{exp // 3600}h. "
                    f"Auto-refresh active.")
                xbmcgui.Dialog().notification(
                    "[B][COLOR pink]Trakt[/COLOR][/B]",
                    "Connected successfully!",
                    TRAKT_ICON, 3000, False
                )
                
                # ══════════════════════════════════════════════════════════
                # ADĂUGAT: Pornire automată sincronizare totală în background
                # ══════════════════════════════════════════════════════════
                import threading
                from resources.lib import trakt_sync
                # Rulăm cu silent=False pentru ca utilizatorul să vadă progresul primei importări
                t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': False, 'force': True})
                t.daemon = True
                t.start()
                # ══════════════════════════════════════════════════════════
                
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
    # --- START PROTECTIE DECONECTARE ACCIDENTALA ---
    if not xbmcgui.Dialog().yesno("[B][COLOR pink]Disconnect Trakt[/COLOR][/B]", "Are you sure you want to disconnect from Trakt?\n[COLOR gray]Synced data will be deleted for security.[/COLOR]"):
        return
    # --- END PROTECTIE ---

    if xbmcvfs.exists(TRAKT_TOKEN_FILE):
        xbmcvfs.delete(TRAKT_TOKEN_FILE)

    if xbmcvfs.exists(TRAKT_CACHE_FILE):
        xbmcvfs.delete(TRAKT_CACHE_FILE)
        
    # --- ÎNCEPUT MODIFICARE: Ștergem complet datele locale ale contului vechi ---
    from resources.lib.config import ADDON_DATA_DIR
    for db_ext in ['trakt_sync.db', 'trakt_sync.db-shm', 'trakt_sync.db-wal', 'last_sync.json']:
        db_path = os.path.join(ADDON_DATA_DIR, db_ext)
        if xbmcvfs.exists(db_path):
            try:
                xbmcvfs.delete(db_path)
            except:
                try: os.remove(db_path)
                except: pass
    # --- SFÂRȘIT MODIFICARE ---

    ADDON.setSetting('trakt_status', "Disconnected")
    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Disconnected.", TRAKT_ICON, 3000, False)
    
    # Curățăm și memoria RAM ca să dispară imediat din meniuri
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    xbmc.executebuiltin("Container.Refresh")


# ===================== TRAKT API REQUEST =====================
# ══════════════════════════════════════════════════════════
# MODIFICAT: trakt_api_request — retry pe 401
# ══════════════════════════════════════════════════════════
def _do_request(method, url, headers, data=None, params=None):
    """Execută cererea folosind sesiunea globală Trakt."""
    # --- ÎNCEPUT MODIFICARE: Folosim TRAKT_SESSION în loc de requests ---
    if method == 'GET':
        return TRAKT_SESSION.get(url, headers=headers, params=params, timeout=15)
    elif method == 'POST':
        return TRAKT_SESSION.post(url, headers=headers, json=data, timeout=15)
    elif method == 'DELETE':
        return TRAKT_SESSION.delete(url, headers=headers, json=data, timeout=15)
    return None
    # --- SFÂRȘIT MODIFICARE ---


def trakt_api_request(endpoint, method='GET', data=None, params=None):
    token = get_trakt_token()
    
    # Identificăm dacă endpoint-ul solicitat necesită autentificare obligatorie
    endpoint_lower = endpoint.lower()
    is_private = False
    
    if (endpoint_lower.startswith("/sync") or 
        endpoint_lower.startswith("/users/me") or 
        endpoint_lower.startswith("/users/hidden") or
        endpoint_lower.startswith("/scrobble") or 
        endpoint_lower.startswith("/calendars/my") or 
        endpoint_lower.startswith("/recommendations")):
        is_private = True

    # Dacă endpoint-ul este privat și nu avem un token valid, oprim cererea discret
    if is_private and not token:
        log(f"[TRAKT] Private endpoint {endpoint} skipped because user is not connected.", xbmc.LOGDEBUG)
        return None

    headers = get_trakt_headers(token)
    url = f"{TRAKT_API_URL}{endpoint}"

    max_retries = 3

    for attempt in range(max_retries + 1):
        try:
            r = _do_request(method, url, headers, data, params)
            if r is None:
                return None

            # ── 429 Rate Limit ──
            if r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 5))
                retry_after = min(retry_after, 30)
                if attempt < max_retries:
                    log(f"[TRAKT] 429 Rate Limit on {endpoint}. "
                        f"Waiting {retry_after}s... (attempt {attempt + 1}/{max_retries})",
                        xbmc.LOGWARNING)
                    time.sleep(retry_after)
                    continue
                else:
                    log(f"[TRAKT] 429 Rate Limit PERSISTENT on {endpoint}. "
                        f"Giving up after {max_retries} attempts.", xbmc.LOGWARNING)
                    return None

            # ── 401 Unauthorized ── (Se execută doar dacă am trimis un token expirat)
            if r.status_code == 401 and token:
                log(f"[TRAKT] 401 on {endpoint}. Refresh + retry...",
                    xbmc.LOGWARNING)
                new_token = refresh_trakt_token()
                if new_token:
                    headers = get_trakt_headers(new_token)
                    r = _do_request(method, url, headers, data, params)
                    if r is None:
                        return None
                else:
                    _notify_reauth_needed()
                    return None

            # ── Success ──
            if r.status_code in (200, 201, 204):
                if r.content:
                    return r.json()
                return True

            log(f"[TRAKT] {method} {endpoint} → HTTP {r.status_code}",
                xbmc.LOGWARNING)
            return None

        except requests.exceptions.Timeout:
            log(f"[TRAKT] Timeout pe {endpoint}", xbmc.LOGWARNING)
            return None
        except Exception as e:
            log(f"[TRAKT] API Error: {e}", xbmc.LOGERROR)
            return None

    return None


# ===================== TRAKT DATA HELPERS =====================
# ══════════════════════════════════════════════════════════
# MODIFICAT: get_trakt_request_worker — retry pe 401
# ══════════════════════════════════════════════════════════
def get_trakt_request_worker(endpoint, params=None):
    token = get_trakt_token()
    headers = get_trakt_headers(token)
    url = f"{TRAKT_API_URL}{endpoint}"

    max_retries = 3
    for attempt in range(max_retries + 1):
        r = requests.get(url, headers=headers, params=params, timeout=15)

        # ── 429 Rate Limit → așteptăm și reîncercăm ──
        if r.status_code == 429:
            retry_after = min(int(r.headers.get('Retry-After', 5)), 30)
            if attempt < max_retries:
                log(f"[TRAKT] 429 in worker on {endpoint}. "
                    f"Waiting {retry_after}s...", xbmc.LOGWARNING)
                time.sleep(retry_after)
                continue
            else:
                log(f"[TRAKT] 429 PERSISTENT in worker on {endpoint}.",
                    xbmc.LOGWARNING)
                return r

        # ── 401 → refresh + retry ──
        if r.status_code == 401:
            log(f"[TRAKT] 401 in worker on {endpoint}. Refresh + retry...",
                xbmc.LOGWARNING)
            new_token = refresh_trakt_token()
            if new_token:
                headers = get_trakt_headers(new_token)
                r = requests.get(url, headers=headers, params=params, timeout=15)
            return r

        # ── Orice alt cod → returnăm direct ──
        return r

    return r

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
    from resources.lib import trakt_sync
    import datetime
    
    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'movie'
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'show'

    result = trakt_api_request("/sync/watchlist", method='POST', data=data)
    if result:
        # --- UPDATE SQL INSTANT ---
        try:
            details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'movie' if media_type == 'movie' else 'tv') or {}
            title = details.get('title') or details.get('name', 'Unknown')
            year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            poster = details.get('poster_path', '')
            overview = details.get('overview', '')
            
            # Data format Trakt (ISO) pentru sortare corectă
            added_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            conn = trakt_sync.get_connection()
            # Inserăm fix 9 valori, matching exact structura tabelului
            # (list_type, media_type, tmdb_id, title, year, added_at, poster, backdrop, overview)
            conn.execute("INSERT OR REPLACE INTO trakt_lists VALUES (?,?,?,?,?,?,?,?,?)",
                      ('watchlist', db_type, str(tmdb_id), title, year, added_at, poster, '', overview))
            conn.commit()
            conn.close()
        except: pass
        # --------------------------

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Added to [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def remove_from_trakt_watchlist(tmdb_id, media_type):
    from resources.lib import trakt_sync
    
    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'movie'
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'show'

    result = trakt_api_request("/sync/watchlist/remove", method='POST', data=data)
    
    if result:
        # --- UPDATE SQL INSTANT (ȘTERGERE LOCALĂ) ---
        try:
            conn = trakt_sync.get_connection()
            # Ștergem din tabelul trakt_lists unde ținem watchlist-ul local
            conn.execute("DELETE FROM trakt_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                         ('watchlist', db_type, str(tmdb_id)))
            conn.commit()
            conn.close()
        except: pass
        # -------------------------------------------

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Removed from [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def is_in_trakt_watchlist(tmdb_id, media_type):
    """Verifică instant în SQL dacă e în Watchlist."""
    from resources.lib import trakt_sync
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        db_type = 'movie' if media_type == 'movie' else 'show'
        # Căutăm doar dacă există rândul
        c.execute("SELECT 1 FROM trakt_lists WHERE list_type='watchlist' AND media_type=? AND tmdb_id=?", (db_type, str(tmdb_id)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False

# ===================== TRAKT FAVORITES (New) =====================

def add_to_trakt_favorites(tmdb_id, media_type):
    from resources.lib import trakt_sync, tmdb_api # Import corect
    type_key = 'movies' if media_type == 'movie' else 'shows'
    data = {type_key: [{'ids': {'tmdb': int(tmdb_id)}}]}
    result = trakt_api_request("/sync/favorites", method='POST', data=data)
    if result:
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        try:
            # FIX: Folosim get_tmdb_item_details care face API call dacă SQL e gol
            details = tmdb_api.get_tmdb_item_details(str(tmdb_id), 'movie' if media_type == 'movie' else 'tv') or {}
            title = details.get('title') or details.get('name') or 'Unknown'
            year = str(details.get('release_date') or details.get('first_air_date') or '')[:4]
            poster = details.get('poster_path', '')
            overview = details.get('overview', '')
            
            conn = trakt_sync.get_connection()
            m_type_db = 'movie' if media_type in ['movie', 'movies'] else 'show'
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO trakt_favorites (media_type, tmdb_id, title, year, poster, overview, rank) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                      (m_type_db, str(tmdb_id), title, year, poster, overview, int(time.time())))
            conn.commit()
            conn.close()
        except: pass
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Added to [B][COLOR pink]Favorites[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False


def remove_from_trakt_favorites(tmdb_id, media_type):
    """Șterge de la favorite Trakt și face update instant în SQL."""
    type_key = 'movies' if media_type == 'movie' else 'shows'
    data = {type_key: [{'ids': {'tmdb': int(tmdb_id)}}]}
    result = trakt_api_request("/sync/favorites/remove", method='POST', data=data)
    if result:
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        # STERGERE INSTANTĂ DIN SQL PENTRU MENIU DINAMIC
        try:
            from resources.lib import trakt_sync
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            m_type_db = 'movie' if media_type in ['movie', 'movies'] else 'show'
            c.execute("DELETE FROM trakt_favorites WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), m_type_db))
            conn.commit()
            conn.close()
        except: pass
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Removed from [B][COLOR pink]Favorites[/COLOR][/B]", TRAKT_ICON, 3000, False)
        return True
    return False

def is_in_trakt_favorites(tmdb_id, media_type):
    """Verifică instant în SQL dacă e la Favorite."""
    from resources.lib import trakt_sync
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        # Mapare: movies->movie, shows->show pentru tabelul trakt_favorites
        m_type_db = 'movie' if media_type in ['movie', 'movies'] else 'show'
        c.execute("SELECT 1 FROM trakt_favorites WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), m_type_db))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
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
    if not username: return False

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request(f"/users/{username}/lists/{list_slug}/items", method='POST', data=data)
    
    if result:
        # --- UPDATE SQL LOCAL PENTRU LISTĂ (VITEZĂ) ---
        try:
            from resources.lib import trakt_sync
            # Luăm metadatele din cache-ul local (este instantaneu)
            details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'movie' if media_type == 'movie' else 'tv') or {}
            title = details.get('title') or details.get('name', 'Unknown')
            year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            poster = details.get('poster_path', '')
            overview = details.get('overview', '')
            
            from datetime import datetime
            added_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
            conn = trakt_sync.get_connection()
            # 1. Inserăm filmul în listă (cu timestamp curent pentru Newest First)
            conn.execute("INSERT OR REPLACE INTO user_list_items (list_slug, media_type, tmdb_id, title, year, added_at, poster, overview) VALUES (?,?,?,?,?,?,?,?)",
                         (list_slug, 'movie' if media_type == 'movie' else 'show', str(tmdb_id), title, year, added_iso, poster, overview))
            # 2. Incrementăm contorul listei (+1)
            conn.execute("UPDATE user_lists SET item_count = item_count + 1 WHERE slug=?", (list_slug,))
            # 3. Actualizăm posterul listei (noul prim element)
            if poster:
                conn.execute("UPDATE user_lists SET poster=?, poster_tmdb_id=? WHERE slug=?", (poster, str(tmdb_id), list_slug))
            conn.commit()
            conn.close()
        except: pass

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmc.executebuiltin("Container.Refresh")
        return True
        
    return False

# --- COD CORECTAT (Linia 374) ---
def remove_from_trakt_list(list_slug, tmdb_id, media_type):
    username = get_trakt_username()
    if not username: return False

    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}

    result = trakt_api_request(f"/users/{username}/lists/{list_slug}/items/remove", method='POST', data=data)
    if result:
        # --- UPDATE SQL INSTANT (CONTENT + COUNTER) ---
        try:
            from resources.lib import trakt_sync
            conn = trakt_sync.get_connection()
            # 1. Ștergem item-ul din baza de date locală imediat
            conn.execute("DELETE FROM user_list_items WHERE list_slug=? AND tmdb_id=?", (list_slug, str(tmdb_id)))
            # 2. Scădem 1 din numărul de iteme afișat în meniu
            conn.execute("UPDATE user_lists SET item_count = item_count - 1 WHERE slug=? AND item_count > 0", (list_slug,))
            # 3. Dacă itemul șters era primul (poster_tmdb_id), actualizăm posterul
            cur = conn.execute("SELECT poster_tmdb_id FROM user_lists WHERE slug=?", (list_slug,))
            row = cur.fetchone()
            if row and row[0] == str(tmdb_id):
                cur2 = conn.execute("SELECT tmdb_id, media_type, poster FROM user_list_items WHERE list_slug=? ORDER BY added_at DESC LIMIT 1", (list_slug,))
                new_first = cur2.fetchone()
                if new_first:
                    new_first_id = new_first[0]
                    new_first_type = 'movie' if new_first[1] == 'movie' else 'tv'
                    new_poster = new_first[2]
                    if new_poster:
                        conn.execute("UPDATE user_lists SET poster=?, poster_tmdb_id=? WHERE slug=?", (new_poster, new_first_id, list_slug))
                    else:
                        meta = trakt_sync.get_tmdb_item_details_from_db(new_first_id, new_first_type) or {}
                        if meta.get('poster_path'):
                            conn.execute("UPDATE user_lists SET poster=?, poster_tmdb_id=? WHERE slug=?", (meta['poster_path'], new_first_id, list_slug))
                else:
                    conn.execute("UPDATE user_lists SET poster=?, poster_tmdb_id=? WHERE slug=?", ('', '', list_slug))
            conn.commit()
            conn.close()
        except: pass
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def is_in_trakt_list(list_slug, tmdb_id, media_type):
    """Verifică instant în SQL dacă un film este în listă (pentru Context Menu)."""
    from resources.lib import trakt_sync
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        # Căutăm direct în tabelul de iteme al listelor
        c.execute("SELECT 1 FROM user_list_items WHERE list_slug=? AND tmdb_id=?", (list_slug, str(tmdb_id)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False


# ===================== TRAKT HISTORY =====================

def get_trakt_history(media_type='movies', limit=50, page=1):

    return trakt_api_request(f"/sync/history/{media_type}", params={'limit': limit, 'page': page, 'extended': 'full'})

def get_trakt_watched(media_type='movies'):

    return trakt_api_request(f"/sync/watched/{media_type}", params={'extended': 'full'})

def get_trakt_playback_progress():

    return trakt_api_request("/sync/playback", params={'extended': 'full'})


# ===================== TRAKT DISCOVER =====================

def get_trakt_trending(media_type='movies', limit=40, page=1):

    return trakt_api_request(f"/{media_type}/trending", params={'limit': limit, 'page': page, 'extended': 'full'})

def get_trakt_popular(media_type='movies', limit=40, page=1):

    return trakt_api_request(f"/{media_type}/popular", params={'limit': limit, 'page': page, 'extended': 'full'})

def _fetch_trakt_paginated(api_func, media_type, max_items=500, page_limit=100):
    """Fetches multiple pages from a Trakt endpoint and combines results."""
    all_results = []
    page = 1
    while len(all_results) < max_items:
        results = api_func(media_type, page_limit, page)
        if not results or not isinstance(results, list) or len(results) == 0:
            break
        all_results.extend(results)
        if len(results) < page_limit:
            break
        page += 1
        if page > 10:
            break
    return all_results[:max_items]

def get_trakt_most_watched(media_type='movies', period='weekly', limit=40):

    return trakt_api_request(f"/{media_type}/watched/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_most_favorited(media_type='movies', period='weekly', limit=40):

    return trakt_api_request(f"/{media_type}/favorited/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_anticipated(media_type='movies', limit=40, page=1):

    return trakt_api_request(f"/{media_type}/anticipated", params={'limit': limit, 'page': page, 'extended': 'full'})

def get_trakt_box_office():

    return trakt_api_request("/movies/boxoffice", params={'extended': 'full'})

def get_trakt_recommendations(media_type='movies', limit=40):

    return trakt_api_request(f"/recommendations/{media_type}", params={'limit': limit, 'extended': 'full'})

# ===================== TRAKT CALENDAR =====================

# ══════════════════════════════════════════════════════════
# ADĂUGAT: Preluare seriale ascunse din calendar
# ══════════════════════════════════════════════════════════

# ===================== TRAKT CALENDAR =====================

def get_trakt_hidden_calendar_shows():
    """
    Preia serialele hidden din calendar.
    Returnează dict cu seturi SEPARATE per tip de ID.
    """
    hidden = {
        'trakt': set(),
        'imdb': set(),
        'tmdb': set(),
        'tvdb': set(),
        'slug': set()
    }
    try:
        result = trakt_api_request(
            '/users/hidden/calendar',
            params={'type': 'show', 'limit': 500}
        )
        if result and isinstance(result, list):
            for item in result:
                ids = item.get('show', {}).get('ids', {})
                for key in hidden:
                    val = ids.get(key)
                    if val:
                        hidden[key].add(str(val))
            log(f"[TRAKT] Calendar hidden: {len(result)} shows "
                f"(trakt={len(hidden['trakt'])}, tmdb={len(hidden['tmdb'])}, "
                f"tvdb={len(hidden['tvdb'])}, imdb={len(hidden['imdb'])})")
    except Exception as e:
        log(f"[TRAKT] Error hidden calendar: {e}", xbmc.LOGWARNING)
    return hidden


def _filter_hidden_from_calendar(calendar_data):
    """
    Filtrează episoadele din calendar care aparțin serialelor hidden.
    Compară FIECARE tip de ID separat (tmdb cu tmdb, tvdb cu tvdb, etc.)
    """
    if not calendar_data or not isinstance(calendar_data, list):
        return calendar_data

    hidden = get_trakt_hidden_calendar_shows()
    # Verificăm dacă există cel puțin un ID hidden
    if not any(s for s in hidden.values()):
        return calendar_data

    filtered = []
    for item in calendar_data:
        show_ids = item.get('show', {}).get('ids', {})
        is_hidden = False
        # Comparăm STRICT: tmdb cu tmdb, tvdb cu tvdb, etc.
        for key in ('trakt', 'imdb', 'tmdb', 'tvdb', 'slug'):
            val = show_ids.get(key)
            if val and str(val) in hidden.get(key, set()):
                is_hidden = True
                break
        if not is_hidden:
            filtered.append(item)

    removed = len(calendar_data) - len(filtered)
    if removed > 0:
        log(f"[TRAKT] Calendar: {removed} episodes removed (hidden shows).")
    return filtered


def get_trakt_calendar_shows(start_date=None, days=14):
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    result = trakt_api_request(
        f"/calendars/my/shows/{start_date}/{days}",
        params={'extended': 'full'}
    )
    return _filter_hidden_from_calendar(result)


def get_trakt_calendar_movies(start_date=None, days=30):
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    return trakt_api_request(
        f"/calendars/my/movies/{start_date}/{days}",
        params={'extended': 'full'}
    )


def get_trakt_calendar_premieres(start_date=None, days=30):
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    result = trakt_api_request(
        f"/calendars/all/shows/premieres/{start_date}/{days}",
        params={'extended': 'full'}
    )
    return _filter_hidden_from_calendar(result)


def get_trakt_calendar_new_shows(start_date=None, days=30):
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    result = trakt_api_request(
        f"/calendars/all/shows/new/{start_date}/{days}",
        params={'extended': 'full'}
    )
    return _filter_hidden_from_calendar(result)


# ===================== TRAKT GENRES =====================

def get_trakt_genres(media_type='movies'):

    return trakt_api_request(f"/genres/{media_type}")

def get_trakt_by_genre(media_type, genre_slug, limit=40):

    return None


# ===================== TRAKT PUBLIC LISTS =====================

def get_trakt_trending_lists(limit=50):
    """Returnează liste trending cu detalii complete."""
    return trakt_api_request("/lists/trending", params={'limit': limit, 'extended': 'full'})

def get_trakt_popular_lists(limit=50):
    """Returnează liste populare cu detalii complete."""
    return trakt_api_request("/lists/popular", params={'limit': limit, 'extended': 'full'})

def get_liked_lists(limit=50):
    """Returnează listele liked de user cu detalii complete."""
    return trakt_api_request("/users/likes/lists", params={'limit': limit, 'extended': 'full'})


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
    from resources.lib import trakt_sync
    
    was_watched_before = False
    try:
        if content_type == 'movie':
            was_watched_before = trakt_sync.is_movie_watched(tmdb_id)
        elif season and episode:
            was_watched_before = trakt_sync.is_episode_watched(tmdb_id, season, episode)
    except: pass

    # --- PAS 1: Ștergere Locală SQL (Instant UI) ---
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

    # --- PAS 2: Execuție API Trakt (Metoda Corectă: DELETE /sync/playback/{id}) ---
    res_std = False
    try:
        log(f"[REMOVE] Looking for playback session on Trakt to delete...")
        playback_data = trakt_api_request("/sync/playback")
        playback_id = None
        
        if playback_data and isinstance(playback_data, list):
            for item in playback_data:
                item_type = item.get('type')
                if content_type == 'movie' and item_type == 'movie':
                    if str(item.get('movie', {}).get('ids', {}).get('tmdb')) == str(tmdb_id):
                        playback_id = item.get('id')
                        break
                elif content_type in ['tv', 'episode'] and item_type == 'episode':
                    show_tmdb = str(item.get('show', {}).get('ids', {}).get('tmdb'))
                    ep = item.get('episode', {})
                    if show_tmdb == str(tmdb_id) and str(ep.get('season')) == str(season) and str(ep.get('number')) == str(episode):
                        playback_id = item.get('id')
                        break
        
        if playback_id:
            log(f"[REMOVE] Session found (ID: {playback_id}). Executing DELETE...")
            # Trimitem metoda DELETE curata
            res_del = trakt_api_request(f"/sync/playback/{playback_id}", method='DELETE')
            if res_del or res_del is True:
                res_std = True
                log(f"[REMOVE] Session {playback_id} successfully deleted from Trakt.")
        else:
            log(f"[REMOVE] Item does not exist in Trakt playback list. Done.")
            res_std = True
    except Exception as e:
        log(f"[REMOVE] Error reading/deleting Trakt session: {e}", xbmc.LOGERROR)

    # --- PAS 3: Fallback (Doar dacă API-ul a dat crash, ex. Timeout) ---
    if not res_std:
        log("[REMOVE] Method A failed. Starting Fallback (Scrobble 100%)...", xbmc.LOGWARNING)
        ids = {'tmdb': int(tmdb_id)}
        payload_scrobble = {'progress': 100, 'app_version': '1.0'}
        
        if content_type == 'movie':
            payload_scrobble['movie'] = {'ids': ids}
        else:
            payload_scrobble['episode'] = {'season': int(season), 'number': int(episode), 'ids': ids}
            payload_scrobble['show'] = {'ids': ids}
            
        res_scrobble = trakt_api_request("/scrobble/stop", method='POST', data=payload_scrobble)
        if res_scrobble and not was_watched_before:
            time.sleep(1.0)
            payload_remove = {}
            if content_type == 'movie':
                payload_remove = {'movies': [{'ids': ids}]}
            else:
                payload_remove = {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}
            trakt_api_request("/sync/history/remove", method='POST', data=payload_remove)

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Removed from Progress", TRAKT_ICON, 2000, False)
    
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
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

    # --- MODIFICARE: Verificăm dacă episodul e vizionat ---
    is_ep_watched = False
    if season and episode:
        is_ep_watched = trakt_sync.is_episode_watched(tmdb_id, season, episode)

    if is_ep_watched:
        cm.append(('Mark as [B][COLOR FFE41B17]Unwatched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(unwatched_params)})"))
    else:
        cm.append(('Mark as [B][COLOR FFE41B17]Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(watched_params)})"))
    # ----------------------------------------------------

    return cm

def hide_show_from_progress(tmdb_id):
    from resources.lib.tmdb_api import get_trakt_id  
    
    trakt_id = get_trakt_id(None, tmdb_id, 'show')
    ids_dict = {}
    
    try:
        if tmdb_id and str(tmdb_id) != 'None':
            ids_dict['tmdb'] = int(tmdb_id)
    except: pass
    
    if trakt_id:
        ids_dict['trakt'] = int(trakt_id)
        
    if not ids_dict:
        return False
        
    data = {'shows':[{'ids': ids_dict}]}
    
    # --- MODIFICARE CHEIE: Trimitem către TOATE cele 3 secțiuni (inclusiv DROPPED) ---
    r1 = trakt_api_request("/users/hidden/progress_watched", method='POST', data=data)
    r2 = trakt_api_request("/users/hidden/calendar", method='POST', data=data)
    r3 = trakt_api_request("/users/hidden/dropped", method='POST', data=data)
    # --------------------------------------------------------------------------------
    
    if r1 or r2 or r3:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Marked as [B][COLOR FF33CCFF]Dropped (Hidden)[/COLOR][/B]", TRAKT_ICON, 3000, False)
        from resources.lib import trakt_sync
        try:
            conn = trakt_sync.get_connection()
            # Ștergem din Next Episodes (Up Next) local
            conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            # Adăugăm INSTANT în lista de ascunse (Dropped) locală, fără să mai așteptăm sync-ul
            conn.execute("INSERT OR REPLACE INTO trakt_hidden_shows VALUES (?)", (str(tmdb_id),))
            conn.commit()
            conn.close()
        except: pass
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def unhide_show_from_progress(tmdb_id):
    from resources.lib.tmdb_api import get_trakt_id  
    
    trakt_id = get_trakt_id(None, tmdb_id, 'show')
    ids_dict = {}
    
    try:
        if tmdb_id and str(tmdb_id) != 'None':
            ids_dict['tmdb'] = int(tmdb_id)
    except: pass
    
    if trakt_id:
        ids_dict['trakt'] = int(trakt_id)
        
    if not ids_dict:
        return False
        
    data = {'shows':[{'ids': ids_dict}]}
    
    # --- MODIFICARE CHEIE: Scoatem din TOATE cele 3 secțiuni (inclusiv DROPPED) ---
    r1 = trakt_api_request("/users/hidden/progress_watched/remove", method='POST', data=data)
    r2 = trakt_api_request("/users/hidden/calendar/remove", method='POST', data=data)
    r3 = trakt_api_request("/users/hidden/dropped/remove", method='POST', data=data)
    # ------------------------------------------------------------------------------
    
    if r1 or r2 or r3:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Restored to [B][COLOR FF33CCFF]Up Next[/COLOR][/B]", TRAKT_ICON, 3000, False)
        from resources.lib import trakt_sync
        try:
            conn = trakt_sync.get_connection()
            # Ștergem din lista locală de Dropped/Ascunse
            conn.execute("DELETE FROM trakt_hidden_shows WHERE tmdb_id=?", (str(tmdb_id),))
            conn.commit()
            conn.close()
        except: pass
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        # Declanșăm refresh la episod în background ca să apară la loc în Up Next instant
        import threading
        threading.Thread(target=trakt_sync.refresh_next_episode, args=(tmdb_id, True)).start()
        return True
    return False

def show_trakt_context_menu(tmdb_id, content_type, title='', season=None, episode=None):
    token = get_trakt_token()
    if not token:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
        return

    options =[]
    from resources.lib import trakt_sync
    
    # 1. Watchlist Toggle (Dinamic)
    if is_in_trakt_watchlist(tmdb_id, content_type):
        options.append(('Remove from [B][COLOR pink]Watchlist[/COLOR][/B]', 'remove_watchlist'))
    else:
        options.append(('Add to [B][COLOR pink]Watchlist[/COLOR][/B]', 'add_watchlist'))
        
    # 2. Favorite Toggle (Dinamic)
    if is_in_trakt_favorites(tmdb_id, content_type):
        options.append(('Remove from [B][COLOR pink]Favorites[/COLOR][/B]', 'remove_trakt_favorite'))
    else:
        options.append(('Add to [B][COLOR pink]Favorites[/COLOR][/B]', 'add_trakt_favorite'))

    options.append(('Add to [B][COLOR pink]My Lists[/COLOR][/B]', 'add_to_list'))
    options.append(('Remove from [B][COLOR pink] My Lists[/COLOR][/B]', 'remove_from_list'))
    
    # 3. Watched State
    is_watched_state = False
    if content_type == 'movie':
        is_watched_state = trakt_sync.is_movie_watched(tmdb_id)
    elif content_type == 'episode' or (season is not None and episode is not None):
        is_watched_state = trakt_sync.is_episode_watched(tmdb_id, season, episode)
    elif content_type == 'season' or (season is not None and episode is None):
        is_watched_state = (get_watched_counts(tmdb_id, 'season', season) > 0)
    elif content_type in['tv', 'show']:
        is_watched_state = (get_watched_counts(tmdb_id, 'tv') > 0)

    if is_watched_state:
        options.append(('Mark as [B][COLOR FFE41B17]Unwatched[/COLOR][/B]', 'mark_unwatched'))
    else:
        options.append(('Mark as [B][COLOR FFE41B17]Watched[/COLOR][/B]', 'mark_watched'))
    
    # 4. Meniu Dinamic pentru Dropped Shows
    if content_type in ['tv', 'show', 'episode']:
        if trakt_sync.is_show_hidden(tmdb_id):
            options.append(('Restore to [B][COLOR FF33CCFF]Up Next[/COLOR][/B] (Unhide)', 'unhide_progress'))
        else:
            options.append(('Hide from [B][COLOR FF33CCFF]Up Next [COLOR FFCCCCFF](Drop Show)[/COLOR][/B]', 'hide_progress'))
        
    options.append(('Add [B][COLOR pink]Rating[/COLOR][/B]', 'add_rating'))

    dialog = xbmcgui.Dialog()
    ret = dialog.contextmenu([opt[0] for opt in options])
    if ret < 0: return

    action = options[ret][1]
    if action == 'add_watchlist': add_to_trakt_watchlist(tmdb_id, content_type)
    elif action == 'remove_watchlist': remove_from_trakt_watchlist(tmdb_id, content_type)
    elif action == 'add_trakt_favorite': add_to_trakt_favorites(tmdb_id, content_type)
    elif action == 'remove_trakt_favorite': remove_from_trakt_favorites(tmdb_id, content_type)
    elif action == 'add_to_list': show_trakt_add_to_list_dialog(tmdb_id, content_type, title)
    elif action == 'remove_from_list': show_trakt_remove_from_list_dialog(tmdb_id, content_type, title)
    elif action == 'mark_watched': trakt_sync.mark_as_watched_internal(tmdb_id, content_type, season, episode)
    elif action == 'mark_unwatched': trakt_sync.mark_as_unwatched_internal(tmdb_id, content_type, season, episode)
    elif action == 'hide_progress': hide_show_from_progress(tmdb_id)
    elif action == 'unhide_progress': unhide_show_from_progress(tmdb_id)
    elif action == 'add_rating': rate_trakt_item(tmdb_id, content_type, season, episode)
    
    xbmc.executebuiltin("Container.Refresh")


def show_trakt_add_to_list_dialog(tmdb_id, content_type, title=''):
    lists = get_trakt_user_lists()
    if not lists:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "You have no lists created", TRAKT_ICON, 3000, False)
        return

    poster_map = {}
    try:
        db_lists = trakt_sync.get_lists_from_db()
        for lst in db_lists:
            slug = lst.get('ids', {}).get('slug', '')
            icon = lst.get('icon', '')
            if slug and icon:
                poster_map[slug] = icon
    except:
        pass

    display_items = []
    for lst in lists:
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        slug = lst.get('ids', {}).get('slug', '')

        styled_name = f"[B][COLOR pink]{name}[/COLOR][/B]"
        li = xbmcgui.ListItem(styled_name)
        li.setLabel2(f"[B][COLOR yellow]{count}[/COLOR][/B] items")
        poster = poster_map.get(slug, TRAKT_ICON)
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        display_items.append(li)

    ret = xbmcgui.Dialog().select("[B][COLOR pink]Trakt[/COLOR][/B]: Add to List", display_items, useDetails=True)

    if ret >= 0:
        selected_list = lists[ret]
        list_slug = selected_list.get('ids', {}).get('slug', '')
        list_name = selected_list.get('name', '')
        
        if list_slug:
            if add_to_trakt_list(list_slug, tmdb_id, content_type):
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] added to [B][COLOR yellow]{list_name}[/COLOR][/B]", TRAKT_ICON, 3000, False)

def show_trakt_remove_from_list_dialog(tmdb_id, content_type, title=''):
    lists = get_trakt_user_lists()
    if not lists:
        return

    poster_map = {}
    try:
        db_lists = trakt_sync.get_lists_from_db()
        for lst in db_lists:
            slug = lst.get('ids', {}).get('slug', '')
            icon = lst.get('icon', '')
            if slug and icon:
                poster_map[slug] = icon
    except:
        pass

    lists_with_item = []
    for lst in lists:
        list_slug = lst.get('ids', {}).get('slug', '')
        if is_in_trakt_list(list_slug, tmdb_id, content_type):
            lists_with_item.append(lst)

    if not lists_with_item:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Not in any list", TRAKT_ICON, 3000, False)
        return

    display_items = []
    for lst in lists_with_item:
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        slug = lst.get('ids', {}).get('slug', '')

        styled_name = f"[B][COLOR pink]{name}[/COLOR][/B]"
        li = xbmcgui.ListItem(styled_name)
        li.setLabel2(f"[B][COLOR yellow]{count}[/COLOR][/B] items")
        poster = poster_map.get(slug, TRAKT_ICON)
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        display_items.append(li)

    ret = xbmcgui.Dialog().select("Remove from List", display_items, useDetails=True)

    if ret >= 0:
        selected_list = lists_with_item[ret]
        list_slug = selected_list.get('ids', {}).get('slug', '')
        list_name = selected_list.get('name', '')
        
        if list_slug:
            if remove_from_trakt_list(list_slug, tmdb_id, content_type):
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] removed from [B][COLOR yellow]{list_name}[/COLOR][/B]", TRAKT_ICON, 3000, False)


class TraktRatingWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.meta = kwargs.get('meta', {})
        self.rating_val = -1

    def onInit(self):
        self.setProperty('tmdbmovies.fanart', self.meta.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.meta.get('clearlogo', ''))
        self.setProperty('tmdbmovies.service_title', self.meta.get('service_title', 'RATE'))
        self.setProperty('tmdbmovies.service_icon', self.meta.get('service_icon', ''))
        
        content_type = self.meta.get('content_type', 'movie')
        if content_type == 'movie':
            self.setProperty('tmdbmovies.show_title', self.meta.get('title', 'Unknown'))
            self.setProperty('tmdbmovies.ep_label', '')
        else:
            self.setProperty('tmdbmovies.show_title', self.meta.get('tvshowtitle', 'Unknown'))
            s_val = int(self.meta.get('season') or 1)
            e_val = int(self.meta.get('episode') or 1)
            ep_title = self.meta.get('title', '')
            if ep_title:
                self.setProperty('tmdbmovies.ep_label', f"S{s_val:02d}E{e_val:02d} - {ep_title}")
            else:
                self.setProperty('tmdbmovies.ep_label', f"S{s_val:02d}E{e_val:02d}")
        
        try: self.setFocusId(11039)
        except: pass

    def onClick(self, controlId):
        if 11030 <= controlId <= 11039:
            self.rating_val = controlId - 11029 
            self.close()
        elif controlId == 1000:
            self.rating_val = -1
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110):
            self.rating_val = -1
            self.close()

def _prompt_trakt_rating(tmdb_id, content_type, season, episode, title, service='trakt'):
    if service == 'trakt':
        token = get_trakt_token()
        if not token: return
        service_label = "RATE ON TRAKT"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
    else:
        # TMDb
        service_label = "RATE ON TMDB"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
    
    meta_info = {
        'content_type': content_type, 'title': title, 'season': season, 'episode': episode, 
        'fanart': '', 'clearlogo': '', 'tvshowtitle': '',
        'service_title': service_label, 'service_icon': service_icon
    }
    
    from resources.lib.tmdb_api import get_tmdb_item_details
    try:
        details = get_tmdb_item_details(str(tmdb_id), 'movie' if content_type == 'movie' else 'tv')
        if details:
            if details.get('backdrop_path'): meta_info['fanart'] = f"{BACKDROP_BASE}{details.get('backdrop_path')}"
            if details.get('clearlogo'): meta_info['clearlogo'] = f"{IMG_BASE}{details.get('clearlogo')}"
            if content_type != 'movie':
                meta_info['tvshowtitle'] = details.get('name', 'Unknown')
                if not title or title.startswith('Episode '):
                    from resources.lib.tmdb_api import get_smart_season_details
                    season_data = get_smart_season_details(str(tmdb_id), season)
                    if season_data:
                        for ep in season_data.get('episodes',[]):
                            if str(ep.get('episode_number')) == str(episode):
                                if ep.get('name'): meta_info['title'] = ep.get('name')
                                break
    except: pass
    
    win = TraktRatingWindow('TraktRating.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', meta=meta_info)
    win.doModal()
    val_10 = win.rating_val
    del win
    
    if val_10 > 0:
        if service == 'trakt':
            # RESTAURARE SCALĂ 1-10: Trakt site maprează 1-10 la 0.5-5.0 stele.
            # Dacă userul alege butonul 3, trimitem 3, iar pe site apare 1.5 stele.
            val_final = val_10
            
            if content_type == 'movie':
                data = {'movies':[{'ids': {'tmdb': int(tmdb_id)}, 'rating': val_final}]}
            else:
                data = {'shows':[{'ids': {'tmdb': int(tmdb_id)}, 'seasons':[{'number': int(season), 'episodes':[{'number': int(episode), 'rating': val_final}]}]}]}
            
            res = trakt_api_request("/sync/ratings", method='POST', data=data)
            if res is not None:
                stars = val_final / 2.0
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"Rated [B][COLOR lime]{stars} Stars[/COLOR][/B]", service_icon, 3000, False)
        else:
            # TMDb - Rămâne 1-10
            from resources.lib.tmdb_api import rate_tmdb_item_silent
            if rate_tmdb_item_silent(tmdb_id, content_type, val_10, season, episode):
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb[/COLOR][/B]", f"Rated [B][COLOR lime]{val_10}/10[/COLOR][/B]", service_icon, 3000, False)

def rate_trakt_item(tmdb_id, content_type, season=None, episode=None):
    _prompt_trakt_rating(tmdb_id, content_type, season, episode, "")

# ===================== TRAKT MY LISTS - MODIFICAT COMPLET =====================

def get_next_episodes(params=None):
    """Aliat pentru service.py - Înlocuiește funcția care lipsea."""
    from resources.lib.tmdb_api import get_next_episodes as display_up_next
    return display_up_next(params)


def trakt_discovery_list(params):
    from resources.lib.tmdb_api import render_from_fast_cache, get_fast_cache # Importuri noi
    from resources.lib import trakt_sync
    from resources.lib.utils import paginate_list

    list_type = params.get('list_type')
    media_type = params.get('media_type', 'movies')
    page = int(params.get('page', '1'))
    
    # --- 1. FAST CACHE CHECK (RAM) ---
    cache_key = f"list_{media_type}_{list_type}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

    db_m_type = 'movie' if media_type == 'movies' else 'show'
    
    # 1. CITIRE DIN SQL
    data = trakt_sync.get_trakt_discovery_from_db(list_type, db_m_type)
    
    # 2. FALLBACK API (Dacă SQL e gol - ex: prima rulare)
    if not data:
        log(f"[TRAKT] Discovery SQL empty for {list_type}/{media_type}, using API...")
        api_data = None
        
        if list_type == 'trending': 
            api_data = _fetch_trakt_paginated(get_trakt_trending, media_type, 500, 100)
        elif list_type == 'popular': 
            api_data = _fetch_trakt_paginated(get_trakt_popular, media_type, 500, 100)
        elif list_type == 'anticipated': 
            api_data = _fetch_trakt_paginated(get_trakt_anticipated, media_type, 500, 100)
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
        add_directory("[COLOR gray]Updating list...[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)
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
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
            {'mode': 'trakt_discovery_list', 'list_type': list_type, 'media_type': media_type, 'page': str(page + 1)},
            icon=NEXT_PAGE_ICON,
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_public_lists(params):
    """Afișează liste publice Trakt (trending sau popular) cu descriere."""
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
        description = lst.get('description', '')  # ✅ ADĂUGAT
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        # ✅ ADĂUGAT: info cu description
        info = {
            'mediatype': 'video',
            'title': name,
            'plot': description if description else f"By: {user}\n{count} items • {likes} likes"
        }
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, info=info, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_liked_lists(params=None):
    """Afișează listele apreciate de utilizator cu descriere."""
    from resources.lib.tmdb_api import add_directory
    
    data = get_liked_lists()
    
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "You have no liked lists", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', {})
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        description = lst.get('description', '')  # ✅ ADĂUGAT
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        # ✅ ADĂUGAT: info cu description
        info = {
            'mediatype': 'video',
            'title': name,
            'plot': description if description else f"By: {user}\n{count} items • {likes} likes"
        }
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, info=info, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_search_list(params=None):
    """Caută liste pe Trakt cu descriere."""
    from resources.lib.tmdb_api import add_directory
    
    dialog = xbmcgui.Dialog()
    query = dialog.input("Search list...", type=xbmcgui.INPUT_ALPHANUM)
    
    if not query:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    
    data = trakt_api_request("/search/list", params={'query': query, 'limit': 50})
    
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "No list found", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', {})
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        description = lst.get('description', '')  # ✅ ADĂUGAT
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        if not slug or not user:
            continue
        
        # ✅ ADĂUGAT: info cu description
        info = {
            'mediatype': 'video',
            'title': name,
            'plot': description if description else f"By: {user}\n{count} items • {likes} likes"
        }
        
        add_directory(
            f"{name} [COLOR gray]by {user} ({count})[/COLOR]",
            {'mode': 'trakt_list_items', 'list_type': 'public_list', 'user': user, 'slug': slug},
            icon=TRAKT_ICON, thumb=TRAKT_ICON, info=info, folder=True
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
            data = _fetch_trakt_paginated(get_trakt_trending, media_type, 500, limit_request)
        elif list_type == 'trending_recent':
            data = _fetch_trakt_paginated(get_trakt_trending, media_type, 500, limit_request)
        elif list_type == 'popular':
            data = _fetch_trakt_paginated(get_trakt_popular, media_type, 500, limit_request)
        elif list_type == 'most_watched':
            data = get_trakt_most_watched(media_type, 'weekly', limit_request)
        elif list_type == 'most_favorited':
            data = get_trakt_most_favorited(media_type, 'weekly', limit_request)
        elif list_type == 'anticipated':
            data = _fetch_trakt_paginated(get_trakt_anticipated, media_type, 500, limit_request)
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
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
            {
                'mode': 'build_movie_list' if media_type == 'movies' else 'build_tvshow_list',
                'action': f'trakt_{media_type.rstrip("s")}_{list_type}',
                'new_page': str(page + 1)
            },
            icon=NEXT_PAGE_ICON,
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_list_items(params):
    """Afișează conținutul listelor Trakt - VITEZĂ POV (RAM Cache + Batch Rendering)."""
    from resources.lib.tmdb_api import (
        render_from_fast_cache, get_fast_cache, set_fast_cache, 
        prefetch_metadata_parallel, _process_movie_item, _process_tv_item, get_tmdb_item_details
    )
    from resources.lib.utils import paginate_list
    from resources.lib import trakt_sync
    import xbmcplugin

    list_type = params.get('list_type')
    user = params.get('user')
    slug = params.get('slug')
    media_filter = params.get('media_filter') or params.get('type')
    page = int(params.get('new_page', '1'))

    # 1. RAM Check
    cache_key = f"trakt_list_{list_type}_{slug}_{media_filter}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    data = None
    is_sql_data = False
    
    # Determinăm tipul real pentru SQL
    filter_type = 'movie' if (media_filter == 'movies' or media_filter == 'movie') else 'show'

    # 2. Citire SQL
    if list_type == 'favorites' or params.get('mode') == 'trakt_favorites_list':
        data = trakt_sync.get_trakt_favorites_from_db('movies' if filter_type == 'movie' else 'shows')
        if data: is_sql_data = True
    elif list_type == 'watchlist':
        data = trakt_sync.get_trakt_list_from_db('watchlist', filter_type)
        if data: is_sql_data = True
    elif list_type == 'history':
        data = trakt_sync.get_history_from_db(filter_type)
        if data: is_sql_data = True
    elif list_type == 'user_list' and slug:
        data = trakt_sync.get_trakt_user_list_items_from_db(slug)
        if data: is_sql_data = True

    # 3. Fallback API
    if not data:
        if list_type == 'watchlist':
            data = get_trakt_watchlist('movies' if filter_type == 'movie' else 'shows')
        elif list_type == 'history':
            if filter_type == 'movie': data = get_trakt_history('movies', 100)
            else: data = _extract_unique_shows_from_episodes(get_trakt_history('episodes', 200))
        elif (list_type == 'public_list' or list_type == 'user_list') and slug:
            data = get_trakt_list_items(slug, username=user)
            if data:
                data.sort(key=lambda x: x.get('listed_at', ''), reverse=True)

    if not data:
        xbmcplugin.endOfDirectory(HANDLE); return

    # 4. Procesare
    paginated_items, total_pages = paginate_list(data, page, limit=PAGE_LIMIT)
    
    # Prefetch-ul este critic aici pentru History TV (unde lipsesc date în SQL)
    prefetch_metadata_parallel(paginated_items, filter_type if filter_type else 'movie')

    items_to_add = []
    cache_list = []

    for item in paginated_items:
        current_media_type = 'movie'
        
        if is_sql_data:
            # Detectare tip
            row_type = item.get('media_type', '')
            # FIX HISTORY TV: Dacă e history și filtrul e shows, forțăm tipul TV
            if list_type == 'history' and filter_type == 'show':
                current_media_type = 'tv'
            elif row_type in ['show', 'tv', 'tvshow']:
                current_media_type = 'tv'
            
            tmdb_id = str(item.get('tmdb_id') or item.get('id', ''))
            
            # --- FIX HISTORY: Date lipsă în SQL ---
            # Dacă nu avem an sau poster (cazul history tv), le luăm din cache-ul proaspăt descărcat de prefetch
            year_val = str(item.get('year', ''))
            poster_path = item.get('poster_path') or item.get('poster', '')

            if (not year_val or not poster_path) and tmdb_id:
                # Citim rapid din cache-ul local (populat de prefetch_metadata_parallel mai sus)
                meta = get_tmdb_item_details(tmdb_id, current_media_type)
                if meta:
                    if not year_val: 
                        d = meta.get('release_date') or meta.get('first_air_date')
                        year_val = str(d)[:4] if d else ''
                    if not poster_path: 
                        poster_path = meta.get('poster_path', '')

            # Construire date corecte
            release_date = f"{year_val}-01-01" if year_val else ""
            
            # Curățare poster http
            if poster_path and 'image.tmdb.org' in poster_path:
                poster_path = '/' + poster_path.split('/')[-1]

            fake_item = {
                'id': tmdb_id,
                'media_type': current_media_type,
                'title': item.get('title') if current_media_type == 'movie' else None,
                'name': item.get('title') if current_media_type == 'tv' else None, # În history TV, coloana title e numele serialului
                'poster_path': poster_path,
                'overview': item.get('overview', ''),
                'release_date': release_date,
                'first_air_date': release_date
            }
        else:
            # API Data
            mtype = item.get('type', 'movie')
            if mtype in ['show', 'season', 'episode']: current_media_type = 'tv'
            raw = item.get(mtype, item)
            fake_item = {
                'id': str(raw.get('ids', {}).get('tmdb', '')),
                'media_type': current_media_type,
                'title': raw.get('title'),
                'name': raw.get('title'),
                'poster_path': '',
                'overview': raw.get('overview', '')
            }

        # Procesare finală
        processed = None
        if current_media_type == 'movie':
            processed = _process_movie_item(fake_item, return_data=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True)

        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    # 5. Paginare și Afișare
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'trakt_list_items', 'list_type': list_type, 'new_page': str(page + 1)}
        if user: next_params['user'] = user
        if slug: next_params['slug'] = slug
        if media_filter: next_params['media_filter'] = media_filter
        
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        
        items_to_add.append((next_url, next_li, True))
        cache_list.append({
            'label': next_label, 'url': next_url, 'is_folder': True,
            'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video', 'plot': 'Next Page'}, 'cm_items': []
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_filter == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    # Salvare RAM
    final_cache = []
    for i in cache_list:
        final_cache.append({
            'label': i['li'].getLabel() if 'li' in i else i['label'],
            'url': i['url'],
            'is_folder': i['is_folder'],
            'art': i['art'],
            'info': i['info'],
            'cm': i['cm_items'],
            'resume_time': i.get('resume_time', 0),
            'total_time': i.get('total_time', 0)
        })
    set_fast_cache(cache_key, final_cache)


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
    # --- MODIFICARE: Adăugat external_ids și schimbat cheia cache ---
    url = f"{BASE_URL}/{tmdb_endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}&append_to_response=external_ids"
    tmdb_data = cache_object(tmdb_worker, f"meta_ext_{media_type}_{tmdb_id}_{LANG}", url, expiration=168)
    # ---------------------------------------------------------------

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
        
        # --- MODIFICARE: Extragem IMDB ID ---
        imdb_id = tmdb_data.get('external_ids', {}).get('imdb_id', '')
        # ------------------------------------
        
        # MODIFICARE: Logica de Fallback RO -> EN a fost ștearsă complet.
        # Luăm direct titlul din TMDb. Acesta e garantat în engleză datorită parametrului URL.
        tmdb_title = tmdb_data.get('title') if media_type == 'movie' else tmdb_data.get('name')
        if tmdb_title:
            title = tmdb_title

        tagline = tmdb_data.get('tagline', '').strip()
        genres_str = ", ".join([g['name'] for g in tmdb_data.get('genres',[])])
        plot = tmdb_data.get('overview', '')
        
        try:
            from resources.lib.config import ADDON
            show_motto = ADDON.getSetting('show_motto_genre') != 'false'
        except: show_motto = True
        
        plot_header = ""
        if show_motto:
            if tagline and genres_str:
                plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            elif tagline:
                plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B]\n"
            elif genres_str:
                plot_header = f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            
        plot = plot_header + plot
        
        # Extragem metadatele din răspunsul TMDb
        rating = tmdb_data.get('vote_average', 0)
        votes = tmdb_data.get('vote_count', 0)
        
        if media_type == 'movie':
            premiered = tmdb_data.get('release_date', '')
            try:
                duration = int(tmdb_data.get('runtime') or 0) * 60
            except:
                duration = 0
            if tmdb_data.get('production_companies'):
                studio = tmdb_data['production_companies'][0].get('name', '')
        else:
            premiered = tmdb_data.get('first_air_date', '')
            try:
                runtimes = tmdb_data.get('episode_run_time', [])
                duration = int(runtimes[0]) * 60 if runtimes and runtimes[0] else 0
            except:
                duration = 0
            if tmdb_data.get('networks'):
                studio = tmdb_data['networks'][0].get('name', '')
                
        movie_mpaa = tmdb_data.get('mpaa', '')

        # --- SELF HEALING: SALVĂM IMAGINILE ÎN SQL PENTRU DATA VIITOARE ---
        if poster or backdrop:
            trakt_sync.update_item_images(None, tmdb_id, media_type, tmdb_data.get('poster_path', ''), tmdb_data.get('backdrop_path', ''))
 
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
        'duration': duration,
        'mpaa': movie_mpaa if 'movie_mpaa' in locals() else '',
        'genre': genres_str if 'genres_str' in locals() else ''
    }

    # Context menu
    # --- MODIFICARE: Comentat TMDB Info și Adăugat My Plays ---
    plays_params = {
        'mode': 'show_my_plays_menu',
        'tmdb_id': tmdb_id,
        'type': tmdb_endpoint,
        'title': title,
        'year': year,
        'imdb_id': imdb_id
    }

    cm = [
        ('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=trakt_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})"),
        ('[B][COLOR FF00CED1]My TMDB[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=tmdb_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})"),
        # ('[B][COLOR FFFDBD01]TMDB Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_info&tmdb_id={tmdb_id}&type={tmdb_endpoint})"),
        ('[B][COLOR FFFDBD01]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})")
    ]
    # ----------------------------------------------------------
    
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


def trakt_favorites_list(params):
    """Afișează Favoritele Trakt cu paginare și threading."""
    from resources.lib.tmdb_api import add_directory, _process_movie_item, _process_tv_item, prefetch_metadata_parallel
    from resources.lib.utils import paginate_list
    
    m_type = params.get('type')
    page = int(params.get('page', '1'))
    
    data = trakt_sync.get_trakt_favorites_from_db(m_type)
    
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total_pages = paginate_list(data, page, PAGE_LIMIT)
    
    # Threading pentru viteză
    prefetch_metadata_parallel(paginated, 'movie' if m_type == 'movies' else 'tv')

    for item in paginated:
        tmdb_id = item.get('tmdb_id')
        p_item = {
            'id': tmdb_id, 
            'title': item['title'], 
            'name': item['title'],
            'overview': item['overview'], 
            'poster_path': item['poster'],
            'release_date': f"{item['year']}-01-01" if item['year'] else ''
        }
        
        if m_type == 'movies':
            _process_movie_item(p_item)
        else:
            _process_tv_item(p_item)

    if page < total_pages:
        add_directory(f"[B]Next Page ({page+1}/{total_pages}) >>[/B]", 
                      {'mode': 'trakt_favorites_list', 'type': m_type, 'page': str(page+1)}, 
                      icon=NEXT_PAGE_ICON, folder=True)
    
    xbmcplugin.setContent(HANDLE, 'movies' if m_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_dropped_shows_list(params):
    """Afișează serialele abandonate (Dropped/Hidden) cu paginare și caching."""
    from resources.lib.tmdb_api import render_from_fast_cache, get_fast_cache, set_fast_cache, prefetch_metadata_parallel, _process_tv_item, add_directory
    from resources.lib.utils import paginate_list
    from resources.lib import trakt_sync
    import xbmcplugin

    page = int(params.get('new_page', '1'))
    cache_key = f"trakt_dropped_shows_{page}"
    
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    # Extragem ID-urile din SQL (populate de sync-ul global)
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id FROM trakt_hidden_shows")
        rows = c.fetchall()
        conn.close()
        # Construim o listă fake compatibilă cu prefetch-ul
        data = [{'id': r[0], 'media_type': 'tv'} for r in rows if r[0]]
    except:
        data = []

    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "You have no hidden shows (Dropped).", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated_items, total_pages = paginate_list(data, page, PAGE_LIMIT)
    
    # Prefetch metadate (va trage numele, posterele, etc. de pe TMDb)
    prefetch_metadata_parallel(paginated_items, 'tv')

    items_to_add = []
    cache_list = []

    # Importăm funcția necesară din tmdb_api pentru a o putea folosi
    from resources.lib.tmdb_api import get_tmdb_item_details

    for item in paginated_items:
        tmdb_id = item.get('id')
        if not tmdb_id: 
            continue
            
        # Extragem detaliile complete (aduse instantaneu din cache de prefetcher-ul de mai sus)
        details = get_tmdb_item_details(tmdb_id, 'tv')
        
        # Fallback de siguranță în caz că API-ul TMDb dă eroare
        if not details:
            details = item
            
        processed = _process_tv_item(details, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}/{total_pages}) >>[/B]"
        next_params = {'mode': 'trakt_dropped_shows', 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({
            'label': next_label, 'url': next_url, 'is_folder': True,
            'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video', 'plot': 'Next Page'}, 'cm_items': []
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    final_cache = []
    for i in cache_list:
        final_cache.append({
            'label': i['li'].getLabel() if 'li' in i else i['label'],
            'url': i['url'],
            'is_folder': i['is_folder'],
            'art': i['art'],
            'info': i['info'],
            'cm': i['cm_items'],
            'resume_time': i.get('resume_time', 0),
            'total_time': i.get('total_time', 0)
        })
    set_fast_cache(cache_key, final_cache)

