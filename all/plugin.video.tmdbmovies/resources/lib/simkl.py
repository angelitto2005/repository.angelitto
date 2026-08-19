# -*- coding: utf-8 -*-
"""
Simkl integration UI (meniuri) — model mdblist.py, adaptat la API Simkl.
Simkl nu are custom lists/favorites — in loc de ele: 5 statusuri watchlist
(watching, plantowatch, hold, dropped, completed) + ratings + calendar + history.
"""

import sys
import os
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
from datetime import datetime, timedelta, timezone

from resources.lib.config import ADDON as PROXIED_ADDON

SIMKL_ACTIONS = {
    'simkl_menu',
    'simkl_account',
    'simkl_status_menu',
    'simkl_status_items',
    'simkl_watchlist_add',
    'simkl_watchlist_remove',
    'simkl_upnext',
    'simkl_history_menu',
    'simkl_history_items',
    'simkl_ratings_menu',
    'simkl_ratings_items',
    'simkl_calendar',
    'simkl_public_calendar',
    'simkl_import_dropped_trakt',
    'simkl_import_dropped_mdblist',
    'simkl_import_ratings_trakt',
    'simkl_import_ratings_mdblist',
}

_STATUS_KEYS = ('plantowatch', 'watching', 'hold', 'completed', 'dropped')
_KIND_KEYS = {'movie': 'movies', 'tv': 'shows', 'anime': 'anime'}

_HANDLE   = None
_BASE_URL = None
_ADDON    = None

def _ensure_globals():
    global _ADDON, _BASE_URL, _HANDLE
    if _ADDON is None:
        _ADDON = PROXIED_ADDON
    if _BASE_URL is None:
        _BASE_URL = sys.argv[0]
    if _HANDLE is None:
        try: _HANDLE = int(sys.argv[1])
        except: _HANDLE = -1

def _simkl_icon():
    _ensure_globals()
    return os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'simkl.png')

def _build_url(query):
    _ensure_globals()
    if 'action' in query:
        query['mode'] = query.pop('action')
    return _BASE_URL + '?' + urllib.parse.urlencode(query)

def _page_limit():
    from resources.lib.config import get_page_limit_value
    try:
        return int(get_page_limit_value())
    except:
        return 20

def _notify(title, msg, icon=None, ms=4000):
    xbmcgui.Dialog().notification(title, msg, icon or _simkl_icon(), ms, False)

def is_authenticated():
    from resources.lib.simkl_api import SIMKLAPI
    return SIMKLAPI().is_authenticated()

# ------------------------------------------------------------------
# FETCH HELPERS (direct din simkl_sync local mirror + API)
# ------------------------------------------------------------------
def fetch_history(mediatype='movie', offset=0, limit=20):
    """Din mirror-ul local simkl_watched_* (fara paginare server — datele sunt locale)."""
    from resources.lib import simkl_sync
    offset = int(offset)
    limit = int(limit)
    if mediatype == 'movie':
        if not os.path.exists(simkl_sync.DB_PATH):
            return [], 0
        conn = simkl_sync.get_connection()
        c = conn.cursor()
        try:
            c.execute("SELECT tmdb_id, title, year, last_watched_at FROM simkl_watched_movies ORDER BY last_watched_at DESC")
            rows = c.fetchall()
        except:
            rows = []
        conn.close()
        items = [{'movie': {'ids': {'tmdb': r[0]}, 'title': r[1], 'year': r[2]}, 'watched_at': r[3]} for r in rows]
    else:
        if not os.path.exists(simkl_sync.DB_PATH):
            return [], 0
        conn = simkl_sync.get_connection()
        c = conn.cursor()
        try:
            c.execute("SELECT tmdb_id, MAX(last_watched_at) as lw FROM simkl_watched_episodes "
                      "GROUP BY tmdb_id ORDER BY lw DESC")
            rows = c.fetchall()
        except:
            rows = []
        conn.close()
        items = [{'show': {'ids': {'tmdb': r[0]}, 'title': '', 'year': ''}, 'watched_at': r[1]} for r in rows]
    total = len(items)
    paginated = items[offset:offset + limit]
    return paginated, total

# ------------------------------------------------------------------
# RENDERING HELPERS
# ------------------------------------------------------------------
def _end(succeeded=True, cache=True):
    _ensure_globals()
    xbmcplugin.endOfDirectory(_HANDLE, succeeded=succeeded, cacheToDisc=cache)

def _add_dir(url, li, is_folder=True):
    _ensure_globals()
    xbmcplugin.addDirectoryItem(_HANDLE, url, li, is_folder)

def _empty(label):
    _add_dir(_build_url({}), xbmcgui.ListItem(label=label), False)

