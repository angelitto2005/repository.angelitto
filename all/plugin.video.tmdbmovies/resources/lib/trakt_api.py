import sys
import os
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
import time
import threading
import requests
import re
import json
import datetime
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

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

# --- INCEPUT MODIFICARE: SESIUNE GLOBALA TRAKT (Ca in SALTS) ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Cream o sesiune persistenta pentru Trakt, care refoloseste conexiunile (mai rapid)
# si reincearca automat la anumite erori (ex: 502, 503, 504).
# NU punem retry automat pe 429 aici, pentru ca vrem sa-l controlam manual 
# in `trakt_api_request` citind header-ul `Retry-After`.
TRAKT_SESSION = requests.Session()
_retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
TRAKT_SESSION.mount('https://api.trakt.tv', HTTPAdapter(pool_maxsize=50, max_retries=_retries))
# --- SFARSIT MODIFICARE ---

# ══════════════════════════════════════════════════════════
# NOU: Token stocat in Kodi settings (atomic per-cheie)
# ══════════════════════════════════════════════════════════

def _save_trakt_tokens(data):
    """Salveaza tokenii Trakt in Kodi settings (atomic per-cheie)."""
    access_token = data.get('access_token', '')
    refresh_token = data.get('refresh_token', '')
    created_at = data.get('created_at', int(time.time()))
    expires_in = data.get('expires_in', 7776000)

    ADDON.setSetting('trakt_access_token', str(access_token))
    ADDON.setSetting('trakt_refresh_token', str(refresh_token))
    ADDON.setSetting('trakt_created_at', str(created_at))
    ADDON.setSetting('trakt_expires_in', str(expires_in))
    ADDON.setSetting('trakt_permanent_fail', 'false')


def _get_trakt_settings():
    """Citeste tokenii din Kodi settings."""
    access_token = ADDON.getSetting('trakt_access_token')
    refresh_token = ADDON.getSetting('trakt_refresh_token')
    created_at_str = ADDON.getSetting('trakt_created_at')
    expires_in_str = ADDON.getSetting('trakt_expires_in')

    if not access_token:
        return None

    try:
        created_at = int(float(created_at_str)) if created_at_str else 0
        expires_in = int(float(expires_in_str)) if expires_in_str else 7776000
    except:
        created_at = 0
        expires_in = 7776000

    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'created_at': created_at,
        'expires_in': expires_in,
    }


def _delete_old_token_json():
    """Sterge vechiul fisier JSON — utilizatorul se reconecteaza o data."""
    if not xbmcvfs.exists(TRAKT_TOKEN_FILE):
        return

    try:
        xbmcvfs.delete(TRAKT_TOKEN_FILE)
    except:
        pass


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
# ADAUGAT: Functie noua — refresh automat al tokenului
# ══════════════════════════════════════════════════════════

def refresh_trakt_token():
    """Reinnoieste access_token folosind refresh_token (settings)."""
    with _token_lock:
        token_data = _get_trakt_settings()
        if not token_data:
            log("[TRAKT] refresh: No token data.", xbmc.LOGWARNING)
            return None

        if ADDON.getSetting('trakt_permanent_fail') == 'true':
            log("[TRAKT] Permanent fail flag set. Skipping refresh.")
            return None

        retry_until_str = ADDON.getSetting('trakt_retry_until')
        if retry_until_str:
            try:
                retry_until = float(retry_until_str)
                if time.time() < retry_until:
                    remaining = int(retry_until - time.time())
                    log(f"[TRAKT] Rate-limited. Skip refresh for {remaining}s.")
                    return None
                else:
                    ADDON.setSetting('trakt_retry_until', '')
            except:
                ADDON.setSetting('trakt_retry_until', '')

        created_at = token_data.get('created_at', 0)
        expires_in = token_data.get('expires_in', 7776000)
        time_left = (created_at + expires_in) - time.time()
        if time_left > 3600:
            return token_data.get('access_token')

        refresh_token = token_data.get('refresh_token')
        if not refresh_token:
            log("[TRAKT] No refresh_token! Re-auth required.", xbmc.LOGERROR)
            return None

        if not TRAKT_CLIENT_SECRET:
            log("[TRAKT] TRAKT_CLIENT_SECRET missing! Refresh will fail!",
                xbmc.LOGERROR)

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
                _save_trakt_tokens(new_data)
                exp = new_data.get('expires_in', 0)
                log(f"[TRAKT] ✓ Token renewed! Expires in ~{exp // 3600}h")
                return new_data.get('access_token')
            elif r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 300))
                retry_until = time.time() + retry_after
                ADDON.setSetting('trakt_retry_until', str(retry_until))
                log(f"[TRAKT] Rate limited (429). Retry after {retry_after}s.")
                return None
            else:
                log(f"[TRAKT] Refresh FAILED: HTTP {r.status_code}")
                try:
                    resp = r.json()
                    if resp.get('error') == 'invalid_grant':
                        ADDON.setSetting('trakt_permanent_fail', 'true')
                        log("[TRAKT] invalid_grant → permanent fail. Re-auth required.", xbmc.LOGERROR)
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
# MODIFICAT: get_trakt_token — verifica expirarea + refresh
# ══════════════════════════════════════════════════════════

def get_trakt_token():
    """Returneaza un token valid din settings, cu refresh automat daca expira in < 1h."""
    _delete_old_token_json()

    token_data = _get_trakt_settings()
    if not token_data:
        return None

    access_token = token_data.get('access_token')
    if not access_token:
        return None

    created_at = token_data.get('created_at', 0)
    expires_in = token_data.get('expires_in', 7776000)
    time_left = (created_at + expires_in) - time.time()

    if time_left >= 3600:
        return access_token

    if time_left > 0:
        log(f"[TRAKT] Token expires in {int(time_left // 60)} min. Preventive refresh...")
    else:
        log(f"[TRAKT] Token EXPIRED {int(-time_left)}s ago!")

    refreshed = refresh_trakt_token()
    if refreshed:
        return refreshed

    if time_left > 0:
        log("[TRAKT] Refresh failed, but token is still temporarily valid.", xbmc.LOGWARNING)
        return access_token

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
# MODIFICAT: trakt_auth — adaugat client_secret la device/token
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

    # ══════════════════════════════════════════════════════════
    # QR CODE AUTH (stil Umbrella) — dialog custom cu QR + cod
    # doModal() pe MAIN THREAD (input garantat); polling in background
    # ══════════════════════════════════════════════════════════
    from resources.lib.utils import make_qr
    from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread
    qr_path = make_qr(f"https://trakt.tv/activate/{user_code}", 'trakt_qr.png')
    msg = (f"1. Open this link in browser:\n"
           f"[B][COLOR pink]https://trakt.tv/activate/{user_code}[/COLOR][/B]\n"
           f"2. Click Approve on the page (code is already in the link)")
    pdialog = QRProgressDialog(
        'auth_qr.xml', ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR pink]Trakt Authentication[/COLOR][/B]',
        qr_image=qr_path or '',
        icon=TRAKT_ICON,
        addon_icon=os.path.join(ADDON_PATH, 'icon.png'),
        content=msg,
    )

    _result = {}
    _mon = xbmc.Monitor()

    def _poll():
        start_time = time.time()
        interval_cur = interval
        while not pdialog.iscanceled() and not _mon.abortRequested():
            elapsed = time.time() - start_time
            if elapsed > expires_in:
                pdialog.expired = True
                pdialog.close()
                return
            percent = max(0, int(100 - (elapsed / expires_in * 100)))
            pdialog.update(percent, msg)
            time.sleep(interval_cur)

            try:
                poll = requests.post(
                    f"{TRAKT_API_URL}/oauth/device/token",
                    json={
                        'code': device_code,
                        'client_id': TRAKT_CLIENT_ID,
                        'client_secret': TRAKT_CLIENT_SECRET  # ← ADAUGAT
                    },
                    headers=get_trakt_headers(),
                    timeout=10
                )
                if poll.status_code == 200:
                    _result['token'] = poll.json()
                    pdialog.close()
                    return
                elif poll.status_code == 410:
                    pdialog.expired = True
                    pdialog.close()
                    return
                elif poll.status_code == 429:
                    interval_cur += 1
            except:
                pass

    threading.Thread(target=_poll, daemon=True).start()
    run_modal_main_thread(pdialog)
    pdialog.close()

    token_data = _result.get('token')
    if token_data:
        _save_trakt_tokens(token_data)
        user = get_trakt_username(token_data.get('access_token'))
        ADDON.setSetting('trakt_status', f"Connected: {user}")
        exp = token_data.get('expires_in', 0)
        log(f"[TRAKT] Authenticated! Token expires in ~{exp // 3600}h. "
            f"Auto-refresh active.")
        xbmcgui.Dialog().notification(
            "[B][COLOR pink]Trakt[/COLOR][/B]",
            "Connected successfully!",
            TRAKT_ICON, 3000, False
        )
        
        # ══════════════════════════════════════════════════════════
        # ADAUGAT: Pornire automata sincronizare totala in background
        # ══════════════════════════════════════════════════════════
        from resources.lib import trakt_sync
        # Rulam cu silent=False pentru ca utilizatorul sa vada progresul primei importari
        t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': False, 'force': True})
        t.daemon = True
        t.start()
        # ══════════════════════════════════════════════════════════
        
        xbmc.executebuiltin("Container.Refresh")


def trakt_revoke():
    # --- START PROTECTIE DECONECTARE ACCIDENTALA ---
    if not xbmcgui.Dialog().yesno("[B][COLOR pink]Disconnect Trakt[/COLOR][/B]", "Are you sure you want to disconnect from Trakt?\n[COLOR gray]Synced data will be deleted for security.[/COLOR]"):
        return
    # --- END PROTECTIE ---

    ADDON.setSetting('trakt_access_token', '')
    ADDON.setSetting('trakt_refresh_token', '')
    ADDON.setSetting('trakt_created_at', '')
    ADDON.setSetting('trakt_expires_in', '')
    ADDON.setSetting('trakt_permanent_fail', 'false')
    ADDON.setSetting('trakt_retry_until', '')

    if xbmcvfs.exists(TRAKT_TOKEN_FILE):
        xbmcvfs.delete(TRAKT_TOKEN_FILE)

    if xbmcvfs.exists(TRAKT_CACHE_FILE):
        xbmcvfs.delete(TRAKT_CACHE_FILE)
        
    # --- INCEPUT MODIFICARE: Stergem complet datele locale ale contului vechi ---
    from resources.lib.config import ADDON_DATA_DIR
    for db_ext in ['trakt_sync.db', 'trakt_sync.db-shm', 'trakt_sync.db-wal', 'last_sync.json']:
        db_path = os.path.join(ADDON_DATA_DIR, db_ext)
        if xbmcvfs.exists(db_path):
            try:
                xbmcvfs.delete(db_path)
            except:
                try: os.remove(db_path)
                except: pass
    # --- SFARSIT MODIFICARE ---

    ADDON.setSetting('trakt_status', "Disconnected")
    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "Disconnected.", TRAKT_ICON, 3000, False)
    
    # Curatam si memoria RAM ca sa dispara imediat din meniuri
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    xbmc.executebuiltin("Container.Refresh")


