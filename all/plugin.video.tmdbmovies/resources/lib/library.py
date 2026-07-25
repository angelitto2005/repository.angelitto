# Library Export Module — .strm + .nfo generator for Kodi library integration
import xbmc, xbmcvfs, xbmcgui, xbmcaddon
import os, json, time, threading
from urllib.parse import quote
from resources.lib.config import ADDON, ADDON_PATH
from resources.lib.utils import read_json, write_json

ADDON_ID = 'plugin.video.tmdbmovies'
BASE_URL = 'plugin://plugin.video.tmdbmovies/'
LIBRARY_ROOT_NAME = "Kodi Library"
TMDB_URL = 'https://www.themoviedb.org'
LIBRARY_SETTINGS_FILE = 'library_settings.json'
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
    if xbmcvfs.exists(path):
        return xbmcvfs.translatePath(path)
    if xbmcvfs.mkdirs(path):
        return xbmcvfs.translatePath(path)
    if xbmcvfs.exists(path):
        return xbmcvfs.translatePath(path)
    # Ignore folder checking fallback
    try:
        ignore = ADDON.getSetting('library_ignore_folderchecking') == 'true'
    except:
        ignore = False
    if ignore:
        log(f'Ignored xbmcvfs folder check error: {path}', xbmc.LOGWARNING)
        return xbmcvfs.translatePath(path)
    log(f'Cannot create path: {path}', xbmc.LOGERROR)
    return None

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
    from resources.lib.config import clear_settings_cache
    clear_settings_cache()
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
    root = os.path.join(parent, LIBRARY_ROOT_NAME).replace('\\', '/')
    log(f'Library root: {root}')
    return root

def browse_destination():
    from resources.lib.config import clear_settings_cache
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
                                      '[B][COLOR FF6AFB92]Library Destination[/COLOR][/B]\nChoose parent folder — "Kodi Library" will be created inside',
                                      'files',
                                      mask='',
                                      useThumbs=False,
                                      treatAsFolder=True,
                                      defaultt=parent)
    if not picked:
        return
    ADDON.setSetting('library_dest_path', picked.rstrip('/\\'))
    clear_settings_cache()
    xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                   f'Parent set to:\n{picked}\nKodi Library will be created inside',
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
    strm_path = os.path.join(filepath, 'movie.strm').replace('\\', '/')
    if xbmcvfs.exists(strm_path):
        log(f'Skipping existing movie: {title} ({year})', xbmc.LOGDEBUG)
        return STATUS_SKIP
    nfo = _build_nfo_content('movie', tmdb_id)
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
    nfo_path = os.path.join(show_path, 'tvshow.nfo').replace('\\', '/')
    nfo = _build_nfo_content('tv', tmdb_id)
    if not xbmcvfs.exists(nfo_path):
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
            if xbmcvfs.exists(ep_path):
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
    return title, year, seasons_data

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
        c.execute("SELECT tmdb_id, title, year FROM trakt_watched_movies")
        watched_movies = [dict(r) for r in c.fetchall()]
        c.execute("SELECT tmdb_id, season, episode, title FROM trakt_watched_episodes ORDER BY tmdb_id")
        watched_eps = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception as e:
        log(f'Cannot read watched data: {e}', xbmc.LOGWARNING)
        return

    if not watched_movies and not watched_eps:
        log('No watched items to sync')
        return

    # ── Fetch Kodi library (with playcount to skip already-watched) ──
    try:
        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies",
               "params": {"properties": ["uniqueid", "title", "year", "playcount"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        kodi_movies = {}
        kodi_watched_tids = set()
        for m in res.get('result', {}).get('movies', []):
            uid = m.get('uniqueid', {})
            tid = str(uid.get('tmdb', ''))
            if not tid:
                continue
            kodi_movies.setdefault(tid, []).append(m['movieid'])
            if m.get('playcount', 0) >= 1:
                kodi_watched_tids.add(tid)

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

    # ── Batch update playcounts (only items not already watched in Kodi) ──
    batch = []
    batch_id = 0

    for wm in watched_movies:
        tid = wm['tmdb_id']
        if tid in kodi_watched_tids:
            continue  # deja bifat în Kodi, skip
        kids = kodi_movies.get(tid, [])
        for kid in kids:
            batch_id += 1
            batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetMovieDetails",
                           "params": {"movieid": kid, "playcount": 1}, "id": batch_id})

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
                                  "properties": ["season", "episode", "playcount"]},
                       "id": 1}
                res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
                kodi_eps = res.get('result', {}).get('episodes', [])
                kodi_ep_map = {}
                # Collect already-watched episode keys
                watched_ep_keys = set()
                for e in kodi_eps:
                    key = (e['season'], e['episode'])
                    kodi_ep_map.setdefault(key, []).append(e['episodeid'])
                    if e.get('playcount', 0) >= 1:
                        watched_ep_keys.add(key)
                for we in eps_list:
                    key = (we['season'], we['episode'])
                    if key in watched_ep_keys:
                        continue  # deja bifat
                    eids = kodi_ep_map.get(key, [])
                    for eid in eids:
                        batch_id += 1
                        batch.append({"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails",
                                       "params": {"episodeid": eid, "playcount": 1}, "id": batch_id})
            except:
                continue

    # ── Send batch (chunked 50 at a time for safety) ──
    if not batch:
        log('No items to update in Kodi library')
        return
    total_ok = 0
    chunk_size = 20
    for chunk_start in range(0, len(batch), chunk_size):
        chunk = batch[chunk_start:chunk_start + chunk_size]
        try:
            resp = _json.loads(xbmc.executeJSONRPC(_json.dumps(chunk)))
            total_ok += sum(1 for r in (resp if isinstance(resp, list) else []) if r.get('result') == 'OK')
        except Exception as e:
            log(f'Batch chunk error at {chunk_start}: {e}', xbmc.LOGWARNING)
        xbmc.sleep(100)
    log(f'Watched sync: {total_ok}/{len(batch)} items updated in Kodi library')