# ------------------------------------------------------------------
# VIEWS
# ------------------------------------------------------------------
def _view_menu():
    _ensure_globals()
    m_icon = _simkl_icon()

    counts = {}
    try:
        from resources.lib.simkl_sync import DB_PATH as SIMKL_DB_PATH, get_connection
        if os.path.exists(SIMKL_DB_PATH):
            conn = get_connection()
            c = conn.cursor()
            for st in _STATUS_KEYS:
                if st == 'watching':
                    # Mirror-ul local nu stocheaza watched/total — count-ul
                    # corect vine din API filtrat (site-ul arata doar serialele
                    # cu episoade difuzate nevizionate). Paritate cu submeniul.
                    data = _fetch_status_items('watching')
                    c_count = sum(len(data.get(k, []) or []) for k in ('shows', 'anime', 'movies'))
                    if c_count == 0:
                        c.execute("SELECT COUNT(*) FROM simkl_watchlist WHERE status=?", (st,))
                        row = c.fetchone()
                        c_count = row[0] if row else 0
                    counts[st] = c_count
                    continue
                c.execute("SELECT COUNT(*) FROM simkl_watchlist WHERE status=?", (st,))
                row = c.fetchone()
                counts[st] = row[0] if row else 0
            c.execute("SELECT COUNT(*) FROM simkl_ratings")
            row = c.fetchone()
            rat_count = row[0] if row else 0
            c.execute("SELECT COUNT(*) FROM simkl_watched_movies")
            row = c.fetchone()
            hist_count = row[0] if row else 0
            c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM simkl_watched_episodes")
            row = c.fetchone()
            hist_count += row[0] if row else 0
            conn.close()
    except:
        pass

    def _counted(label, count):
        if count > 0:
            return f'{label} [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        return label

    status_labels = {
        'plantowatch': '[B][COLOR mediumpurple]Simkl Plan to Watch[/COLOR][/B]',
        'watching': '[B][COLOR mediumpurple]Simkl Watching[/COLOR][/B]',
        'hold': '[B][COLOR mediumpurple]Simkl On Hold[/COLOR][/B]',
        'completed': '[B][COLOR mediumpurple]Simkl Completed[/COLOR][/B]',
        'dropped': '[B][COLOR FFE41B17]Simkl Dropped[/COLOR][/B]',
    }

    sections = [
        ('[B][COLOR mediumpurple]Simkl Account[/COLOR][/B]', 'simkl_account', m_icon, True, {}),
        ('[B][COLOR mediumpurple]Simkl [COLOR yellow]Up Next[/COLOR][/B]', 'simkl_upnext', m_icon, True, {}),
    ]
    for st in _STATUS_KEYS:
        sections.append((_counted(status_labels[st], counts.get(st, 0)), 'simkl_status_menu', m_icon, True, {'status': st}))
    sections += [
        (_counted('[B][COLOR mediumpurple]Simkl Ratings[/COLOR][/B]', rat_count), 'simkl_ratings_menu', m_icon, True, {}),
        ('[B][COLOR FFFF6600]Simkl [COLOR yellow]My Calendar[/COLOR][/B]', 'simkl_calendar', m_icon, True, {}),
        ('[B][COLOR FFFF6600]Simkl [COLOR white]Public Calendar[/COLOR][/B]', 'simkl_public_calendar', m_icon, True, {}),
        (_counted('[B][COLOR mediumpurple]Simkl Watched History[/COLOR][/B]', hist_count), 'simkl_history_menu', m_icon, True, {}),
    ]

    for label, action, icon, is_folder, extra in sections:
        if action == 'simkl_upnext':
            from resources.lib.watched_provider import is_simkl as _is_simkl_provider
            if not _is_simkl_provider():
                continue
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
        _add_dir(_build_url({'action': action, **extra}), li, is_folder)
    _end(cache=False)

def _view_account():
    _ensure_globals()
    art_path = _simkl_icon()
    from resources.lib.config import ADDON
    username = ADDON.getSetting('simkl_username') or 'Not set'
    status = ADDON.getSetting('simkl_status') or ('Connected' if is_authenticated() else 'Not connected')

    name = ''
    vip = ''
    joined = ''
    if is_authenticated():
        try:
            from resources.lib.simkl_api import SIMKLAPI
            info = SIMKLAPI().get_user_info()
            if isinstance(info, dict):
                name = info.get('name') or ''
                vip = info.get('vip') or ''
                joined = info.get('join_date') or ''
                live_user = info.get('username') or ''
                if live_user and live_user != ADDON.getSetting('simkl_username'):
                    ADDON.setSetting('simkl_username', live_user)
                    ADDON.setSetting('simkl_status', f'Connected: {live_user}')
                    username = live_user
                    status = f'Connected: {live_user}'
        except:
            pass

    labels = [
        ('[B][COLOR mediumpurple]Status: [COLOR FF6AFB92]%s[/COLOR][/B]' % status, None, False),
        ('[B][COLOR mediumpurple]Username: [COLOR yellow]%s[/COLOR][/B]' % username, None, False),
    ]
    if name:
        labels.append(('[B][COLOR mediumpurple]Name: [COLOR yellow]%s[/COLOR][/B]' % name, None, False))
    if vip:
        labels.append(('[B][COLOR mediumpurple]Account type: [COLOR yellow]%s[/COLOR][/B]' % vip, None, False))
    if joined:
        _jf = str(joined)[:10].split('-')
        if len(_jf) == 3:
            joined_fmt = f'{_jf[2]}.{_jf[1]}.{_jf[0]}'
        else:
            joined_fmt = str(joined)[:10]
        labels.append(('[B][COLOR mediumpurple]Member since: [COLOR yellow]%s[/COLOR][/B]' % joined_fmt, None, False))

    # --- Utilizare cont din mirror local (paritate trakt_account_info "Limits") ---
    if is_authenticated():
        wl_n = rat_n = drp_n = hist_m = hist_s = 0
        try:
            import sqlite3
            from resources.lib import simkl_sync
            from resources.lib.simkl_sync import DB_PATH
            simkl_sync.init_database()
            if os.path.exists(DB_PATH):
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM simkl_watchlist")
                wl_n = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM simkl_ratings")
                rat_n = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM simkl_dropped")
                drp_n = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM simkl_watched_movies")
                hist_m = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM simkl_watched_episodes")
                hist_s = c.fetchone()[0] or 0
                conn.close()
        except:
            pass
        labels.append(('[B][COLOR FFFDBD01]--- Account ---[/COLOR][/B]', None, False))
        labels.append(('  Watchlist: [B]%d[/B] items (movies + shows)' % wl_n, None, False))
        labels.append(('  Ratings: [B]%d[/B]' % rat_n, None, False))
        labels.append(('  Dropped: [B]%d[/B]' % drp_n, None, False))
        labels.append(('  History: [B]%d[/B] movies, [B]%d[/B] shows' % (hist_m, hist_s), None, False))

    if is_authenticated():
        labels.append(('[B][COLOR FFE41B17]Disconnect Simkl[/COLOR][/B]', 'simkl_disconnect', False))
    else:
        labels.append(('[B][COLOR FF6AFB92]Connect Simkl[/COLOR][/B]', 'simkl_connect', False))

    for label, action, is_folder in labels:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        if action:
            _add_dir(_build_url({'action': action}), li, is_folder)
        else:
            _add_dir(_build_url({}), li, False)
    _end(cache=False)

