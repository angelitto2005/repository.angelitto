# Library Export Module — .strm + .nfo generator for Kodi library integration
import xbmc, xbmcvfs, xbmcgui, xbmcaddon
import os, json, time, threading
from urllib.parse import quote
from resources.lib.config import ADDON, ADDON_PATH
from resources.lib.utils import read_json, write_json

ADDON_ID = 'plugin.video.tmdbmovies'
BASE_URL = 'plugin://plugin.video.tmdbmovies/'
LIBRARY_ROOT_NAME = "Library"
TMDB_URL = 'https://www.themoviedb.org'
LIBRARY_SETTINGS_FILE = 'library_settings.json'
_LAST_SYNC_FMT = '%d-%m-%Y %H:%M'

def _parse_last_sync(val):
    """Parse last_sync value — handles both float (old) and 'YYYY-MM-DD HH:MM' string (new)."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return time.mktime(time.strptime(str(val), _LAST_SYNC_FMT))
    except Exception:
        return 0.0

# =============================================================================
# TMDb SHOW DATA CACHE (avoids re-fetching API for already-exported shows)
# =============================================================================
_TVSHOW_CACHE_FILE = 'tvshow_data_cache.json'
_TVSHOW_CACHE_TTL = 86400  # 24 hours

def _get_tvshow_cache_path():
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    return os.path.join(profile, _TVSHOW_CACHE_FILE).replace('\\', '/')

def _load_tvshow_cache():
    return read_json(_get_tvshow_cache_path()) or {}

def _save_tvshow_cache(data):
    write_json(_get_tvshow_cache_path(), data)

def _get_cached_tvshow_data(tmdb_id):
    """Get cached show data or return None if expired/missing."""
    cache = _load_tvshow_cache()
    entry = cache.get(str(tmdb_id))
    if not entry:
        return None
    if (time.time() - entry.get('ts', 0)) > _TVSHOW_CACHE_TTL:
        return None
    return entry.get('data')

def _set_cached_tvshow_data(tmdb_id, data):
    """Cache show data with current timestamp."""
    cache = _load_tvshow_cache()
    cache[str(tmdb_id)] = {'ts': time.time(), 'data': data}
    _save_tvshow_cache(cache)

TMDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')

# Status codes
STATUS_OK = 0
STATUS_SKIP = 1
STATUS_ERROR = 2

def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f'[TMDbM Library] {msg}', level)

# =============================================================================
# FILE WRITER
# =============================================================================
def _make_path(path):
    if not path:
        return None
    try:
        path = xbmcvfs.translatePath(path)
    except:
        pass
    try:
        os.makedirs(path, exist_ok=True)
    except:
        pass
    try:
        xbmcvfs.mkdirs(path)
    except:
        pass
    return path

def _write_file(content, filepath, filename):
    path = _make_path(filepath)
    if not path:
        return False
    full = os.path.join(path, filename).replace('\\', '/')
    try:
        f = xbmcvfs.File(full, 'w')
        f.write(content)
        f.close()
        return True
    except Exception as e:
        log(f'Write failed {full}: {e}', xbmc.LOGERROR)
        return False

def _validify_filename(name):
    keep = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_()[],&'
    result = ''.join(c if c in keep else '_' for c in name)
    while '__' in result:
        result = result.replace('__', '_')
    return result.strip('._ ')

# =============================================================================
# LIBRARY ROOT PATH
# =============================================================================
def _get_library_root():
    parent = ADDON.getSetting('library_dest_path')
    if not parent:
        profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        parent = profile.replace('\\', '/')
    else:
        try:
            parent = xbmcvfs.translatePath(parent)
        except:
            pass
    parent = parent.rstrip('/\\')
    for suffix in ('Kodi Library', 'Library'):
        if parent.endswith(suffix):
            parent = parent[:-len(suffix)].rstrip('/\\')
            break
    root = os.path.join(parent, LIBRARY_ROOT_NAME).replace('\\', '/')
    log(f'Library root: {root}')
    return root

def browse_destination():
    parent = ADDON.getSetting('library_dest_path')
    if not parent:
        profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        parent = profile.replace('\\', '/')
    else:
        try:
            parent = xbmcvfs.translatePath(parent)
        except:
            pass
    picked = xbmcgui.Dialog().browse(3,
                                      '[B][COLOR FF6AFB92]Library Destination[/COLOR][/B]\nChoose parent folder — "Library" will be created inside',
                                      'files',
                                      mask='',
                                      useThumbs=False,
                                      treatAsFolder=True,
                                      defaultt=parent)
    if not picked:
        return
    ADDON.setSetting('library_dest_path', picked.rstrip('/\\'))
    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                    f'Parent set to:\n{picked}\nLibrary will be created inside',
                                   ADDON_ICON, 5000)

# =============================================================================
# SETTINGS PERSISTENCE
# =============================================================================
def _get_settings_path():
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    return os.path.join(profile, LIBRARY_SETTINGS_FILE).replace('\\', '/')

def _load_lib_settings():
    path = _get_settings_path()
    data = read_json(path)
    if data and isinstance(data, dict):
        return data
    return {}

def _save_lib_settings(data):
    path = _get_settings_path()
    write_json(path, data)

def get_selected_tmdb_lists():
    s = _load_lib_settings()
    return s.get('tmdb_selected_lists', [])

def save_selected_tmdb_lists(list_ids):
    s = _load_lib_settings()
    s['tmdb_selected_lists'] = list_ids
    _save_lib_settings(s)

def get_selected_trakt_lists():
    s = _load_lib_settings()
    return s.get('trakt_selected_lists', [])

def save_selected_trakt_lists(list_ids):
    s = _load_lib_settings()
    s['trakt_selected_lists'] = list_ids
    _save_lib_settings(s)

# =============================================================================
# URL BUILDERS
# =============================================================================
def _build_strm_url_movie(tmdb_id, title, year):
    params = f'mode=sources&tmdb_id={tmdb_id}&type=movie&title={quote(title)}'
    if year:
        params += f'&year={year}'
    return BASE_URL + '?' + params

def _build_strm_url_episode(tmdb_id, season, episode, title, show_title):
    params = (f'mode=sources&tmdb_id={tmdb_id}&type=tv&season={season}'
              f'&episode={episode}&title={quote(title)}&tv_show_title={quote(show_title)}')
    return BASE_URL + '?' + params

def _build_nfo_content(tmdb_type, tmdb_id):
    return f'{TMDB_URL}/{tmdb_type}/{tmdb_id}'

# =============================================================================
# NAME HELPERS
# =============================================================================
def _get_movie_name(title, year):
    name = f'{title} ({year})' if year else title
    return _validify_filename(name)

def _get_show_name(title, year):
    name = f'{title} ({year})' if year else title
    return _validify_filename(name)

def _get_episode_strm_name(season, episode, ep_title):
    name = f'S{int(season):02d}E{int(episode):02d} - {ep_title}'
    return _validify_filename(name) + '.strm'

# =============================================================================
# MEDIA EXPORTERS
# =============================================================================
def export_movie(basedir, tmdb_id, title, year):
    folder = _get_movie_name(title, year)
    filepath = os.path.join(basedir, folder).replace('\\', '/')
    nfo = _build_nfo_content('movie', tmdb_id)
    nfo_full = os.path.join(filepath, 'movie.nfo').replace('\\', '/')
    if os.path.exists(nfo_full):
        try:
            with open(nfo_full, 'r', encoding='utf-8') as f:
                if str(tmdb_id) in f.read():
                    return STATUS_SKIP
        except:
            pass
    strm = _build_strm_url_movie(tmdb_id, title, year)
    ok_nfo = _write_file(nfo, filepath, 'movie.nfo')
    ok_strm = _write_file(strm, filepath, 'movie.strm')
    if ok_nfo and ok_strm:
        return STATUS_OK
    log(f'Failed to export movie: {title} ({year})')
    return STATUS_ERROR

def export_tvshow(basedir, tmdb_id, title, year, seasons_data):
    folder = _get_show_name(title, year)
    show_path = os.path.join(basedir, folder).replace('\\', '/')
    nfo = _build_nfo_content('tv', tmdb_id)
    nfo_full = os.path.join(show_path, 'tvshow.nfo').replace('\\', '/')
    nfo_exists = False
    if os.path.exists(nfo_full):
        try:
            with open(nfo_full, 'r', encoding='utf-8') as f:
                if str(tmdb_id) in f.read():
                    nfo_exists = True
        except:
            pass
    if not nfo_exists:
        if not _write_file(nfo, show_path, 'tvshow.nfo'):
            log(f'Failed to write tvshow.nfo for: {title}')
            return STATUS_ERROR
    ep_count = 0
    for season_num, episodes in seasons_data.items():
        season_folder = f'Season {int(season_num):d}'
        season_path = os.path.join(show_path, season_folder).replace('\\', '/')
        for ep in episodes:
            ep_title = ep.get('name') or ep.get('title') or f'Episode {ep["episode"]}'
            ep_filename = _get_episode_strm_name(season_num, ep['episode'], ep_title)
            ep_path = os.path.join(season_path, ep_filename).replace('\\', '/')
            if os.path.exists(ep_path):
                continue
            strm = _build_strm_url_episode(tmdb_id, season_num, ep['episode'],
                                           ep_title, title)
            if _write_file(strm, season_path, ep_filename):
                ep_count += 1
    return STATUS_OK if ep_count > 0 else STATUS_SKIP

# =============================================================================
# TMDb API FETCHERS (lightweight, inline to avoid circular imports)
# =============================================================================
def _tmdb_request(endpoint, params=None):
    import requests
    from resources.lib.config import API_KEY
    url = f'https://api.themoviedb.org/3{endpoint}'
    p = {'api_key': API_KEY, 'language': 'en-US'}
    if params:
        p.update(params)
    try:
        r = requests.get(url, params=p, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f'TMDB request error: {e}')
    return None

def _tmdb_v4_request(endpoint):
    import requests
    from resources.lib.tmdb_api import get_tmdb_v4_token
    token = get_tmdb_v4_token()
    if not token:
        return None
    url = f'https://api.themoviedb.org/4{endpoint}'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f'TMDB v4 request error: {e}')
    return None

def get_tmdb_session():
    from resources.lib.tmdb_api import get_tmdb_session as _gts
    return _gts()

def get_tmdb_account_lists():
    session = get_tmdb_session()
    if not session:
        return []
    account_id = session.get('account_id')
    sid = session.get('session_id')
    if not sid:
        return []
    all_lists = []
    page = 1
    while True:
        data = _tmdb_request(f'/account/{account_id}/lists', {'session_id': sid, 'page': page})
        if not data or 'results' not in data:
            break
        results = data.get('results', [])
        if not results:
            break
        all_lists.extend(results)
        if page >= data.get('total_pages', 1):
            break
        page += 1
    return all_lists

def get_tmdb_list_items(list_id):
    items = []
    page = 1
    while True:
        data = _tmdb_request(f'/list/{list_id}', {'page': page, 'language': 'en-US'})
        if not data or 'items' not in data:
            break
        items.extend(data['items'])
        if page >= data.get('total_pages', 1):
            break
        page += 1
    return items

def get_tmdb_watchlist_items(media_type):
    session = get_tmdb_session()
    if not session:
        return []
    account_id = session['account_id']
    sid = session['session_id']
    endpoint = f'/account/{account_id}/watchlist/{media_type}'
    items = []
    page = 1
    while True:
        data = _tmdb_request(endpoint, {'session_id': sid, 'page': page, 'language': 'en-US'})
        if not data or 'results' not in data:
            break
        items.extend(data['results'])
        if page >= data.get('total_pages', 1):
            break
        page += 1
    return items

def get_tmdb_favorites_items(media_type):
    session = get_tmdb_session()
    if not session:
        return []
    account_id = session['account_id']
    sid = session['session_id']
    endpoint = f'/account/{account_id}/favorite/{media_type}'
    items = []
    page = 1
    while True:
        data = _tmdb_request(endpoint, {'session_id': sid, 'page': page, 'language': 'en-US'})
        if not data or 'results' not in data:
            break
        items.extend(data['results'])
        if page >= data.get('total_pages', 1):
            break
        page += 1
    return items

def get_tvshow_seasons_episodes(tmdb_id):
    cached = _get_cached_tvshow_data(tmdb_id)
    if cached is not None:
        return cached
    data = _tmdb_request(f'/tv/{tmdb_id}', {'append_to_response': 'content_ratings,external_ids'})
    if not data:
        return None, None
    title = data.get('name') or data.get('original_name', '')
    year = data.get('first_air_date', '')[:4]
    seasons_data = {}
    for season in data.get('seasons', []):
        sn = season.get('season_number')
        if sn is None or sn == 0:
            continue
        ep_data = _tmdb_request(f'/tv/{tmdb_id}/season/{sn}', {'language': 'en-US'})
        if not ep_data or 'episodes' not in ep_data:
            continue
        episodes = []
        for ep in ep_data['episodes']:
            episodes.append({
                'episode': ep.get('episode_number'),
                'name': ep.get('name', ''),
                'still_path': ep.get('still_path', ''),
            })
        if episodes:
            seasons_data[sn] = episodes
    result = (title, year, seasons_data)
    _set_cached_tvshow_data(tmdb_id, result)
    return result

# =============================================================================
# TRAKT API HELPERS (thin wrappers around trakt_api to avoid circular imports)
# =============================================================================

def _trakt_get_username():
    from resources.lib.trakt_api import get_trakt_username
    return get_trakt_username()

def _trakt_request(endpoint, params=None):
    from resources.lib.trakt_api import trakt_api_request
    return trakt_api_request(endpoint, params=params)

def _trakt_paginated(endpoint, params=None):
    from resources.lib.trakt_api import _get_trakt_paginated_list
    return _get_trakt_paginated_list(endpoint, params=params)

def _get_trakt_watchlist_items(media_type):
    from resources.lib.trakt_api import _get_trakt_paginated_list
    return _get_trakt_paginated_list(f'/sync/watchlist/{media_type}', {'extended': 'full'}) or []

def _get_trakt_favorites_items(media_type):
    from resources.lib.trakt_api import _get_trakt_paginated_list
    all_items = _get_trakt_paginated_list('/sync/favorites', {'extended': 'full'}) or []
    return [item for item in all_items if item.get('type') == media_type]

def _get_trakt_list_items_paginated(slug, username):
    from resources.lib.trakt_api import _get_trakt_paginated_list
    return _get_trakt_paginated_list(f'/users/{username}/lists/{slug}/items', {'extended': 'full'}) or []

def _get_trakt_user_lists():
    from resources.lib.trakt_api import get_trakt_user_lists
    return get_trakt_user_lists() or []

# =============================================================================
# PROGRESS DIALOG
# =============================================================================
ADDON_ICON = os.path.join(ADDON_PATH, 'icon.png')

def _notify(msg, time=3000):
    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', msg, ADDON_ICON, time)

# =============================================================================
# MAIN SYNC ENGINE
# =============================================================================
def sync_library(force=False):
    log('Library sync started')
    enabled = ADDON.getSetting('library_enabled') == 'true'
    if not enabled and not force:
        _notify('Library export is disabled in settings')
        return
    
    dest = _get_library_root()
    
    if not _make_path(dest):
        _notify('Cannot create destination folder', 5000)
        return
    
    session = get_tmdb_session()
    if not session:
        _notify('TMDb account not connected. Go to Accounts tab.', 5000)
        return
    
    threading.Thread(target=_run_sync, args=(dest,), daemon=True).start()
    _notify('Library sync started in background...', 2000)

def _sync_watched_to_kodi():
    log('Syncing watched status to Kodi library...')
    import json as _json

    # ── Read watched data from Trakt local DB ──
    try:
        from resources.lib import trakt_sync as _ts
        conn = _ts.get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id, title, year, last_watched_at FROM trakt_watched_movies")
        watched_movies = [dict(r) for r in c.fetchall()]
        c.execute("SELECT tmdb_id, season, episode, title, last_watched_at FROM trakt_watched_episodes ORDER BY tmdb_id")
        watched_eps = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception as e:
        log(f'Cannot read watched data: {e}', xbmc.LOGWARNING)
        return

    if not watched_movies and not watched_eps:
        log('No watched items to sync')
        return

    # ── Fetch Kodi library (with playcount + lastplayed to skip already-watched) ──
    try:
        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies",
               "params": {"properties": ["uniqueid", "title", "year", "playcount", "lastplayed"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        kodi_movies = {}
        kodi_watched_tids = set()
        kodi_movie_lp = {}
        for m in res.get('result', {}).get('movies', []):
            uid = m.get('uniqueid', {})
            tid = str(uid.get('tmdb', ''))
            if not tid:
                continue
            kodi_movies.setdefault(tid, []).append(m['movieid'])
            if m.get('playcount', 0) >= 1:
                kodi_watched_tids.add(tid)
            kodi_movie_lp[m['movieid']] = m.get('lastplayed', '')

        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows",
               "params": {"properties": ["uniqueid", "title"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        kodi_shows = {}
        for s in res.get('result', {}).get('tvshows', []):
            uid = s.get('uniqueid', {})
            tid = str(uid.get('tmdb', ''))
            if not tid:
                continue
            kodi_shows.setdefault(tid, []).append(s)
    except Exception as e:
        log(f'Cannot fetch Kodi library: {e}', xbmc.LOGERROR)
        return

    # ── Batch update playcounts + lastplayed ──
    batch = []
    batch_id = 0

    def _trakt_ts_to_kodi(ts):
        if not ts:
            return None
        try:
            return ts[:19].replace('T', ' ')
        except:
            return None

    # ── Movies: new watched + backfill missing lastplayed ──
    for wm in watched_movies:
        tid = wm['tmdb_id']
        kids = kodi_movies.get(tid, [])
        lp = _trakt_ts_to_kodi(wm.get('last_watched_at'))
        if tid not in kodi_watched_tids:
            for kid in kids:
                batch_id += 1
                params = {"movieid": kid, "playcount": 1}
                if lp:
                    params["lastplayed"] = lp
                batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetMovieDetails",
                               "params": params, "id": batch_id})
        elif lp:
            for kid in kids:
                if not kodi_movie_lp.get(kid):
                    batch_id += 1
                    batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetMovieDetails",
                                   "params": {"movieid": kid, "lastplayed": lp}, "id": batch_id})

    from collections import defaultdict
    eps_by_show = defaultdict(list)
    for we in watched_eps:
        eps_by_show[we['tmdb_id']].append(we)

    for tmdb_id, eps_list in eps_by_show.items():
        shows = kodi_shows.get(tmdb_id, [])
        if not shows:
            continue
        for s in shows:
            try:
                req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes",
                       "params": {"tvshowid": s['tvshowid'],
                                  "properties": ["season", "episode", "playcount", "lastplayed"]},
                       "id": 1}
                res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
                kodi_eps = res.get('result', {}).get('episodes', [])
                kodi_ep_map = {}
                kodi_ep_lp = {}
                watched_ep_keys = set()
                for e in kodi_eps:
                    key = (e['season'], e['episode'])
                    kodi_ep_map.setdefault(key, []).append(e['episodeid'])
                    kodi_ep_lp[key] = e.get('lastplayed', '')
                    if e.get('playcount', 0) >= 1:
                        watched_ep_keys.add(key)
                for we in eps_list:
                    key = (we['season'], we['episode'])
                    lp = _trakt_ts_to_kodi(we.get('last_watched_at'))
                    eids = kodi_ep_map.get(key, [])
                    if key not in watched_ep_keys:
                        for eid in eids:
                            batch_id += 1
                            params = {"episodeid": eid, "playcount": 1}
                            if lp:
                                params["lastplayed"] = lp
                            batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails",
                                           "params": params, "id": batch_id})
                    elif lp and not kodi_ep_lp.get(key):
                        for eid in eids:
                            batch_id += 1
                            batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails",
                                           "params": {"episodeid": eid, "lastplayed": lp}, "id": batch_id})
            except:
                continue

    # ── Send ALL items in one single JSON-RPC batch (no chunking, no sleep) ──
    # Chunking + sleep(100) caused N flickers: each sleep let Kodi GUI process
    # OnVideoLibraryChanged notifications → container refresh → screen flicker.
    # Single batch = notifications queue up and fire all at once = 1 flicker.
    if not batch:
        log('No items to update in Kodi library')
        return
    start_t = time.time()
    try:
        resp = _json.loads(xbmc.executeJSONRPC(_json.dumps(batch)))
        total_ok = sum(1 for r in (resp if isinstance(resp, list) else []) if r.get('result') == 'OK')
    except Exception as e:
        log(f'Batch error: {e}', xbmc.LOGWARNING)
        total_ok = 0
    elapsed = time.time() - start_t
    log(f'Watched sync: {total_ok}/{len(batch)} items updated in {elapsed:.2f}s')


def _sync_kodi_watched_to_addon():
    """Reverse sync: reads playcount from Kodi library, writes to addon DB, syncs new items to Trakt."""
    import json as _json
    import threading
    import traceback
    from resources.lib import trakt_sync as _ts
    log('Reverse syncing Kodi watched status to addon DB...')

    # Ultimul sync timestamp (0 = first ever sync → skip Trakt)
    s = _load_lib_settings()
    last_sync = _parse_last_sync(s.get('last_sync', 0))
    log(f'Reverse sync last_sync={last_sync}')

    conn = None
    try:
        conn = _ts.get_connection()
        c = conn.cursor()
    except Exception as e:
        log(f'Reverse sync connection error: {e}\n{traceback.format_exc()}', xbmc.LOGERROR)
        return
    trakt_movies = []
    trakt_eps = []
    try:
        # ── Movies ──
        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies",
               "params": {"properties": ["uniqueid", "title", "year", "playcount", "lastplayed"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        for m in res.get('result', {}).get('movies', []):
            if m.get('playcount', 0) < 1:
                continue
            uid = m.get('uniqueid', {})
            tid = str(uid.get('tmdb', '')) or str(uid.get('default', ''))
            if not tid:
                continue
            # Check if already in Trakt DB before writing
            c.execute("SELECT last_watched_at FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            existing = c.fetchone()
            already_synced = existing and existing[0]
            lp_val = m.get('lastplayed') or None
            if lp_val:
                if already_synced:
                    # UPDATE only — preserves poster/backdrop/overview
                    c.execute("UPDATE trakt_watched_movies SET last_watched_at=?, title=?, year=? WHERE tmdb_id=?",
                              (lp_val, m.get('title', ''), str(m.get('year', '')), tid))
                else:
                    c.execute("INSERT OR IGNORE INTO trakt_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                              (tid, m.get('title', ''), str(m.get('year', '')), lp_val))
            elif not already_synced:
                c.execute("INSERT OR IGNORE INTO trakt_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,NULL)",
                          (tid, m.get('title', ''), str(m.get('year', ''))))
            # Only send to Trakt if NOT already in DB (truly new movie)
            if not already_synced and last_sync > 0:
                lp = m.get('lastplayed', '')
                if lp:
                    lp_ts = _parse_lastplayed(lp)
                    if lp_ts is not None and lp_ts > last_sync:
                        trakt_movies.append(tid)

        # ── TV Episodes ──
        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows",
               "params": {"properties": ["uniqueid", "title"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        for sh in res.get('result', {}).get('tvshows', []):
            uid = sh.get('uniqueid', {})
            tid = str(uid.get('tmdb', '')) or str(uid.get('default', ''))
            if not tid:
                continue
            ep_req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes",
                      "params": {"tvshowid": sh['tvshowid'],
                                 "properties": ["season", "episode", "playcount", "title", "lastplayed"],
                                 "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}},
                      "id": 1}
            ep_res = _json.loads(xbmc.executeJSONRPC(_json.dumps(ep_req)))
            for ep in ep_res.get('result', {}).get('episodes', []):
                lp_val = ep.get('lastplayed') or None
                s_num = ep.get('season', 0)
                e_num = ep.get('episode', 0)
                # Check if already in Trakt DB before writing
                c.execute("SELECT last_watched_at FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                           (tid, s_num, e_num))
                existing = c.fetchone()
                already_synced = existing and existing[0]
                if lp_val:
                    c.execute("INSERT OR REPLACE INTO trakt_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)",
                              (tid, s_num, e_num,
                               f"{sh.get('title', '')} - S{s_num:02d}E{e_num:02d}",
                               lp_val))
                elif not already_synced:
                    c.execute("INSERT OR IGNORE INTO trakt_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,NULL)",
                              (tid, s_num, e_num,
                               f"{sh.get('title', '')} - S{s_num:02d}E{e_num:02d}"))
                # Only send to Trakt if NOT already in DB (truly new episode)
                if not already_synced and last_sync > 0:
                    lp = ep.get('lastplayed', '')
                    if lp:
                        lp_ts = _parse_lastplayed(lp)
                        if lp_ts is not None and lp_ts > last_sync:
                            trakt_eps.append((tid, s_num, e_num))
        conn.commit()
        c.execute("SELECT COUNT(*) FROM trakt_watched_movies")
        mc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM trakt_watched_episodes")
        ec = c.fetchone()[0]
        msg = f'Reverse sync: {mc}m {ec}e in DB'
        if trakt_movies or trakt_eps:
            msg += f', {len(trakt_movies)}m {len(trakt_eps)}e to Trakt'
            threading.Thread(target=_sync_to_trakt, args=(trakt_movies, trakt_eps), daemon=True).start()
        log(msg)
    except Exception as e:
        log(f'Reverse sync error: {e}\n{traceback.format_exc()}', xbmc.LOGERROR)
    finally:
        if conn:
            conn.close()


def _parse_lastplayed(lp_str):
    """Parse Kodi lastplayed string to unix timestamp. Tries multiple formats."""
    import datetime as _dt
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(lp_str, fmt).timestamp()
        except ValueError:
            continue
    return None

def _sync_to_trakt(movies, episodes):
    """Sync items to Trakt (called in background thread)."""
    from resources.lib.trakt_sync import sync_single_watched_to_trakt
    log(f'Syncing {len(movies)} movies and {len(episodes)} episodes to Trakt...')
    for tid in movies:
        try:
            sync_single_watched_to_trakt(tid, 'movie')
        except Exception as e:
            log(f'Trakt sync error for movie {tid}: {e}', xbmc.LOGWARNING)
    for tid, season, episode in episodes:
        try:
            sync_single_watched_to_trakt(tid, 'episode', season, episode)
        except Exception as e:
            log(f'Trakt sync error for episode {tid} S{season}E{episode}: {e}', xbmc.LOGWARNING)
    log('Trakt sync done')

def _run_sync(dest):
    pbg = xbmcgui.DialogProgressBG()
    pbg.create('', 'Preparing...')
    try:
        _do_sync(dest, pbg)
    except Exception as e:
        log(f'Sync error: {e}', xbmc.LOGERROR)
    finally:
        pbg.close()
    
    # Tot ce urmează (UpdateLibrary + watched sync) într-un thread separat
    threading.Thread(target=_run_post_sync, daemon=True).start()

def _run_post_sync():
    import traceback as _tb
    # 1. Mai întâi watched sync (DB-ul Kodi e liber — niciun scanner activ)
    try:
        _sync_watched_to_kodi()
    except Exception as e:
        log(f'Watched sync error: {e}\n{_tb.format_exc()}', xbmc.LOGWARNING)
    try:
        _sync_kodi_watched_to_addon()
    except Exception as e:
        log(f'Kodi->addon watched sync error: {e}\n{_tb.format_exc()}', xbmc.LOGWARNING)

    # 2. Abia apoi pornește scanarea .strm-urilor (în fundal, fără lock)
    try:
        xbmc.executebuiltin('UpdateLibrary(video)')
    except:
        pass

    # Salvează timestamp-ul ultimului sync
    now_ts = time.time()
    try:
        s = _load_lib_settings()
        s['last_sync'] = time.strftime(_LAST_SYNC_FMT, time.localtime(now_ts))
        _save_lib_settings(s)
        ADDON.setSetting('library_last_sync', time.strftime(_LAST_SYNC_FMT, time.localtime(now_ts)))
    except:
        pass
    
    log('Library sync completed')
    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                   'Library sync completed',
                                   ADDON_ICON, 3000)

def _do_sync(dest, pbg):
    tmdb_selected = get_selected_tmdb_lists()
    trakt_selected = get_selected_trakt_lists()
    all_selected = tmdb_selected + trakt_selected
    if not all_selected:
        pbg.update(0, '', 'No lists selected — use Select Lists to Export first')
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                       'No lists selected',
                                       ADDON_ICON, 3000)
        return
    
    total = len(all_selected)
    for idx, sid in enumerate(all_selected):
        pct = int((idx + 1) / total * 100)
        # TMDb built-in
        if sid == '_wl_movies':
            pbg.update(pct, 'TMDB Watchlist Movies', '')
            _export_watchlist_movies(dest, pbg, 'TMDB Watchlist Movies')
        elif sid == '_wl_tv':
            pbg.update(pct, 'TMDB Watchlist TV', '')
            _export_watchlist_tv(dest, pbg, 'TMDB Watchlist TV')
        elif sid == '_fav_movies':
            pbg.update(pct, 'TMDB Favorites Movies', '')
            _export_favorites_movies(dest, pbg, 'TMDB Favorites Movies')
        elif sid == '_fav_tv':
            pbg.update(pct, 'TMDB Favorites TV', '')
            _export_favorites_tv(dest, pbg, 'TMDB Favorites TV')
        # Trakt built-in
        elif sid == '_trakt_wl_movies':
            pbg.update(pct, 'Trakt Watchlist Movies', '')
            _export_trakt_watchlist_movies(dest, pbg, 'Trakt Watchlist Movies')
        elif sid == '_trakt_wl_tv':
            pbg.update(pct, 'Trakt Watchlist TV', '')
            _export_trakt_watchlist_tv(dest, pbg, 'Trakt Watchlist TV')
        elif sid == '_trakt_fav_movies':
            pbg.update(pct, 'Trakt Favorites Movies', '')
            _export_trakt_favorites_movies(dest, pbg, 'Trakt Favorites Movies')
        elif sid == '_trakt_fav_tv':
            pbg.update(pct, 'Trakt Favorites TV', '')
            _export_trakt_favorites_tv(dest, pbg, 'Trakt Favorites TV')
        # TMDb custom lists
        elif sid.startswith('_tmdb_'):
            continue
        elif sid.startswith('_trakt_'):
            continue
        elif sid.startswith('_'):
            continue
        else:
            # Try TMDb custom list first
            lists_data = get_tmdb_account_lists()
            found = False
            for lst in lists_data:
                if str(lst.get('id')) == sid:
                    name = lst.get('name', f'List {sid}')
                    pbg.update(pct, name, '')
                    _export_custom_list(dest, lst['id'], name, pbg, name)
                    found = True
                    break
            if not found:
                # Try Trakt custom list
                trakt_lists = _get_trakt_user_lists()
                for lst in trakt_lists:
                    if lst.get('ids', {}).get('slug', '') == sid or str(lst.get('ids', {}).get('trakt', '')) == sid:
                        name = lst.get('name', f'List {sid}')
                        slug = lst.get('ids', {}).get('slug', '')
                        pbg.update(pct, name, '')
                        _export_trakt_custom_list(dest, slug, name, pbg, name)
                        break

def _export_watchlist_movies(dest, pbg, hdg):
    base = os.path.join(dest, 'TMDb Lists', 'TMDB Watchlist Movies').replace('\\', '/')
    items = get_tmdb_watchlist_items('movies')
    for item in items:
        tid = item.get('id')
        title = item.get('title') or item.get('original_title', '')
        year = (item.get('release_date') or '')[:4]
        if tid and title:
            result = export_movie(base, tid, title, year)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Added: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_watchlist_tv(dest, pbg, hdg):
    base = os.path.join(dest, 'TMDb Lists', 'TMDB Watchlist TV').replace('\\', '/')
    items = get_tmdb_watchlist_items('tv')
    for item in items:
        tid = item.get('id')
        show_data = get_tvshow_seasons_episodes(tid)
        if not show_data:
            continue
        title, year, seasons = show_data
        if tid and title and seasons:
            result = export_tvshow(base, tid, title, year, seasons)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Updated: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_favorites_movies(dest, pbg, hdg):
    base = os.path.join(dest, 'TMDb Lists', 'TMDB Favorites Movies').replace('\\', '/')
    items = get_tmdb_favorites_items('movies')
    for item in items:
        tid = item.get('id')
        title = item.get('title') or item.get('original_title', '')
        year = (item.get('release_date') or '')[:4]
        if tid and title:
            result = export_movie(base, tid, title, year)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Added: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_favorites_tv(dest, pbg, hdg):
    base = os.path.join(dest, 'TMDb Lists', 'TMDB Favorites TV').replace('\\', '/')
    items = get_tmdb_favorites_items('tv')
    for item in items:
        tid = item.get('id')
        show_data = get_tvshow_seasons_episodes(tid)
        if not show_data:
            continue
        title, year, seasons = show_data
        if tid and title and seasons:
            result = export_tvshow(base, tid, title, year, seasons)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Updated: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_custom_list(dest, list_id, list_name, pbg, hdg):
    items = get_tmdb_list_items(list_id)
    safe_name = _validify_filename(list_name)
    base = os.path.join(dest, 'TMDb Lists', safe_name).replace('\\', '/')
    for item in items:
        tid = item.get('id')
        mtype = item.get('media_type', '')
        title = item.get('title') or item.get('original_title', '')
        year = (item.get('release_date') or '')[:4]
        if mtype == 'movie' and tid and title:
            result = export_movie(base, tid, title, year)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Added: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')
        elif mtype == 'tv' and tid:
            show_data = get_tvshow_seasons_episodes(tid)
            if show_data:
                stitle, syear, seasons = show_data
                result = export_tvshow(base, tid, stitle, syear, seasons)
                if result == STATUS_OK:
                    pbg.update(-1, hdg, f'Updated: {stitle} ({syear})')
                elif result == STATUS_SKIP:
                    pbg.update(-1, hdg, f'Already in library: {stitle} ({syear})')

# =============================================================================
# TRAKT EXPORT FUNCTIONS
# =============================================================================
def _export_trakt_watchlist_movies(dest, pbg, hdg):
    base = os.path.join(dest, 'Trakt Lists', 'Trakt Watchlist Movies').replace('\\', '/')
    items = _get_trakt_watchlist_items('movies')
    for item in items:
        m = item.get('movie') or item
        tid = str((m.get('ids') or {}).get('tmdb', ''))
        if not tid or tid == 'None':
            continue
        title = m.get('title', '')
        year = str(m.get('year', ''))
        if tid and title:
            result = export_movie(base, tid, title, year)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Added: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_trakt_watchlist_tv(dest, pbg, hdg):
    base = os.path.join(dest, 'Trakt Lists', 'Trakt Watchlist TV').replace('\\', '/')
    items = _get_trakt_watchlist_items('shows')
    for item in items:
        s = item.get('show') or item
        tid = str((s.get('ids') or {}).get('tmdb', ''))
        if not tid or tid == 'None':
            continue
        show_data = get_tvshow_seasons_episodes(tid)
        if not show_data:
            continue
        title, year, seasons = show_data
        if tid and title and seasons:
            result = export_tvshow(base, tid, title, year, seasons)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Updated: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_trakt_favorites_movies(dest, pbg, hdg):
    base = os.path.join(dest, 'Trakt Lists', 'Trakt Favorites Movies').replace('\\', '/')
    items = _get_trakt_favorites_items('movie')
    for item in items:
        m = item.get('movie') or item
        tid = str((m.get('ids') or {}).get('tmdb', ''))
        if not tid or tid == 'None':
            continue
        title = m.get('title', '')
        year = str(m.get('year', ''))
        if tid and title:
            result = export_movie(base, tid, title, year)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Added: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_trakt_favorites_tv(dest, pbg, hdg):
    base = os.path.join(dest, 'Trakt Lists', 'Trakt Favorites TV').replace('\\', '/')
    items = _get_trakt_favorites_items('show')
    for item in items:
        s = item.get('show') or item
        tid = str((s.get('ids') or {}).get('tmdb', ''))
        if not tid or tid == 'None':
            continue
        show_data = get_tvshow_seasons_episodes(tid)
        if not show_data:
            continue
        title, year, seasons = show_data
        if tid and title and seasons:
            result = export_tvshow(base, tid, title, year, seasons)
            if result == STATUS_OK:
                pbg.update(-1, hdg, f'Updated: {title} ({year})')
            elif result == STATUS_SKIP:
                pbg.update(-1, hdg, f'Already in library: {title} ({year})')

def _export_trakt_custom_list(dest, slug, list_name, pbg, hdg):
    username = _trakt_get_username()
    if not username:
        return
    items = _get_trakt_list_items_paginated(slug, username)
    safe_name = _validify_filename(list_name)
    base = os.path.join(dest, 'Trakt Lists', safe_name).replace('\\', '/')
    for item in items:
        item_type = item.get('type', '')
        if item_type == 'movie':
            m = item.get('movie', {})
            tid = str((m.get('ids') or {}).get('tmdb', ''))
            if not tid or tid == 'None':
                continue
            title = m.get('title', '')
            year = str(m.get('year', ''))
            if tid and title:
                result = export_movie(base, tid, title, year)
                if result == STATUS_OK:
                    pbg.update(-1, hdg, f'Added: {title} ({year})')
                elif result == STATUS_SKIP:
                    pbg.update(-1, hdg, f'Already in library: {title} ({year})')
        elif item_type == 'show':
            s = item.get('show', {})
            tid = str((s.get('ids') or {}).get('tmdb', ''))
            if not tid or tid == 'None':
                continue
            show_data = get_tvshow_seasons_episodes(tid)
            if not show_data:
                continue
            title, year, seasons = show_data
            if tid and title and seasons:
                result = export_tvshow(base, tid, title, year, seasons)
                if result == STATUS_OK:
                    pbg.update(-1, hdg, f'Updated: {title} ({year})')
                elif result == STATUS_SKIP:
                    pbg.update(-1, hdg, f'Already in library: {title} ({year})')

# =============================================================================
# LIBRARY CHECK / REMOVE (for dynamic context menu)
# =============================================================================
def is_in_library(tmdb_id, media_type=None):
    if not tmdb_id:
        return False
    dest = _get_library_root()
    search = str(tmdb_id)
    for sub in ('Local Movies', 'Local TV Shows'):
        base = os.path.join(dest, sub).replace('\\', '/')
        if not os.path.exists(base):
            continue
        try:
            dirs = os.listdir(base)
        except:
            continue
        for d in dirs:
            nfo_name = 'tvshow.nfo' if sub == 'Local TV Shows' else 'movie.nfo'
            nfo = os.path.join(base, d, nfo_name).replace('\\', '/')
            try:
                with open(nfo, 'r', encoding='utf-8') as f:
                    if search in f.read():
                        return True
            except:
                pass
    return False


# =============================================================================
# ADD SINGLE ITEM TO LIBRARY (context menu)
# =============================================================================
def add_to_library(tmdb_id, media_type, title=None, year=None, season=None, episode=None):
    xbmc.log(f'[TMDbM Library DBG] add_to_library: tmdb_id={tmdb_id}, type={media_type}, title={title}, year={year}', xbmc.LOGINFO)
    dest = _get_library_root()
    if not _make_path(dest):
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                      'Cannot create destination folder',
                                      xbmcgui.NOTIFICATION_ERROR)
        return
    
    if media_type == 'movie':
        basedir = os.path.join(dest, 'Local Movies').replace('\\', '/')
        if not title:
            data = _tmdb_request(f'/movie/{tmdb_id}')
            if data:
                title = data.get('title') or data.get('original_title', '')
                year = (data.get('release_date') or '')[:4]
        if title:
            result = export_movie(basedir, tmdb_id, title, year)
            if result == STATUS_OK:
                xbmc.executebuiltin('UpdateLibrary(video)')
                xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                               f'[B][COLOR yellow]{title}[/COLOR][/B] added to library',
                                               ADDON_ICON)
            elif result == STATUS_SKIP:
                xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                               f'[B][COLOR yellow]{title}[/COLOR][/B] already in library',
                                               ADDON_ICON)
    elif media_type == 'tv':
        basedir = os.path.join(dest, 'Local TV Shows').replace('\\', '/')
        xbmc.log(f'[TMDbM Library DBG] add_to_library TV: basedir={basedir}, fetching show_data for tmdb_id={tmdb_id}', xbmc.LOGINFO)
        show_data = get_tvshow_seasons_episodes(tmdb_id)
        xbmc.log(f'[TMDbM Library DBG] add_to_library TV: show_data={show_data is not None}', xbmc.LOGINFO)
        if show_data:
            title, year, seasons = show_data
            xbmc.log(f'[TMDbM Library DBG] add_to_library TV: title={title}, year={year}, seasons_count={len(seasons) if seasons else 0}', xbmc.LOGINFO)
            if title and seasons:
                result = export_tvshow(basedir, tmdb_id, title, year, seasons)
                xbmc.log(f'[TMDbM Library DBG] add_to_library TV: export result={result}', xbmc.LOGINFO)
                if result == STATUS_OK:
                    xbmc.executebuiltin('UpdateLibrary(video)')
                    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                                   f'[B][COLOR yellow]{title}[/COLOR][/B] added to library',
                                                   ADDON_ICON)
                elif result == STATUS_SKIP:
                    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                                   f'[B][COLOR yellow]{title}[/COLOR][/B] already in library',
                                                   ADDON_ICON)
            else:
                xbmc.log(f'[TMDbM Library DBG] add_to_library TV: SKIP - title or seasons empty', xbmc.LOGINFO)
        else:
            xbmc.log(f'[TMDbM Library DBG] add_to_library TV: SKIP - show_data is None', xbmc.LOGINFO)

# =============================================================================
# SELECT LISTS DIALOG (unified TMDb + Trakt)
# =============================================================================
BUILTIN_LISTS = [
    ('_wl_movies', 'TMDB Watchlist Movies', 0),
    ('_wl_tv', 'TMDB Watchlist TV', 0),
    ('_fav_movies', 'TMDB Favorites Movies', 0),
    ('_fav_tv', 'TMDB Favorites TV', 0),
]

TRAKT_BUILTIN_LISTS = [
    ('_trakt_wl_movies', 'Trakt Watchlist Movies', 0),
    ('_trakt_wl_tv', 'Trakt Watchlist TV', 0),
    ('_trakt_fav_movies', 'Trakt Favorites Movies', 0),
    ('_trakt_fav_tv', 'Trakt Favorites TV', 0),
]

def select_tmdb_lists_dialog():
    lists = get_tmdb_account_lists()
    trakt_lists = _get_trakt_user_lists()

    tmdb_selected = set(get_selected_tmdb_lists())
    trakt_selected = set(get_selected_trakt_lists())

    def _build_separator(label, color='FF00CED1'):
        li = xbmcgui.ListItem(f"[B][COLOR {color}]───── {label} ─────[/COLOR][/B]")
        li.setLabel2('')
        li.setArt({'thumb': '', 'icon': '', 'poster': ''})
        li.setProperty('is_separator', 'true')
        return li

    def build_items():
        items = []
        item_data = []

        # ── TMDB section ──
        items.append(_build_separator('TMDB', 'FF00CED1'))
        item_data.append(None)

        for sid, label, _ in BUILTIN_LISTS:
            styled = f"[B]{label}[/B]" if sid not in tmdb_selected else f"[B][COLOR FF00CED1]{label}[/COLOR][/B]"
            li = xbmcgui.ListItem(styled)
            li.setLabel2('')
            li.setArt({'thumb': TMDB_ICON, 'icon': TMDB_ICON, 'poster': TMDB_ICON})
            items.append(li)
            item_data.append((sid, 'tmdb'))

        for lst in (lists or []):
            lid = str(lst.get('id', ''))
            name = lst.get('name', f'List {lid}')
            styled = f"[B]{name}[/B]" if lid not in tmdb_selected else f"[B][COLOR FF00CED1]{name}[/COLOR][/B]"
            li = xbmcgui.ListItem(styled)
            count = lst.get('item_count', 0)
            li.setLabel2(f"[B][COLOR yellow]{count}[/COLOR][/B] items")
            li.setArt({'thumb': TMDB_ICON, 'icon': TMDB_ICON, 'poster': TMDB_ICON})
            items.append(li)
            item_data.append((lid, 'tmdb'))

        # ── Trakt section ──
        items.append(_build_separator('Trakt', 'pink'))
        item_data.append(None)

        for sid, label, _ in TRAKT_BUILTIN_LISTS:
            styled = f"[B]{label}[/B]" if sid not in trakt_selected else f"[B][COLOR pink]{label}[/COLOR][/B]"
            li = xbmcgui.ListItem(styled)
            li.setLabel2('')
            li.setArt({'thumb': TRAKT_ICON, 'icon': TRAKT_ICON, 'poster': TRAKT_ICON})
            items.append(li)
            item_data.append((sid, 'trakt'))

        for lst in (trakt_lists or []):
            slug = lst.get('ids', {}).get('slug', '')
            lid = slug or str(lst.get('ids', {}).get('trakt', ''))
            name = lst.get('name', f'List {slug or lid}')
            styled = f"[B]{name}[/B]" if lid not in trakt_selected else f"[B][COLOR pink]{name}[/COLOR][/B]"
            li = xbmcgui.ListItem(styled)
            count = lst.get('item_count', 0)
            li.setLabel2(f"[B][COLOR yellow]{count}[/COLOR][/B] items")
            li.setArt({'thumb': TRAKT_ICON, 'icon': TRAKT_ICON, 'poster': TRAKT_ICON})
            items.append(li)
            item_data.append((lid, 'trakt'))

        return items, item_data

    dialog = xbmcgui.Dialog()
    while True:
        items, item_data = build_items()
        ret = dialog.select("[B][COLOR yellow]Select Lists to Export[/COLOR][/B]", items, useDetails=True)
        if ret < 0:
            break
        if ret >= len(item_data):
            continue
        entry = item_data[ret]
        if entry is None:
            continue
        sid, source = entry
        if source == 'tmdb':
            if sid in tmdb_selected:
                tmdb_selected.discard(sid)
            else:
                tmdb_selected.add(sid)
        else:
            if sid in trakt_selected:
                trakt_selected.discard(sid)
            else:
                trakt_selected.add(sid)

    s = _load_lib_settings()
    s['tmdb_selected_lists'] = list(tmdb_selected)
    s['trakt_selected_lists'] = list(trakt_selected)
    _save_lib_settings(s)

    total = len(tmdb_selected) + len(trakt_selected)
    if total:
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                       f'[B][COLOR yellow]{total} list(s)[/COLOR][/B] selected',
                                       ADDON_ICON)
    else:
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                       'No lists selected',
                                       ADDON_ICON)

# =============================================================================
# AUTO-SYNC (called from service)
# =============================================================================
_LAST_SYNC_CHECK = 0

def check_auto_sync(startup=False):
    """Check if library auto-sync should trigger.
    startup=True: at Kodi startup, also catch up if target hour already passed today.
    """
    global _LAST_SYNC_CHECK
    now = time.time()
    if not startup and now - _LAST_SYNC_CHECK < 600:
        return
    _LAST_SYNC_CHECK = now
    
    enabled = ADDON.getSetting('library_enabled') == 'true'
    auto = ADDON.getSetting('library_auto_sync') == 'true'
    if not enabled or not auto:
        return
    
    interval = ADDON.getSetting('library_auto_interval')
    hours = {'0': 24, '1': 168}.get(interval, 24)
    
    hour_idx = ADDON.getSetting('library_auto_hour')
    try:
        target_hour = int(hour_idx)
    except:
        target_hour = 2
    current_hour = time.localtime().tm_hour
    
    s = _load_lib_settings()
    last = _parse_last_sync(s.get('last_sync', 0))
    already_synced_today = (now - last) < 24 * 3600 and time.localtime(last).tm_yday == time.localtime(now).tm_yday
    
    if current_hour == target_hour:
        # Normal trigger: exact hour match — sync if not already synced today
        if not already_synced_today:
            log('Auto-sync triggered (hour match)')
            threading.Thread(target=sync_library, daemon=True).start()
    elif startup and current_hour > target_hour and not already_synced_today:
        # Startup catch-up: Kodi started after target hour, no sync today yet
        log(f'Auto-sync triggered (startup catch-up, target={target_hour}:00, current={current_hour}:00)')
        threading.Thread(target=sync_library, daemon=True).start()

def clear_library():
    root = _get_library_root()
    inp = xbmcgui.Dialog().input('[B][COLOR red]Clear Library[/COLOR][/B]\nType "[B]Clear all[/B]" to confirm deletion:',
                                  type=xbmcgui.INPUT_ALPHANUM)
    if inp != 'Clear all':
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                       'Cancelled — type "[B]Clear all[/B]" to confirm',
                                       xbmcgui.NOTIFICATION_WARNING)
        return
    success = False
    try:
        success = xbmcvfs.rmdir(root, force=True)
    except:
        pass
    if not success:
        try:
            import shutil
            shutil.rmtree(root)
            success = True
        except:
            pass
    if success:
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                       'All library files deleted',
                                       ADDON_ICON)
    else:
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                       f'Not found or cannot delete:\n{root}',
                                       ADDON_ICON, 5000)



