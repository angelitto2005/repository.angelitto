# -*- coding: utf-8 -*-
import sys
import os
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmc

from resources.lib.config import ADDON as PROXIED_ADDON, PUNCHPLAY_COLOR, provider_color, provider_icon, provider_title
from resources.lib.utils import select_ext_info_params, calendar_row_click_params, sort_calendar_items, calendar_context_menu, process_media_item

PUNCHPLAY_ACTIONS = {
    'punchplay_menu',
    'punchplay_account',
    'punchplay_watchlist',
    'punchplay_watchlist_menu',
    'punchplay_watchlist_items',
    'punchplay_upnext',
    'punchplay_history_menu',
    'punchplay_history_items',
    'punchplay_favourites',
    'punchplay_favourites_menu',
    'punchplay_favourites_items',
    'punchplay_favourite_add',
    'punchplay_favourite_remove',
    'punchplay_collection',
    'punchplay_calendar',
    'punchplay_dropped',
    'punchplay_public_lists',
    'punchplay_catalog_menu',
    'punchplay_catalog',
    'punchplay_my_lists',
    'punchplay_my_list_items',
}

_HANDLE = None
_BASE_URL = None
_ADDON = None

def _ensure_globals():
    global _ADDON, _BASE_URL, _HANDLE
    if _ADDON is None:
        _ADDON = PROXIED_ADDON
    if _BASE_URL is None:
        _BASE_URL = sys.argv[0]
    if _HANDLE is None:
        try: _HANDLE = int(sys.argv[1])
        except: _HANDLE = -1

def _pp_icon():
    return provider_icon('punchplay')

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
    xbmcgui.Dialog().notification(title, msg, icon or _pp_icon(), ms, False)

def is_authenticated():
    from resources.lib.punchplay_api import PunchplayAPI
    return PunchplayAPI().is_authenticated()

def _end(succeeded=True, cache=True):
    _ensure_globals()
    xbmcplugin.endOfDirectory(_HANDLE, succeeded=succeeded, cacheToDisc=cache)

def _add_dir(url, li, is_folder=True):
    _ensure_globals()
    xbmcplugin.addDirectoryItem(_HANDLE, url, li, is_folder)

def _empty(label):
    _add_dir(_build_url({}), xbmcgui.ListItem(label=label), False)