def _filter_fully_watched(data):
    """Exclude serialele fara episoade difuzate nevizionate din listele de status
    (paritate cu site-ul Simkl: 'Watching' arata DOAR serialele cu episoade
    DIFUZATE nevizionate — cele la zi cu difuzarea nu apar). Site-ul filtreaza
    pe aired (total - not_aired), nu pe total: Reacher 27/32 cu 5 ne-difuzate
    e la zi -> nu apare, desi w < t."""
    if not isinstance(data, dict):
        return data
    out = {}
    for key in ('shows', 'anime'):
        raw = data.get(key, []) or []
        kept = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            w = item.get('watched_episodes_count')
            t = item.get('total_episodes_count')
            na = item.get('not_aired_episodes_count')
            if not isinstance(w, int) or not isinstance(t, int) or t <= 0:
                kept.append(item)
                continue
            aired = t - (na if isinstance(na, int) else 0)
            if w >= aired:
                continue
            kept.append(item)
        out[key] = kept
    for key in ('movies',):
        out[key] = data.get(key, []) or []
    return out

def _fetch_status_items(status):
    """Itemii watchlist pe status din API live, cu cache TTL 15min (paritate lists_cache Redlight)."""
    from resources.lib.simkl_sync import get_cached, set_cached
    key = f'simkl_wl_{status}'
    data = get_cached(key, ttl=900)
    if data is None:
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        if not api.is_authenticated():
            return {}
        data = api.get_watchlist(status=status, extended='full') or {}
        if isinstance(data, dict):
            set_cached(key, data)
    if isinstance(data, dict) and status == 'watching':
        data = _filter_fully_watched(data)
    return data if isinstance(data, dict) else {}

def _add_import_dropped_buttons():
    """Butoane de import dropped din Trakt/MDBList — DOAR la seriale (TV Shows)."""
    _ensure_globals()
    art_path = _simkl_icon()
    if _ADDON.getSetting('trakt_access_token'):
        li = xbmcgui.ListItem(label='[B][COLOR mediumpurple]Import Dropped from Trakt[/COLOR][/B]')
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_import_dropped_trakt'}), li, False)
    if _ADDON.getSetting('mdblist_access_token') or _ADDON.getSetting('mdblist_api'):
        li = xbmcgui.ListItem(label='[B][COLOR mediumpurple]Import Dropped from MDBList[/COLOR][/B]')
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_import_dropped_mdblist'}), li, False)


def _view_status_menu(status):
    _ensure_globals()
    art_path = _simkl_icon()
    status = status or 'plantowatch'
    data = _fetch_status_items(status)
    if status == 'dropped':
        # Counter din mirror-ul local (paritate cu _view_status_items) — cache-ul
        # API poate fi stale (TTL 15min) dupa import.
        from resources.lib.simkl_sync import get_dropped_local
        data = {'shows': [None] * len(get_dropped_local())}

    def _counted(label, kind_key):
        count = len(data.get(kind_key, []) or [])
        if count > 0:
            return f'{label} [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        return label

    entries = [
        (_counted('[B][COLOR mediumpurple]Movies[/COLOR][/B]', 'movies'), 'movie'),
        (_counted('[B][COLOR mediumpurple]TV Shows[/COLOR][/B]', 'shows'), 'tv'),
        (_counted('[B][COLOR mediumpurple]Anime[/COLOR][/B]', 'anime'), 'anime'),
    ]
    for label, kind in entries:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_status_items', 'status': status, 'kind': kind, 'page': 1}), li, True)
    _end()

def _prefetch_or_fill(fake_items, mt, fill_timeout=12):
    """Prefetch paralel (deadline 1.1s) + fill pentru itemii ratati (semafor 8,
    join fill_timeout) — paritate trakt_api.py (lists). Fara fill, itemii pe care
    prefetch-ul nu-i apuca raman fara plot/poster (skip_details=True citeste
    DOAR cache-ul RAM pool/SQLite)."""
    if not fake_items:
        return
    from resources.lib.tmdb_api import prefetch_metadata_parallel, _get_cached_details, get_tmdb_item_details
    prefetch_metadata_parallel(fake_items, mt)
    missing = []
    for _it in fake_items:
        _tid = str(_it.get('id') or _it.get('tmdb_id') or '')
        _m = _it.get('media_type') or mt
        if _tid and _tid != 'None' and not _get_cached_details(_tid, _m):
            missing.append((_tid, _m))
    if missing:
        import threading as _th
        _sem = _th.Semaphore(8)
        def _fill(_t):
            try:
                with _sem:
                    get_tmdb_item_details(_t[0], _t[1], lightweight=True)
            except Exception:
                pass
        _ths = [_th.Thread(target=_fill, args=(t,), daemon=True) for t in missing]
        for _t in _ths:
            _t.start()
        for _t in _ths:
            _t.join(timeout=fill_timeout)

