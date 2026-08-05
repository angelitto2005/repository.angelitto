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
from datetime import datetime, timedelta, timezone

from resources.lib.config import ADDON as PROXIED_ADDON

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
    'mdblist_collection_menu',
    'mdblist_collection_items',
    'mdblist_dropped',
    'mdblist_calendar',
    'mdblist_account',
    'mdblist_create_list',
    'mdblist_delete_list',
    'mdblist_import_dropped',
}

BASE_URL_API = 'https://api.mdblist.com/'

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

def _oauth_api():
    """Fallback OAuth: returns MDBListAPI when OAuth token is configured but no API key."""
    from resources.lib.mdblist_api import MDBListAPI
    api = MDBListAPI()
    if api.is_authenticated():
        return api
    return None

def _page_limit():
    from resources.lib.config import PAGE_LIMIT
    return PAGE_LIMIT

def _new_episode_days():
    try:
        return max(1, min(int(_setting('new_episode_days', '7')), 30))
    except:
        return 7

def _notify(title, msg, icon=None, ms=4000):
    if not icon or icon in (xbmcgui.NOTIFICATION_INFO, xbmcgui.NOTIFICATION_WARNING, xbmcgui.NOTIFICATION_ERROR):
        icon = _mdb_icon()
    xbmcgui.Dialog().notification(title, msg, icon, ms, False)

def is_authenticated():
    if _api_key():
        return True
    return bool(_oauth_api())