# ===================== TRAKT API REQUEST =====================
# ══════════════════════════════════════════════════════════
# MODIFICAT: trakt_api_request — retry pe 401
# ══════════════════════════════════════════════════════════
def _do_request(method, url, headers, data=None, params=None):
    """Executa cererea folosind sesiunea globala Trakt."""
    # --- INCEPUT MODIFICARE: Folosim TRAKT_SESSION in loc de requests ---
    if method == 'GET':
        return TRAKT_SESSION.get(url, headers=headers, params=params, timeout=15)
    elif method == 'POST':
        return TRAKT_SESSION.post(url, headers=headers, json=data, timeout=15)
    elif method == 'DELETE':
        return TRAKT_SESSION.delete(url, headers=headers, json=data, timeout=15)
    return None
    # --- SFARSIT MODIFICARE ---


def trakt_api_request(endpoint, method='GET', data=None, params=None, pagination=False):
    token = get_trakt_token()
    
    # Identificam daca endpoint-ul solicitat necesita autentificare obligatorie
    endpoint_lower = endpoint.lower()
    is_private = False
    
    if (endpoint_lower.startswith("/sync") or 
        endpoint_lower.startswith("/users/me") or 
        endpoint_lower.startswith("/users/hidden") or
        endpoint_lower.startswith("/scrobble") or 
        endpoint_lower.startswith("/calendars/my") or 
        endpoint_lower.startswith("/recommendations")):
        is_private = True

    # Daca endpoint-ul este privat si nu avem un token valid, oprim cererea discret
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
                    return (None, 0) if pagination else None

            # ── 420 Account Limit Exceeded ──
            if r.status_code == 420:
                try:
                    err_json = r.json()
                    err_desc = err_json.get('error_description') or err_json.get('error', '')
                except: err_desc = ''
                log(f"[TRAKT] 420 Account Limit Exceeded on {endpoint}: {err_desc}", xbmc.LOGWARNING)
                xbmcgui.Dialog().notification(
                    "[B][COLOR pink]Trakt[/COLOR][/B]",
                    f"[B][COLOR red]No more space:[/COLOR][/B] Watchlist/List is FULL! "
                    f"[B][COLOR red]Item NOT added.[/COLOR][/B]",
                    TRAKT_ICON, 5000, False)
                return (None, 0) if pagination else None

            # ── 401 Unauthorized ── (Se executa doar daca am trimis un token expirat)
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
                    return (None, 0) if pagination else None

            # ── Success ──
            if r.status_code in (200, 201, 204):
                if not r.content:
                    return (True, 1) if pagination else True
                data_json = r.json()
                if pagination:
                    page_count = int(r.headers.get('X-Pagination-Page-Count', 1))
                    return (data_json, page_count)
                return data_json

            log(f"[TRAKT] {method} {endpoint} → HTTP {r.status_code}",
                xbmc.LOGWARNING)
            return (None, 0) if pagination else None

        except requests.exceptions.Timeout:
            log(f"[TRAKT] Timeout pe {endpoint}", xbmc.LOGWARNING)
            return (None, 0) if pagination else None
        except Exception as e:
            log(f"[TRAKT] API Error: {e}", xbmc.LOGERROR)
            return (None, 0) if pagination else None

    return (None, 0) if pagination else None


# ===================== PAGINATED LIST HELPER =====================

def _get_trakt_paginated_list(endpoint, params=None, max_workers=5):
    """
    Preia TOATE paginile de la un endpoint Trakt paginat.
    - Prima pagina e ceruta cu flag pagination=True (returneaza si page_count).
    - Paginile ramase sunt fetch-uite in paralel cu ThreadPoolExecutor.
    Returneaza lista completa combinata.
    """
    p = dict(params or {})
    # Trakt limiteaza la 250 per pagina pentru majoritatea endpoint-urilor
    p.setdefault('limit', 250)
    
    first_page, page_count = trakt_api_request(
        endpoint,
        params={**p, 'page': 1},
        pagination=True
    )
    
    if not first_page or not isinstance(first_page, list):
        return first_page if isinstance(first_page, list) else []
    
    if page_count <= 1:
        return first_page
    
    all_data = list(first_page)
    
    def _fetch_page(page_num):
        page_data = trakt_api_request(endpoint, params={**p, 'page': page_num})
        if page_data and isinstance(page_data, list):
            return page_data
        return []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pages = range(2, page_count + 1)
        for page_result in executor.map(_fetch_page, pages):
            all_data.extend(page_result)
    
    log(f"[TRAKT] Paginated {endpoint}: {len(all_data)} items from {page_count} pages")
    return all_data


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

        # ── 429 Rate Limit → asteptam si reincercam ──
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

        # ── Orice alt cod → returnam direct ──
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

def _item_title(tmdb_id, media_type):
    """Titlul itemului pentru notificari (meta cache -> API)."""
    try:
        from resources.lib import trakt_sync
        details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, media_type) or {}
        t = details.get('title') or details.get('name')
        if t:
            return t
    except:
        pass
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        details = get_tmdb_item_details(str(tmdb_id), media_type) or {}
        return details.get('title') or details.get('name', 'Unknown')
    except:
        return 'Unknown'

def get_trakt_watchlist(media_type='movies'):

    return trakt_api_request(f"/sync/watchlist/{media_type}", params={'extended': 'full'})