def _view_status_items(status, kind, page=1):
    _ensure_globals()
    kind = kind or 'tv'
    is_movie = kind == 'movie'
    xbmcplugin.setContent(_HANDLE, 'movies' if is_movie else 'tvshows')
    limit = _page_limit()
    page = int(page)
    status = status or 'plantowatch'

    data = _fetch_status_items(status)
    raw_items = data.get(_KIND_KEYS.get(kind, 'shows'), []) or []

    items = []
    if status == 'dropped' and kind == 'tv':
        # Dropped din mirror-ul local (paritate MDBList _view_dropped) — cache-ul API
        # poate fi stale (TTL 15min) dupa import; _sync_dropped e autoritatea.
        from resources.lib.simkl_sync import get_dropped_local
        for d in get_dropped_local():
            tmdb_id = str(d.get('tmdb_id') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            items.append({'tmdb_id': tmdb_id, 'title': d.get('title') or 'Unknown',
                          'year': '', 'media_type': 'tv'})
    else:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            inner = item.get('show') or item.get('movie') or item.get('anime') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            items.append({'tmdb_id': tmdb_id, 'title': inner.get('title') or inner.get('name') or 'Unknown',
                          'year': inner.get('year') or '', 'media_type': 'movie' if is_movie else 'tv'})

    if not items:
        if status == 'dropped' and kind == 'tv':
            _add_import_dropped_buttons()
        _empty('[No items in this status]')
        _end()
        return

    # Watching = echivalentul Trakt In Progress TV Shows — afisam TOATE pe o
    # singura pagina (fara paginare), paritate cu in_progress_tvshows.
    if status == 'watching':
        page_items = items
    else:
        start = (page - 1) * limit
        page_items = items[start:start + limit]

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, _get_cached_details
    mt = 'movie' if is_movie else 'tv'
    fake_items = [{'id': i['tmdb_id'], 'media_type': mt} for i in page_items]
    _prefetch_or_fill(fake_items, mt)

    is_dropped = status == 'dropped'
    if is_dropped and kind == 'tv':
        _add_import_dropped_buttons()
    for item in page_items:
        tmdb_id = item.get('tmdb_id')
        if not tmdb_id:
            continue
        fake_item = {'id': tmdb_id, 'title': item.get('title', ''), 'name': item.get('title', ''), 'overview': ''}
        processed = _process_movie_item(fake_item, return_data=True, skip_details=True) if is_movie \
            else _process_tv_item(fake_item, return_data=True, skip_details=True)
        if not processed:
            continue
        li = processed['li']
        if is_dropped:
            label = f'[B][COLOR FFE41B17]{processed.get("label", "")}[/COLOR][/B]'
            li.setLabel(label)
            cm = [('[B][COLOR FF6AFB92]Restore Show[/COLOR][/B]',
                   f"RunPlugin({_build_url({'action': 'simkl_dropped_restore', 'tmdb_id': tmdb_id, 'mediatype': mt, 'title': processed.get('label', '')})})")]
            li.addContextMenuItems(cm)
        _add_dir(processed['url'], li, processed['is_folder'])

    if status != 'watching' and page * limit < len(items):
        li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        li.setArt({'icon': _simkl_icon(), 'thumb': _simkl_icon(), 'poster': _simkl_icon()})
        _add_dir(_build_url({'action': 'simkl_status_items', 'status': status, 'kind': kind, 'page': page + 1}), li, True)
    _end()

def _add_import_ratings_buttons():
    """Butoane de import ratings din Trakt/MDBList (filme + seriale + episoade)."""
    _ensure_globals()
    art_path = _simkl_icon()
    if _ADDON.getSetting('trakt_access_token'):
        li = xbmcgui.ListItem(label='[B][COLOR mediumpurple]Import Ratings from Trakt[/COLOR][/B]')
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_import_ratings_trakt'}), li, False)
    if _ADDON.getSetting('mdblist_access_token') or _ADDON.getSetting('mdblist_api'):
        li = xbmcgui.ListItem(label='[B][COLOR mediumpurple]Import Ratings from MDBList[/COLOR][/B]')
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_import_ratings_mdblist'}), li, False)


def _view_ratings_menu():
    _ensure_globals()
    art_path = _simkl_icon()
    from resources.lib import simkl_sync
    movie_count = 0
    show_count = 0
    if os.path.exists(simkl_sync.DB_PATH):
        try:
            conn = simkl_sync.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM simkl_ratings WHERE media_type='movie'")
            row = c.fetchone()
            movie_count = row[0] if row else 0
            c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM simkl_ratings WHERE media_type IN ('show','episode')")
            row = c.fetchone()
            show_count = row[0] if row else 0
            conn.close()
        except:
            pass
    _add_import_ratings_buttons()
    for label, db_type, mtype in [('Movies', 'movie', 'movie'), ('TV Shows', 'tv', 'show')]:
        count = movie_count if db_type == 'movie' else show_count
        display = f'[B][COLOR mediumpurple]{label}[/COLOR][/B]'
        if count > 0:
            display = f'{display} [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=display)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_ratings_items', 'mediatype': mtype, 'page': 1}), li, True)
    _end()