def _sync_kodi_watched_to_addon():
    """Reverse sync: reads playcount from Kodi library, writes to addon DB, syncs new items to Trakt."""
    import json as _json
    import threading
    from resources.lib import trakt_sync as _ts
    log('Reverse syncing Kodi watched status to addon DB...')

    # Ultimul sync timestamp (0 = first ever sync → skip Trakt)
    s = _load_lib_settings()
    last_sync = float(s.get('last_sync', 0))
    log(f'Reverse sync last_sync={last_sync}')

    conn = _ts.get_connection()
    c = conn.cursor()
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
            c.execute("INSERT OR REPLACE INTO trakt_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,datetime('now'))",
                      (tid, m.get('title', ''), str(m.get('year', ''))))
            # Sync to Trakt only if lastplayed > last_sync (newly watched since last sync)
            if last_sync > 0:
                lp = m.get('lastplayed', '')
                if lp:
                    lp_ts = _parse_lastplayed(lp)
                    if lp_ts is not None and lp_ts > last_sync:
                        trakt_movies.append(tid)

        # ── TV Episodes ──
        req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows",
               "params": {"properties": ["uniqueid", "title"]}, "id": 1}
        res = _json.loads(xbmc.executeJSONRPC(_json.dumps(req)))
        for s in res.get('result', {}).get('tvshows', []):
            uid = s.get('uniqueid', {})
            tid = str(uid.get('tmdb', '')) or str(uid.get('default', ''))
            if not tid:
                continue
            ep_req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes",
                      "params": {"tvshowid": s['tvshowid'],
                                 "properties": ["season", "episode", "playcount", "title", "lastplayed"],
                                 "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}},
                      "id": 1}
            ep_res = _json.loads(xbmc.executeJSONRPC(_json.dumps(ep_req)))
            for ep in ep_res.get('result', {}).get('episodes', []):
                c.execute("INSERT OR REPLACE INTO trakt_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,datetime('now'))",
                          (tid, ep.get('season', 0), ep.get('episode', 0),
                           f"{s.get('title', '')} - S{ep.get('season', 0):02d}E{ep.get('episode', 0):02d}"))
                if last_sync > 0:
                    lp = ep.get('lastplayed', '')
                    if lp:
                        lp_ts = _parse_lastplayed(lp)
                        if lp_ts is not None and lp_ts > last_sync:
                            trakt_eps.append((tid, ep.get('season', 0), ep.get('episode', 0)))
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
    finally:
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
    # 1. Mai întâi watched sync (DB-ul Kodi e liber — niciun scanner activ)
    try:
        _sync_watched_to_kodi()
    except Exception as e:
        log(f'Watched sync error: {e}', xbmc.LOGWARNING)
    try:
        _sync_kodi_watched_to_addon()
    except Exception as e:
        log(f'Kodi->addon watched sync error: {e}', xbmc.LOGWARNING)

    # 2. Abia apoi pornește scanarea .strm-urilor (în fundal, fără lock)
    try:
        xbmc.executebuiltin('UpdateLibrary(video)')
    except:
        pass

    # Salvează timestamp-ul ultimului sync
    now_ts = time.time()
    try:
        s = _load_lib_settings()
        s['last_sync'] = now_ts
        _save_lib_settings(s)
        ADDON.setSetting('library_last_sync', time.strftime('%Y-%m-%d %H:%M', time.localtime(now_ts)))
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
# ADD SINGLE ITEM TO LIBRARY (context menu)
# =============================================================================
def add_to_library(tmdb_id, media_type, title=None, year=None, season=None, episode=None):
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
            export_movie(basedir, tmdb_id, title, year)
            xbmc.executebuiltin('UpdateLibrary(video)')
            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                           f'[B][COLOR yellow]{title}[/COLOR][/B] added to library',
                                           ADDON_ICON)
    elif media_type == 'tv':
        basedir = os.path.join(dest, 'Local TV Shows').replace('\\', '/')
        show_data = get_tvshow_seasons_episodes(tmdb_id)
        if show_data:
            title, year, seasons = show_data
            if title and seasons:
                export_tvshow(basedir, tmdb_id, title, year, seasons)
                xbmc.executebuiltin('UpdateLibrary(video)')
                xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                               f'[B][COLOR yellow]{title}[/COLOR][/B] added to library',
                                               ADDON_ICON)

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

    save_selected_tmdb_lists(list(tmdb_selected))
    save_selected_trakt_lists(list(trakt_selected))

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

def check_auto_sync():
    global _LAST_SYNC_CHECK
    now = time.time()
    if now - _LAST_SYNC_CHECK < 600:
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
    if current_hour != target_hour:
        return
    
    s = _load_lib_settings()
    last = s.get('last_sync', 0)
    if now - last >= hours * 3600:
        log('Auto-sync triggered')
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