def _get(path, params=None):
    _ensure_globals()
    key = _api_key()
    
    if not key:
        api = _oauth_api()
        if api is None:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Add [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key or authenticate via OAuth in Settings!', xbmcgui.NOTIFICATION_WARNING)
            return None
        return api._get(path, params=params)
        
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
        api = _oauth_api()
        if api is None:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Add [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key or authenticate via OAuth in Settings to save!', xbmcgui.NOTIFICATION_WARNING)
            return None
        return api._post(path, data=payload)

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

def _delete(path):
    _ensure_globals()
    key = _api_key()

    if not key:
        api = _oauth_api()
        if api is None:
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Add [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key or authenticate via OAuth in Settings to save!', xbmcgui.NOTIFICATION_WARNING)
            return None
        return api._delete(path)

    url = f"{BASE_URL_API}{path}?apikey={key}"
    try:
        r = requests.delete(url, timeout=10)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError:
            return {}
    except requests.HTTPError as e:
        xbmc.log(f'[mdblist] DELETE Error {e.response.status_code} pe /{path}. Response: {e.response.text}', xbmc.LOGERROR)
        _notify('MDB Error', f'Status {e.response.status_code}: Check Kodi Log', xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        xbmc.log(f'[mdblist] Exception on DELETE /{path}: {e}', xbmc.LOGERROR)
    return None

def fetch_user_lists():
    """Listele utilizatorului — cache POV-style (0 calluri la revizitare)."""
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached('lists_user')
    if cached is not None:
        return cached
    data = _get('lists/user')
    if data is None:
        return []
    result = data if isinstance(data, list) else data.get('lists', [])
    set_cached('lists_user', result)
    return result

def fetch_top_lists(offset=0, limit=20):
    key = f'lists_top_{int(offset)}'
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached(key)
    if cached is not None:
        return cached
    data = _get('lists/top', {'limit': limit, 'offset': offset})
    if data is None:
        return []
    result = data if isinstance(data, list) else data.get('lists', [])
    set_cached(key, result)
    return result

def fetch_liked_lists(offset=0, limit=20):
    key = f'lists_liked_{int(offset)}'
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached(key)
    if cached is not None:
        return cached
    data = _get('lists/liked', {'limit': limit, 'offset': offset})
    if data is None:
        return []
    result = data if isinstance(data, list) else data.get('lists', [])
    set_cached(key, result)
    return result

def search_lists(query, offset=0, limit=20):
    if not query:
        return []
    key = 'lists_search_' + urllib.parse.quote(query)[:80]
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached(key)
    if cached is not None:
        return cached
    data = _get('lists/search', {'query': query, 'limit': limit, 'offset': offset})
    if data is None:
        return []
    result = data if isinstance(data, list) else data.get('lists', [])
    set_cached(key, result)
    return result

def fetch_list_items(list_id, page=1, limit=20, external=False):
    """Itemele unei liste — cache intreaga lista (1 call, limit=1000), paginare locala.
    external=True foloseste endpoint-ul listelor externe (external/lists/{id}/items)."""
    key = f'list_items_ext_{list_id}' if external else f'list_items_{list_id}'
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached(key)
    if cached is not None:
        items = cached
    else:
        data = _get(f'external/lists/{list_id}/items' if external else f'lists/{list_id}/items', {'offset': 0, 'limit': 1000})
        if data is None:
            return [], 0
        if isinstance(data, dict):
            items = data.get('items') or data.get('movies', []) + data.get('shows', [])
        else:
            items = data
        set_cached(key, items)
    total = len(items)
    offset = (int(page) - 1) * int(limit)
    return items[offset:offset + int(limit)], total

def fetch_watchlist(mediatype=None):
    """Watchlist intreaga — cache (1 call, limit=1000) + mirror local."""
    from resources.lib.mdblist_sync import get_cached, set_cached, sync_watchlist_local
    cached = get_cached('watchlist')
    if cached is not None:
        data = cached
    else:
        data = _get('watchlist/items', {'limit': 1000})
        if data is not None:
            set_cached('watchlist', data)
            sync_watchlist_local(data.get('movies', []) + data.get('shows', []))
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if mediatype == 'movie':
        return data.get('movies', [])
    if mediatype == 'show':
        return data.get('shows', [])
    return data.get('movies', []) + data.get('shows', [])

def fetch_external_lists():
    """Liste externe (made by others) — cache POV-style."""
    from resources.lib.mdblist_sync import get_cached, set_cached
    cached = get_cached('external_user')
    if cached is not None:
        return cached
    data = _get('external/lists/user')
    if data is None:
        return []
    result = data if isinstance(data, list) else data.get('lists', [])
    set_cached('external_user', result)
    return result

def create_mdbl_list(name):
    """Creeaza o lista noua pe MDBList (POST lists/user/add)."""
    result = _post('lists/user/add', {'name': name})
    if result is not None:
        from resources.lib.mdblist_sync import clear_cached
        clear_cached('lists_user')
        return result
    return None

def delete_mdbl_list(list_id):
    """Sterge o lista proprie (DELETE lists/{id})."""
    result = _delete(f'lists/{list_id}')
    if result is not None:
        from resources.lib.mdblist_sync import clear_cached, clear_cache_prefix
        clear_cached('lists_user')
        clear_cache_prefix('list_items_' + str(list_id))
        return True
    return False

def fetch_account_info():
    """Informatii cont + cota API zilnica ramasa (GET user/)."""
    return _get('user/')

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

def watchlist_add(imdb_id=None, tmdb_id=None, mediatype='movie', title=''):
    if not imdb_id and not tmdb_id: return False
    result = _post('watchlist/items/add', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        added = result.get('added', {}).get('movies', 0) + result.get('added', {}).get('shows', 0)
        existing = result.get('existing', {}).get('movies', 0) + result.get('existing', {}).get('shows', 0)
        if added > 0 or existing > 0:
            from resources.lib.mdblist_sync import clear_cached, clear_cache_prefix, watchlist_add_local
            clear_cached('watchlist')
            clear_cache_prefix('calendar')
            if tmdb_id and str(tmdb_id).lower() not in ('none', ''):
                mtype = 'tv' if str(mediatype).lower() in ('show', 'tv', 'series', 'tvshow', 'season', 'episode') else 'movie'
                watchlist_add_local(tmdb_id, mtype, title=title, year='')
            if added > 0:
                if title:
                    _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', f'[B][COLOR yellow]{title}[/COLOR][/B] added to [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
                else:
                    _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Added to [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            else:
                _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Already in [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            return True
    return False

def watchlist_remove(imdb_id=None, tmdb_id=None, mediatype='movie', title=''):
    if not imdb_id and not tmdb_id: return False
    result = _post('watchlist/items/remove', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        removed = result.get('removed', {})
        count = removed.get('movies', 0) + removed.get('shows', 0) if isinstance(removed, dict) else int(removed)
        if count > 0:
            from resources.lib.mdblist_sync import clear_cached, clear_cache_prefix, watchlist_remove_local
            clear_cached('watchlist')
            clear_cache_prefix('calendar')
            if tmdb_id and str(tmdb_id).lower() not in ('none', ''):
                watchlist_remove_local(tmdb_id)
            if title:
                _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', f'[B][COLOR yellow]{title}[/COLOR][/B] removed from [B][COLOR FF6AFB92]MDB Watchlist[/COLOR][/B].')
            else:
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
            from resources.lib.mdblist_sync import clear_cached
            clear_cached(f'list_items_{list_id}')
            clear_cached('lists_user')
            return True
    return False

def list_remove(list_id, imdb_id=None, tmdb_id=None, mediatype='movie'):
    if not imdb_id and not tmdb_id: return False
    result = _post(f'lists/{list_id}/items/remove', _watchlist_payload(imdb_id, tmdb_id, mediatype))
    if result is not None:
        removed = result.get('removed', {})
        count = removed.get('movies', 0) + removed.get('shows', 0) if isinstance(removed, dict) else int(removed)
        if count > 0:
            from resources.lib.mdblist_sync import clear_cached
            clear_cached(f'list_items_{list_id}')
            clear_cached('lists_user')
            return True
    return False

def fetch_upnext(page=1, limit=20):
    offset = (int(page) - 1) * int(limit)
    data = _get('upnext', {'limit': limit, 'offset': offset, 'hide_unreleased': 'true'})
    if data is None: return [], False
    if isinstance(data, dict): return data.get('items', []), data.get('has_more', False)
    if isinstance(data, list): return data, False
    return [], False

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
    # REMOVED xbmcplugin.setContent(_HANDLE, 'files') FROM HERE!
    
    if is_authenticated():
        auth_label = '[B][COLOR FF6AFB92]MDBList API Connected (Click for Settings)[/COLOR][/B]'
        auth_icon = 'DefaultUser.png'
    else:
        auth_label = '[B][COLOR FFF535AA]Add MDBList API Key (Click for Settings)[/COLOR][/B]'
        auth_icon = 'DefaultUser.png'

    m_icon = _mdb_icon()

    dropped_count = 0
    try:
        from resources.lib.mdblist_sync import get_dropped_local
        dropped_count = len(get_dropped_local())
    except Exception:
        dropped_count = 0

    sections = [
        (auth_label, 'mdblist_settings', auth_icon, False),
        ('[B][COLOR lightskyblue]MDB Account[/COLOR][/B]', 'mdblist_account', 'DefaultUser.png', False),
        ('[B][COLOR lightskyblue]MDB [COLOR yellow]Up Next[/COLOR][/B]', 'mdblist_upnext', m_icon, True),
        ('[B][COLOR lightskyblue]MDB Watchlist[/COLOR][/B]', 'mdblist_watchlist_menu', m_icon, True),
        ('[B][COLOR lightskyblue]MDB Collection[/COLOR][/B]', 'mdblist_collection_menu', m_icon, True),
        ('[B][COLOR lightskyblue]My MDBLists[/COLOR][/B]', 'mdblist_my', m_icon, True),
        ('[B][COLOR lightskyblue]Popular MDB Lists[/COLOR][/B]', 'mdblist_popular', m_icon, True),
        ('[B][COLOR lightskyblue]Liked Lists[/COLOR][/B]', 'mdblist_liked', m_icon, True),
        ('[B][COLOR lightskyblue]Search Lists[/COLOR][/B]', 'mdblist_search', m_icon, True),
        ('[B][COLOR FFE41B17]MDB Dropped Shows[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % dropped_count, 'mdblist_dropped', m_icon, True),
        ('[B][COLOR FFFF6600]MDB Calendar[/COLOR][/B]', 'mdblist_calendar', m_icon, True),
        ('[B][COLOR lightskyblue]MDB Watched History[/COLOR][/B]', 'mdblist_history_menu', m_icon, True),
    ]
    
    for label, action, icon, is_folder in sections:
        if action == 'mdblist_upnext':
            from resources.lib.watched_provider import is_trakt as _is_trakt_provider
            if _is_trakt_provider():
                continue
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
        _add_dir(_build_url({'action': action}), li, is_folder)
    _end(cache=False)

def _render_list_folders(lists, empty_label='[No lists found]', show_delete=False, create_list=False, external_lists=None, pov_style=False):
    all_lists = list(lists or []) + list(external_lists or [])
    if not all_lists:
        _empty(empty_label)
    else:
        art_path = _mdb_icon()
        for lst in all_lists:
            name = lst.get('name', 'Unnamed List')
            list_id = lst.get('id')
            is_ext = 'source' in lst
            
            if pov_style:
                item_count = lst.get('items')
                if item_count:
                    display = f'{name} [B][COLOR FFFDBD01]({item_count})'
                else:
                    display = name
                if lst.get('private') and not is_ext:
                    display = '[I]%s[/I]' % display
                label = f'[B][COLOR lightskyblue]{display}[/COLOR][/B]'
            else:
                parts = []
                if lst.get('items'): parts.append(f'{lst["items"]} items')
                if lst.get('likes'): parts.append(f'♥ {lst["likes"]}')
                if lst.get('user_name'): parts.append(f'by {lst["user_name"]}')
                suffix = f'  [{", ".join(parts)}]' if parts else ''
                label = f'[B][COLOR lightskyblue]{name}[/COLOR][/B]{suffix}'
            
            li = xbmcgui.ListItem(label=label)
            li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
            
            url_params = {'action': 'mdblist_view_list', 'list_id': str(list_id), 'page': 1}
            if is_ext:
                url_params['list_type'] = 'external'
            
            if show_delete and list_id and not is_ext:
                cm = [('[B][COLOR FFE41B17]Delete List[/COLOR][/B]', f"RunPlugin({_build_url({'action': 'mdblist_delete_list', 'list_id': str(list_id)})})")]
                li.addContextMenuItems(cm)
            
            _add_dir(_build_url(url_params), li, True)
        if create_list:
            li = xbmcgui.ListItem(label='[B][COLOR FF6AFB92]+ Create List[/COLOR][/B]')
            li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
            _add_dir(_build_url({'action': 'mdblist_create_list'}), li, True)
    _end()

def _view_my_lists():
    _ensure_globals()
    _render_list_folders(fetch_user_lists(), show_delete=True, create_list=True, external_lists=fetch_external_lists(), pov_style=True)

def _view_create_list():
    _ensure_globals()
    dialog = xbmcgui.Dialog()
    name = dialog.input('New MDBList name', type=xbmcgui.INPUT_ALPHANUM)
    if not name:
        return
    result = create_mdbl_list(name)
    if result is not None:
        _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', f'List [B][COLOR FF6AFB92]{name}[/COLOR][/B] created.')
        xbmc.sleep(1000)
        xbmc.executebuiltin("Container.Refresh")
    else:
        _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Could not create list.', xbmcgui.NOTIFICATION_ERROR)

def _view_delete_list(list_id):
    _ensure_globals()
    if not list_id:
        return
    dialog = xbmcgui.Dialog()
    if dialog.yesno('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Delete this list permanently?', 'This cannot be undone!'):
        if delete_mdbl_list(list_id):
            _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'List deleted.')
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")

def _view_account():
    _ensure_globals()
    data = fetch_account_info()
    if not data or not isinstance(data, dict):
        _notify('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Could not fetch account info.', xbmcgui.NOTIFICATION_ERROR)
        return
    try:
        username = data.get('username') or data.get('name') or 'Unknown'
        joined_raw = str(data.get('date_joined') or '')
        joined = 'Unknown'
        if joined_raw:
            try:
                import datetime as _dt
                joined = _dt.date.fromisoformat(joined_raw[:10]).strftime('%d.%m.%Y')
            except:
                joined = joined_raw[:10]
        supporter = 'Yes' if data.get('is_supporter') else 'No'
        api_limit = int(data.get('api_requests') or 0)
        api_used = int(data.get('api_requests_count') or 0)
        remaining = max(0, api_limit - api_used)
        lines = [
            f'[B][COLOR lightskyblue]Username:[/COLOR][/B] [B]{username}[/B]',
            f'[B][COLOR lightskyblue]Joined:[/COLOR][/B] {joined}',
            f'[B][COLOR lightskyblue]MDBList Supporter:[/COLOR][/B] {supporter}',
            f'[B][COLOR lightskyblue]API Requests:[/COLOR][/B] {api_used} / {api_limit}',
            f'[B][COLOR lightskyblue]API Requests Remaining:[/COLOR][/B] [B][COLOR {"FF6AFB92" if remaining > 100 else "FFE41B17"}]{remaining}[/COLOR][/B]',
        ]
        xbmcgui.Dialog().textviewer('[B][COLOR lightskyblue]MDBList Account[/COLOR][/B]', '\n'.join(lines))
    except Exception as e:
        xbmc.log(f'[mdblist] _view_account error: {e}', xbmc.LOGERROR)

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

def _view_list_contents(list_id, page=1, list_type=''):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'videos')
    limit = _page_limit()
    external = str(list_type).lower() == 'external'
    items, total = fetch_list_items(list_id, page=int(page), limit=limit, external=external)
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
        next_params = {'action': 'mdblist_view_list', 'list_id': list_id, 'page': int(page) + 1}
        if external:
            next_params['list_type'] = 'external'
        _add_dir(_build_url(next_params), next_li, True)
    _end()

def _view_watchlist_menu():
    _ensure_globals()
    art_path = _mdb_icon()
    
    for label, db_type, url_type in [('Movies', 'movie', 'movie'), ('Shows', 'tv', 'show')]:
        count = 0
        try:
            from resources.lib.mdblist_sync import get_connection, DB_PATH
            import os
            if os.path.exists(DB_PATH):
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM mdblist_watchlist WHERE media_type=?", (db_type,))
                row = c.fetchone()
                count = row[0] if row else 0
                conn.close()
        except:
            pass
        display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B]'
        if count > 0:
            display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B] [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=display)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'mdblist_watchlist_items', 'mediatype': url_type, 'page': 1}), li, True)
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

# ==================================================================
# MDBLIST COLLECTION
# ==================================================================
def _view_collection_menu():
    _ensure_globals()
    art_path = _mdb_icon()
    
    for label, mediatype in [('Movies', 'movie'), ('Shows', 'show')]:
        count = 0
        try:
            from resources.lib.mdblist_sync import get_connection, DB_PATH
            import os
            if os.path.exists(DB_PATH):
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM mdblist_collection WHERE media_type=?", (mediatype,))
                row = c.fetchone()
                count = row[0] if row else 0
                conn.close()
        except:
            pass
        display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B]'
        if count > 0:
            display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B] [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=display)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'mdblist_collection_items', 'mediatype': mediatype, 'page': 1}), li, True)
    _end()