def _view_ratings_items(mediatype, page=1):
    _ensure_globals()
    kodi_content = 'movies' if mediatype == 'movie' else 'tvshows'
    xbmcplugin.setContent(_HANDLE, kodi_content)
    limit = _page_limit()
    page = int(page)

    from resources.lib import simkl_sync
    items = []
    if os.path.exists(simkl_sync.DB_PATH):
        conn = simkl_sync.get_connection()
        c = conn.cursor()
        try:
            if mediatype == 'movie':
                c.execute("SELECT tmdb_id, rating FROM simkl_ratings WHERE media_type='movie' ORDER BY rated_at DESC")
            else:
                c.execute("SELECT tmdb_id, rating FROM simkl_ratings WHERE media_type IN ('show','episode') ORDER BY rated_at DESC")
            rows = c.fetchall()
        except:
            rows = []
        conn.close()
        items = [{'tmdb_id': r[0], 'title': '', 'rating': r[1]} for r in rows]

    if not items:
        _empty('[No ratings found]')
        _end()
        return

    start = (page - 1) * limit
    page_items = items[start:start + limit]

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, _get_cached_details
    fake_items = [{'id': i['tmdb_id'], 'media_type': mediatype} for i in page_items]
    _prefetch_or_fill(fake_items, mediatype)

    for item in page_items:
        tmdb_id = item.get('tmdb_id')
        if not tmdb_id:
            continue
        cached = _get_cached_details(tmdb_id, mediatype)
        title = (cached or {}).get('title') or (cached or {}).get('name') or ''
        fake_item = {'id': tmdb_id, 'title': title, 'name': title, 'overview': ''}
        if mediatype == 'movie':
            processed = _process_movie_item(fake_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True, skip_details=True)
        if processed:
            li = processed['li']
            rating = item.get('rating')
            if rating:
                label = f'{processed.get("label", "")} [B][COLOR lime]★ {rating}/10[/COLOR][/B]'
                li.setLabel(label)
            _add_dir(processed['url'], li, processed['is_folder'])

    if page * limit < len(items):
        li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        li.setArt({'icon': _simkl_icon(), 'thumb': _simkl_icon(), 'poster': _simkl_icon()})
        _add_dir(_build_url({'action': 'simkl_ratings_items', 'mediatype': mediatype, 'page': page + 1}), li, True)
    _end()

def _load_calendar_data():
    """Payload CDN v2 (tv+anime) din cache (TTL 24h, actualizat de sync-ul de 30min)
    sau API. Returneaza (cal_list, meta)."""
    from resources.lib.simkl_sync import get_cached, set_cached
    data = get_cached('calendar', ttl=86400)
    if data is None:
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        data = api.calendar_events()
        if data is not None:
            set_cached('calendar', data)
    if not isinstance(data, dict):
        return None, None
    cal_list = data.get('calendar')
    meta = data.get('metadata')
    if not isinstance(cal_list, list) or not isinstance(meta, dict):
        return None, None
    return cal_list, meta

def _calendar_window():
    import datetime as _dt
    _CAL_PREV = [0, 1, 3, 7, 14, 30]
    _CAL_FUT = [7, 14, 21, 30, 60, 90]
    prev_days = _CAL_PREV[int(_ADDON.getSetting('mdblist_cal_previous_days') or 0)]
    fut_days = _CAL_FUT[int(_ADDON.getSetting('mdblist_cal_future_days') or 3)]
    sort_asc = int(_ADDON.getSetting('mdblist_cal_sort_order') or 0) == 0
    today_top = _ADDON.getSetting('mdblist_cal_today_top') != 'false'
    today = _dt.date.today()
    return {
        'prev_days': prev_days,
        'fut_days': fut_days,
        'sort_asc': sort_asc,
        'today_top': today_top,
        'today': today,
        'start': today - _dt.timedelta(days=prev_days),
        'end': today + _dt.timedelta(days=fut_days),
    }

def _parse_calendar_episodes(cal_list, meta, wnd, tmdb_filter=None):
    """Extrage episoadele din CDN in fereastra; optional filtrat pe set de tmdb_id (My Calendar)."""
    import datetime as _dt
    entries = []
    seen = set()
    for item in cal_list:
        if not isinstance(item, dict):
            continue
        simkl_id = item.get('simkl_id')
        show_info = (meta.get(str(simkl_id)) or {}) if simkl_id is not None else {}
        ids = show_info.get('ids') or {}
        tmdb_id = str(ids.get('tmdb', '') or '')
        if not tmdb_id:
            continue
        if tmdb_filter is not None and tmdb_id not in tmdb_filter:
            continue
        ep = item.get('episode') or {}
        season = int(ep.get('season', 0) or 0)
        episode = int(ep.get('episode', 0) or 0)
        date_str = str(item.get('date', ''))[:10]
        try:
            d = _dt.date.fromisoformat(date_str)
        except Exception:
            continue
        if d < wnd['start'] or d > wnd['end']:
            continue
        key = (tmdb_id, season, episode)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            'media_type': 'tv',
            'tmdb_id': tmdb_id,
            'show_title': show_info.get('title', ''),
            'season': season,
            'episode': episode,
            'ep_title': ep.get('title', ''),
            'air_date': date_str,
            'diff': (d - wnd['today']).days,
            'poster': show_info.get('poster', ''),
            'fanart': show_info.get('fanart', ''),
        })
    return entries

