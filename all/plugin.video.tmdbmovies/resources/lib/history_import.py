# -*- coding: utf-8 -*-
"""
History Import Trakt <-> MDBList.

Importa istoricul de vizionare dintr-un serviciu in celalalt,
pastrand datele originale de vizionare (watched_at) si fara rewatched
(itemele deja vizionate in destinatie sunt sarite).

Flow:
  1. Fetch istoric SURSĂ din API (nu din baza locala a addonului).
  2. Fetch istoric DESTINATIE din API (skip-sets: filme pe tmdb_id,
     episoade pe (tmdb_id, season, episode)).
  3. Push in chunk-uri de max 150 itemi (limita MDBList = 200/request).
  4. Mirror local in baza destinatiei + clear fast cache.
"""

import os
import datetime

import xbmc
import xbmcgui

from resources.lib.config import ADDON_PATH

TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
MDBLIST_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'mdblist.png')
TMDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
SIMKL_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'simkl.png')

TRAKT_COLOR = 'pink'
MDBLIST_COLOR = 'lightskyblue'
TMDB_COLOR = 'FF00CED1'
SIMKL_COLOR = 'mediumpurple'

CHUNK = 150  # MDBList respinge >200 shows/request; 150 e marja sigura

_PROVIDER_INFO = {
    'trakt': ('Trakt', TRAKT_COLOR, TRAKT_ICON),
    'mdblist': ('MDBList', MDBLIST_COLOR, MDBLIST_ICON),
    'tmdb': ('TMDb', TMDB_COLOR, TMDB_ICON),
    'simkl': ('Simkl', SIMKL_COLOR, SIMKL_ICON),
}


def _now_iso():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')


# =============================================================================
# FETCH SURSĂ/DESTINATIE (direct din API)
# =============================================================================

def _fetch_trakt_history():
    """Returneaza (movies, episodes) din API-ul Trakt.

    movies:   list[(tmdb_id, title, year, watched_at)]
    episodes: list[(tmdb_id, season, episode, title, watched_at)]
    """
    from resources.lib import trakt_api
    movies, episodes = [], []

    data = trakt_api._get_trakt_paginated_list('/sync/watched/movies',
                                               params={'extended': 'full'})
    for item in data or []:
        m = item.get('movie') or {}
        ids = m.get('ids') or {}
        tid = ids.get('tmdb')
        if not tid:
            continue
        movies.append((str(tid), m.get('title') or 'Unknown',
                       str(m.get('year') or ''),
                       item.get('last_watched_at') or _now_iso()))

    data = trakt_api._get_trakt_paginated_list('/sync/watched/shows',
                                               params={'extended': 'progress'})
    for item in data or []:
        s = item.get('show') or {}
        ids = s.get('ids') or {}
        tid = ids.get('tmdb')
        if not tid:
            continue
        show_title = s.get('title') or 'Unknown Show'
        for season in item.get('seasons') or []:
            s_num = season.get('number')
            if s_num is None:
                continue
            for ep in season.get('episodes') or []:
                e_num = ep.get('number')
                if e_num is None:
                    continue
                episodes.append((str(tid), int(s_num), int(e_num), show_title,
                                 ep.get('last_watched_at') or _now_iso()))
    return movies, episodes


def _fetch_mdblist_history(api):
    """Idem, din API-ul MDBList (cursor pagination, limit 1000)."""
    movies, episodes = [], []
    cursor = None
    for _ in range(100):
        data = api.get_sync_watched(cursor=cursor, limit=1000)
        if not data or not isinstance(data, dict):
            break
        for movie in data.get('movies') or []:
            inner = movie.get('movie', movie) or {}
            ids = inner.get('ids') or {}
            tid = ids.get('tmdb')
            if not tid:
                continue
            movies.append((str(tid), inner.get('title') or 'Unknown',
                           str(inner.get('year') or inner.get('release_year') or ''),
                           movie.get('watched_at') or movie.get('last_watched_at') or _now_iso()))
        for row in data.get('episodes') or []:
            inner = row.get('episode', row) or {}
            show = inner.get('show') or {}
            ids = show.get('ids') or inner.get('ids') or {}
            tid = ids.get('tmdb')
            if not tid:
                continue
            season = inner.get('season', 1)
            number = inner.get('number', inner.get('episode', 1))
            if season is None or number is None:
                continue
            episodes.append((str(tid), int(season), int(number),
                             show.get('title') or inner.get('name') or 'Unknown Show',
                             row.get('last_watched_at') or row.get('watched_at') or _now_iso()))
        pagination = data.get('pagination') or {}
        if not pagination.get('has_more'):
            break
        cursor = pagination.get('next_cursor')
        if not cursor:
            break
    return movies, episodes


