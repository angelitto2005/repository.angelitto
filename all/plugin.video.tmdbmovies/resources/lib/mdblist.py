# -*- coding: utf-8 -*-
"""
MDBList integration adapted for TMDb Movies (API Key Only + Custom Icons/Colors)
"""

import sys
import os
import urllib.parse
import requests
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs

MDBLIST_ACTIONS = {
    'mdblist_settings',
    'mdblist_menu',
    'mdblist_my',
    'mdblist_popular',
    'mdblist_liked',
    'mdblist_search',
    'mdblist_view_list',
    'mdblist_watchlist_menu',
    'mdblist_watchlist_items',
    'mdblist_watchlist_add',
    'mdblist_watchlist_remove',
    'mdblist_upnext',
    'mdblist_history_menu',
    'mdblist_history_items',
}

BASE_URL_API = 'https://api.mdblist.com/'

_HANDLE   = None
_BASE_URL = None
_ADDON    = None

def _ensure_globals():
    global _ADDON, _BASE_URL, _HANDLE
    if _ADDON is None:
        try:
            import xbmcaddon
            _ADDON = xbmcaddon.Addon()
        except: pass
    if _BASE_URL is None:
        _BASE_URL = sys.argv[0]
    if _HANDLE is None:
        try: _HANDLE = int(sys.argv[1])
        except: _HANDLE = -1

def _mdb_icon():
    _ensure_globals()
    return os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')

def _build_url(query):
    _ensure_globals()
    if 'action' in query:
        query['mode'] = query.pop('action')
    return _BASE_URL + '?' + urllib.parse.urlencode(query)

def _setting(key, fallback=''):
    _ensure_globals()
    try: return (_ADDON.getSetting(key) or fallback).strip()
    except Exception: return fallback

def _api_key():
    return _setting('mdblist_api')

def _page_limit():
    return 20

def _new_episode_days():
    try:
        return max(1, min(int(_setting('new_episode_days', '7')), 30))
    except:
        return 7

def _notify(title, msg, icon=None, ms=4000):
    if not icon or icon == xbmcgui.NOTIFICATION_INFO:
        icon = _mdb_icon()
    xbmcgui.Dialog().notification(title, msg, icon, ms, False)

def is_authenticated():
    return bool(_api_key())