def _view_calendar(page=1):
    """My Calendar: episoade din CDN (tv+anime) pentru serialele din watchlist
    (watching/plantowatch) + filmele din watchlist cu data premierei in fereastra."""
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'episodes')

    wnd = _calendar_window()
    cal_list, meta = _load_calendar_data()
    if not cal_list:
        _empty('[No Calendar Events]')
        _end()
        return

    from resources.lib.simkl_sync import get_watchlist_local
    wl = get_watchlist_local() or []
    watch_tv = set()
    watch_movies = []
    for row in wl:
        mt = str(row.get('media_type', '') or '')
        st = str(row.get('status', '') or '')
        if st not in ('watching', 'plantowatch'):
            continue
        tid = str(row.get('tmdb_id', '') or '')
        if not tid:
            continue
        if mt == 'movie':
            watch_movies.append(row)
        else:
            watch_tv.add(tid)

    entries = []
    if watch_tv:
        entries = _parse_calendar_episodes(cal_list, meta, wnd, tmdb_filter=watch_tv)

    # Filme din watchlist cu data premierei (din TMDb) in fereastra.
    # Prefetch paralel NON-BLOCKING (deadline 1.1s) — paritate cu calendarul
    # Trakt/MDBList; filmele ratate de prefetch se completeaza la a 2-a vizita
    # (SQLite populat de persist-ul din _render_calendar_entries).
    if watch_movies:
        import datetime as _dt
        from resources.lib.config import IMG_BASE, BACKDROP_BASE
        from resources.lib.tmdb_api import _get_cached_details
        fake_movies = [{'id': str(r.get('tmdb_id', '')), 'media_type': 'movie'} for r in watch_movies]
        # Fill paralel marginit (semafor 8, join 8s) — NU secvential: 259 filme
        # secvential = minute de blocare. Itemii ratati sunt sariti la prima
        # vizita si apar la a 2-a (SQLite populat de persist).
        _prefetch_or_fill(fake_movies, 'movie', fill_timeout=8)
        for row in watch_movies:
            tid = str(row.get('tmdb_id', ''))
            details = _get_cached_details(tid, 'movie')
            if not details:
                continue
            rd = (details.get('release_dates') or {}).get('results') or []
            date_str = ''
            for r in rd:
                if str(r.get('iso_3166_1', '')).upper() == 'US':
                    date_str = str(((r.get('release_dates') or [{}])[0] or {}).get('release_date', ''))[:10]
                    break
            if not date_str:
                for r in rd:
                    ds = str(((r.get('release_dates') or [{}])[0] or {}).get('release_date', ''))[:10]
                    if ds:
                        date_str = ds
                        break
            if not date_str:
                continue
            try:
                d = _dt.date.fromisoformat(date_str)
            except Exception:
                continue
            if d < wnd['start'] or d > wnd['end']:
                continue
            entries.append({
                'media_type': 'movie',
                'tmdb_id': tid,
                'show_title': row.get('title', '') or details.get('title', ''),
                'season': 0,
                'episode': 0,
                'ep_title': '',
                'air_date': date_str,
                'diff': (d - wnd['today']).days,
                'poster': f"{IMG_BASE}{details.get('poster_path', '')}" if details.get('poster_path') else '',
                'fanart': f"{BACKDROP_BASE}{details.get('backdrop_path', '')}" if details.get('backdrop_path') else '',
            })

    if not entries:
        _empty('[No Calendar Events]')
        _end()
        return
    _render_calendar_entries(entries, wnd)

def _view_public_calendar(page=1):
    """Public Calendar: toate intrarile CDN (tv+anime), cap 250 cele mai apropiate de azi."""
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'episodes')

    wnd = _calendar_window()
    cal_list, meta = _load_calendar_data()
    if not cal_list:
        _empty('[No Calendar Events]')
        _end()
        return

    entries = _parse_calendar_episodes(cal_list, meta, wnd)
    if len(entries) > 250:
        entries.sort(key=lambda e: abs(e['diff']))
        entries = entries[:250]
    if not entries:
        _empty('[No Calendar Events]')
        _end()
        return
    _render_calendar_entries(entries, wnd)