def _fetch_simkl_history(api):
    """History din GET /sync/all-items (singurul endpoint viu — /sync/movies + /sync/shows
    intorc null de cand Simkl a mutat totul pe all-items).

    Returneaza (movies, episodes, fully_watched_shows):
    - movies: entry-uri cu last_watched_at (history real, nu doar watchlist)
    - episodes: din seasons (doar show-urile partiale au seasons; cele complet
      vizionate vin fara -> dedupe la nivel de serial cu watched==total)
    - fully_watched_shows: set de tmdb_id cu watched_episodes_count == total_episodes_count
      (toate episoadele sunt in history -> se skip la nivel de serial)
    """
    movies, episodes, fully = [], [], set()
    data = api.get_watchlist()
    if not isinstance(data, dict):
        return movies, episodes, fully
    for m in (data.get('movies') or []):
        if not m.get('last_watched_at'):
            continue
        obj = m.get('movie') or {}
        ids = obj.get('ids') or {}
        tid = ids.get('tmdb')
        if not tid:
            continue
        movies.append((str(tid), obj.get('title') or 'Unknown',
                       str(obj.get('year') or ''),
                       m.get('last_watched_at') or _now_iso()))
    for s in (data.get('shows') or []) + (data.get('anime') or []):
        obj = s.get('show') or {}
        ids = obj.get('ids') or {}
        tid = ids.get('tmdb')
        if not tid:
            continue
        show_title = obj.get('title') or 'Unknown Show'
        total = int(s.get('total_episodes_count') or 0)
        watched = int(s.get('watched_episodes_count') or 0)
        if total and watched >= total:
            fully.add(str(tid))
            continue
        for season in s.get('seasons') or []:
            s_num = season.get('number')
            if s_num is None:
                continue
            for ep in season.get('episodes') or []:
                e_num = ep.get('number')
                if e_num is None:
                    continue
                episodes.append((str(tid), int(s_num), int(e_num), show_title,
                                 ep.get('watched_at') or s.get('last_watched_at') or _now_iso()))
    return movies, episodes, fully


# =============================================================================
# PAYLOAD + PUSH
# =============================================================================

def _build_movie_payload(movies):
    return {'movies': [{'ids': {'tmdb': int(tid)}, 'watched_at': d}
                       for tid, _t, _y, d in movies]}