def _view_collection_items(mediatype, page=1):
    _ensure_globals()
    kodi_content = 'movies' if mediatype == 'movie' else 'tvshows'
    xbmcplugin.setContent(_HANDLE, kodi_content)
    limit = _page_limit()
    page = int(page)
    from resources.lib.mdblist_sync import get_cached, set_cached
    data = get_cached('collection')
    if data is None:
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        data = api.get_collection(limit=1000)
        if data is not None:
            set_cached('collection', data)
    
    empty_label = '[No Movies in Collection]' if mediatype == 'movie' else '[No Shows in Collection]'
    if not data:
        _empty(empty_label)
        _end()
        return
    
    items_list = data.get('movies', []) if mediatype == 'movie' else data.get('shows', [])
    if not items_list:
        _empty(empty_label)
        _end()
        return
    
    from resources.lib.tmdb_api import _process_movie_item, _process_tv_item, prefetch_metadata_parallel

    start = (page - 1) * limit
    page_items = items_list[start:start + limit]
    
    fake_items = []
    for item in page_items:
        obj = item.get('movie', {}) if mediatype == 'movie' else item.get('show', {})
        ids = obj.get('ids', {})
        tmdb_id = ids.get('tmdb', '')
        if tmdb_id:
            fake_items.append({'id': tmdb_id, 'media_type': mediatype})
            
    prefetch_metadata_parallel(fake_items, mediatype)

    items_to_add = []
    for item in page_items:
        obj = item.get('movie', {}) if mediatype == 'movie' else item.get('show', {})
        ids = obj.get('ids', {})
        tmdb_id = ids.get('tmdb', '')
        if not tmdb_id: continue
        
        fake_item = {'id': tmdb_id, 'title': obj.get('title'), 'name': obj.get('title'), 'overview': obj.get('overview', '')}
        
        if mediatype == 'movie':
            processed = _process_movie_item(fake_item, return_data=True)
        else:
            processed = _process_tv_item(fake_item, return_data=True)
            
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    if page * limit < len(items_list):
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        next_icon = os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png')
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
        _add_dir(_build_url({'action': 'mdblist_collection_items', 'mediatype': mediatype, 'page': page + 1}), next_li, True)
    _end()