def _get(path, params=None):
    _ensure_globals()
    key = _api_key()
    
    if not key:
        _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Add [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key in settings!', xbmcgui.NOTIFICATION_WARNING)
        return None
        
    p = {'apikey': key}
    if params: p.update(params)
    
    url = BASE_URL_API + path
    try:
        r = requests.get(url, params=p, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        xbmc.log(f'[mdblist] GET Error {e.response.status_code} on /{path}. Response: {e.response.text}', xbmc.LOGERROR)
        _notify('MDB Error', f'Error Server: {e.response.status_code}', xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        xbmc.log(f'[mdblist] Exception pe GET /{path}: {e}', xbmc.LOGERROR)
    return None

def _post(path, payload):
    _ensure_globals()
    key = _api_key()
    
    if not key:
        _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Add [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key in settings to save!', xbmcgui.NOTIFICATION_WARNING)
        return None

    url = f"{BASE_URL_API}{path}?apikey={key}"
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return {} 
    except requests.HTTPError as e:
        xbmc.log(f'[mdblist] POST Error {e.response.status_code} pe /{path}. Response: {e.response.text}', xbmc.LOGERROR)
        _notify('MDB Error', f'Status {e.response.status_code}: Check Kodi Log', xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        xbmc.log(f'[mdblist] Exception on POST /{path}: {e}', xbmc.LOGERROR)
    return None

def fetch_user_lists():
    data = _get('lists/user')
    return data if isinstance(data, list) else []

def fetch_top_lists(offset=0, limit=20):
    data = _get('lists/top', {'limit': limit, 'offset': offset})
    if data is None: return []
    return data if isinstance(data, list) else data.get('lists', [])

def fetch_liked_lists(offset=0, limit=20):
    data = _get('lists/liked', {'limit': limit, 'offset': offset})
    if data is None: return []
    return data if isinstance(data, list) else data.get('lists', [])

def search_lists(query, offset=0, limit=20):
    if not query: return []
    data = _get('lists/search', {'query': query, 'limit': limit, 'offset': offset})
    if data is None: return []
    return data if isinstance(data, list) else data.get('lists', [])

def fetch_list_items(list_id, page=1, limit=20):
    offset = (int(page) - 1) * int(limit)
    data = _get(f'lists/{list_id}/items', {'offset': offset, 'limit': limit})
    if data is None: return [], 0
    if isinstance(data, dict):
        items = data.get('items') or data.get('movies', []) + data.get('shows', [])
        total = int(data.get('total_items', 0) or data.get('total', len(items)))
        return items, total
    return data, len(data)

def fetch_watchlist(mediatype=None):
    params = {'mediatype': mediatype} if mediatype else {}
    data = _get('watchlist/items', params)
    if data is None: return []
    if isinstance(data, list): return data
    if mediatype == 'movie': return data.get('movies', [])
    if mediatype == 'show': return data.get('shows', [])
    return data.get('movies', []) + data.get('shows', [])

def _watchlist_payload(imdb_id, tmdb_id, mediatype):
    entry = {}
    if imdb_id and str(imdb_id).lower() != 'none': entry['imdb'] = str(imdb_id)
    if tmdb_id and str(tmdb_id).lower() != 'none':
        try: entry['tmdb'] = int(tmdb_id)
        except: pass
        
    mtype = str(mediatype).lower()
    if mtype in ('show', 'tv', 'series', 'tvshow', 'season', 'episode'): 
        return {'shows': [entry]}
    return {'movies': [entry]}

def watchlist_add(imdb_id=None, tmdb_id=None, mediatype='movie'):
    if not imdb_id and not tmdb_id: return False
    result = _post('watchlist/items/add', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        added = result.get('added', {}).get('movies', 0) + result.get('added', {}).get('shows', 0)
        existing = result.get('existing', {}).get('movies', 0) + result.get('existing', {}).get('shows', 0)
        if added > 0:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Added to [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            return True
        elif existing > 0:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Already in [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            return True
    return False

def watchlist_remove(imdb_id=None, tmdb_id=None, mediatype='movie'):
    if not imdb_id and not tmdb_id: return False
    result = _post('watchlist/items/remove', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        removed = result.get('removed', {})
        count = removed.get('movies', 0) + removed.get('shows', 0) if isinstance(removed, dict) else int(removed)
        if count > 0:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Removed from [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            return True
        else:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Item not found.')
    return False

def list_add(list_id, imdb_id=None, tmdb_id=None, mediatype='movie'):
    if not imdb_id and not tmdb_id: return False
    result = _post(f'lists/{list_id}/items/add', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        added = result.get('added', {}).get('movies', 0) + result.get('added', {}).get('shows', 0)
        existing = result.get('existing', {}).get('movies', 0) + result.get('existing', {}).get('shows', 0)
        if added > 0 or existing > 0:
            return True
    return False

def list_remove(list_id, imdb_id=None, tmdb_id=None, mediatype='movie'):
    if not imdb_id and not tmdb_id: return False
    result = _post(f'lists/{list_id}/items/remove', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        removed = result.get('removed', {})
        count = removed.get('movies', 0) + removed.get('shows', 0) if isinstance(removed, dict) else int(removed)
        if count > 0:
            return True
    return False

def fetch_upnext(page=1, limit=20):
    offset = (int(page) - 1) * int(limit)
    data = _get('upnext', {'limit': limit, 'offset': offset, 'hide_unreleased': 'true'})
    if data is None: return [], False
    if isinstance(data, dict): return data.get('items', []), data.get('has_more', False)
    if isinstance(data, list): return data, False
    return [], False

def _end(succeeded=True):
    _ensure_globals()
    xbmcplugin.endOfDirectory(_HANDLE, succeeded=succeeded)

def _add_dir(url, li, is_folder=True):
    _ensure_globals()
    xbmcplugin.addDirectoryItem(_HANDLE, url, li, is_folder)

def _empty(label):
    _add_dir(_build_url({}), xbmcgui.ListItem(label=label), False)

def _view_menu():
    _ensure_globals()
    # REMOVED xbmcplugin.setContent(_HANDLE, 'files') FROM HERE!
    
    if is_authenticated():
        auth_label = '[B][COLOR FF6AFB92]MDBList API Connected (Click for Settings)[/COLOR][/B]'
        auth_icon = 'DefaultUser.png'
    else:
        auth_label = '[B][COLOR FFF535AA]Add MDBList API Key (Click for Settings)[/COLOR][/B]'
        auth_icon = 'DefaultUser.png'

    m_icon = _mdb_icon()
    sections = [
        (auth_label, 'mdblist_settings', auth_icon, False),
        ('[B][COLOR lightskyblue]MDB Watchlist[/COLOR][/B]', 'mdblist_watchlist_menu', m_icon, True),
        ('[B][COLOR lightskyblue]MDB Up Next[/COLOR][/B]', 'mdblist_upnext', m_icon, True),
        ('[B][COLOR lightskyblue]My MDB Lists[/COLOR][/B]', 'mdblist_my', m_icon, True),
        ('[B][COLOR lightskyblue]Popular MDB Lists[/COLOR][/B]', 'mdblist_popular', m_icon, True),
        ('[B][COLOR lightskyblue]Liked Lists[/COLOR][/B]', 'mdblist_liked', m_icon, True),
        ('[B][COLOR lightskyblue]Search Lists[/COLOR][/B]', 'mdblist_search', m_icon, True),
        ('[B][COLOR lightskyblue]MDB Watched History[/COLOR][/B]', 'mdblist_history_menu', m_icon, True), 
    ]
    
    for label, action, icon, is_folder in sections:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
        _add_dir(_build_url({'action': action}), li, is_folder)
    _end()

def _render_list_folders(lists, empty_label='[No lists found]'):
    if not lists:
        _empty(empty_label)
    else:
        art_path = _mdb_icon()
        for lst in lists:
            name = lst.get('name', 'Unnamed List')
            list_id = lst.get('id')
            parts = []
            if lst.get('items'): parts.append(f'{lst["items"]} items')
            if lst.get('likes'): parts.append(f'♥ {lst["likes"]}')
            if lst.get('user_name'): parts.append(f'by {lst["user_name"]}')
            suffix = f'  [{", ".join(parts)}]' if parts else ''
            
            li = xbmcgui.ListItem(label=f'[B][COLOR lightskyblue]{name}[/COLOR][/B]{suffix}')
            li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
            
            _add_dir(_build_url({'action': 'mdblist_view_list', 'list_id': str(list_id), 'page': 1}), li, True)
    _end()

def _view_my_lists():
    _ensure_globals()
    _render_list_folders(fetch_user_lists())

def _view_popular(offset=0):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'files')
    limit = _page_limit()
    lists = fetch_top_lists(offset=int(offset), limit=limit)
    if not lists: 
        _empty('[No popular lists found]')
    else:
        art_path = _mdb_icon()
        for lst in lists:
            name = lst.get('name', 'Unnamed List')
            list_id = lst.get('id')
            
            # ADDED: Extract number of items, likes and user
            parts = []
            if lst.get('items'): parts.append(f'{lst["items"]} items')
            if lst.get('likes'): parts.append(f'♥ {lst["likes"]}')
            if lst.get('user_name'): parts.append(f'by {lst["user_name"]}')
            suffix = f'  [{", ".join(parts)}]' if parts else ''
            
            li = xbmcgui.ListItem(label=f'[B][COLOR lightskyblue]{name}[/COLOR][/B]{suffix}')
            li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
            _add_dir(_build_url({'action': 'mdblist_view_list', 'list_id': str(list_id), 'page': 1}), li, True)
            
        if len(lists) == limit:
            next_page = (int(offset) // limit) + 2
            next_li = xbmcgui.ListItem(label=f'[B]Next Page ({next_page}) >>[/B]')
            next_icon = xbmcvfs.translatePath(os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png'))
            next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
            _add_dir(_build_url({'action': 'mdblist_popular', 'offset': int(offset) + limit}), next_li, True)
    _end()

def _view_liked(offset=0):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'files')
    limit = _page_limit()
    lists = fetch_liked_lists(offset=int(offset), limit=limit)
    
    if not lists: 
        _empty('[No liked lists found]')
    else:
        art_path = _mdb_icon()
        for lst in lists:
            name = lst.get('name', 'Unnamed List')
            list_id = lst.get('id')
            
            # Extract details for Liked lists
            parts = []
            if lst.get('items'): parts.append(f'{lst["items"]} items')
            if lst.get('likes'): parts.append(f'♥ {lst["likes"]}')
            if lst.get('user_name'): parts.append(f'by {lst["user_name"]}')
            suffix = f'  [{", ".join(parts)}]' if parts else ''
            
            li = xbmcgui.ListItem(label=f'[B][COLOR lightskyblue]{name}[/COLOR][/B]{suffix}')
            li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
            _add_dir(_build_url({'action': 'mdblist_view_list', 'list_id': str(list_id), 'page': 1}), li, True)
            
        # ADDED: Full pagination for Liked lists
        if len(lists) == limit:
            next_page = (int(offset) // limit) + 2
            next_li = xbmcgui.ListItem(label=f'[B]Next Page ({next_page}) >>[/B]')
            next_icon = xbmcvfs.translatePath(os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png'))
            next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
            _add_dir(_build_url({'action': 'mdblist_liked', 'offset': int(offset) + limit}), next_li, True)
    _end()

def _view_search(query=None):
    _ensure_globals()
    if not query: 
        query = xbmcgui.Dialog().input('Search [B][COLOR lightskyblue]MDBList[/COLOR][/B]', type=xbmcgui.INPUT_ALPHANUM)
        
    if not query:
        # HERE IS THE FIX: We tell Kodi that the action was cancelled
        xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
        return
        
    xbmcplugin.setContent(_HANDLE, 'files')
    _render_list_folders(search_lists(query), f'[No result for "{query}"]')

def _view_list_contents(list_id, page=1):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'videos')
    limit = _page_limit()
    items, total = fetch_list_items(list_id, page=int(page), limit=limit)
    if not items:
        _empty('[List is empty]')
        _end()
        return

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, prefetch_metadata_parallel
    
    fake_items = []
    for item in items:
        tmdb_id = item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', '')
        mediatype = item.get('mediatype', 'movie')
        k_type = 'tv' if str(mediatype).lower() in ('show', 'tv', 'series', 'tvshow') else 'movie'
        if tmdb_id:
            fake_items.append({'id': tmdb_id, 'media_type': k_type})
            
    prefetch_metadata_parallel(fake_items, 'movie')

    items_to_add = []
    for item in items:
        tmdb_id = item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', '')
        if not tmdb_id: continue
        
        mediatype = item.get('mediatype', 'movie')
        k_type = 'tv' if str(mediatype).lower() in ('show', 'tv', 'series', 'tvshow') else 'movie'
        
        fake_item = {
            'id': tmdb_id,
            'title': item.get('title'),
            'name': item.get('title'),
            'overview': item.get('overview', ''),
            'poster_path': item.get('poster_url', '').replace('https://image.tmdb.org/t/p/w500', '') if item.get('poster_url') else ''
        }
        
        if k_type == 'movie':
            processed = _process_movie_item(fake_item, return_data=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True)
            
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    # FIXED: Even if "total" is missing from the MDB site, we rely on the 20 item per page limit
    if total > int(page) * limit or len(items) == limit:
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({int(page) + 1}) >>[/B]')
        next_icon = xbmcvfs.translatePath(os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png'))
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
        _add_dir(_build_url({'action': 'mdblist_view_list', 'list_id': list_id, 'page': int(page) + 1}), next_li, True)
    _end()

def _view_watchlist_menu():
    _ensure_globals()
    art_path = _mdb_icon()
    
    for label, mediatype in [('[B][COLOR lightskyblue]Movies[/COLOR][/B]', 'movie'), ('[B][COLOR lightskyblue]Shows[/COLOR][/B]',  'show')]:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'mdblist_watchlist_items', 'mediatype': mediatype, 'page': 1}), li, True)
    _end()

def _view_watchlist_items(mediatype, page=1):
    _ensure_globals()
    kodi_content = 'movies' if mediatype == 'movie' else 'tvshows'
    xbmcplugin.setContent(_HANDLE, kodi_content)
    limit    = _page_limit()
    page     = int(page)
    all_items = fetch_watchlist(mediatype=mediatype)

    empty_label = '[No Movies in Watchlist]' if mediatype == 'movie' else '[No Shows in Watchlist]'
    if not all_items:
        _empty(empty_label)
        _end()
        return

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, prefetch_metadata_parallel

    start = (page - 1) * limit
    page_items = all_items[start:start + limit]
    
    fake_items = []
    for item in page_items:
        tmdb_id = item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', '')
        if tmdb_id:
            fake_items.append({'id': tmdb_id, 'media_type': mediatype})
            
    prefetch_metadata_parallel(fake_items, mediatype)

    items_to_add = []
    for item in page_items:
        tmdb_id = item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', '')
        if not tmdb_id: continue
        
        fake_item = {
            'id': tmdb_id,
            'title': item.get('title'),
            'name': item.get('title'),
            'overview': item.get('overview', '')
        }
        
        if mediatype == 'movie':
            processed = _process_movie_item(fake_item, return_data=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True)
            
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    if page * limit < len(all_items):
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        next_icon = os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png')
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
        _add_dir(_build_url({'action': 'mdblist_watchlist_items', 'mediatype': mediatype, 'page': page + 1}), next_li, True)
    _end()

def _view_upnext(page=1):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'episodes')
    limit    = _page_limit()
    page     = int(page)
    items, has_more = fetch_upnext(page=page, limit=limit)

    if not items:
        _empty('[No episodes found]')
        _end()
        return

    new_days = _new_episode_days()
    from resources.lib.tmdb_api import get_tmdb_item_details, get_smart_season_details

    for item in items:
        show     = item.get('show', {})
        next_ep  = item.get('next_episode', {})
        progress = item.get('progress', {})

        tmdb_id = show.get('ids', {}).get('tmdb') or item.get('show_tmdbid') or item.get('tmdbid') or item.get('tmdb_id') or item.get('id')
        show_title = show.get('title') or item.get('show_title') or item.get('title') or item.get('name') or 'Unknown Show'
        season  = int(next_ep.get('season', 1))
        episode = int(next_ep.get('episode', 1))
        ep_title = next_ep.get('title') or f'Episode {episode}'

        watched = int(progress.get('watched_episode_count', 0))
        total   = int(progress.get('total_episode_count', 0))

        is_new = False
        air_date_str = next_ep.get('air_date')
        if air_date_str:
            try:
                air_date = datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                cutoff   = datetime.now(timezone.utc) - timedelta(days=new_days)
                is_new   = air_date >= cutoff
            except: pass
            
        show_details = get_tmdb_item_details(str(tmdb_id), 'tv') or {}
        show_poster = show_details.get('poster_path', '')
        show_fanart = show_details.get('backdrop_path', '')
        show_status = show_details.get('status', '')
        total_seasons = show_details.get('number_of_seasons', 0)
        
        ep_thumb = ''
        ep_plot = ''
        api_ep_type = ''
        total_eps_in_season = 0
        
        season_data = get_smart_season_details(str(tmdb_id), season)
        if season_data:
            total_eps_in_season = len(season_data.get('episodes', []))
            for ep in season_data.get('episodes', []):
                if ep.get('episode_number') == episode:
                    ep_thumb = ep.get('still_path', '')
                    ep_plot = ep.get('overview', '')
                    api_ep_type = ep.get('episode_type', '')
                    break

        # --- CALCUL EPISODE TYPE (BADGE-URI NATIVE CORECTATE) ---
        ep_type = api_ep_type
        if episode == 1:
            ep_type = 'series_premiere' if season == 1 else 'season_premiere'
        elif total_eps_in_season > 0 and episode == total_eps_in_season:
            if show_status in ['Ended', 'Canceled'] and season == total_seasons:
                ep_type = 'series_finale'
            else:
                ep_type = 'season_finale'
        elif api_ep_type == 'mid_season':
            ep_type = 'mid_season_finale'
            
        # --- CONFIGURARE COMPATIBILITATE ESTUARY (ALINIERE EXACTĂ CU TRAKT) ---
        skin_compat = _setting('skin_type', '0')
        
        badge = ""
        if skin_compat == '0':
            if ep_type in ['series_premiere', 'season_premiere']:
                badge = "[B][COLOR FF00FA9A] • Season Premiere[/COLOR][/B]"
            elif ep_type in ['series_finale', 'season_finale']:
                badge = "[B][COLOR FFFF4444] • Season Finale[/COLOR][/B]"
            elif ep_type == 'mid_season_finale':
                badge = "[B][COLOR FFFF4444] • Mid-Season Finale[/COLOR][/B]"

        new_tag       = '[NEW] ' if is_new else ''
        display_label = f'{new_tag}[B][COLOR lightskyblue]{show_title}[/COLOR][/B] • [B][COLOR FFCCCCCC]S{season:02d}E{episode:02d}[/COLOR][/B] • [I]{ep_title}{badge}[/I]'

        li = xbmcgui.ListItem(label=display_label)
        li.setInfo('video', {'mediatype': 'episode', 'tvshowtitle': show_title, 'title': ep_title, 'season': season, 'episode': episode, 'plot': ep_plot})
        li.setProperty('IsPlayable', 'false')
        
        # Setează ID-urile unice (critic pentru logouri, clearlogos și ratings în AF3)
        try:
            tag = li.getVideoInfoTag()
            if tag:
                uids = {'tmdb': str(tmdb_id)}
                show_imdb = show_details.get('external_ids', {}).get('imdb_id', '')
                if show_imdb:
                    uids['imdb'] = show_imdb
                tag.setUniqueIDs(uids, 'tmdb')
        except: pass
        
        li.setProperty('tmdb_id', str(tmdb_id))
        
        # Setează proprietatea 'episode_type' cerută de Arctic Fuse 3
        if ep_type:
            li.setProperty('episode_type', ep_type)

        # Proprietățile pentru bula de episoade rămase (Kodi / AF3)
        unwatched = max(0, total - watched)
        if total > 0:
            li.setProperty('TotalEpisodes', str(total))
            li.setProperty('WatchedEpisodes', str(watched))
            li.setProperty('UnWatchedEpisodes', str(unwatched))
            li.setProperty('unwatchedepisodes', str(unwatched)) # fallback
        
        poster_full = f"https://image.tmdb.org/t/p/w500{show_poster}" if show_poster else ''
        thumb_full = f"https://image.tmdb.org/t/p/w500{ep_thumb}" if ep_thumb else poster_full
        fanart_full = f"https://image.tmdb.org/t/p/w1280{show_fanart}" if show_fanart else poster_full

        li.setArt({'thumb': thumb_full, 'poster': poster_full, 'fanart': fanart_full, 'icon': thumb_full})

        play_url = f"{sys.argv[0]}?mode=sources&tmdb_id={tmdb_id}&type=tv&season={season}&episode={episode}&title={urllib.parse.quote_plus(ep_title)}&tv_show_title={urllib.parse.quote_plus(show_title)}"
        _add_dir(play_url, li, False)

    if has_more:
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        next_icon = os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png')
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
        _add_dir(_build_url({'action': 'mdblist_upnext', 'page': page + 1}), next_li, True)
    _end()


def fetch_history(mediatype='movie', offset=0, limit=20, cursor=None):
    _ensure_globals()
    xbmc.log(f'[mdblist] fetch_history: mediatype={mediatype}, offset={offset}', xbmc.LOGINFO)
    
    target_count = int(offset) + int(limit)
    filtered_items = []
    shows_dict = {}
    
    current_cursor = cursor
    current_offset = 0
    total_count = 0

    # Run a loop of max 8 bulk pages to collect enough titles.
    # We dynamically increment our offset exactly with how many elements we receive from the server.
    for iteration in range(8):
        params = {'limit': 500}
        if current_cursor:
            params['cursor'] = current_cursor
        else:
            params['offset'] = current_offset

        data = _get('sync/watched', params)
        if data is None:
            break

        pagination = data.get('pagination', {})
        current_cursor = pagination.get('next_cursor')
        has_more = pagination.get('has_more', False)
        
        # Get the correct total from the pagination object sent by MDBList
        if mediatype == 'movie':
            total_count = int(pagination.get('total_movies') or 0)
        else:
            total_count = int(pagination.get('total_shows') or 0)

        # Calculate total raw elements returned by server in this call
        raw_count = len(data.get('movies', [])) + len(data.get('shows', [])) + len(data.get('episodes', [])) + len(data.get('seasons', []))
        
        # Increment offset exactly with the number of raw elements received
        current_offset += raw_count

        # Extraction & Filtering
        if mediatype == 'movie':
            filtered_items.extend(data.get('movies', []))
        else:
            # 1. Serialele din 'shows'
            for s in data.get('shows', []):
                show_inner = s.get('show', {})
                tid = show_inner.get('ids', {}).get('tmdb')
                if tid:
                    shows_dict[str(tid)] = s
                    
            # 2. Serialele unice din 'episodes'
            for ep in data.get('episodes', []):
                show_inner = ep.get('show', {})
                tid = show_inner.get('ids', {}).get('tmdb')
                if tid and str(tid) not in shows_dict:
                    shows_dict[str(tid)] = {
                        'watched_at': ep.get('watched_at'),
                        'show': show_inner
                    }
            
            # Re-generate list sorted chronologically
            sorted_shows = sorted(shows_dict.values(), key=lambda x: x.get('watched_at', ''), reverse=True)
            filtered_items = sorted_shows

        # If we've collected enough unique items for the requested page, stop (save runtime)
        if len(filtered_items) >= target_count:
            break
            
        # Stop if server reports has_more is False or we received 0 elements
        if not has_more or raw_count == 0:
            break

    # Local pagination in Kodi
    start_idx = int(offset)
    end_idx = start_idx + int(limit)
    
    paginated_items = filtered_items[start_idx:end_idx]
    
    # If total from API is reported as 0, use our list length as fallback
    if total_count == 0:
        total_count = len(filtered_items)
        
    xbmc.log(f'[mdblist] fetch_history: Target={target_count}, Accumulated={len(filtered_items)}, Total_API={total_count}, Returning={len(paginated_items)}', xbmc.LOGINFO)

    return paginated_items, total_count, current_cursor

def _view_history_menu():
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'videos')
    art_path = _mdb_icon()
    
    for label, mediatype in [('[B][COLOR lightskyblue]Movies[/COLOR][/B]', 'movie'), ('[B][COLOR lightskyblue]Shows[/COLOR][/B]',  'show')]:
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'mdblist_history_items', 'mediatype': mediatype, 'offset': 0}), li, True)
    _end()

def _view_history_items(mediatype, offset=0, cursor=None):
    _ensure_globals()
    kodi_content = 'movies' if mediatype == 'movie' else 'tvshows'
    xbmcplugin.setContent(_HANDLE, kodi_content)
    limit  = _page_limit()
    offset = int(offset)

    items, total, next_cursor = fetch_history(mediatype, offset=offset, limit=limit, cursor=cursor or None)

    empty_label = '[No watched movies found]' if mediatype == 'movie' else '[No watched shows found]'
    if not items:
        _empty(empty_label)
        _end()
        return

    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, prefetch_metadata_parallel

    fake_items = []
    for item in items:
        inner = item.get('movie') if mediatype == 'movie' else item.get('show')
        if not inner: continue
        tmdb_id = inner.get('ids', {}).get('tmdb')
        if tmdb_id:
            fake_items.append({'id': tmdb_id, 'media_type': mediatype})

    prefetch_metadata_parallel(fake_items, mediatype)

    items_to_add = []
    for item in items:
        inner = item.get('movie') if mediatype == 'movie' else item.get('show')
        if not inner: continue

        tmdb_id = inner.get('ids', {}).get('tmdb')
        if not tmdb_id: continue

        fake_item = {
            'id': tmdb_id,
            'title': inner.get('title', ''),
            'name':  inner.get('title', ''),
            'overview': '',
        }

        if mediatype == 'movie':
            processed = _process_movie_item(fake_item, return_data=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True)

        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    # Buton Next Page — preferăm cursor, fallback pe offset
    has_more = next_cursor or (total > offset + limit)
    if has_more:
        next_page_num = (offset // limit) + 2
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({next_page_num}) >>[/B]')
        next_icon = xbmcvfs.translatePath(os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png'))
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})

        url_params = {'action': 'mdblist_history_items', 'mediatype': mediatype, 'offset': offset + limit}
        if next_cursor:
            url_params['cursor'] = next_cursor
        _add_dir(_build_url(url_params), next_li, True)

    _end()


def handle_mdblist_action(params, handle, base_url, addon):
    global _HANDLE, _BASE_URL, _ADDON
    _HANDLE   = handle
    _BASE_URL = base_url
    _ADDON    = addon

    action = params.get('action', '')
    if action == 'mdblist_settings': _ADDON.openSettings()
    elif action == 'mdblist_menu': _view_menu()
    elif action == 'mdblist_my': _view_my_lists()
    elif action == 'mdblist_popular': _view_popular(params.get('offset', 0))
    elif action == 'mdblist_liked': _view_liked(params.get('offset', 0))   # HERE I ADDED OFFSET SUPPORT
    elif action == 'mdblist_search': _view_search(params.get('query'))
    elif action == 'mdblist_view_list': _view_list_contents(params['list_id'], params.get('page', 1))
    elif action == 'mdblist_watchlist_menu': _view_watchlist_menu()
    elif action == 'mdblist_watchlist_items': _view_watchlist_items(params.get('mediatype', 'movie'), params.get('page', 1))
    elif action == 'mdblist_watchlist_add': watchlist_add(imdb_id=params.get('imdb_id'), tmdb_id=params.get('tmdb_id'), mediatype=params.get('mediatype', 'movie'))
    elif action == 'mdblist_watchlist_remove': watchlist_remove(imdb_id=params.get('imdb_id'), tmdb_id=params.get('tmdb_id'), mediatype=params.get('mediatype', 'movie'))
    elif action == 'mdblist_upnext': _view_upnext(params.get('page', 1))
    elif action == 'mdblist_history_menu': _view_history_menu()
    elif action == 'mdblist_history_items': _view_history_items(params.get('mediatype', 'movie'), params.get('offset', 0), params.get('cursor', None))