def _build_episode_payload(episodes):
    """Grupare episoade pe serial+sezon — format identic la Trakt si MDBList."""
    from collections import OrderedDict
    shows = OrderedDict()
    for tid, season, number, _title, d in episodes:
        shows.setdefault(tid, OrderedDict()).setdefault(season, []).append((number, d))
    out = []
    for tid, seasons in shows.items():
        seasons_list = []
        for s_num, eps in seasons.items():
            seasons_list.append({'number': s_num,
                                 'episodes': [{'number': e, 'watched_at': d}
                                              for e, d in eps]})
        out.append({'ids': {'tmdb': int(tid)}, 'seasons': seasons_list})
    return {'shows': out}


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _push_to_mdblist(api, movies, episodes, progress_cb):
    added_m = added_e = 0
    done = 0
    total = len(movies) + len(episodes)
    for chunk in _chunks(movies, CHUNK):
        res = api._post('sync/watched', data=_build_movie_payload(chunk))
        updated = (res or {}).get('updated') or {}
        added_m += int(updated.get('movies', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    for chunk in _chunks(episodes, CHUNK):
        res = api._post('sync/watched', data=_build_episode_payload(chunk))
        updated = (res or {}).get('updated') or {}
        added_e += int(updated.get('episodes', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    return added_m, added_e


def _push_to_trakt(movies, episodes, progress_cb):
    from resources.lib import trakt_api
    added_m = added_e = 0
    done = 0
    total = len(movies) + len(episodes)
    for chunk in _chunks(movies, CHUNK):
        res = trakt_api.trakt_api_request('/sync/history', method='POST',
                                          data=_build_movie_payload(chunk))
        added_m += int(((res or {}).get('added') or {}).get('movies', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    for chunk in _chunks(episodes, CHUNK):
        res = trakt_api.trakt_api_request('/sync/history', method='POST',
                                          data=_build_episode_payload(chunk))
        added_e += int(((res or {}).get('added') or {}).get('episodes', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    return added_m, added_e


def _push_to_simkl(api, movies, episodes, progress_cb):
    added_m = added_e = 0
    done = 0
    total = len(movies) + len(episodes)
    for chunk in _chunks(movies, CHUNK):
        res = api.add_history_bulk([(t, d) for t, *_x, d in chunk], [])
        updated = (res or {}).get('added') or {}
        added_m += int(updated.get('movies', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    for chunk in _chunks(episodes, CHUNK):
        res = api.add_history_bulk([], [(t, s, e, d) for t, s, e, *_x, d in chunk])
        updated = (res or {}).get('added') or {}
        added_e += int(updated.get('episodes', 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    return added_m, added_e


# =============================================================================
# MIRROR LOCAL (baza destinatiei)
# =============================================================================

def _mirror_to_mdblist_db(movies, episodes):
    from resources.lib import mdblist_sync
    conn = mdblist_sync.get_connection()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO mdblist_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?, ?, ?, ?)",
            [(tid, t, y, d) for tid, t, y, d in movies])
        conn.executemany(
            "INSERT OR REPLACE INTO mdblist_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?, ?, ?, ?, ?)",
            [(tid, s, e, t, d) for tid, s, e, t, d in episodes])
        conn.commit()
    finally:
        conn.close()


def _mirror_to_trakt_db(movies, episodes):
    from resources.lib import trakt_sync
    conn = trakt_sync.get_connection()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO trakt_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?, ?, ?, ?)",
            [(tid, t, y, d) for tid, t, y, d in movies])
        conn.executemany(
            "INSERT OR REPLACE INTO trakt_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?, ?, ?, ?, ?)",
            [(tid, s, e, t, d) for tid, s, e, t, d in episodes])
        conn.commit()
    finally:
        conn.close()


def _mirror_to_simkl_db(movies, episodes):
    from resources.lib import simkl_sync
    conn = simkl_sync.get_connection()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO simkl_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?, ?, ?, ?)",
            [(tid, t, y, d) for tid, t, y, d in movies])
        conn.executemany(
            "INSERT OR REPLACE INTO simkl_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?, ?, ?, ?, ?)",
            [(tid, s, e, t, d) for tid, s, e, t, d in episodes])
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# ENTRY POINT
# =============================================================================

def import_history(direction):
    """direction: 'trakt_to_mdblist' | 'mdblist_to_trakt' | 'trakt_to_simkl' | 'simkl_to_trakt' | ..."""
    src, dst = direction.split('_to_')
    src_name, src_color, _ = _PROVIDER_INFO[src]
    dst_name, dst_color, dst_icon = _PROVIDER_INFO[dst]

    # --- Auth checks (doar providerii implicati) ---
    if 'trakt' in (src, dst):
        from resources.lib import trakt_api
        if not trakt_api.get_trakt_token():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]History Import[/COLOR][/B]",
                "[B][COLOR pink]Trakt[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                TRAKT_ICON, 5000, False)
            return
    api = None
    if 'mdblist' in (src, dst):
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        if not api.is_authenticated():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]History Import[/COLOR][/B]",
                "[B][COLOR lightskyblue]MDBList[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                MDBLIST_ICON, 5000, False)
            return
    skapi = None
    if 'simkl' in (src, dst):
        from resources.lib.simkl_api import SIMKLAPI
        skapi = SIMKLAPI()
        if not skapi.is_authenticated():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]History Import[/COLOR][/B]",
                "[B][COLOR mediumpurple]Simkl[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                SIMKL_ICON, 5000, False)
            return

    confirmed = xbmcgui.Dialog().yesno(
        "[B][COLOR yellow]History Import[/COLOR][/B]",
        "Import [B]watched history[/B] from [B][COLOR %s]%s[/COLOR][/B] to [B][COLOR %s]%s[/COLOR][/B]?"
        "\nItems already watched in [B][COLOR %s]%s[/COLOR][/B] will be skipped. Original [B]watched dates[/B] will be kept. [B][COLOR yellow]Continue?[/COLOR][/B]" %
        (src_color, src_name, dst_color, dst_name, dst_color, dst_name))
    if not confirmed:
        return

    prog = None
    try:
        prog = xbmcgui.DialogProgressBG()
        prog.create("[B][COLOR yellow]History Import[/COLOR][/B]",
                    "[B][COLOR %s]%s[/COLOR][/B] -> [B][COLOR %s]%s[/COLOR][/B]" %
                    (src_color, src_name, dst_color, dst_name))
    except Exception:
        prog = None

    def update(pct, line):
        if prog:
            try:
                prog.update(int(pct), line)
            except Exception:
                pass

    fetch = {
        'trakt': _fetch_trakt_history,
        'mdblist': lambda: _fetch_mdblist_history(api),
        'simkl': lambda: _fetch_simkl_history(skapi),
    }
    push = {
        'trakt': lambda _api, movies, episodes, cb: _push_to_trakt(movies, episodes, cb),
        'mdblist': lambda _api, movies, episodes, cb: _push_to_mdblist(api, movies, episodes, cb),
        'simkl': lambda _api, movies, episodes, cb: _push_to_simkl(skapi, movies, episodes, cb),
    }
    mirror = {
        'trakt': _mirror_to_trakt_db,
        'mdblist': _mirror_to_mdblist_db,
        'simkl': _mirror_to_simkl_db,
    }

    try:
        update(3, "Fetching source history from %s..." % src_name)
        src_res = fetch[src]()
        src_movies, src_eps = src_res[0], src_res[1]

        update(18, "Fetching destination history from %s..." % dst_name)
        dst_res = fetch[dst]()
        dst_movies, dst_eps = dst_res[0], dst_res[1]
        dst_full_shows = dst_res[2] if len(dst_res) > 2 else set()

        dst_movie_ids = {t for t, *_ in dst_movies}
        dst_ep_keys = {(t, s, e) for t, s, e, *_ in dst_eps}

        movies = [m for m in src_movies if m[0] not in dst_movie_ids]
        episodes = [e for e in src_eps
                    if (e[0], e[1], e[2]) not in dst_ep_keys and e[0] not in dst_full_shows]

        skipped = len(src_movies) + len(src_eps) - len(movies) - len(episodes)
        xbmc.log("[HISTORY IMPORT] source: %d movies, %d episodes | to push: %d movies, %d episodes | skipped (already watched): %d"
                 % (len(src_movies), len(src_eps), len(movies), len(episodes), skipped), xbmc.LOGINFO)

        def cb(done, total):
            update(25 + 65 * done // max(total, 1),
                   "Pushing to [B][COLOR %s]%s[/COLOR][/B]: %d/%d..." % (dst_color, dst_name, done, total))
        added_m, added_e = push[dst](None, movies, episodes, cb)
        update(92, "Updating local database...")
        mirror[dst](movies, episodes)

        update(98, "Clearing cache...")
        from resources.lib.watched_provider import _invalidate_fast_cache
        _invalidate_fast_cache()

        if prog:
            try:
                prog.close()
            except Exception:
                pass

        msg = ("[B][COLOR %s]%s[/COLOR][/B] -> [B][COLOR %s]%s[/COLOR][/B]: imported "
               "[B][COLOR FF6AFB92]%d movies[/COLOR][/B] + [B][COLOR FF6698FF]%d episodes[/COLOR][/B]. "
               "Skipped (already watched): [B]%d[/B]."
               % (src_color, src_name, dst_color, dst_name, added_m, added_e, skipped))
        xbmcgui.Dialog().notification("[B][COLOR yellow]History Import[/COLOR][/B]", msg, dst_icon, 8000, False)
    except Exception as e:
        xbmc.log("[HISTORY IMPORT] Error: %s" % e, xbmc.LOGERROR)
        if prog:
            try:
                prog.close()
            except Exception:
                pass
        xbmcgui.Dialog().notification(
            "[B][COLOR yellow]History Import[/COLOR][/B]",
            "Error: %s" % e, xbmcgui.NOTIFICATION_ERROR, 6000, False)


# =============================================================================
# WATCHLIST IMPORT (Trakt / MDBList / TMDb — toate directiile)
# =============================================================================
# Item shape: (tmdb_id, title, year, added_at, poster, overview)

def _fetch_trakt_watchlist(media_type):
    """media_type: 'movies' | 'shows' (endpoint Trakt)."""
    from resources.lib import trakt_api
    from resources.lib.config import IMG_BASE
    items = []
    data = trakt_api._get_trakt_paginated_list('/sync/watchlist/%s' % media_type,
                                               params={'extended': 'full'})
    for item in data or []:
        obj = item.get('movie') or item.get('show') or {}
        ids = obj.get('ids') or {}
        tid = ids.get('tmdb')
        if not tid:
            continue
        poster = ''
        try:
            p_urls = (obj.get('images') or {}).get('poster') or []
            if p_urls and isinstance(p_urls, list) and p_urls[0] and 'image.tmdb.org' in str(p_urls[0]):
                poster = IMG_BASE + '/' + str(p_urls[0]).split('/')[-1].split('?')[0]
        except Exception:
            pass
        items.append((str(tid), obj.get('title') or obj.get('name') or 'Unknown',
                      str(obj.get('year') or ''), item.get('listed_at') or '',
                      poster, ''))
    return items


def _fetch_mdblist_watchlist(api, media_type):
    """media_type: 'movie' | 'tv'. Fetch paginat (limit 1000)."""
    items = []
    key = 'movies' if media_type == 'movie' else 'shows'
    cursor = None
    for _ in range(100):
        data = api.get_watchlist(cursor=cursor, limit=1000)
        if not data or not isinstance(data, dict):
            break
        for entry in data.get(key) or []:
            inner = entry.get('movie', entry.get('show', entry))
            if not isinstance(inner, dict):
                continue
            ids = inner.get('ids') or {}
            tid = ids.get('tmdb', '')
            if not tid:
                continue
            items.append((str(tid), inner.get('title') or inner.get('name') or 'Unknown',
                          str(inner.get('year') or inner.get('release_year') or ''),
                          entry.get('added_at') or '', '', ''))
        pagination = data.get('pagination') or {}
        if not pagination.get('has_more'):
            break
        cursor = pagination.get('next_cursor')
        if not cursor:
            break
    return items


def _fetch_simkl_watchlist(api, media_type):
    """media_type: 'movie' | 'tv'. GET /sync/all-items (dict shows/movies/anime, status per item).

    Dedupe-ul trebuie sa caute in TOATE categoriile — Simkl poate clasifica un film
    ca anime (ex. Ne Zha 2 -> anime, nu movie), iar importul l-ar re-importa mereu."""
    items = []
    data = api.get_watchlist()
    if not isinstance(data, dict):
        return items
    for key in ('movies', 'shows', 'anime'):
        for entry in (data.get(key) or []):
            if not isinstance(entry, dict):
                continue
            inner = entry.get('movie') or entry.get('show') or entry.get('anime') or entry
            if not isinstance(inner, dict):
                continue
            ids = inner.get('ids') or {}
            tid = ids.get('tmdb', '')
            if not tid:
                continue
            items.append((str(tid), inner.get('title') or inner.get('name') or 'Unknown',
                          str(inner.get('year') or ''),
                          entry.get('added_to_watchlist_at') or entry.get('added_at') or '', '', ''))
    return items


def _fetch_tmdb_watchlist(media_type):
    """media_type: 'movie' | 'tv'. v4 GET /account/{id}/{movie|tv}/watchlist (paginat)."""
    from resources.lib import tmdb_api
    session = tmdb_api.get_tmdb_session()
    if not session:
        return []
    aid = session['account_id']
    ep = 'movie' if media_type == 'movie' else 'tv'
    items = []
    page = 1
    while True:
        data = tmdb_api.tmdb_auth_request('/account/%s/%s/watchlist' % (aid, ep), method='GET',
                                          params={'page': page, 'sort_by': 'created_at.desc'}, v4=True)
        if not data or not isinstance(data, dict) or 'results' not in data:
            break
        results = data.get('results') or []
        if not results:
            break
        for r in results:
            items.append((str(r.get('id', '')), r.get('title') or r.get('name') or 'Unknown',
                          str((r.get('release_date') or r.get('first_air_date') or ''))[:4],
                          _now_iso(), r.get('poster_path') or '', r.get('overview') or ''))
        if page >= data.get('total_pages', 1):
            break
        page += 1
    return items


def _push_watchlist_to_mdblist(api, items, media_type, progress_cb):
    added = 0
    done = 0
    total = len(items)
    key = 'movies' if media_type == 'movie' else 'shows'
    for chunk in _chunks(items, CHUNK):
        data = {key: [{'ids': {'tmdb': int(t)}} for t, *_ in chunk]}
        res = api._post('watchlist/items/add', data=data)
        added += int(((res or {}).get('added') or {}).get(key, 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    return added


def _push_watchlist_to_trakt(items, media_type, progress_cb):
    from resources.lib import trakt_api
    added = 0
    done = 0
    total = len(items)
    key = 'movies' if media_type == 'movie' else 'shows'
    for chunk in _chunks(items, CHUNK):
        data = {key: [{'ids': {'tmdb': int(t)}} for t, *_ in chunk]}
        res = trakt_api.trakt_api_request('/sync/watchlist', method='POST', data=data)
        added += int(((res or {}).get('added') or {}).get(key, 0) or 0)
        done += len(chunk)
        progress_cb(done, total)
    return added


def _push_watchlist_to_simkl(api, items, media_type, progress_cb):
    added = 0
    done = 0
    total = len(items)
    movie_ids = []
    show_ids = []
    for chunk in _chunks(items, CHUNK):
        ids = [int(t) for t, *_ in chunk]
        if media_type == 'movie':
            movie_ids = ids
            show_ids = []
        else:
            movie_ids = []
            show_ids = ids
        res = api.watchlist_add_bulk(movie_ids, show_ids, status='plantowatch')
        added_items = (res or {}).get('added') or {}
        added += len(added_items.get('movies') or []) + len(added_items.get('shows') or [])
        done += len(chunk)
        progress_cb(done, total)
    return added


def _push_watchlist_to_tmdb(items, media_type, progress_cb):
    """TMDb n-are bulk — un POST v3 per item (limita ~50/10s, pauza la 40)."""
    from resources.lib import tmdb_api
    session = tmdb_api.get_tmdb_session()
    if not session:
        return 0
    aid = session['account_id']
    m_type = 'movie' if media_type == 'movie' else 'tv'
    added = 0
    total = len(items)
    for i, item in enumerate(items, start=1):
        if i % 40 == 0:
            xbmc.sleep(600)
        res = tmdb_api.tmdb_auth_request('/account/%s/watchlist' % aid, method='POST',
                                         data={'media_type': m_type, 'media_id': int(item[0]),
                                               'watchlist': True}, v4=False)
        if res is not None and res.get('success', True):
            added += 1
        progress_cb(i, total)
    return added


def _mirror_watchlist_to_mdblist_db(items, media_type):
    from resources.lib import mdblist_sync
    conn = mdblist_sync.get_connection()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO mdblist_watchlist (tmdb_id, media_type, added_at, title, year) VALUES (?, ?, ?, ?, ?)",
            [(t, media_type, d, title, y) for t, title, y, d, _p, _o in items])
        conn.commit()
    finally:
        conn.close()


def _mirror_watchlist_to_simkl_db(items, media_type):
    from resources.lib import simkl_sync
    conn = simkl_sync.get_connection()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO simkl_watchlist (tmdb_id, media_type, status, title, year, added_at) VALUES (?, ?, 'plantowatch', ?, ?, ?)",
            [(t, media_type, title, y, d) for t, title, y, d, _p, _o in items])
        conn.commit()
    finally:
        conn.close()


def _mirror_watchlist_to_trakt_db(items, media_type):
    from resources.lib import trakt_sync
    conn = trakt_sync.get_connection()
    try:
        db_mt = 'movie' if media_type == 'movie' else 'show'
        conn.executemany(
            "INSERT OR REPLACE INTO trakt_lists (list_type, media_type, tmdb_id, title, year, added_at, poster, backdrop, overview) VALUES ('watchlist', ?, ?, ?, ?, ?, ?, '', ?)",
            [(db_mt, t, title, y, d, p, o) for t, title, y, d, p, o in items])
        conn.commit()
    finally:
        conn.close()


def _mirror_watchlist_to_tmdb_db(items, media_type):
    from resources.lib import trakt_sync
    conn = trakt_sync.get_connection()
    try:
        m_type = 'movie' if media_type == 'movie' else 'tv'
        conn.executemany(
            "INSERT OR REPLACE INTO tmdb_account_lists VALUES ('watchlist', ?, ?, ?, ?, ?, ?, ?, '', '')",
            [(m_type, t, title, y, p, d, o) for t, title, y, d, p, o in items])
        conn.commit()
    finally:
        conn.close()


_WATCHLIST_DIRS = {
    'trakt_to_mdblist': ('trakt', 'mdblist'),
    'mdblist_to_trakt': ('mdblist', 'trakt'),
    'trakt_to_tmdb': ('trakt', 'tmdb'),
    'tmdb_to_trakt': ('tmdb', 'trakt'),
    'mdblist_to_tmdb': ('mdblist', 'tmdb'),
    'tmdb_to_mdblist': ('tmdb', 'mdblist'),
    'trakt_to_simkl': ('trakt', 'simkl'),
    'simkl_to_trakt': ('simkl', 'trakt'),
    'mdblist_to_simkl': ('mdblist', 'simkl'),
    'simkl_to_mdblist': ('simkl', 'mdblist'),
    'tmdb_to_simkl': ('tmdb', 'simkl'),
    'simkl_to_tmdb': ('simkl', 'tmdb'),
}


def import_watchlist(direction, media_type):
    """Importa watchlist (movie|tv) dintr-un provider in altul, fara duplicate."""
    if direction not in _WATCHLIST_DIRS or media_type not in ('movie', 'tv'):
        return
    src, dst = _WATCHLIST_DIRS[direction]
    src_name, src_color, _ = _PROVIDER_INFO[src]
    dst_name, dst_color, dst_icon = _PROVIDER_INFO[dst]
    kind_label = 'TV shows' if media_type == 'tv' else 'movies'

    if src == 'trakt' or dst == 'trakt':
        from resources.lib import trakt_api
        if not trakt_api.get_trakt_token():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
                "[B][COLOR pink]Trakt[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                TRAKT_ICON, 5000, False)
            return
    api = None
    if src == 'mdblist' or dst == 'mdblist':
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        if not api.is_authenticated():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
                "[B][COLOR lightskyblue]MDBList[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                MDBLIST_ICON, 5000, False)
            return
    skapi = None
    if src == 'simkl' or dst == 'simkl':
        from resources.lib.simkl_api import SIMKLAPI
        skapi = SIMKLAPI()
        if not skapi.is_authenticated():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
                "[B][COLOR mediumpurple]Simkl[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                SIMKL_ICON, 5000, False)
            return
    if src == 'tmdb' or dst == 'tmdb':
        from resources.lib import tmdb_api
        if not tmdb_api.get_tmdb_session():
            xbmcgui.Dialog().notification(
                "[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
                "[B][COLOR FF00CED1]TMDb[/COLOR][/B] is not connected. Connect it in Settings -> Accounts.",
                TMDB_ICON, 5000, False)
            return

    confirmed = xbmcgui.Dialog().yesno(
        "[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
        "Import [B]%s watchlist[/B] from [B][COLOR %s]%s[/COLOR][/B] to [B][COLOR %s]%s[/COLOR][/B]?"
        "\nItems already in [B][COLOR %s]%s[/COLOR][/B]'s [B]watchlist[/B] will be skipped."
        "\n[B][COLOR yellow]Are you sure you want to continue?[/COLOR][/B]" %
        (kind_label, src_color, src_name, dst_color, dst_name, dst_color, dst_name))
    if not confirmed:
        return

    prog = None
    try:
        prog = xbmcgui.DialogProgressBG()
        prog.create("[B][COLOR yellow]Watchlist Import[/COLOR][/B]",
                    "[B][COLOR %s]%s[/COLOR][/B] -> [B][COLOR %s]%s[/COLOR][/B] (%s)" %
                    (src_color, src_name, dst_color, dst_name, kind_label))
    except Exception:
        prog = None

    def update(pct, line):
        if prog:
            try:
                prog.update(int(pct), line)
            except Exception:
                pass

    fetch = {
        'trakt': lambda mt: _fetch_trakt_watchlist('shows' if mt == 'tv' else 'movies'),
        'mdblist': lambda mt: _fetch_mdblist_watchlist(api, mt),
        'tmdb': _fetch_tmdb_watchlist,
        'simkl': lambda mt: _fetch_simkl_watchlist(skapi, mt),
    }
    push = {
        'trakt': _push_watchlist_to_trakt,
        'mdblist': lambda items, mt, cb: _push_watchlist_to_mdblist(api, items, mt, cb),
        'tmdb': _push_watchlist_to_tmdb,
        'simkl': lambda items, mt, cb: _push_watchlist_to_simkl(skapi, items, mt, cb),
    }
    mirror = {
        'trakt': _mirror_watchlist_to_trakt_db,
        'mdblist': _mirror_watchlist_to_mdblist_db,
        'tmdb': _mirror_watchlist_to_tmdb_db,
        'simkl': _mirror_watchlist_to_simkl_db,
    }

    try:
        update(3, "Fetching %s watchlist from [B][COLOR %s]%s[/COLOR][/B]..." % (kind_label, src_color, src_name))
        src_items = fetch[src](media_type)
        update(18, "Fetching %s watchlist from [B][COLOR %s]%s[/COLOR][/B]..." % (kind_label, dst_color, dst_name))
        dst_items = fetch[dst](media_type)

        dst_ids = {t for t, *_ in dst_items}
        items = [it for it in src_items if it[0] not in dst_ids]
        skipped = len(src_items) - len(items)
        xbmc.log("[IMPORT] %s watchlist %s -> %s: source %d | to push %d | skipped (already there): %d"
                 % (kind_label, src, dst, len(src_items), len(items), skipped), xbmc.LOGINFO)

        def cb(done, total):
            update(25 + 65 * done // max(total, 1),
                   "Pushing to [B][COLOR %s]%s[/COLOR][/B]: %d/%d..." % (dst_color, dst_name, done, total))
        added = push[dst](items, media_type, cb)

        update(92, "Updating local database...")
        mirror[dst](items, media_type)

        update(98, "Clearing cache...")
        from resources.lib.watched_provider import _invalidate_fast_cache
        _invalidate_fast_cache()
        if dst == 'mdblist':
            try:
                from resources.lib.mdblist_sync import clear_cached
                clear_cached('watchlist')
            except Exception:
                pass
        if dst == 'simkl':
            try:
                from resources.lib.simkl_sync import clear_cached
                clear_cached('watchlist')
            except Exception:
                pass

        if prog:
            try:
                prog.close()
            except Exception:
                pass

        msg = ("[B][COLOR %s]%s[/COLOR][/B] -> [B][COLOR %s]%s[/COLOR][/B]: imported "
               "[B][COLOR FF6AFB92]%d %s[/COLOR][/B]. Skipped (already there): [B]%d[/B]."
               % (src_color, src_name, dst_color, dst_name, added, kind_label, skipped))
        xbmcgui.Dialog().notification("[B][COLOR yellow]Import[/COLOR][/B]", msg, dst_icon, 8000, False)
    except Exception as e:
        xbmc.log("[IMPORT] Error: %s" % e, xbmc.LOGERROR)
        if prog:
            try:
                prog.close()
            except Exception:
                pass
        xbmcgui.Dialog().notification(
            "[B][COLOR yellow]Import[/COLOR][/B]",
            "Error: %s" % e, xbmcgui.NOTIFICATION_ERROR, 6000, False)


# =============================================================================
# DISPATCHER (selector din Settings -> Accounts)
# =============================================================================

def run_import(selector_idx):
    """Ruleaza importul selectat in setari (0-13)."""
    try:
        idx = int(str(selector_idx or '0').strip() or '0')
    except Exception:
        idx = 0
    actions = [
        ('history', 'trakt_to_mdblist', None),
        ('history', 'mdblist_to_trakt', None),
        ('watchlist', 'trakt_to_mdblist', 'movie'),
        ('watchlist', 'mdblist_to_trakt', 'movie'),
        ('watchlist', 'trakt_to_tmdb', 'movie'),
        ('watchlist', 'tmdb_to_trakt', 'movie'),
        ('watchlist', 'mdblist_to_tmdb', 'movie'),
        ('watchlist', 'tmdb_to_mdblist', 'movie'),
        ('watchlist', 'trakt_to_mdblist', 'tv'),
        ('watchlist', 'mdblist_to_trakt', 'tv'),
        ('watchlist', 'trakt_to_tmdb', 'tv'),
        ('watchlist', 'tmdb_to_trakt', 'tv'),
        ('watchlist', 'mdblist_to_tmdb', 'tv'),
        ('watchlist', 'tmdb_to_mdblist', 'tv'),
        ('history', 'trakt_to_simkl', None),
        ('history', 'simkl_to_trakt', None),
        ('watchlist', 'trakt_to_simkl', 'movie'),
        ('watchlist', 'simkl_to_trakt', 'movie'),
        ('watchlist', 'mdblist_to_simkl', 'movie'),
        ('watchlist', 'simkl_to_mdblist', 'movie'),
        ('watchlist', 'trakt_to_simkl', 'tv'),
        ('watchlist', 'simkl_to_trakt', 'tv'),
        ('watchlist', 'mdblist_to_simkl', 'tv'),
        ('watchlist', 'simkl_to_mdblist', 'tv'),
        ('history', 'mdblist_to_simkl', None),
        ('history', 'simkl_to_mdblist', None),
        ('watchlist', 'tmdb_to_simkl', 'movie'),
        ('watchlist', 'simkl_to_tmdb', 'movie'),
        ('watchlist', 'tmdb_to_simkl', 'tv'),
        ('watchlist', 'simkl_to_tmdb', 'tv'),
    ]
    if idx < 0 or idx >= len(actions):
        idx = 0
    kind, direction, media_type = actions[idx]
    xbmc.log("[IMPORT] run_import: selector_idx=%r -> kind=%s direction=%s media_type=%s" % (selector_idx, kind, direction, media_type), xbmc.LOGINFO)
    if kind == 'history':
        import_history(direction)
    else:
        import_watchlist(direction, media_type)