# ==================================================================
# MDBLIST DROPPED
# ==================================================================
def _view_dropped(page=1):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'tvshows')
    limit = _page_limit()
    page = int(page)
    from resources.lib.mdblist_sync import get_dropped_local
    dropped = get_dropped_local()

    if _setting('trakt_access_token'):
        li = xbmcgui.ListItem(label='[B][COLOR lightskyblue]Import Dropped from Trakt[/COLOR][/B]')
        li.setArt({'icon': _mdb_icon(), 'thumb': _mdb_icon(), 'poster': _mdb_icon()})
        _add_dir(_build_url({'action': 'mdblist_import_dropped'}), li, False)

    if not dropped:
        _empty('[No Dropped Shows]')
        _end()
        return
    
    items_list = [{'tmdb_id': d['tmdb_id'], 'title': d['title']} for d in dropped]
    
    from resources.lib.tmdb_api import _process_tv_item, prefetch_metadata_parallel

    start = (page - 1) * limit
    page_items = items_list[start:start + limit]
    
    fake_items = [{'id': d['tmdb_id'], 'media_type': 'tv'} for d in page_items]
    prefetch_metadata_parallel(fake_items, 'tv')

    items_to_add = []
    for d in page_items:
        tmdb_id = d['tmdb_id']
        if not tmdb_id:
            continue
        
        fake_item = {'id': tmdb_id, 'title': d.get('title', ''), 'name': d.get('title', ''), 'overview': ''}
        processed = _process_tv_item(fake_item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

    if items_to_add:
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    if page * limit < len(items_list):
        next_li = xbmcgui.ListItem(label=f'[B]Next Page ({page + 1}) >>[/B]')
        next_icon = os.path.join(_ADDON.getAddonInfo('path'), 'resources', 'media', 'item_next.png')
        next_li.setArt({'icon': next_icon, 'thumb': next_icon, 'poster': next_icon})
        _add_dir(_build_url({'action': 'mdblist_dropped', 'page': page + 1}), next_li, True)
    _end()

# ==================================================================
# MDBLIST CALENDAR
# ==================================================================
_CAL_PREV = [0, 1, 3, 7, 14, 30]
_CAL_FUT  = [7, 14, 21, 30, 60, 90]

def _calendar_settings():
    prev = _CAL_PREV[int(_ADDON.getSetting('mdblist_cal_previous_days') or 0)]
    fut  = _CAL_FUT[int(_ADDON.getSetting('mdblist_cal_future_days') or 3)]
    sort_asc = int(_ADDON.getSetting('mdblist_cal_sort_order') or 0) == 0
    today_top = _ADDON.getSetting('mdblist_cal_today_top') != 'false'
    return prev, fut, sort_asc, today_top

def _view_calendar(page=1):
    _ensure_globals()
    xbmcplugin.setContent(_HANDLE, 'episodes')

    prev_days, fut_days, sort_asc, today_top = _calendar_settings()

    from resources.lib.mdblist_sync import get_cached, set_cached
    import datetime as _dt
    today = _dt.date.today()
    start = today - _dt.timedelta(days=prev_days)
    end   = today + _dt.timedelta(days=fut_days)
    cache_key = f'calendar_{prev_days}_{fut_days}'

    data = get_cached(cache_key, ttl=3600)
    if data is None:
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        data = api.calendar_events(start=start.isoformat(), end=end.isoformat(), limit=1000)
        if data is not None:
            set_cached(cache_key, data)
    
    if not data:
        _empty('[No Calendar Events]')
        _end()
        return
    
    items_list = data.get('events', data.get('items', []))
    if not items_list:
        _empty('[No Calendar Events]')
        _end()
        return

    seen_ids = set()
    movie_idx = {}
    deduped = []
    for item in items_list:
        if item.get('type') == 'show':
            continue
        key_id = item.get('tmdb') or item.get('show_tmdb')
        etype = item.get('type', 'episode')
        if etype == 'movie' and key_id:
            # MDBList intoarce 2 evenimente per film (theatrical + digital).
            # Site-ul afiseaza digital release -> pastram digital peste
            # theatrical (altfel apare data veche de cinema in calendar).
            tid = str(key_id)
            if tid in movie_idx:
                if item.get('release_type') == 'digital':
                    deduped[movie_idx[tid]] = item
                continue
            movie_idx[tid] = len(deduped)
            deduped.append(item)
            continue
        dedup = (key_id, etype, item.get('season_number', 0), item.get('episode_number', 0))
        if dedup in seen_ids:
            continue
        seen_ids.add(dedup)
        deduped.append(item)
    items_list = deduped
    
    from resources.lib.tmdb_api import prefetch_metadata_parallel
    from resources.lib.config import BASE_URL, API_KEY, get_headers

    page_items = items_list
    
    from resources.lib.config import IMG_BASE, BACKDROP_BASE
    from resources.lib.tmdb_api import set_metadata
    fake_items = []
    for item in page_items:
        if item.get('type') == 'movie':
            tmdb_id = item.get('tmdb', '')
            if tmdb_id:
                fake_items.append({'id': tmdb_id, 'media_type': 'movie'})
        else:
            tmdb_id = item.get('show_tmdb', '')
            if tmdb_id:
                fake_items.append({'id': tmdb_id, 'media_type': 'tv'})
            
    prefetch_metadata_parallel(fake_items, 'tv')
    from resources.lib.cache import ram_pool_get

    from resources.lib.tmdb_api import get_smart_season_details
    ep_overview_map = {}
    ep_keys_seen = set()
    for item in page_items:
        if item.get('type') == 'movie':
            continue
        tmdb_id = str(item.get('show_tmdb', ''))
        s_num = int(item.get('season_number', 0) or 0)
        key = (tmdb_id, s_num)
        if tmdb_id and s_num and key not in ep_keys_seen:
            ep_keys_seen.add(key)
            try:
                details = get_smart_season_details(tmdb_id, s_num)
                if details:
                    for ep in details.get('episodes', []):
                        ep_num = ep.get('episode_number', 0)
                        overview = ep.get('overview', '')
                        if overview:
                            ep_overview_map[(tmdb_id, s_num, ep_num)] = overview
            except Exception:
                pass

    def _upgrade_poster(url):
        if url and '/w200/' in url:
            return url.replace('/w200/', '/w500/')
        return url

    def _format_cal_date(raw_date):
        if not raw_date:
            return '', 'white', 999
        try:
            parts = str(raw_date).split('T')[0].split('-')
            d = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
            diff = (d - today).days
            ds = f'{parts[2]}.{parts[1]}.{parts[0]}'
            if diff == 0:  return 'Azi', 'white', 0
            if diff == 1:  return 'Maine', 'yellow', 1
            if diff == -1: return 'Ieri', 'FF00FA9A', -1
            if diff >= 2:  return f'peste {diff} zile ({ds})', 'yellow', diff
            if diff <= -2: return f'acum {-diff} zile ({ds})', 'FF00FA9A', diff
            return ds, 'white', diff
        except Exception:
            return str(raw_date)[:10], 'white', 999

    items_to_add = []
    for item in page_items:
        if item.get('type') == 'movie':
            tmdb_id = item.get('tmdb', '')
            if not tmdb_id: continue
            movie_title = item.get('title', '') or 'Unknown'
            air_date = item.get('start', item.get('date', item.get('release_date', '')))
            movie_year = str(air_date)[:4] if air_date else ''
            display_title = f'{movie_title} ({movie_year})' if movie_year else movie_title
            cal_date, date_color, diff = _format_cal_date(air_date)
            label = f'[B][COLOR FFFF6600]{display_title}[/COLOR][/B]'
            if cal_date:
                if cal_date in ('Azi', 'Maine'):
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
                else:
                    label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
            li = xbmcgui.ListItem(label=label)
            li.setProperty('cal_diff', str(diff))
            movie_plot = ''
            movie_cached = ram_pool_get(str(tmdb_id))
            if movie_cached:
                movie_plot = movie_cached.get('overview', '') or ''
            set_metadata(li, {'mediatype': 'movie', 'title': movie_title, 'plot': movie_plot},
                         unique_ids={'tmdb': str(tmdb_id)})
            poster_url = _upgrade_poster(item.get('poster', '') or '')
            art = {'icon': _mdb_icon(), 'thumb': poster_url or _mdb_icon()}
            if poster_url:
                art['poster'] = poster_url
            backdrop_rel = item.get('backdrop', '') or ''
            if backdrop_rel:
                art['fanart'] = f"{BACKDROP_BASE}{backdrop_rel}"
            li.setArt(art)
            if diff <= 0:
                url_params = {'mode': 'sources', 'tmdb_id': str(tmdb_id), 'type': 'movie', 'title': movie_title}
            else:
                url_params = {'mode': 'extended_info', 'tmdb_id': str(tmdb_id), 'type': 'movie'}
            url = f"{_BASE_URL}?{urllib.parse.urlencode(url_params)}"
            items_to_add.append((url, li, False))
            continue

        tmdb_id = item.get('show_tmdb', '')
        if not tmdb_id: continue
        
        show_title = item.get('title', '')
        ep_name = item.get('episode_title', '')
        ep_num = item.get('episode_number', 0)
        s_num = item.get('season_number', 0)
        if not show_title:
            cached = ram_pool_get(str(tmdb_id))
            if cached:
                show_title = cached.get('name', '')
        if not show_title:
            try:
                import requests
                r = requests.get(f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en", headers=get_headers(), timeout=3)
                if r.status_code == 200:
                    show_title = r.json().get('name', 'Unknown')
            except:
                pass
        if not show_title:
            show_title = 'Unknown'
        air_date = item.get('start', item.get('date', item.get('air_date', '')))
        cal_date, date_color, diff = _format_cal_date(air_date)
        
        label = f'[B][COLOR lightskyblue]{show_title}[/COLOR][/B] - [B][COLOR {date_color}]S{s_num:02d}E{ep_num:02d}[/COLOR][/B]'
        if ep_name:
            label += f' - [B][I][COLOR FFCCCCFF]{ep_name}[/I][/COLOR][/B]'
        if cal_date:
            if cal_date in ('Azi', 'Maine'):
                label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
            else:
                label += f' [COLOR {date_color}] • [B]{cal_date}[/B][/COLOR]'
        
        li = xbmcgui.ListItem(label=label)
        li.setProperty('cal_diff', str(diff))
        ep_plot = ep_overview_map.get((str(tmdb_id), s_num, ep_num), '') or item.get('description', '') or ''
        if not ep_plot:
            show_cached = ram_pool_get(str(tmdb_id))
            if show_cached:
                ep_plot = show_cached.get('overview', '') or ''
        set_metadata(li, {'mediatype': 'episode', 'title': ep_name, 'tvshowtitle': show_title,
                          'season': s_num, 'episode': ep_num, 'plot': ep_plot},
                     unique_ids={'tmdb': str(tmdb_id)})
        poster_url = _upgrade_poster(item.get('poster', '') or '')
        art = {'icon': _mdb_icon(), 'thumb': poster_url or _mdb_icon()}
        if poster_url:
            art['poster'] = poster_url
        backdrop_rel = item.get('backdrop', '') or ''
        if backdrop_rel:
            art['fanart'] = f"{BACKDROP_BASE}{backdrop_rel}"
        li.setArt(art)
        
        if diff <= 0:
            url_params = {'mode': 'sources', 'tmdb_id': str(tmdb_id), 'type': 'tv', 'season': str(s_num),
                          'episode': str(ep_num), 'title': f"{show_title} S{s_num:02d}E{ep_num:02d}",
                          'tv_show_title': show_title}
            is_folder = False
        else:
            url_params = {'mode': 'episodes', 'tmdb_id': str(tmdb_id), 'season': str(s_num), 'tv_show_title': show_title}
            is_folder = True
        url = f"{_BASE_URL}?{urllib.parse.urlencode(url_params)}"
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
        xbmcplugin.addDirectoryItems(_HANDLE, items_to_add, len(items_to_add))

    _end()

def _view_upnext(page=1):
    """Delegatie catre Next Episodes dinamic (identic cu TV Shows -> Next Episodes)."""
    from resources.lib.tmdb_api import get_next_episodes as _dynamic_next
    return _dynamic_next(None)


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
                ep_inner = ep.get('episode', ep) or {}
                show_inner = ep_inner.get('show', {}) or {}
                tid = show_inner.get('ids', {}).get('tmdb')
                if tid and str(tid) not in shows_dict:
                    shows_dict[str(tid)] = {
                        'watched_at': ep.get('last_watched_at') or ep.get('watched_at'),
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
    
    for label, db_type, url_type in [('Movies', 'movie', 'movie'), ('Shows', 'tv', 'show')]:
        count = 0
        try:
            from resources.lib.mdblist_sync import get_connection, DB_PATH
            import os
            if os.path.exists(DB_PATH):
                conn = get_connection()
                c = conn.cursor()
                table = 'mdblist_watched_movies' if db_type == 'movie' else 'mdblist_watched_episodes'
                if db_type == 'movie':
                    c.execute("SELECT COUNT(*) FROM mdblist_watched_movies")
                else:
                    c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM mdblist_watched_episodes")
                row = c.fetchone()
                count = row[0] if row else 0
                conn.close()
        except:
            pass
        display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B]'
        if count > 0:
            display = f'[B][COLOR lightskyblue]{label}[/COLOR][/B] [B][COLOR FFFDBD01]({count})[/COLOR][/B]'
        li = xbmcgui.ListItem(label=display)
        li.setArt({'icon': art_path, 'thumb': art_path, 'poster': art_path})
        _add_dir(_build_url({'action': 'mdblist_history_items', 'mediatype': url_type, 'offset': 0}), li, True)
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

    # Buton Next Page — preferam cursor, fallback pe offset
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
    elif action == 'mdblist_view_list': _view_list_contents(params['list_id'], params.get('page', 1), params.get('list_type', ''))
    elif action == 'mdblist_watchlist_menu': _view_watchlist_menu()
    elif action == 'mdblist_watchlist_items': _view_watchlist_items(params.get('mediatype', 'movie'), params.get('page', 1))
    elif action == 'mdblist_watchlist_add':
        if watchlist_add(imdb_id=params.get('imdb_id'), tmdb_id=params.get('tmdb_id'), mediatype=params.get('mediatype', 'movie')):
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_watchlist_remove':
        if watchlist_remove(imdb_id=params.get('imdb_id'), tmdb_id=params.get('tmdb_id'), mediatype=params.get('mediatype', 'movie')):
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_upnext': _view_upnext(params.get('page', 1))
    elif action == 'mdblist_history_menu': _view_history_menu()
    elif action == 'mdblist_history_items': _view_history_items(params.get('mediatype', 'movie'), params.get('offset', 0), params.get('cursor', None))
    elif action == 'mdblist_collection_menu': _view_collection_menu()
    elif action == 'mdblist_collection_items': _view_collection_items(params.get('mediatype', 'movie'), params.get('page', 1))
    elif action == 'mdblist_dropped': _view_dropped(params.get('page', 1))
    elif action == 'mdblist_calendar': _view_calendar(params.get('page', 1))
    elif action == 'mdblist_account': _view_account()
    elif action == 'mdblist_create_list': _view_create_list()
    elif action == 'mdblist_delete_list': _view_delete_list(params.get('list_id'))
    elif action == 'mdblist_import_dropped':
        from resources.lib.mdblist_sync import import_dropped_from_trakt
        imported, _ = import_dropped_from_trakt(silent=False)
        if imported > 0:
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")