def _view_menu():
    _ensure_globals()
    m_icon = _pp_icon()
    counts = {}
    fav_count = 0
    hist_count = 0
    coll_count = 0
    drop_count = 0
    try:
        from resources.lib.punchplay_sync import get_connection, DB_PATH, get_history_counts, get_collection_local
        if os.path.exists(DB_PATH):
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT media_type, COUNT(*) FROM punchplay_watchlist GROUP BY media_type")
            for r in c.fetchall():
                counts[str(r[0] or '')] = r[1] or 0
            try:
                rows = get_collection_local()
                coll_count = len(rows)
            except:
                coll_count = 0
            try:
                c.execute("SELECT COUNT(*) FROM punchplay_dropped")
                drop_count = (c.fetchone() or [0])[0] or 0
            except:
                drop_count = 0
            conn.close()
            hm, hs = get_history_counts()
            hist_count = hm + hs
    except:
        pass
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        _fav_data = PunchplayAPI().get_favourites(page=1) or {}
        fav_count = int(_fav_data.get('total') or len(_fav_data.get('items') or []) or 0)
    except:
        pass

    def _counted(label, count):
        return f'{label} [B][COLOR FFFDBD01]({count})[/COLOR][/B]'

    wl_m = counts.get('movie', 0)
    wl_t = counts.get('tv', 0) + counts.get('show', 0)
    wl_total = wl_m + wl_t
    sections = [
        (f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Account[/COLOR][/B]', 'punchplay_account', m_icon, True, {}),
        (f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay [COLOR yellow]Up Next[/COLOR][/B]', 'punchplay_upnext', m_icon, True, {}),
        (_counted(f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Watchlist[/COLOR][/B]', wl_total), 'punchplay_watchlist', m_icon, True, {}),
        (_counted(f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Favourites[/COLOR][/B]', fav_count), 'punchplay_favourites', m_icon, True, {'page': 1}),
        (_counted(f'[B][COLOR {PUNCHPLAY_COLOR}]My Lists[/COLOR][/B]', _my_lists_count()), 'punchplay_my_lists', m_icon, True, {}),
        (f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Public Lists[/COLOR][/B]', 'punchplay_public_lists', m_icon, True, {}),
        (_counted(f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Collection[/COLOR][/B]', coll_count), 'punchplay_collection', m_icon, True, {}),
        (f'[B][COLOR FFFF6600]PunchPlay [COLOR yellow]My Calendar[/COLOR][/B]', 'punchplay_calendar', m_icon, True, {}),
        (_counted(f'[B][COLOR FFE41B17]PunchPlay Dropped Shows[/COLOR][/B]', drop_count), 'punchplay_dropped', m_icon, True, {}),
        (_counted(f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Watched History[/COLOR][/B]', hist_count), 'punchplay_history_menu', m_icon, True, {}),
    ]
    for label, action, icon, is_folder, extra in sections:
        if action == 'punchplay_upnext':
            try:
                from resources.lib.watched_provider import is_punchplay as _is_pp
                if not _is_pp():
                    continue
            except:
                pass
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
        _add_dir(_build_url({'action': action, **extra}), li, is_folder)
    _end(cache=False)

def _view_account():
    _ensure_globals()
    from resources.lib.config import ADDON
    art_path = _pp_icon()
    username = ADDON.getSetting('punchplay_username') or 'Not set'
    status = ADDON.getSetting('punchplay_status') or ('Connected' if is_authenticated() else 'Not connected')
    member_since = ''
    stats = {}
    if is_authenticated():
        try:
            from resources.lib.punchplay_api import PunchplayAPI
            info = PunchplayAPI().get_user_info()
            if isinstance(info, dict):
                live_user = info.get('username') or ''
                if live_user and live_user != ADDON.getSetting('punchplay_username'):
                    ADDON.setSetting('punchplay_username', live_user)
                    ADDON.setSetting('punchplay_status', f'Connected: {live_user}')
                    username = live_user
                    status = f'Connected: {live_user}'
                member_since = info.get('join_date') or ''
                stats = info.get('stats') or {}
        except:
            pass
    try:
        _ms = str(member_since)[:10].split('-')
        joined_fmt = f'{_ms[2]}.{_ms[1]}.{_ms[0]}' if len(_ms) == 3 else str(member_since)[:10]
    except:
        joined_fmt = ''
    labels = [
        (f'[B][COLOR {PUNCHPLAY_COLOR}]Status: [COLOR FF6AFB92]{status}[/COLOR][/B]', None, False),
        (f'[B][COLOR {PUNCHPLAY_COLOR}]Username: [COLOR yellow]{username}[/COLOR][/B]', None, False),
    ]
    if joined_fmt:
        labels.append((f'[B][COLOR {PUNCHPLAY_COLOR}]Member since: [COLOR yellow]{joined_fmt}[/COLOR][/B]', None, False))
    if isinstance(stats, dict) and stats:
        labels.append((f"[B][COLOR {PUNCHPLAY_COLOR}]Watched: [COLOR yellow]{stats.get('titlesWatched', 0)} titles, {stats.get('episodesWatched', 0)} episodes, {stats.get('minutesWatched', 0)} minutes[/COLOR][/B]", None, False))
    wl_m = wl_t = rat_n = drop_n = 0
    hist_m = hist_s = 0
    try:
        from resources.lib.punchplay_sync import get_connection, DB_PATH, get_history_counts
        if os.path.exists(DB_PATH):
            conn = get_connection()
            c = conn.cursor()
            try:
                c.execute("SELECT COUNT(*) FROM punchplay_watchlist WHERE media_type='movie'")
                wl_m = (c.fetchone() or [0])[0] or 0
                c.execute("SELECT COUNT(*) FROM punchplay_watchlist WHERE media_type IN ('tv','show')")
                wl_t = (c.fetchone() or [0])[0] or 0
                c.execute("SELECT COUNT(*) FROM punchplay_ratings WHERE rating IS NOT NULL")
                rat_n = (c.fetchone() or [0])[0] or 0
                c.execute("SELECT COUNT(*) FROM punchplay_dropped")
                drop_n = (c.fetchone() or [0])[0] or 0
            except:
                pass
            conn.close()
            hist_m, hist_s = get_history_counts()
    except:
        pass
    labels.append(('[B][COLOR FFFDBD01]--- Account ---[/COLOR][/B]', None, False))
    labels.append((f'  Watchlist: [B]{wl_m + wl_t}[/B] items ([B]{wl_m}[/B] Movies + [B]{wl_t}[/B] Shows)', None, False))
    labels.append((f'  Ratings Given: [B]{rat_n}[/B]', None, False))
    labels.append((f'  Dropped Shows: [B]{drop_n}[/B]', None, False))
    labels.append((f'  History: [B]{hist_m}[/B] movies, [B]{hist_s}[/B] shows', None, False))
    if not is_authenticated():
        labels.append((f'[B][COLOR FF6AFB92]Connect PunchPlay[/COLOR][/B]', 'punchplay_connect', False))
    for label, action, is_folder in labels:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        if action:
            _add_dir(_build_url({'action': action}), li, is_folder)
        else:
            _add_dir(_build_url({}), li, False)
    _end(cache=False)

def _prefetch_or_fill(fake_items, mt):
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
        for t in missing:
            _th.Thread(target=_fill, args=(t,), daemon=True).start()

def _render_tmdb_rows(rows, mt, page=1, next_action=None, next_extra=None, dropped_mode=False, end_dir=True):
    _ensure_globals()
    from resources.lib.utils import sort_personal_list
    items = []
    for r in rows or []:
        tid = str(r.get('tmdb_id') or '')
        if not tid or tid == 'None':
            continue
        items.append({'tmdb_id': tid, 'title': r.get('title') or 'Unknown', 'year': r.get('year') or '', 'media_type': r.get('media_type') or mt,
                      'rating': r.get('rating')})
    if not items:
        _empty('[No items]')
        if end_dir:
            _end()
        return
    items = sort_personal_list(items)
    limit = _page_limit()
    page = max(int(page or 1), 1)
    page_items = items[(page - 1) * limit:page * limit]
    from resources.lib.tmdb_api import _get_cached_details
    fake_by_mt = {}
    for i in page_items:
        _m = i.get('media_type') or mt
        if mt == 'mixed':
            _m = i.get('media_type') or 'movie'
        fake_by_mt.setdefault(_m, []).append({'id': i['tmdb_id'], 'media_type': _m})
    for _m, _fake in fake_by_mt.items():
        _prefetch_or_fill(_fake, _m)
    for item in page_items:
        try:
            tmdb_id = item.get('tmdb_id')
            _mt = item.get('media_type') or mt
            if mt == 'mixed':
                _mt = item.get('media_type') or 'movie'
            is_movie = _mt == 'movie'
            _title = item.get('title') or ''
            if _title in ('', 'Unknown'):
                try:
                    _cached = _get_cached_details(str(tmdb_id), _mt) or {}
                    _cached_title = _cached.get('title' if is_movie else 'name') or ''
                    try:
                        from resources.lib.tmdb_api import _NON_LATIN_RE as _nl_re
                        _latin = bool(_cached_title) and not _nl_re.search(_cached_title)
                    except Exception:
                        _latin = bool(_cached_title)
                    if _latin:
                        _title = _cached_title
                    if not item.get('year') and _cached:
                        item['year'] = str(_cached.get('release_date') or _cached.get('first_air_date') or '')[:4]
                except:
                    pass
            fake_item = {'id': tmdb_id, 'title': _title, 'name': _title, 'overview': ''}
            processed = process_media_item(fake_item, is_movie)
            if not processed:
                continue
            li = processed['li']
            try:
                if item.get('rating'):
                    li.setLabel(f"{processed.get('label', '')} [B][COLOR gold]({item.get('rating')}/10)[/COLOR][/B]")
            except:
                pass
            if dropped_mode and not is_movie:
                from resources.lib.tmdb_api import _get_full_context_menu
                cm = list(_get_full_context_menu(str(tmdb_id), 'tv', item.get('title', '')) or [])
                try:
                    li.addContextMenuItems(cm)
                except:
                    pass
            _add_dir(processed['url'], li, processed['is_folder'])
        except Exception as _e:
            try:
                xbmc.log(f'[PUNCHPLAY] render item {item.get("tmdb_id")} error: {_e}', xbmc.LOGWARNING)
            except:
                pass
            continue
    if next_action and page * limit < len(items):
        li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': next_action, 'page': page + 1, **(next_extra or {})}), li, True)
    if end_dir:
        _end()

def _view_watchlist_menu():
    _ensure_globals()
    from resources.lib.punchplay_sync import get_watchlist_local
    rows = get_watchlist_local() or []
    n_m = sum(1 for r in rows if str(r.get('media_type') or '') == 'movie')
    n_t = sum(1 for r in rows if str(r.get('media_type') or '') != 'movie')
    for label, mt, n in [('Movies Watchlist', 'movie', n_m), ('TV Shows Watchlist', 'tv', n_t)]:
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]{label}[/COLOR][/B]'
        if n > 0:
            text += f' [B][COLOR FFFDBD01]({n})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=text)
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': 'punchplay_watchlist_items', 'mediatype': mt}), li, True)
    _end()

def _view_watchlist(page=1):
    _view_watchlist_menu()

def _view_watchlist_items(mediatype, page=1):
    _ensure_globals()
    mt = 'movie' if str(mediatype).lower() == 'movie' else 'tv'
    xbmcplugin.setContent(_HANDLE, 'movies' if mt == 'movie' else 'tvshows')
    from resources.lib.punchplay_sync import get_watchlist_local
    rows = []
    for r in get_watchlist_local() or []:
        tid = str(r.get('tmdb_id') or '')
        if not tid or tid == 'None':
            continue
        _m = 'movie' if str(r.get('media_type') or '') == 'movie' else 'tv'
        if _m != mt:
            continue
        rows.append({'tmdb_id': tid, 'title': r.get('title') or '', 'year': r.get('year') or '',
                     'media_type': _m, 'is_anime': r.get('is_anime', 0)})
    _render_tmdb_rows(rows, mt, page=page, next_action='punchplay_watchlist_items', next_extra={'mediatype': mediatype})

def _fetch_all_favourites():
    rows = []
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        page = 1
        for _ in range(20):
            data = api.get_favourites(page=page) or {}
            items = data.get('items') or []
            if not items:
                break
            for it in items:
                if not isinstance(it, dict):
                    continue
                try:
                    tid = int(it.get('tmdbId') or it.get('sourceId') or 0)
                except:
                    continue
                if not tid:
                    continue
                kind = str(it.get('kind') or 'show').lower()
                anime = 0
                try:
                    for k in ('isAnime', 'is_anime', 'anime'):
                        v = it.get(k)
                        if v is True or str(v).lower() in ('1', 'true'):
                            anime = 1
                            break
                except:
                    pass
                mt = 'movie' if kind == 'movie' else ('anime' if anime else 'tv')
                rows.append({'tmdb_id': str(tid), 'title': it.get('title') or '', 'year': it.get('year') or '',
                             'media_type': mt, 'is_anime': anime})
            if not data.get('hasMore'):
                break
            page += 1
    except:
        pass
    return rows

def _view_favourites_menu():
    _ensure_globals()
    rows = _fetch_all_favourites()
    n_m = sum(1 for r in rows if r['media_type'] == 'movie')
    n_t = sum(1 for r in rows if r['media_type'] == 'tv')
    n_a = sum(1 for r in rows if r['media_type'] == 'anime')
    for label, mt, n in [('Movies', 'movie', n_m), ('TV Shows', 'tv', n_t), ('Anime', 'anime', n_a)]:
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Favourites {label}[/COLOR][/B]'
        if n > 0:
            text += f' [B][COLOR FFFDBD01]({n})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=text)
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': 'punchplay_favourites_items', 'mediatype': mt}), li, True)
    _end()

def _view_favourites(page=1):
    _view_favourites_menu()

def _view_favourites_items(mediatype, page=1):
    _ensure_globals()
    mt = str(mediatype or 'movie').lower()
    if mt not in ('movie', 'tv', 'anime'):
        mt = 'movie'
    xbmcplugin.setContent(_HANDLE, 'movies' if mt == 'movie' else 'tvshows')
    rows = [r for r in _fetch_all_favourites() if r['media_type'] == mt]
    for r in rows:
        if r['media_type'] == 'anime':
            r['media_type'] = 'tv'
    _render_tmdb_rows(rows, 'movie' if mt == 'movie' else 'tv', page=page,
                      next_action='punchplay_favourites_items', next_extra={'mediatype': mt})

_LIST_CACHE = {}
_LIST_CACHE_TTL = 300

def invalidate_list_cache(list_id=None):
    try:
        if list_id is None:
            _LIST_CACHE.clear()
        else:
            _LIST_CACHE.pop(f'list_items_{int(list_id)}', None)
    except:
        pass

def _cached_fetch(key, fn):
    try:
        import time as _t
        now = _t.time()
        hit = _LIST_CACHE.get(key)
        if hit and now - hit[0] < _LIST_CACHE_TTL:
            return hit[1]
    except:
        now = None
    rows = fn()
    try:
        import time as _t
        _LIST_CACHE[key] = (_t.time(), rows)
    except:
        pass
    return rows

def _fetch_my_lists():
    return _cached_fetch('my_lists', _fetch_my_lists_live)

def _fetch_my_lists_live():
    rows = []
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        if not api.is_authenticated():
            return []
        cursor = None
        for _ in range(10):
            data = api.get_lists(cursor=cursor, limit=100) or {}
            for lst in data.get('items') or []:
                if not isinstance(lst, dict):
                    continue
                if lst.get('isWatchlist'):
                    continue
                try:
                    lid = int(lst.get('id') or 0)
                except:
                    continue
                if not lid:
                    continue
                rows.append({'list_id': lid, 'name': lst.get('name') or 'Unnamed list',
                             'item_count': int(lst.get('itemCount') or 0),
                             'is_public': bool(lst.get('isPublic')),
                             'is_dynamic': bool(lst.get('isDynamicList'))})
            cursor = data.get('nextCursor')
            if not cursor:
                break
    except:
        pass
    return rows

def _my_lists_count():
    try:
        return len(_fetch_my_lists())
    except:
        return 0

def _view_my_lists():
    _ensure_globals()
    rows = _fetch_my_lists()
    if not rows:
        _empty('[No lists]')
        _end()
        return
    try:
        from resources.lib.utils import sort_personal_list
        rows = sort_personal_list(rows) or rows
    except:
        pass
    try:
        from resources.lib.tmdb_api import _punchplay_lists_with_posters
        _poster_map = {str(p['id']): p.get('poster') or '' for p in (_punchplay_lists_with_posters() or [])}
    except:
        _poster_map = {}
    for r in rows:
        tags = ''
        if r.get('is_dynamic'):
            tags += ' [Dynamic]'
        elif r.get('is_public'):
            tags += ' [Public]'
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]{r["name"]}[/COLOR][/B] [B][COLOR FFFDBD01]({r["item_count"]})[/COLOR][/B]{tags}'
        li = xbmcgui.ListItem(label=text)
        _art = _poster_map.get(str(r.get('list_id') or '')) or _pp_icon()
        li.setArt({'icon': _art, 'thumb': _art, 'poster': _art})
        _add_dir(_build_url({'action': 'punchplay_my_list_items', 'list_id': str(r['list_id'])}), li, True)
    _end()

def _fetch_all_list_items(list_id):
    try:
        lid = int(list_id or 0)
    except:
        return []
    return _cached_fetch(f'list_items_{lid}', lambda: _fetch_all_list_items_live(lid))

def _fetch_all_list_items_live(list_id):
    rows = []
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()

        def _collect(items):
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                try:
                    tid = int(it.get('tmdbId') or 0)
                except:
                    continue
                if not tid:
                    continue
                kind = str(it.get('type') or 'movie').lower()
                mt = 'movie' if kind == 'movie' else 'tv'
                rows.append({'tmdb_id': str(tid), 'title': it.get('title') or 'Unknown',
                             'year': str(it.get('releaseDate') or '')[:4], 'media_type': mt})

        try:
            detail = api.get_list(list_id) or {}
        except:
            detail = {}
        _collect(detail.get('items'))
        if not rows:
            offset = 0
            for _ in range(5):
                data = api.get_list_items(list_id, offset=offset, limit=200) or {}
                items = data.get('items') or []
                if not items:
                    break
                _collect(items)
                offset += len(items)
                if data.get('nextOffset') is None or not data.get('items'):
                    break
    except:
        pass
    return rows

def _view_my_list_items(list_id, page=1):
    _ensure_globals()
    try:
        lid = int(list_id or 0)
    except:
        lid = 0
    if not lid:
        _empty('[No items]')
        _end()
        return
    xbmcplugin.setContent(_HANDLE, 'videos')
    rows = _fetch_all_list_items(lid)
    _render_tmdb_rows(rows, 'mixed', page=page, next_action='punchplay_my_list_items', next_extra={'list_id': str(lid)})

def _view_collection():
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'videos')
    try:
        from resources.lib.punchplay_sync import get_collection_local
        rows = get_collection_local() or []
        movies = [r for r in rows if str(r.get('media_type') or '') == 'movie']
        shows = [r for r in rows if str(r.get('media_type') or '') != 'movie']
        if movies:
            _render_tmdb_rows(movies, 'movie', page=1, end_dir=not shows)
        if shows:
            _render_tmdb_rows(shows, 'tv', page=1)
        if not movies and not shows:
            _empty('[No items]')
            _end()
    except Exception as _e:
        try:
            xbmc.log(f'[PUNCHPLAY] collection view error: {_e}', xbmc.LOGERROR)
        except:
            pass
        try:
            _empty('[No items]')
            _end()
        except:
            pass

def _view_dropped():
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'tvshows')
    from resources.lib.punchplay_sync import get_dropped_local
    rows = get_dropped_local() or []
    try:
        from resources.lib.history_import import _enrich_dropped_titles
        _en = {t: title for t, title, _d in _enrich_dropped_titles(
            [(str(r.get('tmdb_id') or ''), r.get('title') or '', '') for r in rows])}
        for r in rows:
            if not r.get('title') and _en.get(str(r.get('tmdb_id') or '')):
                r['title'] = _en[str(r.get('tmdb_id') or '')]
    except Exception:
        pass
    norm = []
    for r in rows:
        norm.append({'tmdb_id': str(r.get('tmdb_id') or ''), 'title': r.get('title') or 'Unknown', 'year': '', 'media_type': 'tv'})
    _render_tmdb_rows(norm, 'tv', page=1, dropped_mode=True)

_CATALOG_MENUS = (('Movies', 'movie'), ('TV Shows', 'tv'), ('Anime', 'anime'))
_CATALOG_LISTS = {
    'movie': (('Trending', 'trending'), ('Popular', 'popular'), ('Now Playing', 'now_playing'), ('Upcoming', 'upcoming'), ('Top Rated', 'top_rated')),
    'tv': (('Trending', 'trending'), ('Popular', 'popular'), ('Top Rated', 'top_rated'), ('Upcoming', 'upcoming')),
    'anime': (('Trending', 'trending'), ('Popular', 'popular'), ('Top Rated', 'top_rated')),
}
_CATALOG_API_TYPES = {'movie': 'movie', 'tv': 'show', 'anime': 'anime'}

def _view_public_lists():
    _ensure_globals()
    for label, mt in _CATALOG_MENUS:
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay {label}[/COLOR][/B]'
        li = xbmcgui.ListItem(label=text)
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': 'punchplay_catalog_menu', 'mediatype': mt}), li, True)
    _end()

def _view_catalog_menu(mediatype):
    _ensure_globals()
    mt = str(mediatype or 'movie').lower()
    if mt not in _CATALOG_LISTS:
        mt = 'movie'
    for label, _list in _CATALOG_LISTS[mt]:
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay {label}[/COLOR][/B]'
        li = xbmcgui.ListItem(label=text)
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': 'punchplay_catalog', 'mediatype': mt, 'list': _list}), li, True)
    _end()

def _view_catalog(mediatype, list_name):
    _ensure_globals()
    mt = str(mediatype or 'movie').lower()
    if mt not in _CATALOG_LISTS:
        mt = 'movie'
    xbmcplugin.setContent(_HANDLE, 'movies' if mt == 'movie' else 'tvshows')
    api_type = _CATALOG_API_TYPES[mt]
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        if str(list_name or '').lower() == 'trending':
            items = api.catalog_trending(api_type)
        else:
            items = api.catalog_discover(str(list_name or 'popular').lower(), api_type)
    except:
        items = []
    rows = []
    for it in items or []:
        try:
            tid = int(it.get('tmdbId') or 0)
        except:
            continue
        if not tid:
            continue
        rows.append({'tmdb_id': str(tid), 'title': it.get('name') or 'Unknown',
                     'year': it.get('year') or '', 'media_type': 'movie' if mt == 'movie' else 'tv'})
    _render_tmdb_rows(rows, 'movie' if mt == 'movie' else 'tv', page=1)

def _view_history_menu():
    _ensure_globals()
    try:
        from resources.lib.punchplay_sync import get_history_counts
        hm, hs = get_history_counts()
    except:
        hm, hs = 0, 0
    for label, mt, n in [('Movies', 'movie', hm), ('TV Shows', 'tv', hs)]:
        text = f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay History {label}[/COLOR][/B] [B][COLOR FFFDBD01]({n})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=text)
        li.setArt({'icon': _pp_icon(), 'thumb': _pp_icon(), 'poster': _pp_icon()})
        _add_dir(_build_url({'action': 'punchplay_history_items', 'mediatype': mt}), li, True)
    _end()

def _view_history_items(mediatype, page=1):
    _ensure_globals()
    mt = 'movie' if str(mediatype).lower() == 'movie' else 'tv'
    xbmcplugin.setContent(_HANDLE, 'movies' if mt == 'movie' else 'tvshows')
    from resources.lib.punchplay_sync import get_connection, DB_PATH
    rows = []
    try:
        if os.path.exists(DB_PATH):
            conn = get_connection()
            c = conn.cursor()
            if mt == 'movie':
                c.execute("SELECT tmdb_id, title, year, last_watched_at FROM punchplay_watched_movies ORDER BY last_watched_at DESC")
                rows = [{'tmdb_id': str(r[0]), 'title': r[1] or '', 'year': r[2] or '', 'media_type': 'movie'} for r in c.fetchall()]
            else:
                c.execute("SELECT tmdb_id, MAX(title), MAX(last_watched_at) FROM punchplay_watched_episodes GROUP BY tmdb_id ORDER BY MAX(last_watched_at) DESC")
                rows = [{'tmdb_id': str(r[0]), 'title': (r[1] or '').split(' - S')[0], 'year': '', 'media_type': 'tv'} for r in c.fetchall()]
            conn.close()
    except:
        rows = []
    _render_tmdb_rows(rows, mt, page=page, next_action='punchplay_history_items', next_extra={'mediatype': mt})

def _view_upnext():
    from resources.lib.tmdb_api import get_next_episodes as _dynamic_next
    return _dynamic_next(None)

def _calendar_window():
    import datetime as _dt
    _CAL_PREV = [0, 1, 3, 7, 14, 30]
    _CAL_FUT = [0, 7, 14, 21, 30, 60, 90]
    try:
        prev_days = _CAL_PREV[int(_ADDON.getSetting('mdblist_cal_previous_days') or 3)]
    except:
        prev_days = 7
    try:
        fut_days = _CAL_FUT[int(_ADDON.getSetting('mdblist_cal_future_days') or 0)]
    except:
        fut_days = 7
    try:
        sort_asc = int(_ADDON.getSetting('mdblist_cal_sort_order') or 0) == 0
    except:
        sort_asc = True
    try:
        today_top = _ADDON.getSetting('mdblist_cal_today_top') != 'false'
    except:
        today_top = True
    today = _dt.date.today()
    return {'sort_asc': sort_asc, 'today_top': today_top, 'today': today,
            'start': today - _dt.timedelta(days=prev_days), 'end': today + _dt.timedelta(days=fut_days)}

def _view_calendar():
    _ensure_globals()
    import datetime as _dt
    xbmcplugin.setContent(_HANDLE, 'episodes')
    wnd = _calendar_window()
    from resources.lib.punchplay_sync import get_calendar_local
    data = get_calendar_local()
    entries = []
    seen = set()
    for day in (data.get('days') or []):
        if not isinstance(day, dict):
            continue
        try:
            d = _dt.date.fromisoformat(str(day.get('date') or '')[:10])
        except:
            continue
        if d < wnd['start'] or d > wnd['end']:
            continue
        for it in day.get('items') or []:
            if not isinstance(it, dict):
                continue
            try:
                tid = int(it.get('tmdbId') or 0)
            except:
                continue
            if not tid:
                continue
            kind = str(it.get('kind') or 'episode').lower()
            ne = it.get('nextEpisode') or {}
            try:
                s = int(ne.get('season') or 0)
            except:
                s = 0
            try:
                e = int(ne.get('episode') or 0)
            except:
                e = 0
            key = (tid, s, e, kind)
            if key in seen:
                continue
            seen.add(key)
            entries.append({'tmdb_id': str(tid), 'media_type': 'movie' if kind in ('movie', 'movie-digital') else 'tv',
                            'show_title': it.get('title') or '', 'season': s, 'episode': e,
                            'ep_title': ne.get('name') or '', 'air_date': str(ne.get('airDate') or ne.get('air_date') or str(day.get('date'))[:10]),
                            'diff': (d - wnd['today']).days})
    if not entries:
        _empty('[No Calendar Events]')
        _end()
        return
    from resources.lib.config import IMG_BASE, BACKDROP_BASE, calendar_localized_label
    from resources.lib.tmdb_api import set_metadata, _get_full_context_menu, _get_cached_details
    try:
        from resources.lib.watched_provider import is_episode_watched as _wp_is_epw, is_movie_watched as _wp_is_mw, browse_command as _browse_cmd
    except ImportError:
        from resources.lib.watched_provider import is_episode_watched as _wp_is_epw, is_movie_watched as _wp_is_mw
        _browse_cmd = lambda url: 'Container.Update(%s)' % url
    try:
        need = []
        for en in entries:
            if not _get_cached_details(en['tmdb_id'], en['media_type']):
                need.append({'id': en['tmdb_id'], 'media_type': en['media_type']})
        if need:
            from resources.lib.tmdb_api import prefetch_metadata_parallel as _pmp
            _pmp(need, 'tv')
    except:
        pass
    items_to_add = []
    try:
        from resources.lib.tmdb_api import get_smart_season_details as _gsd
        ep_name_map = {}
        _seen_seasons = set()
        for en in entries:
            if en['media_type'] == 'movie':
                continue
            _key = (str(en['tmdb_id']), int(en.get('season') or 0))
            if _key in _seen_seasons:
                continue
            _seen_seasons.add(_key)
            try:
                _sd = _gsd(_key[0], _key[1]) or {}
                for _ep in (_sd.get('episodes') or []):
                    if isinstance(_ep, dict) and _ep.get('name'):
                        ep_name_map[(_key[0], _key[1], int(_ep.get('episode_number') or 0))] = _ep.get('name')
            except Exception:
                pass
    except Exception:
        ep_name_map = {}
    for en in entries:
        tid = en['tmdb_id']
        is_movie = en['media_type'] == 'movie'
        cached = _get_cached_details(tid, 'movie' if is_movie else 'tv') or {}
        db_title = en['show_title'] or ''
        try:
            from resources.lib.tmdb_api import _NON_LATIN_RE as _nl_re
            db_latin = bool(db_title) and not _nl_re.search(db_title)
        except Exception:
            db_latin = bool(db_title)
        if db_latin:
            show_title = db_title
        else:
            cached_title = cached.get('title' if is_movie else 'name', '') or ''
            try:
                from resources.lib.tmdb_api import _NON_LATIN_RE as _nl_re2
                cached_latin = bool(cached_title) and not _nl_re2.search(cached_title)
            except Exception:
                cached_latin = bool(cached_title)
            show_title = cached_title if cached_latin else (db_title or 'Unknown Show')
        poster = f"{IMG_BASE}{cached.get('poster_path', '')}" if cached.get('poster_path') else ''
        fanart = f"{BACKDROP_BASE}{cached.get('backdrop_path', '')}" if cached.get('backdrop_path') else ''
        plot = cached.get('overview', '') or ''
        diff = en['diff']
        try:
            d = _dt.date.fromisoformat(str(en['air_date'])[:10])
            date_label = calendar_localized_label(diff, d)
        except:
            date_label = str(en['air_date'])
        date_color = 'white' if diff == 0 else ('FF00FA9A' if diff < 0 else 'yellow')
        if is_movie:
            display = f'[B][COLOR FFFF4444]{show_title} ({str(en["air_date"])[:4]})[/COLOR][/B]'
        else:
            ep_label = f'S{en["season"]:02d}E{en["episode"]:02d}' if en['season'] else ''
            display = f'[B][COLOR {PUNCHPLAY_COLOR}]{show_title}[/COLOR][/B]'
            if ep_label:
                display += f' - [B][COLOR {date_color}]{ep_label}[/COLOR][/B]'
            try:
                ep_name = ep_name_map.get((str(tid), int(en.get('season') or 0), int(en.get('episode') or 0)), '') or en.get('ep_title')
            except Exception:
                ep_name = en.get('ep_title')
            if ep_name:
                display += f' - [B][I][COLOR FFCCCCFF]{ep_name}[/I][/COLOR][/B]'
        if date_label:
            display += f' [COLOR {date_color}] • [B]{date_label}[/B][/COLOR]'
        li = xbmcgui.ListItem(display)
        li.setProperty('cal_diff', str(diff))
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': fanart})
        if is_movie:
            watched = _wp_is_mw(tid)
            info = {'mediatype': 'movie', 'title': show_title}
        else:
            watched = _wp_is_epw(tid, en['season'], en['episode'])
            ep_label = f'S{en["season"]:02d}E{en["episode"]:02d}' if en['season'] else ''
            try:
                ep_name = ep_name_map.get((str(tid), int(en.get('season') or 0), int(en.get('episode') or 0)), '') or en.get('ep_title')
            except Exception:
                ep_name = en.get('ep_title')
            info = {'mediatype': 'episode', 'title': ep_name or ep_label, 'tvshowtitle': show_title,
                    'season': en['season'], 'episode': en['episode']}
        if plot:
            info['plot'] = plot
        try:
            set_metadata(li, info, unique_ids={'tmdb': tid}, watched_info=watched)
        except:
            pass
        try:
            if is_movie:
                cm = _get_full_context_menu(tid, 'movie', show_title)
            else:
                cm = calendar_context_menu(_get_full_context_menu(tid, 'episode', show_title, season=en['season'], episode=en['episode']),
                                           'episode', tid, show_title, en['season'], en['episode'],
                                           base_url=_BASE_URL, browse_cmd=_browse_cmd, urlencode_fn=urllib.parse.urlencode, clear_sources=True)
            if cm:
                li.addContextMenuItems(cm)
        except:
            pass
        if is_movie:
            url_params, is_folder = calendar_row_click_params('movie', tid, diff, show_title=show_title, sources_title=show_title)
        else:
            url_params, is_folder = calendar_row_click_params('episode', tid, diff, en['season'], en['episode'], show_title)
        if url_params:
            items_to_add.append((f"{_BASE_URL}?{urllib.parse.urlencode(url_params)}", li, is_folder))
    items_to_add = sort_calendar_items(items_to_add, wnd['today_top'], wnd['sort_asc'])
    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))
    _end()

def watchlist_add(tmdb_id=None, mediatype='movie', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        result = api.watchlist_add(mediatype, tmdb_id, title=title or '')
        if result is not None:
            from resources.lib.punchplay_sync import watchlist_add_local
            mt = 'tv' if str(mediatype).lower() in ('tv', 'tvshow', 'show', 'season', 'episode') else 'movie'
            watchlist_add_local(tmdb_id, mt, 'watching', title=title or '')
            if mt == 'tv':
                try:
                    import threading
                    from resources.lib.punchplay_sync import refresh_next_episode_punchplay
                    threading.Thread(target=refresh_next_episode_punchplay, args=(str(tmdb_id),), daemon=True).start()
                except:
                    pass
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] added to [B][COLOR {PUNCHPLAY_COLOR}]Watchlist[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] watchlist_add error: {e}', xbmc.LOGERROR)
    return False

def favourite_add(tmdb_id=None, mediatype='movie', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        mt = 'movie' if str(mediatype).lower() in ('movie', 'movies') else 'show'
        result = api.interact(mt, tmdb_id, scope='title', is_favourite=True)
        if result is not None:
            from resources.lib.punchplay_sync import favourite_add_local
            favourite_add_local(tmdb_id, mt, title=title or '')
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] added to [B][COLOR {PUNCHPLAY_COLOR}]Favourites[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] favourite_add error: {e}', xbmc.LOGERROR)
    return False

def favourite_remove(tmdb_id=None, mediatype='movie', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        mt = 'movie' if str(mediatype).lower() in ('movie', 'movies') else 'show'
        result = api.interact(mt, tmdb_id, scope='title', is_favourite=False)
        if result is not None:
            from resources.lib.punchplay_sync import favourite_remove_local
            favourite_remove_local(tmdb_id)
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] removed from [B][COLOR {PUNCHPLAY_COLOR}]Favourites[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] favourite_remove error: {e}', xbmc.LOGERROR)
    return False

def watchlist_remove(tmdb_id=None, mediatype='movie', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        result = api.watchlist_remove(mediatype, tmdb_id)
        if result is not None:
            from resources.lib.punchplay_sync import watchlist_remove_local
            watchlist_remove_local(tmdb_id)
            try:
                import threading
                from resources.lib.punchplay_sync import refresh_next_episode_punchplay
                threading.Thread(target=refresh_next_episode_punchplay, args=(str(tmdb_id),), daemon=True).start()
            except:
                pass
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] removed from [B][COLOR {PUNCHPLAY_COLOR}]Watchlist[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] watchlist_remove error: {e}', xbmc.LOGERROR)
    return False

def collection_add(tmdb_id=None, mediatype='movie', title='', year='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        mt = 'movie' if str(mediatype).lower() in ('movie', 'movies') else 'show'
        try:
            yr = int(str(year or '')[:4]) if str(year or '').strip() else 0
        except:
            yr = 0
        result = api.add_collection(mt, tmdb_id, title=title or '', year=yr)
        if result is not None:
            from resources.lib.punchplay_sync import collection_add_local
            collection_add_local(tmdb_id, 'movie' if mt == 'movie' else 'tv', title=title or '', year=str(yr or ''))
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] added to [B][COLOR {PUNCHPLAY_COLOR}]Collection[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] collection_add error: {e}', xbmc.LOGERROR)
    return False

def collection_remove(tmdb_id=None, mediatype='movie', title='', notify=True):
    if not tmdb_id:
        return False
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        api = PunchplayAPI()
        item_id = None
        try:
            cursor = None
            for _ in range(10):
                data = api.get_collection(cursor=cursor, limit=200) or {}
                for it in data.get('items') or []:
                    if not isinstance(it, dict):
                        continue
                    try:
                        if int(it.get('tmdbId') or 0) == int(tmdb_id):
                            item_id = it.get('id')
                            break
                    except:
                        continue
                if item_id is not None:
                    break
                cursor = data.get('nextCursor')
                if not cursor:
                    break
        except:
            item_id = None
        if item_id is None:
            return False
        result = api.remove_collection(item_id)
        if result is not None:
            from resources.lib.punchplay_sync import collection_remove_local
            collection_remove_local(tmdb_id)
            if notify:
                _notify(provider_title('punchplay'),
                        f'[B][COLOR yellow]{title or tmdb_id}[/COLOR][/B] removed from [B][COLOR {PUNCHPLAY_COLOR}]Collection[/COLOR][/B]')
            return True
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] collection_remove error: {e}', xbmc.LOGERROR)
    return False

def handle_punchplay_action(params, handle, base_url, addon):
    action = params.get('mode', params.get('action', ''))
    if action not in PUNCHPLAY_ACTIONS and action not in ('punchplay_dropped_restore', 'punchplay_connect', 'punchplay_disconnect'):
        return False
    _ensure_globals()
    global _HANDLE, _BASE_URL
    _HANDLE = handle
    _BASE_URL = base_url
    if action == 'punchplay_menu':
        _view_menu()
    elif action == 'punchplay_account':
        _view_account()
    elif action == 'punchplay_connect':
        from resources.lib.punchplay_api import punchplay_auth as _auth_flow
        _auth_flow()
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_disconnect':
        from resources.lib.punchplay_api import punchplay_revoke as _revoke_flow
        _revoke_flow()
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_upnext':
        _view_upnext()
    elif action == 'punchplay_watchlist':
        _view_watchlist_menu()
    elif action == 'punchplay_watchlist_menu':
        _view_watchlist_menu()
    elif action == 'punchplay_watchlist_items':
        _view_watchlist_items(params.get('mediatype', 'movie'), int(params.get('page', '1') or 1))
    elif action == 'punchplay_watchlist_add':
        watchlist_add(params.get('tmdb_id'), params.get('mediatype', 'movie'), title=params.get('title', ''))
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_watchlist_remove':
        watchlist_remove(params.get('tmdb_id'), params.get('mediatype', 'movie'), title=params.get('title', ''))
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_favourites':
        _view_favourites_menu()
    elif action == 'punchplay_favourites_menu':
        _view_favourites_menu()
    elif action == 'punchplay_favourites_items':
        _view_favourites_items(params.get('mediatype', 'movie'), int(params.get('page', '1') or 1))
    elif action == 'punchplay_favourite_add':
        favourite_add(params.get('tmdb_id'), params.get('mediatype', 'movie'), title=params.get('title', ''))
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_favourite_remove':
        favourite_remove(params.get('tmdb_id'), params.get('mediatype', 'movie'), title=params.get('title', ''))
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_collection':
        _view_collection()
    elif action == 'punchplay_my_lists':
        _view_my_lists()
    elif action == 'punchplay_my_list_items':
        _view_my_list_items(params.get('list_id'), int(params.get('page', '1') or 1))
    elif action == 'punchplay_public_lists':
        _view_public_lists()
    elif action == 'punchplay_catalog_menu':
        _view_catalog_menu(params.get('mediatype', 'movie'))
    elif action == 'punchplay_catalog':
        _view_catalog(params.get('mediatype', 'movie'), params.get('list', 'popular'))
    elif action == 'punchplay_calendar':
        _view_calendar()
    elif action == 'punchplay_dropped':
        _view_dropped()
    elif action == 'punchplay_dropped_restore':
        from resources.lib.punchplay_sync import restore_show
        _mt = 'movie' if str(params.get('mediatype', '')).lower() in ('movie', 'movies') else 'show'
        if restore_show(params.get('tmdb_id'), _mt):
            _notify(provider_title('punchplay'),
                    f'[B][COLOR yellow]{params.get("title", "")}[/COLOR][/B] restored')
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'punchplay_history_menu':
        _view_history_menu()
    elif action == 'punchplay_history_items':
        _view_history_items(params.get('mediatype', 'movie'), int(params.get('page', '1') or 1))
    return True