def add_to_trakt_watchlist(tmdb_id, media_type, notify=True):
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
        title = _item_title(tmdb_id, 'movie' if media_type == 'movie' else 'tv')
        try:
            details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'movie' if media_type == 'movie' else 'tv') or {}
            year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            poster = details.get('poster_path', '')
            overview = details.get('overview', '')
            
            # Data format Trakt (ISO) pentru sortare corecta
            added_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            conn = trakt_sync.get_connection()
            # Inseram fix 9 valori, matching exact structura tabelului
            # (list_type, media_type, tmdb_id, title, year, added_at, poster, backdrop, overview)
            conn.execute("INSERT OR REPLACE INTO trakt_lists VALUES (?,?,?,?,?,?,?,?,?)",
                      ('watchlist', db_type, str(tmdb_id), title, year, added_at, poster, '', overview))
            conn.commit()
            conn.close()
        except: pass
        # --------------------------

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        try:
            from resources.lib.mdblist_sync import clear_cache_prefix
            clear_cache_prefix('trakt_calendar')
        except: pass
        
        if notify:
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] added to [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def remove_from_trakt_watchlist(tmdb_id, media_type, notify=True):
    from resources.lib import trakt_sync
    
    if media_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'movie'
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        db_type = 'show'

    result = trakt_api_request("/sync/watchlist/remove", method='POST', data=data)
    
    if result:
        title = ''
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("SELECT title FROM trakt_lists WHERE list_type='watchlist' AND media_type=? AND tmdb_id=?", (db_type, str(tmdb_id)))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                title = row[0]
        except: pass
        if not title:
            title = _item_title(tmdb_id, 'movie' if media_type == 'movie' else 'tv')
        # --- UPDATE SQL INSTANT (STERGERE LOCALA) ---
        try:
            conn = trakt_sync.get_connection()
            # Stergem din tabelul trakt_lists unde tinem watchlist-ul local
            conn.execute("DELETE FROM trakt_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                         ('watchlist', db_type, str(tmdb_id)))
            conn.commit()
            conn.close()
        except: pass
        # -------------------------------------------

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        try:
            from resources.lib.mdblist_sync import clear_cache_prefix
            clear_cache_prefix('trakt_calendar')
        except: pass
        
        if notify:
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] removed from [B][COLOR pink]Watchlist[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False

def is_in_trakt_watchlist(tmdb_id, media_type):
    """Verifica instant in SQL daca e in Watchlist."""
    from resources.lib import trakt_sync
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        db_type = 'movie' if media_type == 'movie' else 'show'
        # Cautam doar daca exista randul
        c.execute("SELECT 1 FROM trakt_lists WHERE list_type='watchlist' AND media_type=? AND tmdb_id=?", (db_type, str(tmdb_id)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False

# ===================== TRAKT FAVORITES (New) =====================

def add_to_trakt_favorites(tmdb_id, media_type, notify=True):
    from resources.lib import trakt_sync, tmdb_api # Import corect
    type_key = 'movies' if media_type == 'movie' else 'shows'
    data = {type_key: [{'ids': {'tmdb': int(tmdb_id)}}]}
    result = trakt_api_request("/sync/favorites", method='POST', data=data)
    if result:
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        title = ''
        try:
            # FIX: Folosim get_tmdb_item_details care face API call daca SQL e gol
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
        if notify:
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] added to [B][COLOR pink]Favorites[/COLOR][/B]", TRAKT_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True
    return False


def remove_from_trakt_favorites(tmdb_id, media_type, notify=True):
    """Sterge de la favorite Trakt si face update instant in SQL."""
    type_key = 'movies' if media_type == 'movie' else 'shows'
    data = {type_key: [{'ids': {'tmdb': int(tmdb_id)}}]}
    result = trakt_api_request("/sync/favorites/remove", method='POST', data=data)
    if result:
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        from resources.lib import trakt_sync
        m_type_db = 'movie' if media_type in ['movie', 'movies'] else 'show'
        title = ''
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("SELECT title FROM trakt_favorites WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), m_type_db))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                title = row[0]
        except: pass
        if not title:
            title = _item_title(tmdb_id, 'movie' if media_type == 'movie' else 'tv')
        # STERGERE INSTANTA DIN SQL PENTRU MENIU DINAMIC
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM trakt_favorites WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), m_type_db))
            conn.commit()
            conn.close()
        except: pass
        if notify:
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{title}[/COLOR][/B] removed from [B][COLOR pink]Favorites[/COLOR][/B]", TRAKT_ICON, 3000, False)
        return True
    return False

def is_in_trakt_favorites(tmdb_id, media_type):
    """Verifica instant in SQL daca e la Favorite."""
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
        # --- UPDATE SQL LOCAL PENTRU LISTA (VITEZA) ---
        try:
            from resources.lib import trakt_sync
            # Luam metadatele din cache-ul local (este instantaneu)
            details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'movie' if media_type == 'movie' else 'tv') or {}
            title = details.get('title') or details.get('name', 'Unknown')
            year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            poster = details.get('poster_path', '')
            overview = details.get('overview', '')
            
            from datetime import datetime
            added_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
            conn = trakt_sync.get_connection()
            # 1. Verificam daca exista deja (contorul nu se incrementeaza la duplicate)
            cur = conn.execute("SELECT 1 FROM user_list_items WHERE list_slug=? AND media_type=? AND tmdb_id=?",
                               (list_slug, 'movie' if media_type == 'movie' else 'show', str(tmdb_id)))
            is_duplicate = cur.fetchone() is not None
            # 2. Inseram filmul in lista (cu timestamp curent pentru Newest First)
            conn.execute("INSERT OR REPLACE INTO user_list_items (list_slug, media_type, tmdb_id, title, year, added_at, poster, overview) VALUES (?,?,?,?,?,?,?,?)",
                         (list_slug, 'movie' if media_type == 'movie' else 'show', str(tmdb_id), title, year, added_iso, poster, overview))
            # 3. Incrementam contorul listei (+1) doar daca e item nou
            if not is_duplicate:
                conn.execute("UPDATE user_lists SET item_count = item_count + 1 WHERE slug=?", (list_slug,))
            # 3. Actualizam posterul listei (noul prim element)
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
            # 1. Stergem item-ul din baza de date locala imediat
            conn.execute("DELETE FROM user_list_items WHERE list_slug=? AND tmdb_id=?", (list_slug, str(tmdb_id)))
            # 2. Scadem 1 din numarul de iteme afisat in meniu
            conn.execute("UPDATE user_lists SET item_count = item_count - 1 WHERE slug=? AND item_count > 0", (list_slug,))
            # 3. Daca itemul sters era primul (poster_tmdb_id), actualizam posterul
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
    """Verifica instant in SQL daca un film este in lista (pentru Context Menu)."""
    from resources.lib import trakt_sync
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        # Cautam direct in tabelul de iteme al listelor
        c.execute("SELECT 1 FROM user_list_items WHERE list_slug=? AND tmdb_id=?", (list_slug, str(tmdb_id)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False


# ===================== TRAKT HISTORY =====================

def get_trakt_history(media_type='movies', limit=50, page=1):

    return trakt_api_request(f"/sync/history/{media_type}", params={'limit': limit, 'page': page, 'extended': 'full'})

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

def get_trakt_most_collected(media_type='movies', period='weekly', limit=40):
    return trakt_api_request(f"/{media_type}/collected/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_most_played(media_type='movies', period='weekly', limit=40):
    return trakt_api_request(f"/{media_type}/played/{period}", params={'limit': limit, 'extended': 'full'})

def get_trakt_calendar(endpoint, days=30, start_date=None):
    import datetime
    if not start_date:
        start_date = datetime.datetime.now().strftime('%Y-%m-%d')
    return trakt_api_request(f"/calendars/{endpoint}/{start_date}/{days}", params={'extended': 'full'})

# ===================== TRAKT CALENDAR =====================

# ══════════════════════════════════════════════════════════
# ADAUGAT: Preluare seriale ascunse din calendar
# ══════════════════════════════════════════════════════════

# ===================== TRAKT CALENDAR =====================

def get_trakt_hidden_calendar_shows():
    """
    Preia serialele hidden din calendar.
    Returneaza dict cu seturi SEPARATE per tip de ID.
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
    Filtreaza episoadele din calendar care apartin serialelor hidden.
    Compara FIECARE tip de ID separat (tmdb cu tmdb, tvdb cu tvdb, etc.)
    """
    if not calendar_data or not isinstance(calendar_data, list):
        return calendar_data

    hidden = get_trakt_hidden_calendar_shows()
    # Verificam daca exista cel putin un ID hidden
    if not any(s for s in hidden.values()):
        return calendar_data

    filtered = []
    for item in calendar_data:
        show_ids = item.get('show', {}).get('ids', {})
        is_hidden = False
        # Comparam STRICT: tmdb cu tmdb, tvdb cu tvdb, etc.
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


def _filter_specials_from_calendar(calendar_data):
    """
    Filtreaza episoadele din sezonul 0 (specials) din calendar.
    Specials (S00E78 etc.) nu au ce cauta in calendarul de episoade —
    Trakt le intoarce cu first_aired, dar MDBList nu le afiseaza.
    """
    if not calendar_data or not isinstance(calendar_data, list):
        return calendar_data
    filtered = []
    for item in calendar_data:
        if not isinstance(item, dict):
            continue
        ep = item.get('episode', {}) or {}
        if not isinstance(ep, dict):
            ep = {}
        season = ep.get('season', 0) or 0
        if int(season) <= 0:
            continue
        filtered.append(item)
    removed = len(calendar_data) - len(filtered)
    if removed > 0:
        log(f"[TRAKT] Calendar: {removed} specials (S00) episodes removed.")
    return filtered


def get_trakt_calendar_shows(start_date=None, days=14, limit=0):
    import datetime as _dt
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    cal_params = {'extended': 'full'}
    if limit:
        cal_params['limit'] = limit
    # Trakt API limiteaza la 33 zile per cerere; chunking automat
    MAX_CHUNK = 33
    if days <= MAX_CHUNK:
        result = trakt_api_request(
            f"/calendars/my/shows/{start_date}/{days}",
            params=cal_params
        )
        return _filter_specials_from_calendar(_filter_hidden_from_calendar(result))
    all_results = []
    # Parsare manuala (fara strptime din datetime windows shared-runtime)
    _y, _m, _d = (int(x) for x in start_date.split('-')[:3])
    cur_date = _dt.date(_y, _m, _d)
    end_date = cur_date + _dt.timedelta(days=days)
    while cur_date < end_date:
        chunk_days = min(MAX_CHUNK, (end_date - cur_date).days)
        chunk_start = cur_date.strftime('%Y-%m-%d')
        result = trakt_api_request(
            f"/calendars/my/shows/{chunk_start}/{chunk_days}",
            params=cal_params
        )
        if result and isinstance(result, list):
            all_results.extend(result)
        cur_date += _dt.timedelta(days=chunk_days)
    seen = set()
    deduped = []
    for item in all_results:
        show = item.get('show', {}) or {}
        ids = show.get('ids', {}) or {}
        trakt_id = ids.get('trakt', 0)
        ep = item.get('episode', {}) or {}
        key = (trakt_id, ep.get('season', 0), ep.get('number', 0))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return _filter_specials_from_calendar(_filter_hidden_from_calendar(deduped))


def get_trakt_calendar_movies(start_date=None, days=30, limit=0):
    import datetime as _dt
    if not start_date:
        start_date = time.strftime('%Y-%m-%d')
    cal_params = {'extended': 'full'}
    if limit:
        cal_params['limit'] = limit
    # Trakt API limiteaza la 66 zile per cerere; chunking automat
    MAX_CHUNK = 66
    if days <= MAX_CHUNK:
        return trakt_api_request(
            f"/calendars/my/movies/{start_date}/{days}",
            params=cal_params
        )
    all_results = []
    _y, _m, _d = (int(x) for x in start_date.split('-')[:3])
    cur_date = _dt.date(_y, _m, _d)
    end_date = cur_date + _dt.timedelta(days=days)
    while cur_date < end_date:
        chunk_days = min(MAX_CHUNK, (end_date - cur_date).days)
        chunk_start = cur_date.strftime('%Y-%m-%d')
        result = trakt_api_request(
            f"/calendars/my/movies/{chunk_start}/{chunk_days}",
            params=cal_params
        )
        if result and isinstance(result, list):
            all_results.extend(result)
        cur_date += _dt.timedelta(days=chunk_days)
    seen = set()
    deduped = []
    for item in all_results:
        ids = (item.get('movie', {}) or {}).get('ids', {}) or {}
        mid = ids.get('trakt', 0)
        if mid not in seen:
            seen.add(mid)
            deduped.append(item)
    return deduped


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
    """Returneaza liste trending cu detalii complete."""
    return trakt_api_request("/lists/trending", params={'limit': limit, 'extended': 'full'})

def get_trakt_popular_lists(limit=50):
    """Returneaza liste populare cu detalii complete."""
    return trakt_api_request("/lists/popular", params={'limit': limit, 'extended': 'full'})

def get_liked_lists(limit=50):
    """Returneaza listele liked de user cu detalii complete."""
    return trakt_api_request("/users/likes/lists", params={'limit': limit, 'extended': 'full'})


# ===================== TRAKT SYNC =====================

def perform_trakt_sync(force=False, silent=False):
    """Sync Trakt - totul e in SQL."""
    trakt_sync.sync_full_library(silent=silent, force=force)
    return True

def rebuild_watched_cache():
    """Reconstruieste cache-ul watched din baza SQL Trakt."""
    import time
    from resources.lib import trakt_sync
    from resources.lib.utils import write_json
    
    log("[TRAKT SYNC] Rebuilding watched cache from SQL...")
    
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
        log(f"[TRAKT SYNC] Error reading watched movies: {e}", xbmc.LOGERROR)
    
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
        log(f"[TRAKT SYNC] Error reading watched episodes: {e}", xbmc.LOGERROR)
    
    conn.close()
    
    # Salvam cache-ul
    write_json(TRAKT_CACHE_FILE, cache)
    
    log(f"[TRAKT SYNC] Watched cache rebuilt: {len(cache['movies'])} movies, {len(cache['shows'])} shows")


def check_auto_sync():
    """
    Verifica daca e nevoie de sincronizare si o ruleaza in fundal (thread separat)
    folosind noul sistem Smart Sync din trakt_sync.
    """
    token = get_trakt_token()
    if not token:
        return

    # Pornim direct sync_full_library intr-un thread.
    # Aceasta va verifica intern (needs_sync) daca chiar e nevoie de update.
    t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': True})
    t.daemon = True
    t.start()

def get_watched_counts(tmdb_id, content_type, season_num=None):
    """
    Returneaza numarul de vizionari DIRECT din baza de date SQL.
    - movie: 1 daca e vizionat, 0 altfel
    - tv: numarul total de episoade vizionate
    - season: numarul de episoade vizionate din sezonul specificat
    """
    from resources.lib import trakt_sync
    
    str_id = str(tmdb_id)
    
    # Verifica daca DB exista
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
    """Verifica daca un episod specific e vizionat - DIRECT din SQL."""
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

    # --- PAS 1: Stergere Locala SQL (Instant UI) ---
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

    # --- PAS 2: Executie API Trakt (Metoda Corecta: DELETE /sync/playback/{id}) ---
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

    # --- PAS 3: Fallback (Doar daca API-ul a dat crash, ex. Timeout) ---
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

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", f"[B][COLOR lime]{_item_title(tmdb_id, 'movie' if content_type == 'movie' else 'tv')}[/COLOR][/B] removed from [B][COLOR FF33CCFF]Progress[/COLOR][/B]", TRAKT_ICON, 2000, False)
    
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    # NICIODATA Container.Refresh AICI: ruleaza in timp ce meniul contextual se
    # inchide inca -> Kodi e "updating in progress" si inghite Container.Update-ul
    # ulterior din handle-ul remove_progress (markerul de resume ramane pana
    # re-intri in sezon). Refresh-ul il face handle-ul from entry.py.

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

    from resources.lib.watched_provider import get_label as _prov_label, get_color as _prov_color, is_episode_watched as _is_ep_watched
    _prov_lbl = _prov_label()
    _prov_clr = _prov_color()
    is_ep_watched = False
    if season and episode:
        is_ep_watched = _is_ep_watched(tmdb_id, season, episode)

    if is_ep_watched:
        cm.append((f'[B][COLOR FFE41B17]Mark Unwatched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(unwatched_params)})"))
    else:
        cm.append((f'[B][COLOR FF6AFB92]Mark Watched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(watched_params)})"))

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
    
    # --- MODIFICARE CHEIE: Trimitem catre TOATE cele 3 sectiuni (inclusiv DROPPED) ---
    r1 = trakt_api_request("/users/hidden/progress_watched", method='POST', data=data)
    r2 = trakt_api_request("/users/hidden/calendar", method='POST', data=data)
    r3 = trakt_api_request("/users/hidden/dropped", method='POST', data=data)
    # --------------------------------------------------------------------------------
    
    if r1 or r2 or r3:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{_item_title(tmdb_id, 'tv')}[/COLOR][/B] — [B][COLOR FFE41B17]Drop Show[/COLOR][/B]", TRAKT_ICON, 3000, False)
        from resources.lib import trakt_sync
        try:
            conn = trakt_sync.get_connection()
            # Stergem din Next Episodes (Up Next) local
            conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            # Adaugam INSTANT in lista de ascunse (Dropped) locala, fara sa mai asteptam sync-ul
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
    
    # --- MODIFICARE CHEIE: Scoatem din TOATE cele 3 sectiuni (inclusiv DROPPED) ---
    r1 = trakt_api_request("/users/hidden/progress_watched/remove", method='POST', data=data)
    r2 = trakt_api_request("/users/hidden/calendar/remove", method='POST', data=data)
    r3 = trakt_api_request("/users/hidden/dropped/remove", method='POST', data=data)
    # ------------------------------------------------------------------------------
    
    if r1 or r2 or r3:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"[B][COLOR lime]{_item_title(tmdb_id, 'tv')}[/COLOR][/B] — Restore [B][COLOR FF6AFB92]Dropped Show[/COLOR][/B]", TRAKT_ICON, 3000, False)
        from resources.lib import trakt_sync
        try:
            conn = trakt_sync.get_connection()
            # Stergem din lista locala de Dropped/Ascunse
            conn.execute("DELETE FROM trakt_hidden_shows WHERE tmdb_id=?", (str(tmdb_id),))
            conn.commit()
            conn.close()
        except: pass
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        # Declansam refresh la episod in background ca sa apara la loc in Up Next instant
        import threading
        threading.Thread(target=trakt_sync.refresh_next_episode, args=(tmdb_id, True), daemon=True).start()
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
    
    # 3. Meniu Dinamic pentru Dropped Shows (paritate cu MDBList: rosu/verde)
    if content_type in ['tv', 'show', 'episode']:
        if trakt_sync.is_show_hidden(tmdb_id):
            options.append(('Restore [B][COLOR FF6AFB92]Dropped Show[/COLOR][/B]', 'unhide_progress'))
        else:
            options.append(('[B][COLOR FFE41B17]Drop Show[/COLOR][/B]', 'hide_progress'))
        
    if content_type != 'season':
        options.append(('[B]Rate on [COLOR pink]Trakt[/COLOR][/B]', 'add_rating'))
    # --- Mark Watched/Unwatched (Dinamic, pe serverul Trakt — cross-provider) ---
    if content_type == 'movie':
        _trak_is_w = trakt_sync.is_movie_watched(tmdb_id)
    elif content_type in ('tv', 'show'):
        _trak_is_w = trakt_sync.get_episode_watched_count(tmdb_id) > 0
    elif content_type == 'episode' and season is not None and episode is not None:
        _trak_is_w = trakt_sync.is_episode_watched(tmdb_id, season, episode)
    else:
        _trak_is_w = False
    if _trak_is_w:
        options.append(('[B][COLOR FFE41B17]Mark Unwatched [COLOR pink](Trakt)[/COLOR][/B]', 'mark_unwatched_trakt'))
    else:
        options.append(('[B][COLOR FF6AFB92]Mark Watched [COLOR pink](Trakt)[/COLOR][/B]', 'mark_watched_trakt'))

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
    elif action == 'hide_progress': hide_show_from_progress(tmdb_id)
    elif action == 'unhide_progress': unhide_show_from_progress(tmdb_id)
    elif action == 'add_rating': rate_trakt_item(tmdb_id, content_type, season, episode, title)
    elif action == 'mark_watched_trakt':
        from resources.lib import trakt_sync
        trakt_sync.mark_as_watched_internal(tmdb_id, content_type, season, episode, sync_trakt=True, refresh_ui=True)
    elif action == 'mark_unwatched_trakt':
        from resources.lib import trakt_sync
        trakt_sync.mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_trakt=True, refresh_ui=True)
    
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
        self.setProperty('tmdbmovies.service_icon2', self.meta.get('service_icon2', ''))
        self.setProperty('tmdbmovies.service_icon3', self.meta.get('service_icon3', ''))
        self.setProperty('tmdbmovies.service_icon4', self.meta.get('service_icon4', ''))
        
        content_type = self.meta.get('content_type', 'movie')
        if content_type == 'movie':
            self.setProperty('tmdbmovies.show_title', self.meta.get('title', 'Unknown'))
            self.setProperty('tmdbmovies.ep_label', '')
        elif content_type == 'episode' and self.meta.get('season') and self.meta.get('episode'):
            self.setProperty('tmdbmovies.show_title', self.meta.get('tvshowtitle', 'Unknown'))
            s_val = int(self.meta.get('season'))
            e_val = int(self.meta.get('episode'))
            ep_title = self.meta.get('title', '')
            if ep_title:
                self.setProperty('tmdbmovies.ep_label', f"S{s_val:02d}E{e_val:02d} - {ep_title}")
            else:
                self.setProperty('tmdbmovies.ep_label', f"S{s_val:02d}E{e_val:02d}")
        else:
            # show/season: doar numele serialului, fara SXXEYY
            self.setProperty('tmdbmovies.show_title', self.meta.get('tvshowtitle', 'Unknown'))
            self.setProperty('tmdbmovies.ep_label', '')
        
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

def show_rating_window(tmdb_id, content_type, season, episode, title, service_icon, service_title, extra_icons=None):
    """Deschide TraktRating.xml (inimioare 1-10). Returneaza valoarea; 0 = anulat/Back."""
    meta_info = {
        'content_type': content_type, 'title': title, 'season': season, 'episode': episode,
        'fanart': '', 'clearlogo': '', 'tvshowtitle': '',
        'service_title': service_title, 'service_icon': service_icon,
        'service_icon2': (extra_icons[0] if extra_icons and len(extra_icons) > 0 else ''),
        'service_icon3': (extra_icons[1] if extra_icons and len(extra_icons) > 1 else ''),
        'service_icon4': (extra_icons[2] if extra_icons and len(extra_icons) > 2 else ''),
    }

    from resources.lib.tmdb_api import get_tmdb_item_details
    try:
        details = get_tmdb_item_details(str(tmdb_id), 'movie' if content_type == 'movie' else 'tv')
        if details:
            if details.get('backdrop_path'): meta_info['fanart'] = f"{BACKDROP_BASE}{details.get('backdrop_path')}"
            if details.get('clearlogo'): meta_info['clearlogo'] = f"{IMG_BASE}{details.get('clearlogo')}"
            if content_type != 'movie':
                meta_info['tvshowtitle'] = details.get('name', 'Unknown')
                if not title or re.match(r'^[A-Za-zÀ-ÿ]+\s+\d+$', title):
                    from resources.lib.tmdb_api import get_smart_season_details
                    season_data = get_smart_season_details(str(tmdb_id), season)
                    if season_data:
                        for ep in season_data.get('episodes', []):
                            if str(ep.get('episode_number')) == str(episode):
                                if ep.get('name'): meta_info['title'] = ep.get('name')
                                break
    except: pass

    win = TraktRatingWindow('TraktRating.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', meta=meta_info)
    win.doModal()
    val_10 = win.rating_val
    del win
    return val_10


def _prompt_trakt_rating(tmdb_id, content_type, season, episode, title, service='trakt'):
    if service == 'trakt':
        token = get_trakt_token()
        if not token: return
        service_label = "RATE ON TRAKT"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
    elif service == 'mdblist':
        from resources.lib.mdblist_api import MDBListAPI
        if not MDBListAPI().is_authenticated():
            xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                           'MDBList is not connected.',
                                           xbmcgui.NOTIFICATION_ERROR, 3000, False)
            return
        service_label = "RATE ON MDBLIST"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'mdblist.png')
    elif service == 'simkl':
        from resources.lib.simkl_api import SIMKLAPI
        if not SIMKLAPI().is_authenticated():
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                           'Simkl is not connected.',
                                           xbmcgui.NOTIFICATION_ERROR, 3000, False)
            return
        service_label = "RATE ON SIMKL"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'simkl.png')
    else:
        # TMDb
        service_label = "RATE ON TMDB"
        service_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
    
    val_10 = show_rating_window(tmdb_id, content_type, season, episode, title, service_icon, service_label)
    
    if val_10 > 0:
        if service == 'trakt':
            # RESTAURARE SCALA 1-10: Trakt site mapreaza 1-10 la 0.5-5.0 stele.
            # Daca userul alege butonul 3, trimitem 3, iar pe site apare 1.5 stele.
            val_final = val_10
            
            if content_type == 'movie':
                data = {'movies':[{'ids': {'tmdb': int(tmdb_id)}, 'rating': val_final}]}
            else:
                # Payload corect per tip (show/season/episode) — reuse din tmdb_api.
                # Inainte construia seasons/episodes cu int(season)/int(episode) →
                # crash la show/season (int(None)) → ratingul nu ajungea niciodata.
                from resources.lib.tmdb_api import _trakt_rating_payload
                data = _trakt_rating_payload(tmdb_id, content_type, season, episode, val_final)
            
            res = trakt_api_request("/sync/ratings", method='POST', data=data)
            if res is not None:
                stars = val_final / 2.0
                xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"Rated [B][COLOR lime]{stars} Stars[/COLOR][/B]", service_icon, 3000, False)
        elif service == 'mdblist':
            from resources.lib.mdblist_api import MDBListAPI
            api = MDBListAPI()
            res = api.rate_item(content_type, tmdb_id, val_10, season, episode)
            if res is not None:
                xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]",
                                               f"Rated [B][COLOR lime]{val_10}/10[/COLOR][/B]",
                                               service_icon, 3000, False)
        elif service == 'simkl':
            from resources.lib.simkl_api import SIMKLAPI
            api = SIMKLAPI()
            res = api.rate_item(content_type, tmdb_id, val_10, season, episode)
            if res is not None:
                # Simkl nu suporta rating per episod/sezon — ratingul se aplica
                # show-ului parinte (vezi simkl_api.rate_item).
                target = 'Show' if content_type != 'movie' else ''
                xbmcgui.Dialog().notification("[B][COLOR mediumpurple]Simkl[/COLOR][/B]",
                                               f"Rated {target} [B][COLOR lime]{val_10}/10[/COLOR][/B]",
                                               service_icon, 3000, False)
        else:
            # TMDb - Ramane 1-10
            from resources.lib.tmdb_api import rate_tmdb_item_silent
            if rate_tmdb_item_silent(tmdb_id, content_type, val_10, season, episode):
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb[/COLOR][/B]", f"Rated [B][COLOR lime]{val_10}/10[/COLOR][/B]", service_icon, 3000, False)