def _render_calendar_entries(entries, wnd):
    import datetime as _dt
    from resources.lib.config import IMG_BASE, BACKDROP_BASE, calendar_localized_label
    from resources.lib.tmdb_api import set_metadata, _get_full_context_menu, _get_cached_details
    from resources.lib.watched_provider import is_episode_watched as _wp_is_epw, is_movie_watched as _wp_is_mw

    fake_items = [{'id': e['tmdb_id'], 'media_type': 'tv' if e['media_type'] == 'tv' else 'movie'} for e in entries]
    # Prefetch doar itemii lipsa din cache (pool/SQLite) — evita rate-limit TMDb la 500 itemi.
    # NON-BLOCKING (deadline 1.1s intern) + persist in background — paritate cu
    # calendarul Trakt/MDBList: prima vizita instant, a 2-a cu tot (SQLite).
    try:
        need = []
        for it in fake_items:
            if not _get_cached_details(str(it['id']), it['media_type']):
                need.append(it)
        if need:
            from resources.lib.tmdb_api import prefetch_metadata_parallel as _pmp
            _pmp(need, 'tv' if entries[0]['media_type'] == 'tv' else 'movie')
    except Exception:
        from resources.lib.tmdb_api import prefetch_metadata_parallel as _pmp
        _pmp(fake_items, 'tv' if entries[0]['media_type'] == 'tv' else 'movie')

    # Persist pool-ul prefetch in SQLite (background) — vizitele urmatoare au
    # poster/plot/fanart din cache zero-HTTP (paritate Redlight tvshow_meta).
    try:
        import threading
        from resources.lib.cache import ram_pool_get
        from resources.lib.config import get_plot_language_code

        def _persist():
            try:
                from resources.lib import trakt_sync as _ts
                cur_lang = get_plot_language_code()
                conn = _ts.get_connection()
                for it in fake_items:
                    tid = str(it.get('id') or '')
                    if not tid or tid == 'None':
                        continue
                    d = ram_pool_get(tid)
                    if not d or not isinstance(d, dict):
                        continue
                    if d.get('_cached_lang') != cur_lang:
                        continue
                    try:
                        _ts.set_tmdb_item_details_to_db(conn.cursor(), tid, it.get('media_type') or 'tv', d)
                    except Exception:
                        pass
                try:
                    conn.commit()
                except Exception:
                    pass
                conn.close()
            except Exception:
                pass
        threading.Thread(target=_persist, daemon=True).start()
    except Exception:
        pass

    items_to_add = []
    for e in entries:
        tmdb_id = e['tmdb_id']
        is_movie = e['media_type'] == 'movie'

        cached = _get_cached_details(tmdb_id, 'movie' if is_movie else 'tv') or {}
        title_key = 'title' if is_movie else 'name'
        show_title = cached.get(title_key, '') or e['show_title'] or 'Unknown Show'
        poster = ''
        fanart = ''
        pp = cached.get('poster_path', '')
        if pp:
            poster = f"{IMG_BASE}{pp}"
        bd = cached.get('backdrop_path', '')
        if bd:
            fanart = f"{BACKDROP_BASE}{bd}"
        plot = cached.get('overview', '') or ''

        diff = e['diff']
        try:
            d = _dt.date.fromisoformat(str(e['air_date']))
            date_label = calendar_localized_label(diff, d)
        except:
            date_label = str(e['air_date'])
        if diff == 0:
            date_color = 'white'
        elif diff < 0:
            date_color = 'FF00FA9A'
        else:
            date_color = 'yellow'

        if is_movie:
            movie_year = str(e['air_date'])[:4] if e['air_date'] else ''
            display_title = f'{show_title} ({movie_year})' if movie_year else show_title
            display = f'[B][COLOR FFFF6600]{display_title}[/COLOR][/B]'
        else:
            ep_label = f'S{e["season"]:02d}E{e["episode"]:02d}' if e['season'] else ''
            display = f'[B][COLOR mediumpurple]{show_title}[/COLOR][/B]'
            if ep_label:
                display += f' - [B][COLOR {date_color}]{ep_label}[/COLOR][/B]'
            if e.get('ep_title'):
                display += f' - [B][I][COLOR FFCCCCFF]{e["ep_title"]}[/I][/COLOR][/B]'
        if date_label:
            display += f' [COLOR {date_color}] • [B]{date_label}[/B][/COLOR]'

        li = xbmcgui.ListItem(display)
        li.setProperty('cal_diff', str(diff))
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': fanart})
        if is_movie:
            watched = _wp_is_mw(tmdb_id)
            info = {'mediatype': 'movie', 'title': show_title}
        else:
            watched = _wp_is_epw(tmdb_id, e['season'], e['episode'])
            ep_label = f'S{e["season"]:02d}E{e["episode"]:02d}' if e['season'] else ''
            info = {'mediatype': 'episode', 'title': e['ep_title'] or ep_label, 'tvshowtitle': show_title,
                    'season': e['season'], 'episode': e['episode']}
        if plot:
            info['plot'] = plot
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id}, watched_info=watched)
        if is_movie:
            cm = _get_full_context_menu(tmdb_id, 'movie', show_title)
        else:
            cm = _get_full_context_menu(tmdb_id, 'episode', show_title, season=e['season'], episode=e['episode'])
            b_show_params = urllib.parse.urlencode({'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': show_title})
            cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({_BASE_URL}?{b_show_params})"))
            b_season_params = urllib.parse.urlencode({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(e['season']), 'tv_show_title': show_title})
            cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({_BASE_URL}?{b_season_params})"))
        if cm:
            li.addContextMenuItems(cm)
        if is_movie:
            if diff <= 0:
                url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': show_title}
                is_folder = False
            else:
                url_params = {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': show_title}
                is_folder = True
        elif diff <= 0:
            url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(e['season']),
                          'episode': str(e['episode']), 'title': f"{show_title} S{e['season']:02d}E{e['episode']:02d}",
                          'tv_show_title': show_title}
            is_folder = False
        else:
            url_params = {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(e['season']), 'tv_show_title': show_title}
            is_folder = True
        url = f"{_BASE_URL}?{urllib.parse.urlencode(url_params)}"
        items_to_add.append((url, li, is_folder))

    today_top = wnd['today_top']
    sort_asc = wnd['sort_asc']
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
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))
    _end()

def _view_history_menu():
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'videos')
    art_path = _simkl_icon()

    for label, db_type, url_type in [('Movies', 'movie', 'movie'), ('TV Shows', 'tv', 'show')]:
        count = 0
        try:
            from resources.lib.simkl_sync import DB_PATH as SIMKL_DB_PATH, get_connection
            if os.path.exists(SIMKL_DB_PATH):
                conn = get_connection()
                c = conn.cursor()
                if db_type == 'movie':
                    c.execute("SELECT COUNT(*) FROM simkl_watched_movies")
                else:
                    c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM simkl_watched_episodes")
                row = c.fetchone()
                count = row[0] if row else 0
                conn.close()
        except:
            pass
        display = f'[B][COLOR mediumpurple]{label}[/COLOR][/B]'
        if count > 0:
            display = f'{display} [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=display)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'simkl_history_items', 'mediatype': url_type, 'offset': 0}), li, True)
    _end()