def rate_trakt_item(tmdb_id, content_type, season=None, episode=None, title=''):
    _prompt_trakt_rating(tmdb_id, content_type, season, episode, title)

# ===================== TRAKT MY LISTS - MODIFICAT COMPLET =====================

def get_next_episodes(params=None):
    """Aliat pentru service.py - Inlocuieste functia care lipsea."""
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
    
    # 2. FALLBACK API (Daca SQL e gol - ex: prima rulare)
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
        elif list_type == 'collected':
            period = params.get('period', 'all')
            api_data = get_trakt_most_collected(media_type, period, 500)
        elif list_type == 'watched':
            period = params.get('period', 'all')
            api_data = get_trakt_most_watched(media_type, period, 500)
        elif list_type == 'played':
            period = params.get('period', 'all')
            api_data = get_trakt_most_played(media_type, period, 500)
        
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

    # Construim fake_items + prefetch
    fake_items = []
    for item in paginated_items:
        fake_items.append({
            'id': item.get('tmdb_id') or item.get('id'),
            'title': item.get('title'),
            'name': item.get('title'),
            'release_date': f"{item.get('year', '')}-01-01",
            'first_air_date': f"{item.get('year', '')}-01-01",
            'overview': item.get('overview', ''),
            'poster_path': item.get('poster_path', '')
        })

    prefetch_metadata_parallel(fake_items, 'movie' if media_type == 'movies' else 'tv')

    cache_list = []
    items_to_add = []
    for processed_item in fake_items:
        if media_type == 'movies':
            processed = _process_movie_item(processed_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(processed_item, return_data=True, skip_details=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'trakt_discovery_list', 'list_type': list_type, 'media_type': media_type, 'page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        items_to_add.append((next_url, next_li, True))
        cache_list.append({
            'url': next_url, 'li': next_li, 'is_folder': True,
            'info': {'mediatype': 'video'},
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
            'cm_items': [], 'resume_time': 0, 'total_time': 0
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)

    from resources.lib.tmdb_api import set_fast_cache
    set_fast_cache(cache_key, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'],
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'],
                                'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def trakt_public_lists(params):
    """Afiseaza liste publice Trakt (trending sau popular) cu descriere si paginare."""
    from resources.lib.tmdb_api import add_directory
    
    list_type = params.get('list_type', 'trending')
    page = int(params.get('page', '1'))
    
    if list_type == 'trending':
        data = trakt_api_request("/lists/trending", params={'limit': PAGE_LIMIT, 'page': page, 'extended': 'full'})
    else:
        data = trakt_api_request("/lists/popular", params={'limit': PAGE_LIMIT, 'page': page, 'extended': 'full'})
    
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', item)
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        description = lst.get('description', '')
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
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
    
    if len(data) >= PAGE_LIMIT:
        add_directory(
            f"[B]Next Page ({page+1}) >>[/B]",
            {'mode': 'trakt_public_lists', 'list_type': list_type, 'page': str(page + 1)},
            icon=NEXT_PAGE_ICON, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


def trakt_liked_lists(params=None):
    """Afiseaza listele apreciate de utilizator cu descriere."""
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
        description = lst.get('description', '')  # ✅ ADAUGAT
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        # ✅ ADAUGAT: info cu description
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
    """Cauta liste pe Trakt cu descriere si paginare."""
    from resources.lib.tmdb_api import add_directory
    
    page = int(params.get('page', '1')) if params else 1
    query = params.get('query', '') if params else ''
    
    if not query:
        dialog = xbmcgui.Dialog()
        query = dialog.input("Search list...", type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return
    
    data = trakt_api_request("/search/list", params={'query': query, 'limit': PAGE_LIMIT, 'page': page})
    
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", "No list found", TRAKT_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    for item in data:
        lst = item.get('list', {})
        name = lst.get('name', 'Unknown')
        count = lst.get('item_count', 0)
        description = lst.get('description', '')
        likes = lst.get('likes', 0)
        user = lst.get('user', {}).get('username', '')
        slug = lst.get('ids', {}).get('slug', '')
        
        if not slug or not user:
            continue
        
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
    
    if len(data) >= PAGE_LIMIT:
        add_directory(
            f"[B]Next Page ({page+1}) >>[/B]",
            {'mode': 'trakt_search_list', 'query': query, 'page': str(page + 1)},
            icon=NEXT_PAGE_ICON, folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)


# ===================== TRAKT LIST CONTENT =====================

def trakt_list_content(params):
    """Afiseaza liste Trakt Discovery (trending, popular, etc.) din SQL CU POSTERE."""
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
    
    # 2. Fallback API daca SQL e gol
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

    # Construim fake_items uniform + prefetch
    fake_items = []
    for item in paginated_items:
        if 'poster_path' in item:
            fake_items.append({
                'id': item.get('id') or item.get('tmdb_id'),
                'title': item.get('title'),
                'name': item.get('name') or item.get('title'),
                'release_date': item.get('release_date', ''),
                'first_air_date': item.get('first_air_date', ''),
                'overview': item.get('overview', ''),
                'poster_path': item.get('poster_path', '')
            })
        else:
            raw = item.get('movie') or item.get('show') or item
            tmdb_id = str(raw.get('ids', {}).get('tmdb', '') or raw.get('id', ''))
            title = raw.get('title', '') or raw.get('name', '')
            year_val = str(raw.get('year') or '')[:4]
            fake_items.append({
                'id': tmdb_id,
                'title': title if media_type == 'movies' else None,
                'name': title if media_type != 'movies' else None,
                'release_date': f"{year_val}-01-01",
                'first_air_date': f"{year_val}-01-01",
                'overview': raw.get('overview', ''),
                'poster_path': ''
            })

    prefetch_metadata_parallel([i for i in fake_items if i.get('id')], 'movie' if media_type == 'movies' else 'tv')

    cache_list = []
    items_to_add = []
    for processed_item in fake_items:
        if not processed_item.get('id'):
            continue
        if media_type == 'movies':
            processed = _process_movie_item(processed_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(processed_item, return_data=True, skip_details=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if page < total_pages:
        mode = 'build_movie_list' if media_type == 'movies' else 'build_tvshow_list'
        action = f'trakt_{media_type.rstrip("s")}_{list_type}'
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': mode, 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        items_to_add.append((next_url, next_li, True))
        cache_list.append({
            'url': next_url, 'li': next_li, 'is_folder': True,
            'info': {'mediatype': 'video'},
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
            'cm_items': [], 'resume_time': 0, 'total_time': 0
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)

    from resources.lib.tmdb_api import set_fast_cache
    cache_key2 = f"list_{media_type}_{list_type}_{page}"
    set_fast_cache(cache_key2, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'],
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'],
                                'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def trakt_list_items(params):
    """Afiseaza continutul listelor Trakt (RAM Cache + Batch Rendering)."""
    from resources.lib.tmdb_api import (
        render_from_fast_cache, get_fast_cache, set_fast_cache, 
        prefetch_metadata_parallel, _process_movie_item, _process_tv_item, get_tmdb_item_details,
        _get_cached_details
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
    
    # Determinam tipul real pentru SQL
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
    
    # Prefetch-ul este critic aici pentru History TV (unde lipsesc date in SQL)
    prefetch_metadata_parallel(paginated_items, filter_type if filter_type else 'movie')

    # API lists (public/user/liked): prefetch-ul are deadline 1.1s si poate rata
    # iteme — fetch-ul ramas CONCURRENT cu semafor (max 8 requesturi in paralel).
    # Fara semafor, 40 de thread-uri x 2 requesturi (EN + localizare) = ~80 in
    # paralel -> TMDB da rate-limit/429 -> timeout -> pagina mai LENTA, nu mai
    # rapida. Loop-ul citeste apoi doar din RAM pool (zero HTTP in randare).
    if not is_sql_data and data:
        import threading as _th
        _missing = []
        for _it in paginated_items:
            _mtype = _it.get('type', 'movie')
            _m = 'tv' if _mtype in ('show', 'season', 'episode') else 'movie'
            _raw = _it.get(_mtype, _it)
            _tid = str(_raw.get('ids', {}).get('tmdb', ''))
            if _tid and not _get_cached_details(_tid, _m):
                _missing.append((_tid, _m))
        if _missing:
            _sem = _th.Semaphore(8)
            def _fill(_t):
                try:
                    with _sem:
                        get_tmdb_item_details(_t[0], _t[1], lightweight=True)
                except Exception:
                    pass
            _ths = [_th.Thread(target=_fill, args=(t,), daemon=True) for t in _missing]
            for _t in _ths: _t.start()
            for _t in _ths: _t.join(timeout=12)

    items_to_add = []
    cache_list = []

    for item in paginated_items:
        current_media_type = 'movie'
        
        if is_sql_data:
            # Detectare tip
            row_type = item.get('media_type', '')
            # FIX HISTORY TV: Daca e history si filtrul e shows, fortam tipul TV
            if list_type == 'history' and filter_type == 'show':
                current_media_type = 'tv'
            elif row_type in ['show', 'tv', 'tvshow']:
                current_media_type = 'tv'
            
            tmdb_id = str(item.get('tmdb_id') or item.get('id', ''))
            
            # --- FIX HISTORY: Date lipsa in SQL ---
            # Daca nu avem an sau poster (cazul history tv), le luam din cache-ul proaspat descarcat de prefetch
            year_val = str(item.get('year', ''))
            poster_path = item.get('poster_path') or item.get('poster', '')

            if (not year_val or not poster_path) and tmdb_id:
                # 1. Cache-only (RAM pool + SQLite, populat de prefetch_metadata_parallel) - ZERO HTTP.
                #    Rows de watchlist au acum poster salvat direct in SQL la sync (full,images).
                meta = _get_cached_details(tmdb_id, current_media_type)
                if meta:
                    if not year_val: 
                        d = meta.get('release_date') or meta.get('first_air_date')
                        year_val = str(d)[:4] if d else ''
                    if not poster_path: 
                        poster_path = meta.get('poster_path', '')
                # 2. Fallback ONLY daca tot lipseste (randuri vechi fara poster in SQL):
                #    fetch lightweight (O singura data, salvat in SQLite de mai departe).
                if (not year_val or not poster_path) and tmdb_id:
                    meta = get_tmdb_item_details(tmdb_id, current_media_type, lightweight=True)
                    if meta:
                        if not year_val: 
                            d = meta.get('release_date') or meta.get('first_air_date')
                            year_val = str(d)[:4] if d else ''
                        if not poster_path: 
                            poster_path = meta.get('poster_path', '')

            # Construire date corecte
            release_date = f"{year_val}-01-01" if year_val else ""
            
            # Curatare poster http
            if poster_path and 'image.tmdb.org' in poster_path:
                poster_path = '/' + poster_path.split('/')[-1]

            fake_item = {
                'id': tmdb_id,
                'media_type': current_media_type,
                'title': item.get('title') if current_media_type == 'movie' else None,
                'name': item.get('title') if current_media_type == 'tv' else None, # In history TV, coloana title e numele serialului
                'poster_path': poster_path,
                'overview': item.get('overview', ''),
                'release_date': release_date,
                'first_air_date': release_date
            }
        else:
            # API Data (public/user lists, liked lists): Trakt nu trimite posterul
            # TMDb in items (images.poster e lista/dict de URL-uri Trakt, pe alt CDN
            # — _process_*_item lipeaza IMG_BASE peste orice poster_path ne-gol,
            # deci URL-urile Trakt ies 404). Posterul/backdrop-ul trebuie sa vina
            # din metadata TMDb: RAM pool/SQLite (populat de prefetch) sau
            # lightweight fetch care populeaza si pool-ul — de acolo _process_*_item
            # ia si runtime-ul real (altfel filmele arata 2:00:00, default 7200s).
            mtype = item.get('type', 'movie')
            if mtype in ['show', 'season', 'episode']: current_media_type = 'tv'
            raw = item.get(mtype, item)
            tmdb_id = str(raw.get('ids', {}).get('tmdb', ''))
            year_val = str(raw.get('year') or '')
            overview = raw.get('overview', '')

            poster_path = ''
            if tmdb_id:
                meta = _get_cached_details(tmdb_id, current_media_type)
                if not meta:
                    meta = get_tmdb_item_details(tmdb_id, current_media_type, lightweight=True) or {}
                if meta:
                    if not year_val:
                        d = meta.get('release_date') or meta.get('first_air_date')
                        year_val = str(d)[:4] if d else ''
                    poster_path = meta.get('poster_path', '') or ''
                    # Curatare poster http (daca pool-ul contine URL complet)
                    if poster_path and 'image.tmdb.org' in poster_path:
                        poster_path = '/' + poster_path.split('/')[-1]

            release_date = f"{year_val}-01-01" if year_val else ""
            fake_item = {
                'id': tmdb_id,
                'media_type': current_media_type,
                'title': raw.get('title'),
                'name': raw.get('title'),
                'poster_path': poster_path,
                'overview': overview,
                'release_date': release_date,
                'first_air_date': release_date
            }

        # Procesare finala
        processed = None
        if current_media_type == 'movie':
            processed = _process_movie_item(fake_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True, skip_details=True)

        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    # 5. Paginare si Afisare
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
            # Creeaza un item in format show pentru procesare
            seen_shows[show_id] = {
                'type': 'show',
                'show': show_data
            }
    
    return list(seen_shows.values())


# ===================== PROCESS TRAKT ITEM - MODIFICAT CU WATCHED STATUS =====================

def _process_trakt_item_with_tmdb(tmdb_id, media_type, trakt_data):
    """Proceseaza un item Trakt si il afiseaza cu metadate TMDb (Doar EN)."""
    from resources.lib.tmdb_api import add_directory, IMG_BASE, BACKDROP_BASE
    from resources.lib.cache import cache_object

    tmdb_endpoint = 'movie' if media_type == 'movie' else 'tv'

    def tmdb_worker(u):
        return requests.get(u, timeout=10)

    # Cerem datele in EN (LANG este 'en-US' din config)
    # --- MODIFICARE: Adaugat external_ids si schimbat cheia cache ---
    url = f"{BASE_URL}/{tmdb_endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}&append_to_response=external_ids"
    tmdb_data = cache_object(tmdb_worker, f"meta_ext_{media_type}_{tmdb_id}_{LANG}", url, expiration=168)
    # ---------------------------------------------------------------

    # Titlul din Trakt ca baza
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
        
        # MODIFICARE: Logica de Fallback RO -> EN a fost stearsa complet.
        # Luam direct titlul din TMDb. Acesta e garantat in engleza datorita parametrului URL.
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
        
        # Extragem metadatele din raspunsul TMDb
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

        # --- SELF HEALING: SALVAM IMAGINILE IN SQL PENTRU DATA VIITOARE ---
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
    # --- MODIFICARE: Comentat TMDB Info si Adaugat My Plays ---
    plays_params = {
        'mode': 'show_my_plays_menu',
        'tmdb_id': tmdb_id,
        'type': tmdb_endpoint,
        'title': title,
        'year': year,
        'imdb_id': imdb_id
    }

    cm = []
    if ADDON.getSetting('show_cm_trakt') != 'false':
        cm.append(('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=trakt_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})"))
    if ADDON.getSetting('show_cm_tmdb') != 'false':
        cm.append(('[B][COLOR FF00CED1]My TMDB[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=tmdb_context_menu&tmdb_id={tmdb_id}&type={tmdb_endpoint}&title={title})"))
    # ('[B][COLOR FFFDBD01]TMDB Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_info&tmdb_id={tmdb_id}&type={tmdb_endpoint})"),
    if ADDON.getSetting('show_cm_my_plays') != 'false':
        cm.append(('[B][COLOR FFFF69B4]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
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
    Trimite statusul redarii catre Trakt (start, pause, stop).
    action: 'start', 'pause', 'stop'
    """
    if not get_trakt_token():
        return

    # Endpoint-urile sunt /scrobble/start, /scrobble/pause, /scrobble/stop
    # Daca action e 'scrobble', folosim 'start' pentru a mentine activitatea (watching now)
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
        # Folosim functia existenta trakt_api_request
        trakt_api_request(url, method='POST', data=payload)
    except Exception as e:
        xbmc.log(f"[TRAKT] Scrobble error: {e}", xbmc.LOGERROR)


def trakt_favorites_list(params):
    """Afiseaza Favoritele Trakt cu paginare si threading."""
    from resources.lib.tmdb_api import add_directory, _process_movie_item, _process_tv_item, prefetch_metadata_parallel
    from resources.lib.utils import paginate_list
    
    m_type = params.get('type')
    page = int(params.get('page', '1'))
    
    data = trakt_sync.get_trakt_favorites_from_db(m_type)
    
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total_pages = paginate_list(data, page, PAGE_LIMIT)
    
    # Threading pentru viteza
    prefetch_metadata_parallel(paginated, 'movie' if m_type == 'movies' else 'tv')

    cache_list = []
    items_to_add = []
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
            processed = _process_movie_item(p_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(p_item, return_data=True, skip_details=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'trakt_favorites_list', 'type': m_type, 'page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        items_to_add.append((next_url, next_li, True))
        cache_list.append({
            'url': next_url, 'li': next_li, 'is_folder': True,
            'info': {'mediatype': 'video'},
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
            'cm_items': [], 'resume_time': 0, 'total_time': 0
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if m_type == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)

    cache_key_fav = f"trakt_fav_{m_type}_{page}"
    from resources.lib.tmdb_api import set_fast_cache
    set_fast_cache(cache_key_fav, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'],
                                    'art': i['art'], 'info': i['info'], 'cm': i['cm_items'],
                                    'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def trakt_dropped_shows_list(params):
    """Afiseaza serialele abandonate (Dropped/Hidden) cu paginare si caching."""
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
        # Construim o lista fake compatibila cu prefetch-ul
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

    # Importam functia necesara din tmdb_api pentru a o putea folosi
    from resources.lib.tmdb_api import get_tmdb_item_details

    for item in paginated_items:
        tmdb_id = item.get('id')
        if not tmdb_id: 
            continue
            
        # Extragem detaliile complete (aduse instantaneu din cache de prefetcher-ul de mai sus)
        details = get_tmdb_item_details(tmdb_id, 'tv')
        
        # Fallback de siguranta in caz ca API-ul TMDb da eroare
        if not details:
            details = item
            
        processed = _process_tv_item(details, return_data=True, skip_details=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
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


def trakt_period_dialog(params):
    from resources.lib.tmdb_api import add_directory

    list_type = params.get('list_type')
    media_type = params.get('media_type', 'movies')
    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    trakt_icon = os.path.join(icons_path, 'trakt.png')

    periods = [
        {'name': 'This Week', 'period': 'weekly'},
        {'name': 'This Month', 'period': 'monthly'},
        {'name': 'This Year', 'period': 'yearly'},
        {'name': 'All Time', 'period': 'all'},
    ]

    for p in periods:
        add_directory(p['name'],
                     {'mode': 'trakt_discovery_list', 'list_type': list_type, 'media_type': media_type, 'period': p['period']},
                     icon=trakt_icon, folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def _view_trakt_my_calendar():
    """My Calendar (stil MDB): filme + episoade din watchlist/collection, o singura pagina,
    date formatate, sortare, today on top, click pe lansat -> surse."""
    from resources.lib.tmdb_api import set_metadata, add_directory, get_smart_season_details, prefetch_metadata_parallel, get_tmdb_item_details, _get_full_context_menu
    from resources.lib.cache import ram_pool_get
    from resources.lib.mdblist_sync import get_cached, set_cached
    from resources.lib.watched_provider import is_movie_watched as _wp_is_mw, is_episode_watched as _wp_is_epw
    from resources.lib.config import calendar_localized_label, IMG_BASE, BACKDROP_BASE
    import datetime as _dt

    xbmcplugin.setContent(HANDLE, 'episodes')

    _CAL_PREV = [0, 1, 3, 7, 14, 30]
    _CAL_FUT  = [7, 14, 21, 30, 60, 90]
    try:
        prev_days = _CAL_PREV[int(ADDON.getSetting('mdblist_cal_previous_days') or 0)]
        fut_days  = _CAL_FUT[int(ADDON.getSetting('mdblist_cal_future_days') or 3)]
    except:
        prev_days, fut_days = 0, 30
    try:
        sort_asc = int(ADDON.getSetting('mdblist_cal_sort_order') or 0) == 0
    except:
        sort_asc = True
    try:
        today_top = ADDON.getSetting('mdblist_cal_today_top') != 'false'
    except:
        today_top = True

    today = _dt.date.today()
    start = today - _dt.timedelta(days=prev_days)
    total_days = prev_days + fut_days
    cache_key = f"trakt_calendar_{prev_days}_{fut_days}"

    data = get_cached(cache_key, ttl=3600)
    if data is None:
        shows_data = get_trakt_calendar_shows(start_date=start.strftime('%Y-%m-%d'), days=total_days, limit=500)
        movies_data = get_trakt_calendar_movies(start_date=start.strftime('%Y-%m-%d'), days=total_days, limit=500)
        movies_data = movies_data or []
        # Calendarul Trakt e cache-uit server-side: filmele adaugate recent in
        # watchlist pot sa apara cu intarziere. Facem merge cu watchlist-ul
        # proaspat (/sync/watchlist e mereu la zi) pentru filmele care se
        # incadreaza in fereastra calendarului.
        try:
            wl_movies = get_trakt_watchlist('movies') or []
            existing = set()
            for m in movies_data:
                try:
                    if isinstance(m, dict):
                        mid = m.get('movie', {}).get('ids', {}) or {}
                        tid = str(mid.get('tmdb', ''))
                        if tid:
                            existing.add(tid)
                except Exception:
                    continue
            end_date = start + _dt.timedelta(days=total_days)
            # Calendarul Trakt e cache-uit server-side, dar merge-ul trebuie
            # sa respecte fereastra configurata (past days): fara extindere de
            # 60 de zile in trecut, altfel filmele deja lansate din watchlist
            # apareau oricat de mic ar fi fost past days.
            merge_start = start
            for wl_item in wl_movies:
                try:
                    if not isinstance(wl_item, dict): continue
                    movie = wl_item.get('movie', {}) or {}
                    if not isinstance(movie, dict): movie = {}
                    wl_tmdb = str((movie.get('ids', {}) or {}).get('tmdb', ''))
                    if not wl_tmdb or wl_tmdb == 'None' or wl_tmdb in existing: continue
                    released = (movie.get('released', '') or '')[:10]
                    if not released: continue
                    try:
                        parts = released.split('-')
                        rdate = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
                    except Exception:
                        continue
                    if not (merge_start <= rdate <= end_date): continue
                    existing.add(wl_tmdb)
                    movies_data.append({'released': released, 'movie': movie})
                except Exception:
                    continue
        except Exception:
            pass
        data = {'shows': shows_data or [], 'movies': movies_data}
        set_cached(cache_key, data)

    shows_list = data.get('shows', []) or []
    movies_list = data.get('movies', []) or []

    raw_items = []
    seen_ids = set()
    for item in movies_list:
        try:
            if not isinstance(item, dict): continue
            movie = item.get('movie', {}) or {}
            if not isinstance(movie, dict): movie = {}
            ids = movie.get('ids', {}) or {}
            if not isinstance(ids, dict): ids = {}
            tmdb_id = str(ids.get('tmdb', ''))
            if not tmdb_id or tmdb_id == 'None': continue
            air_date = (item.get('released', '') or '')[:10]
            movie_img = movie.get('images') or {}
            if not isinstance(movie_img, dict): movie_img = {}
            poster_obj = movie_img.get('poster') or {}
            backdrop_obj = movie_img.get('fanart') or {}
            if not isinstance(poster_obj, dict): poster_obj = {}
            if not isinstance(backdrop_obj, dict): backdrop_obj = {}
            raw_items.append({
                'media_type': 'movie', 'tmdb_id': tmdb_id, 'title': movie.get('title', '') or 'Unknown',
                'air_date': air_date, 'plot': movie.get('overview', '') or '',
                'poster': poster_obj.get('medium', '') or '',
                'backdrop': backdrop_obj.get('full', '') or '',
                'season': 0, 'episode': 0, 'ep_title': ''
            })
        except Exception:
            continue
    for item in shows_list:
        try:
            if not isinstance(item, dict): continue
            episode = item.get('episode', {}) or {}
            if not isinstance(episode, dict): episode = {}
            show = item.get('show', {}) or {}
            if not isinstance(show, dict): show = {}
            show_ids = show.get('ids', {}) or {}
            if not isinstance(show_ids, dict): show_ids = {}
            tmdb_id = str(show_ids.get('tmdb', ''))
            if not tmdb_id or tmdb_id == 'None': continue
            s_num = int(episode.get('season', 0) or 0)
            ep_num = int(episode.get('number', 0) or 0)
            dedup = (tmdb_id, s_num, ep_num)
            if dedup in seen_ids: continue
            seen_ids.add(dedup)
            air_date = (item.get('first_aired', '') or '')[:10]
            show_img = show.get('images') or {}
            if not isinstance(show_img, dict): show_img = {}
            poster_obj = show_img.get('poster') or {}
            backdrop_obj = show_img.get('fanart') or {}
            if not isinstance(poster_obj, dict): poster_obj = {}
            if not isinstance(backdrop_obj, dict): backdrop_obj = {}
            raw_items.append({
                'media_type': 'tv', 'tmdb_id': tmdb_id, 'title': show.get('title', '') or 'Unknown',
                'air_date': air_date, 'plot': episode.get('overview', '') or show.get('overview', '') or '',
                'poster': poster_obj.get('medium', '') or '',
                'backdrop': backdrop_obj.get('full', '') or '',
                'season': s_num, 'episode': ep_num, 'ep_title': episode.get('title', '') or ''
            })
        except Exception:
            continue

    if not raw_items:
        add_directory("[COLOR gray]No calendar events in this range[/COLOR]", {'mode': 'noop'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    fake_items = [{'id': i['tmdb_id'], 'media_type': i['media_type']} for i in raw_items]
    prefetch_metadata_parallel(fake_items, 'tv')

    ep_overview_map = {}
    ep_title_map = {}
    ep_keys_seen = set()
    for it in raw_items:
        if it['media_type'] != 'tv' or not it['season']: continue
        key = (it['tmdb_id'], it['season'])
        if key in ep_keys_seen: continue
        ep_keys_seen.add(key)
        try:
            details = get_smart_season_details(it['tmdb_id'], it['season'])
            if details:
                for ep in details.get('episodes', []):
                    ep_num = ep.get('episode_number', 0)
                    overview = ep.get('overview', '')
                    if overview:
                        ep_overview_map[(it['tmdb_id'], it['season'], ep_num)] = overview
                    ep_name = (ep.get('name') or '').strip()
                    if ep_name and not re.match(r'^[A-Za-z\u00c0-\u024f]+\s+\d+$', ep_name):
                        ep_title_map[(it['tmdb_id'], it['season'], ep_num)] = ep_name
        except Exception:
            pass

    def _format_cal_date(raw_date):
        if not raw_date:
            return '', 'white', 999
        try:
            parts = str(raw_date).split('T')[0].split('-')
            d = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
            diff = (d - today).days
            ds = f'{parts[2]}.{parts[1]}.{parts[0]}'
            if diff == -1 or diff <= -2:
                color = 'FF00FA9A'
            elif diff == 0:
                color = 'white'
            else:
                color = 'yellow'
            return calendar_localized_label(diff, ds), color, diff
        except Exception:
            return str(raw_date)[:10], 'white', 999

    items_to_add = []
    for it in raw_items:
        cal_date, date_color, diff = _format_cal_date(it['air_date'])
        cached = ram_pool_get(it['tmdb_id'])
        poster_url = it['poster']
        if not poster_url and cached:
            pp = cached.get('poster_path', '')
            if pp:
                poster_url = f"{IMG_BASE}{pp}"
        fanart_url = it['backdrop']
        if not fanart_url and cached:
            bd = cached.get('backdrop_path', '')
            if bd:
                fanart_url = f"{BACKDROP_BASE}{bd}"
        details = None
        if not poster_url:
            try:
                details = get_tmdb_item_details(it['tmdb_id'], 'movie' if it['media_type'] == 'movie' else 'tv', lightweight=True) or {}
            except Exception:
                details = {}
            if not poster_url and details.get('poster_path'):
                poster_url = f"{IMG_BASE}{details['poster_path']}"
            if not fanart_url and details.get('backdrop_path'):
                fanart_url = f"{BACKDROP_BASE}{details['backdrop_path']}"

        if it['media_type'] == 'movie':
            movie_year = str(it['air_date'])[:4] if it['air_date'] else ''
            display_title = f'{it["title"]} ({movie_year})' if movie_year else it['title']
            label = f'[B][COLOR FFFF6600]{display_title}[/COLOR][/B]'
            if cal_date:
                if cal_date in ('Azi', 'Maine'):
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
                else:
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
            li = xbmcgui.ListItem(label=label)
            li.setProperty('cal_diff', str(diff))
            movie_plot = ''
            if cached:
                movie_plot = cached.get('overview', '') or ''
            if not movie_plot:
                movie_plot = it['plot']
            if not movie_plot and details:
                movie_plot = details.get('overview', '') or ''
            set_metadata(li, {'mediatype': 'movie', 'title': it['title'], 'plot': movie_plot},
                         unique_ids={'tmdb': it['tmdb_id']}, watched_info=_wp_is_mw(it['tmdb_id']))
            art = {'icon': TRAKT_ICON, 'thumb': poster_url or TRAKT_ICON}
            if poster_url: art['poster'] = poster_url
            if fanart_url: art['fanart'] = fanart_url
            li.setArt(art)
            cm = _get_full_context_menu(it['tmdb_id'], 'movie', it['title'], year=movie_year)
            if cm: li.addContextMenuItems(cm)
            if diff <= 0:
                url_params = {'mode': 'sources', 'tmdb_id': it['tmdb_id'], 'type': 'movie', 'title': it['title']}
            else:
                url_params = {'mode': 'extended_info', 'tmdb_id': it['tmdb_id'], 'type': 'movie'}
            url = f"{sys.argv[0]}?{urlencode(url_params)}"
            items_to_add.append((url, li, False))
        else:
            ep_title = it['ep_title']
            if not ep_title or ep_title.strip().upper() in ('TBA', 'TBD', 'TO BE ANNOUNCED'):
                ep_title = ep_title_map.get((it['tmdb_id'], it['season'], it['episode']), '') or ep_title
            label = f'[B][COLOR pink]{it["title"]}[/COLOR][/B] - [B][COLOR {date_color}]S{it["season"]:02d}E{it["episode"]:02d}[/COLOR][/B]'
            if ep_title:
                label += f' - [B][I][COLOR FFCCCCFF]{ep_title}[/I][/COLOR][/B]'
            if cal_date:
                if cal_date in ('Azi', 'Maine'):
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
                else:
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
            li = xbmcgui.ListItem(label=label)
            li.setProperty('cal_diff', str(diff))
            ep_plot = ep_overview_map.get((it['tmdb_id'], it['season'], it['episode']), '') or it['plot']
            if not ep_plot and cached:
                ep_plot = cached.get('overview', '') or ''
            if not ep_plot and details:
                ep_plot = details.get('overview', '') or ''
            set_metadata(li, {'mediatype': 'episode', 'title': ep_title, 'tvshowtitle': it['title'],
                              'season': it['season'], 'episode': it['episode'], 'plot': ep_plot},
                         unique_ids={'tmdb': it['tmdb_id']}, watched_info=_wp_is_epw(it['tmdb_id'], it['season'], it['episode']))
            art = {'icon': TRAKT_ICON, 'thumb': poster_url or TRAKT_ICON}
            if poster_url: art['poster'] = poster_url
            if fanart_url: art['fanart'] = fanart_url
            li.setArt(art)
            cm = _get_full_context_menu(it['tmdb_id'], 'episode', it['title'], season=it['season'], episode=it['episode'])
            b_show_params = urlencode({'mode': 'details', 'tmdb_id': it['tmdb_id'], 'type': 'tv', 'title': it['title']})
            cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_show_params})"))
            b_season_params = urlencode({'mode': 'episodes', 'tmdb_id': it['tmdb_id'], 'season': str(it['season']), 'tv_show_title': it['title']})
            cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_season_params})"))
            clear_p_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': it['tmdb_id'], 'type': 'tv',
                                        'season': str(it['season']), 'episode': str(it['episode']),
                                        'title': f"{it['title']} S{it['season']:02d}E{it['episode']:02d}"})
            cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
            if cm: li.addContextMenuItems(cm)
            if diff <= 0:
                url_params = {'mode': 'sources', 'tmdb_id': it['tmdb_id'], 'type': 'tv', 'season': str(it['season']),
                              'episode': str(it['episode']), 'title': f'{it["title"]} S{it["season"]:02d}E{it["episode"]:02d}',
                              'tv_show_title': it['title']}
                is_folder = False
            else:
                url_params = {'mode': 'episodes', 'tmdb_id': it['tmdb_id'], 'season': str(it['season']), 'tv_show_title': it['title']}
                is_folder = True
            url = f"{sys.argv[0]}?{urlencode(url_params)}"
            items_to_add.append((url, li, is_folder))

    if today_top:
        today_items = [(u, li, f) for u, li, f in items_to_add if li.getProperty('cal_diff') == '0']
        other_items = [(u, li, f) for u, li, f in items_to_add if li.getProperty('cal_diff') != '0']
        if sort_asc:
            other_items.sort(key=lambda x: int(x[1].getProperty('cal_diff') or 0))
        else:
            other_items.sort(key=lambda x: int(x[1].getProperty('cal_diff') or 0), reverse=True)
        items_to_add = today_items + other_items
    else:
        if sort_asc:
            items_to_add.sort(key=lambda x: int(x[1].getProperty('cal_diff') or 0))
        else:
            items_to_add.sort(key=lambda x: int(x[1].getProperty('cal_diff') or 0), reverse=True)

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)


def trakt_calendar_menu(params):
    from resources.lib.tmdb_api import add_directory

    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    trakt_icon = os.path.join(icons_path, 'trakt.png')
    tv_icon = os.path.join(icons_path, 'tv.png')
    movies_icon = os.path.join(icons_path, 'movies.png')
    calendar_items = [
        {'name': 'My Calendar', 'icon': trakt_icon, 'calendar_type': 'my_combined', 'days': '30'},
        {'name': 'TV Episodes Airing This Week', 'icon': tv_icon, 'calendar_type': 'all/shows', 'days': '7'},
        {'name': 'My TV Episodes Airing This Week', 'icon': trakt_icon, 'calendar_type': 'my/shows', 'days': '7'},
        {'name': 'New Show Premieres', 'icon': tv_icon, 'calendar_type': 'all/shows/new', 'days': '30'},
        {'name': 'Season Premieres', 'icon': tv_icon, 'calendar_type': 'all/shows/premieres', 'days': '30'},
        {'name': 'My Season Premieres', 'icon': trakt_icon, 'calendar_type': 'my/shows/premieres', 'days': '30'},
        {'name': 'Movie Premieres', 'icon': movies_icon, 'calendar_type': 'all/movies', 'days': '30'},
    ]

    for item in calendar_items:
        cal_params = {'mode': 'trakt_calendar', 'calendar_type': item['calendar_type'], 'days': item.get('days', '30')}
        add_directory(item['name'], cal_params, icon=item['icon'], folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def trakt_calendar(params):
    from resources.lib.tmdb_api import render_from_fast_cache, get_fast_cache, set_fast_cache, _process_movie_item, add_directory, get_tmdb_item_details, TMDbmovies_ICON, prefetch_metadata_parallel, get_smart_season_details
    from resources.lib.config import PAGE_LIMIT, calendar_localized_label
    import datetime

    calendar_type = params.get('calendar_type', 'all/movies')
    if calendar_type == 'my_combined':
        _view_trakt_my_calendar()
        return
    page = int(params.get('page', '1'))
    days = int(params.get('days', '30'))
    is_movie = '/movies' in calendar_type or calendar_type.startswith('my/movies')

    cache_key = f"trakt_calendar_{calendar_type}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    data = get_trakt_calendar(calendar_type, days=days)

    if not data or not isinstance(data, list):
        add_directory("[COLOR gray]No calendar data available (connect Trakt?)[/COLOR]", {'mode': 'noop'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    raw_items = []
    for item in data:
        try:
            if not isinstance(item, dict): continue
            if is_movie:
                raw = item.get('movie', {})
                if not isinstance(raw, dict): raw = {}
                ids = raw.get('ids') or {}
                if not isinstance(ids, dict): ids = {}
                tmdb_id = str(ids.get('tmdb', ''))
                if not tmdb_id or tmdb_id == 'None': continue
                raw_items.append({
                    'id': int(tmdb_id),
                    'title': raw.get('title', ''),
                    'name': raw.get('title', ''),
                    'release_date': (item.get('released', '') or '')[:10],
                    'first_air_date': '',
                    'overview': raw.get('overview', ''),
                    'poster_path': raw.get('poster_path', '') or '',
                    'media_type': 'movie'
                })
            else:
                episode = item.get('episode', {})
                if not isinstance(episode, dict): episode = {}
                show = item.get('show', {})
                if not isinstance(show, dict): show = {}
                show_ids = show.get('ids') or {}
                if not isinstance(show_ids, dict): show_ids = {}
                tmdb_id = str(show_ids.get('tmdb', ''))
                if not tmdb_id or tmdb_id == 'None': continue
                show_title = show.get('title', '')
                ep_num = episode.get('number', 0)
                season_num = episode.get('season', 0)
                if int(season_num or 0) <= 0:
                    continue
                ep_title = episode.get('title', '')
                air_date = (item.get('first_aired', '') or '')[:10]
                raw_items.append({
                    'id': int(tmdb_id),
                    'show_title': show_title,
                    'ep_num': ep_num,
                    'season_num': season_num,
                    'ep_title': ep_title,
                    'air_date': air_date,
                    'title': f"{show_title} - S{season_num:02d}E{ep_num:02d} - {ep_title}",
                    'name': show_title,
                    'release_date': air_date,
                    'first_air_date': (show.get('first_air_date', '') or '')[:10],
                    'overview': episode.get('overview', show.get('overview', '')),
                    'poster_path': '',
                    'media_type': 'tv'
                })
        except:
            continue

    if not raw_items:
        if is_movie:
            add_directory(f"[COLOR gray]No movie releases in the next {days} days[/COLOR]", {'mode': 'noop'}, folder=False)
        else:
            add_directory(f"[COLOR gray]No episodes in the next {days} days[/COLOR]", {'mode': 'noop'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated_items, total_pages = paginate_list(raw_items, page, PAGE_LIMIT)

    prefetch_metadata_parallel(paginated_items, 'movie' if is_movie else 'tv')

    items_to_add = []
    cache_list = []

    for item in paginated_items:
        try:
            if is_movie:
                processed = _process_movie_item(item, return_data=True, skip_details=False)
                if processed:
                    items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
                    cache_list.append(processed)
            else:
                tv_id = str(item.get('id', ''))
            show_title = item.get('show_title', item.get('name', ''))
            ep_num = int(item.get('ep_num', 0))
            season_num = int(item.get('season_num', 0))
            ep_title = item.get('ep_title', '')
            if not ep_title or ep_title.strip().upper() in ('TBA', 'TBD', 'TO BE ANNOUNCED'):
                try:
                    if tv_id and season_num:
                        details = get_smart_season_details(tv_id, season_num)
                        if details:
                            for ep in details.get('episodes', []):
                                if ep.get('episode_number') == ep_num:
                                    ep_name = (ep.get('name') or '').strip()
                                    if ep_name and not re.match(r'^[A-Za-z\u00c0-\u024f]+\s+\d+$', ep_name):
                                        ep_title = ep_name
                                    break
                except Exception:
                    pass
            air_date = item.get('air_date', item.get('release_date', ''))
            overview = item.get('overview', '')

            display_label = f"{show_title} - S{season_num:02d}E{ep_num:02d} - {ep_title}"
            if air_date:
                try:
                    ad = str(air_date)[:10]
                    parts = ad.split('-')
                    ep_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                    today = datetime.date.today()
                    diff_d = (ep_date - today).days
                    if 0 <= diff_d <= 1:
                        label = calendar_localized_label(diff_d, '')
                        date_label = f"[B][COLOR white]({label})[/COLOR][/B]"
                    else:
                        date_label = f"[B][COLOR white]({parts[2]}.{parts[1]}.{parts[0]})[/COLOR][/B]"
                    if ep_date == today or ep_date == today + datetime.timedelta(days=1):
                        display_label = f"{display_label} {date_label}"
                    elif ep_date > today:
                        display_label = f"[B][COLOR FFE238EC]{display_label}[/COLOR] {date_label}"
                    else:
                        display_label = f"{display_label} {date_label}"
                except:
                    display_label = f"{display_label} [B][COLOR white]({air_date})[/COLOR][/B]"

            poster = TMDbmovies_ICON
            details = get_tmdb_item_details(tv_id, 'tv')
            if details:
                pp = details.get('poster_path', '')
                if pp:
                    poster = f"https://image.tmdb.org/t/p/w500{pp}"

            info = {
                'mediatype': 'tvshow',
                'title': display_label,
                'tvshowtitle': show_title,
                'episode': ep_num,
                'season': season_num,
                'plot': overview,
                'premiered': air_date
            }
            if details and details.get('mpaa'):
                info['mpaa'] = details['mpaa']

            url_params = {'mode': 'details', 'tmdb_id': tv_id, 'type': 'tv', 'title': show_title}
            url = f"{sys.argv[0]}?{urlencode(url_params)}"
            li = xbmcgui.ListItem(display_label)
            li.setArt({'icon': poster, 'thumb': poster, 'poster': poster})
            try:
                _tag = li.getVideoInfoTag()
                _tag.setMediaType('tvshow')
                _tag.setTitle(str(display_label))
                _tag.setTVShowTitle(str(show_title))
                if ep_num:
                    _tag.setEpisode(int(ep_num))
                if season_num:
                    _tag.setSeason(int(season_num))
                if overview:
                    _tag.setPlot(str(overview))
                if air_date:
                    _tag.setPremiered(str(air_date))
                if details and details.get('mpaa'):
                    _tag.setMpaa(str(details['mpaa']))
            except:
                pass

            items_to_add.append((url, li, True))
            cache_list.append({
                'url': url, 'li': li, 'is_folder': True,
                'info': info, 'art': {'icon': poster, 'thumb': poster, 'poster': poster},
                'cm_items': [], 'label': display_label
            })
        except:
            continue

    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'trakt_calendar', 'calendar_type': calendar_type, 'page': str(page + 1), 'days': str(days)}
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

    xbmcplugin.setContent(HANDLE, 'movies' if is_movie else 'tvshows')
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


def trakt_account_info():
    """Afiseaza informatii despre contul Trakt intr-un dialog text."""
    try:
        settings_data = trakt_api_request('/users/settings')
        if not settings_data or 'user' not in settings_data:
            xbmcgui.Dialog().notification('[B][COLOR pink]Trakt[/COLOR][/B]', 'Failed to load account info', TRAKT_ICON, 3000, False)
            return
        user = settings_data['user']
        account = settings_data.get('account', {})
        username = user.get('username', 'N/A')
        private = user.get('private', False)
        vip = user.get('vip', False)
        vip_years = user.get('vip_years', 0)
        timezone = account.get('timezone', 'N/A')
        joined = user.get('joined_at', '')
        if joined:
            try:
                joined = joined.replace('T', ' ').replace('Z', '')[:10]
                parts = joined.split('-')
                if len(parts) == 3:
                    joined = f'{parts[2]}.{parts[1]}.{parts[0]}'
            except:
                pass

        stats = trakt_api_request(f"/users/{user['ids']['slug']}/stats")
        
        def label(text):
            return f'[B][COLOR pink]{text}[/COLOR][/B]'

        def val(v):
            return f'[B]{v}[/B]'

        def section(text):
            return f'[B][COLOR FFFDBD01]{text}[/COLOR][/B]'

        body = []
        body.append(f'{label("Username:")} {val(username)}')
        body.append(f'{label("Private:")} {val(private)}')
        body.append(f'{label("Timezone:")} {val(timezone)}')
        if vip:
            body.append(f'{label("VIP:")} {val(f"Yes ({vip_years} years)")}')
        else:
            body.append(f'{label("VIP:")} {val("No")}')
        body.append(f'{label("Joined:")} {val(joined)}')

        # --- LIMITE CONT (din /users/settings) ---
        limits = settings_data.get('limits', {})
        wl_lim = (limits.get('watchlist') or {}).get('item_count')
        lst_lim = (limits.get('list') or {}).get('item_count')
        lst_cnt = (limits.get('list') or {}).get('count')
        fav_lim = (limits.get('favorites') or {}).get('item_count')
        col_lim = (limits.get('collection') or {}).get('item_count')
        rec_lim = (limits.get('recommendations') or {}).get('item_count')

        # Utilizare curenta watchlist din DB locala (instant, offline)
        wl_now = 0
        try:
            from resources.lib import trakt_sync
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM trakt_lists WHERE list_type='watchlist'")
            wl_now = c.fetchone()[0]
            conn.close()
        except: pass

        body.append('')
        body.append(section('--- Limits ---'))
        if wl_lim:
            body.append(f'  Watchlist: {val(f"{wl_now}/{wl_lim}")} items (movies + shows)')
        if lst_cnt and lst_lim:
            body.append(f'  Personal Lists: {val(f"{lst_cnt} lists / {lst_lim} items each")}')
        if fav_lim:
            body.append(f'  Favorites: {val(fav_lim)}')
        if col_lim:
            body.append(f'  Collection: {val(col_lim)}')
        if rec_lim:
            body.append(f'  Recommendations: {val(rec_lim)}')

        if stats:
            movies = stats.get('movies', {})
            shows = stats.get('shows', {})
            episodes = stats.get('episodes', {})
            ratings = stats.get('ratings', {})

            body.append('')
            body.append(section('--- Movies ---'))
            body.append(f'  Collected: {val(movies.get("collected", 0))}  |  Watched: {val(movies.get("watched", 0))}  |  Hours: {val(movies.get("minutes", 0) // 60)}')
            
            body.append(section('--- Shows ---'))
            body.append(f'  Collected: {val(shows.get("collected", 0))}  |  Watched: {val(shows.get("watched", 0))}')
            
            body.append(section('--- Episodes ---'))
            body.append(f'  Watched: {val(episodes.get("watched", 0))}  |  Hours: {val(episodes.get("minutes", 0) // 60)}')
            
            body.append(section('--- Ratings ---'))
            body.append(f'  Total given: {val(ratings.get("total", 0))}')

        text = '\n'.join(body)
        xbmcgui.Dialog().textviewer('[B][COLOR pink]TRAKT ACCOUNT INFO[/COLOR][/B]', text)
    except Exception as e:
        log(f"[TRAKT] Account info error: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('[B][COLOR pink]Trakt[/COLOR][/B]', f'Error: {e}', TRAKT_ICON, 3000, False)