def _view_history_items(mediatype, offset=0):
    _ensure_globals()
    kodi_content = 'movies' if mediatype == 'movie' else 'tvshows'
    xbmcplugin.setContent(_HANDLE, kodi_content)
    limit = _page_limit()
    offset = int(offset)

    items, total = fetch_history(mediatype, offset=offset, limit=limit)

    empty_label = '[No watched movies found]' if mediatype == 'movie' else '[No watched shows found]'
    if not items:
        _empty(empty_label)
        _end()
        return

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item

    fake_items = []
    for item in items:
        inner = item.get('movie') if mediatype == 'movie' else item.get('show')
        if not inner:
            continue
        tmdb_id = inner.get('ids', {}).get('tmdb')
        if tmdb_id:
            fake_items.append({'id': tmdb_id, 'media_type': mediatype})
    _prefetch_or_fill(fake_items, mediatype)

    for item in items:
        inner = item.get('movie') if mediatype == 'movie' else item.get('show')
        if not inner:
            continue
        tmdb_id = inner.get('ids', {}).get('tmdb')
        if not tmdb_id:
            continue
        fake_item = {
            'id': tmdb_id,
            'title': inner.get('title', ''),
            'name': inner.get('title', ''),
            'overview': '',
        }
        if mediatype == 'movie':
            processed = _process_movie_item(fake_item, return_data=True, skip_details=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True, skip_details=True)
        if processed:
            _add_dir(processed['url'], processed['li'], processed['is_folder'])

    if offset + limit < total:
        li = xbmcgui.ListItem(label=f'[B]Next Page >>[/B]')
        li.setArt({'icon': _simkl_icon(), 'thumb': _simkl_icon(), 'poster': _simkl_icon()})
        _add_dir(_build_url({'action': 'simkl_history_items', 'mediatype': mediatype, 'offset': offset + limit}), li, True)
    _end()

def _view_upnext():
    """Delegatie catre Next Episodes dinamic (identic cu TV Shows -> Next Episodes)."""
    from resources.lib.tmdb_api import get_next_episodes as _dynamic_next
    return _dynamic_next(None)

# ------------------------------------------------------------------
# WATCHLIST MUTATIONS (din context menu tmdb_api)
# ------------------------------------------------------------------
def watchlist_add(tmdb_id=None, mediatype='movie', status='watching', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        result = api.watchlist_add(mediatype, tmdb_id, status=status)
        if result is not None:
            from resources.lib.simkl_sync import watchlist_add_local
            watchlist_add_local(tmdb_id, mediatype, title, '', status)
            if notify:
                _notify('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] added to [B][COLOR mediumpurple]{status}[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[SIMKL] watchlist_add error: {e}', xbmc.LOGERROR)
    return False

def watchlist_remove(tmdb_id=None, mediatype='movie', status='watching', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        result = api.watchlist_remove(mediatype, tmdb_id, status=status)
        if result is not None:
            from resources.lib.simkl_sync import watchlist_remove_local
            watchlist_remove_local(tmdb_id)
            if notify:
                _notify('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] removed from [B][COLOR mediumpurple]{status}[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[SIMKL] watchlist_remove error: {e}', xbmc.LOGERROR)
    return False

# ------------------------------------------------------------------
# ACTION DISPATCH
# ------------------------------------------------------------------
def handle_simkl_action(params, handle, base_url, addon):
    action = params.get('mode', params.get('action', ''))
    if action not in SIMKL_ACTIONS and action not in ('simkl_dropped_restore', 'simkl_connect', 'simkl_disconnect'):
        return False

    _ensure_globals()
    global _HANDLE, _BASE_URL
    _HANDLE = handle
    _BASE_URL = base_url

    if action == 'simkl_menu':
        _view_menu()
    elif action == 'simkl_account':
        _view_account()
    elif action == 'simkl_connect':
        from resources.lib.simkl_api import simkl_auth as _simkl_auth_flow
        _simkl_auth_flow()
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_disconnect':
        from resources.lib.simkl_api import simkl_revoke as _simkl_revoke_flow
        _simkl_revoke_flow()
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_upnext':
        _view_upnext()
    elif action == 'simkl_status_menu':
        _view_status_menu(params.get('status', 'plantowatch'))
    elif action == 'simkl_status_items':
        _view_status_items(params.get('status', 'plantowatch'), params.get('kind', 'tv'), int(params.get('page', '1')))
    elif action == 'simkl_ratings_menu':
        _view_ratings_menu()
    elif action == 'simkl_ratings_items':
        _view_ratings_items(params.get('mediatype', 'movie'), int(params.get('page', '1')))
    elif action == 'simkl_dropped_restore':
        from resources.lib.simkl_sync import restore_show
        _mt = 'movie' if str(params.get('mediatype', '')).lower() in ('movie', 'movies') else 'show'
        if restore_show(params.get('tmdb_id'), _mt):
            _notify('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                    f'[B][COLOR yellow]{params.get("title", "")}[/COLOR][/B] restored')
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_import_dropped_trakt':
        from resources.lib.simkl_sync import import_dropped_from_trakt
        import_dropped_from_trakt(silent=False)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_import_dropped_mdblist':
        from resources.lib.simkl_sync import import_dropped_from_mdblist
        import_dropped_from_mdblist(silent=False)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_import_ratings_trakt':
        from resources.lib.simkl_sync import import_ratings_from_trakt
        import_ratings_from_trakt(silent=False)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_import_ratings_mdblist':
        from resources.lib.simkl_sync import import_ratings_from_mdblist
        import_ratings_from_mdblist(silent=False)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'simkl_calendar':
        _view_calendar(int(params.get('page', '1')))
    elif action == 'simkl_public_calendar':
        _view_public_calendar(int(params.get('page', '1')))
    elif action == 'simkl_history_menu':
        _view_history_menu()
    elif action == 'simkl_history_items':
        _view_history_items(params.get('mediatype', 'movie'), int(params.get('offset', '0')))
    else:
        return False
    return True
