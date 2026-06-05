import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import os
import json
from urllib.parse import parse_qsl, urlencode, quote, unquote

# =============================================================================
# CACHE GLOBAL PENTRU VITEZĂ
# =============================================================================
_addon = None
_handle = None
_profile = None
_art_path = None

def get_addon():
    global _addon
    if _addon is None:
        _addon = xbmcaddon.Addon()
    return _addon

def get_handle():
    global _handle
    if _handle is None:
        try:
            _handle = int(sys.argv[1])
        except:
            _handle = -1
    return _handle

def get_profile():
    global _profile
    if _profile is None:
        _profile = xbmcvfs.translatePath(get_addon().getAddonInfo('profile')).replace('\\', '/')
        if not _profile.endswith('/'):
            _profile += '/'
    return _profile

def get_art_path():
    global _art_path
    if _art_path is None:
        root = xbmcvfs.translatePath(get_addon().getAddonInfo('path')).replace('\\', '/')
        if not root.endswith('/'):
            root += '/'
        _art_path = root + 'resources/media/'
    return _art_path

def get_params():
    """Parsează parametrii URL rapid."""
    if len(sys.argv) > 2 and sys.argv[2]:
        return dict(parse_qsl(sys.argv[2][1:]))
    return {}

# =============================================================================
# MENIU RAPID (OPTIMIZAT)
# =============================================================================

def build_fast_menu(items, content_type=''):
    """Construiește meniul RAPID fără import-uri externe."""
    handle = get_handle()
    if handle < 0:
        return

    base_url = sys.argv[0]
    art_path = get_art_path()
    listing = []
    
    for item in items:
        mode = item.get('mode')
        if not mode:
            continue
            
        url_params = {'mode': mode}
        for k, v in item.items():
            if k not in ['name', 'iconImage', 'mode', 'cm', 'folder']:
                url_params[k] = v
        
        url = f"{base_url}?{urlencode(url_params)}"
        
        icon_name = item.get('iconImage', 'DefaultFolder.png')
        if icon_name.startswith(('http', 'special', 'Default')):
            icon = icon_name
        else:
            icon = art_path + icon_name

        li = xbmcgui.ListItem(label=item.get('name'))
        art = {'icon': icon, 'thumb': icon, 'poster': icon}
        if item.get('fanart'):
            art['fanart'] = item['fanart']
            art['landscape'] = item['fanart']
        li.setArt(art)
        
        if 'cm' in item:
            li.addContextMenuItems(item['cm'])

        is_folder = item.get('folder', True)
        listing.append((url, li, is_folder))

    xbmcplugin.addDirectoryItems(handle, listing, len(listing))
    if content_type:
        xbmcplugin.setContent(handle, content_type)
    xbmcplugin.endOfDirectory(handle)

# =============================================================================
# MENIURI STATICE (CITITE LOCAL, FĂRĂ API)
# =============================================================================

def get_settings_menu_items():
    """Construiește meniul de setări citind fișierele local."""
    items = []
    profile = get_profile()
    addon = get_addon()
    
    # TMDB Status
    tmdb_user = None
    try:
        with open(profile + 'tmdb_session.json', 'r') as f:
            data = json.load(f)
            if data.get('session_id'):
                tmdb_user = data.get('username', 'Connected')
    except:
        pass

    if tmdb_user:
        items.append({'name': f'[B][COLOR FF00CED1]TMDB: {tmdb_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect TMDB[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'tmdb_logout_action', 'folder': False})
    else:
        items.append({'name': '[B][COLOR FF00CED1]Connect TMDB[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'tmdb_auth_action', 'folder': False})

    items.append({'name': '[B][COLOR FF00CED1]TMDb v4 Authorization (TV Shows)[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'tmdb_auth_v4_action', 'folder': False})

    # Trakt Status
    trakt_user = None
    try:
        with open(profile + 'trakt_token.json', 'r') as f:
            data = json.load(f)
            if data.get('access_token'):
                raw_status = addon.getSetting('trakt_status')
                if raw_status.startswith('Conectat: '):
                    addon.setSetting('trakt_status', raw_status.replace('Conectat: ', 'Connected: '))
                trakt_user = raw_status.replace('Conectat: ', '').replace('Connected: ', '') or 'User'
    except:
        pass

    if trakt_user and trakt_user != 'Disconnected':
        items.append({'name': f'[B][COLOR pink]Trakt: {trakt_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect Trakt[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'trakt_revoke_action', 'folder': False})
        items.append({'name': '[B][COLOR FF6AFB92]Smart Sync[/COLOR][/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'trakt_sync_smart_action', 'folder': False})
        items.append({'name': '[B][COLOR cyan]Full Sync (Force)[/COLOR][/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'trakt_sync_action', 'folder': False})
    else:
        items.append({'name': '[B][COLOR pink]Connect Trakt[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'trakt_auth_action', 'folder': False})

    items.append({'name': 'Addon Settings', 'iconImage': 'DefaultAddonService.png', 'mode': 'open_settings', 'folder': False})
    items.append({'name': '[B][COLOR orange]Delete All Cache[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_cache_action', 'folder': False})
    
    items.append({'name': '[B][COLOR FF7B68EE]Upload Kodi Log to Pastebin[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'upload_log', 'folder': False})
    items.append({'name': '[B][COLOR FF6AFB92]Support the Project (Donate)[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'show_donate', 'folder': False})
        
    return items

def get_search_menu_items():
    """Construiește meniul de căutare cu istoric."""
    items = [
        {'name': '[B][COLOR FFFDBD01]Search Movies[/COLOR][/B]', 'iconImage': 'search_movie.png', 'mode': 'perform_search', 'type': 'movie', 'folder': True},
        {'name': '[B][COLOR FFFDBD01]Search TV Shows[/COLOR][/B]', 'iconImage': 'search_tv.png', 'mode': 'perform_search', 'type': 'tv', 'folder': True}
    ]
    
    history_file = get_profile() + 'search_history.json'
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
                base_url = sys.argv[0]
                for h in history:
                    q = h.get('query')
                    t = h.get('type')
                    if q:
                        cm = [
                            ('Edit', f"RunPlugin({base_url}?mode=edit_search&query={quote(q)}&type={t})"),
                            ('Delete', f"RunPlugin({base_url}?mode=delete_search&query={quote(q)}&type={t})")
                        ]
                        items.append({
                            'name': f"History: [B][I][COLOR FFCA782B]{q} [/COLOR][/I][/B] ({'Movie' if t=='movie' else 'TV'})",
                            'iconImage': 'search_history.png',
                            'mode': 'perform_search_query', 'query': q, 'type': t, 'cm': cm,
                            'folder': True
                        })
        except:
            pass
    
    items.append({'name': '[B][COLOR FFF535AA]Clear Search History[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_search_history', 'folder': False})
    return items


# =============================================================================
# ROUTER PRINCIPAL
# =============================================================================

def run_plugin():
    params = get_params()
    mode = params.get('mode')
    handle = get_handle()

    if not mode:
        from resources.lib import menus
        build_fast_menu(menus.root_list)
        return

    if mode == 'movies_menu':
        from resources.lib import menus
        import time
        window = xbmcgui.Window(10000)
        now = time.time()
        last_warmup = window.getProperty('tmdb_last_warmup_movie')
        if not last_warmup or (now - float(last_warmup)) > 300:
            from resources.lib import tmdb_api
            tmdb_api.run_background_warmup('movie')
            window.setProperty('tmdb_last_warmup_movie', str(now))
        
        build_fast_menu(menus.movie_list)
        return

    if mode == 'tv_menu':
        from resources.lib import menus
        import time
        window = xbmcgui.Window(10000)
        now = time.time()
        last_warmup = window.getProperty('tmdb_last_warmup_tv')
        if not last_warmup or (now - float(last_warmup)) > 300:
            from resources.lib import tmdb_api
            tmdb_api.run_background_warmup('tv')
            window.setProperty('tmdb_last_warmup_tv', str(now))
            
        build_fast_menu(menus.tvshow_list)
        return

    if mode == 'favorites_menu':
        items = [
            {'name': '[B][COLOR FFFF69B4]Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'list_favorites', 'type': 'movie'},
            {'name': '[B][COLOR FFFF69B4]TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'list_favorites', 'type': 'tv'}
        ]
        build_fast_menu(items)
        return

    if mode == 'downloads_menu':
        from resources.lib import utils
        utils.build_downloads_list(params)
        return
    
    if mode == 'my_lists_menu':
        items = [
            {'name': '[B][COLOR pink]Trakt Lists[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_my_lists'},
            {'name': '[B][COLOR FF00CED1]TMDB Lists[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_my_lists'},
            {'name': '[B][COLOR lightskyblue]MDB Lists[/COLOR][/B]', 'iconImage': 'mdblist.png', 'mode': 'mdblist_menu'}
        ]
        build_fast_menu(items)
        return

    if mode == 'settings_menu':
        build_fast_menu(get_settings_menu_items())
        return

    if mode == 'search_menu':
        build_fast_menu(get_search_menu_items())
        return

    if mode == 'hindi_movies_menu':
        from resources.lib import menus
        build_fast_menu(menus.hindi_movies_list)
        return

    if mode == 'romania_menu':
        from resources.lib import menus
        build_fast_menu(menus.romania_menu)
        return

    if mode == 'romania_movies_menu':
        from resources.lib import menus
        build_fast_menu(menus.romania_movies_list)
        return

    if mode == 'romania_tvshows_menu':
        from resources.lib import menus
        build_fast_menu(menus.romania_tvshows_list)
        return

    if mode == 'noop':
        return

    if mode == 'in_progress_movies':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_movies(params)
        return
    if mode == 'in_progress_tvshows':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_tvshows(params)
        return
    if mode == 'in_progress_episodes':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_episodes(params)
        return

    if mode == 'build_movie_list':
        from resources.lib import tmdb_api
        tmdb_api.build_movie_list(params)
        return
    if mode == 'build_tvshow_list':
        from resources.lib import tmdb_api
        tmdb_api.build_tvshow_list(params)
        return

    if mode == 'tmdb_my_lists':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_my_lists()
        return
    if mode == 'tmdb_list_items':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_list_items(params)
        return
    if mode == 'tmdb_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_watchlist(params)
        return
    if mode == 'tmdb_favorites':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_favorites(params)
        return
    if mode == 'tmdb_edit_list':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_edit_list(params)
        return
    if mode == 'tmdb_watchlist_menu':
        from resources.lib import menus
        build_fast_menu(menus.tmdb_watchlist_list_menu)
        return
    if mode == 'tmdb_favorites_menu':
        from resources.lib import menus
        build_fast_menu(menus.tmdb_favorites_list_menu)
        return
    if mode == 'tmdb_recommendations_menu':
        from resources.lib import menus
        build_fast_menu(menus.tmdb_recommendations_list_menu)
        return
    if mode == 'tmdb_account_recommendations':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_account_recommendations(params)
        return

    if mode == 'trakt_auth':
        from resources.lib import trakt_api
        trakt_api.trakt_auth()
        return
    if mode == 'trakt_revoke':
        from resources.lib import trakt_api
        trakt_api.trakt_revoke()
        return
    if mode == 'trakt_sync':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        return
    if mode == 'trakt_sync_smart':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=False)
        return
    if mode == 'trakt_sync_db':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return
    if mode == 'trakt_sync_smart_action':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=False)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'trakt_main_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_main_list)
        return

    if mode == 'trakt_movies_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_movies_list)
        return

    if mode == 'trakt_tv_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_tv_list)
        return
    if mode == 'next_episodes':
        from resources.lib import trakt_api
        trakt_api.get_next_episodes()
        return
    if mode == 'trakt_favorites_list':
        from resources.lib import trakt_api
        trakt_api.trakt_favorites_list(params)
        return
    if mode == 'trakt_list_items':
        from resources.lib import trakt_api
        trakt_api.trakt_list_items(params)
        return
    if mode == 'trakt_discovery_list':
        from resources.lib import trakt_api
        trakt_api.trakt_discovery_list(params)
        return
    if mode == 'trakt_favorites_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_favorites_list_menu)
        return
    if mode == 'trakt_watchlist_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_watchlist_list_menu)
        return
    if mode == 'trakt_history_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_history_list_menu)
        return
    if mode == 'trakt_dropped_shows':
        from resources.lib import trakt_api
        trakt_api.trakt_dropped_shows_list(params)
        return
    if mode == 'trakt_public_lists':
        from resources.lib import trakt_api
        trakt_api.trakt_public_lists(params)
        return
    if mode == 'trakt_liked_lists':
        from resources.lib import trakt_api
        trakt_api.trakt_liked_lists(params)
        return
    if mode == 'trakt_search_list':
        from resources.lib import trakt_api
        trakt_api.trakt_search_list(params)
        return

    if mode == 'trakt_my_lists':
        from resources.lib import trakt_sync
        from resources.lib.utils import read_json
        from resources.lib.config import TRAKT_TOKEN_FILE
        
        token_data = read_json(TRAKT_TOKEN_FILE)
        if not token_data or not token_data.get('access_token'):
            build_fast_menu([{'name': '[B][COLOR pink]Connect Trakt[/COLOR][/B]', 'mode': 'trakt_auth_action', 'iconImage': 'DefaultUser.png', 'folder': False}])
            return
            
        items = [
            {'name': '[B][COLOR FFCCCCFF]Watchlist[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_watchlist_menu'},
            {'name': '[B][COLOR FFCCCCFF]Favorites[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_menu'},
            {'name': '[B][COLOR red]Dropped Shows [COLOR FFCCCCFF](Hidden)[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_dropped_shows'},
            {'name': '[B][COLOR FFCCCCFF]History[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_history_menu'}
        ]
        
        user_lists = trakt_sync.get_lists_from_db()
        if user_lists:
            items.append({'name': '[B][COLOR pink]--- My Lists ---[/COLOR][/B]', 'mode': 'noop', 'iconImage': 'DefaultUser.png', 'folder': False})
            for lst in user_lists:
                items.append({
                    'name': f"[B][COLOR FFCCCCFF]{lst['name']}[/B] [B][COLOR FFFDBD01]({lst['item_count']})[/COLOR][/B]",
                    'mode': 'trakt_list_items',
                    'list_type': 'user_list',
                    'slug': lst['ids']['slug'],
                    'iconImage': lst.get('icon', 'trakt.png'),
                    'fanart': lst.get('fanart', '')
                })
        
        items.append({'name': '[B][COLOR FFCCCCFF]Liked Lists[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_liked_lists'})
        build_fast_menu(items)
        return

    if mode == 'tmdb_auth':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
        return
    if mode in ('tmdb_logout', 'tmdb_revoke'):
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()
        return

    if mode == 'tmdb_auth_v4_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth_v4()
        return

    if mode == 'perform_search':
        from resources.lib import tmdb_api
        tmdb_api.perform_search(params)
        return
    
    if mode == 'perform_search_query':
        from resources.lib import tmdb_api
        tmdb_api.perform_search_query(params)
        return
    
    if mode == 'delete_search':
        from resources.lib import tmdb_api
        tmdb_api.delete_search_item(params)
        return
    
    if mode == 'edit_search':
        from resources.lib import tmdb_api
        tmdb_api.edit_search_item(params)
        return
    
    if mode == 'clear_search_history':
        from resources.lib import tmdb_api
        tmdb_api.clear_search_history_action()
        return

    if mode == 'navigator_genres':
        from resources.lib import tmdb_api
        tmdb_api.navigator_genres(params)
        return
    if mode == 'navigator_years':
        from resources.lib import tmdb_api
        tmdb_api.navigator_years(params)
        return
    if mode == 'navigator_languages':
        from resources.lib import tmdb_api
        tmdb_api.navigator_languages(params)
        return
    if mode == 'navigator_networks':
        from resources.lib import tmdb_api
        tmdb_api.navigator_networks(params)
        return
    if mode == 'navigator_because_you_watched':
        from resources.lib import tmdb_api
        tmdb_api.navigator_because_you_watched(params)
        return
    if mode == 'list_recommendations':
        from resources.lib import tmdb_api
        tmdb_api.list_recommendations(params)
        return
    if mode == 'list_by_genre':
        from resources.lib import tmdb_api
        tmdb_api.list_by_genre(params)
        return
    if mode == 'list_by_year':
        from resources.lib import tmdb_api
        tmdb_api.list_by_year(params)
        return
    if mode == 'list_by_language':
        from resources.lib import tmdb_api
        tmdb_api.list_by_language(params)
        return
    if mode == 'list_by_network':
        from resources.lib import tmdb_api
        tmdb_api.list_by_network(params)
        return

    if mode == 'sources':
        from resources.lib import player
        player.list_sources(params)
        return
    if mode == 'tmdb_resolve':
        from resources.lib import player
        player.tmdb_resolve_dialog(params)
        return

    if mode == 'details':
        from resources.lib import tmdb_api
        tmdb_api.show_details(params.get('tmdb_id'), params.get('type'))
        return
    if mode == 'episodes':
        from resources.lib import tmdb_api
        tmdb_api.list_episodes(params.get('tmdb_id'), params.get('season'), params.get('tv_show_title'))
        return

    if mode == 'show_info':
        from resources.lib import tmdb_api
        tmdb_api.show_info_dialog(params)
        return
    if mode == 'global_info':
        from resources.lib import tmdb_api
        tmdb_api.show_global_info(params)
        return

    if mode == 'mdblist_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_mdblist_context_menu(
            params.get('tmdb_id'),
            params.get('imdb_id'),
            params.get('type'),
            params.get('title', '')
        )
        return

    if mode and mode.startswith('mdblist_'):
        from resources.lib.mdblist import handle_mdblist_action, MDBLIST_ACTIONS
        if mode in MDBLIST_ACTIONS:
            from resources.lib.config import ADDON
            handle_mdblist_action({'action': mode, **params}, handle, sys.argv[0], ADDON)
        return
    
    if mode == 'trakt_context_menu':
        from resources.lib import trakt_api
        trakt_api.show_trakt_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', ''),
            params.get('season'),
            params.get('episode')
        )
        return
    if mode == 'tmdb_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', ''),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'trakt_rating':
        from resources.lib import trakt_api
        trakt_api.rate_trakt_item(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'tmdb_rating':
        from resources.lib import tmdb_api
        tmdb_api.rate_tmdb_item(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'show_my_plays_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_my_plays_menu(params)
        return

    if mode == 'tmdb_add_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.add_to_tmdb_watchlist(params.get('type'), params.get('tmdb_id'))
        return
    if mode == 'tmdb_remove_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.remove_from_tmdb_watchlist(params.get('type'), params.get('tmdb_id'))
        return
    if mode == 'tmdb_add_favorites':
        from resources.lib import tmdb_api
        tmdb_api.add_to_tmdb_favorites(params.get('type'), params.get('tmdb_id'))
        return
    if mode == 'tmdb_remove_favorites':
        from resources.lib import tmdb_api
        tmdb_api.remove_from_tmdb_favorites(params.get('type'), params.get('tmdb_id'))
        return
    if mode == 'tmdb_add_to_list':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_add_to_list_dialog(params.get('tmdb_id'), params.get('type'))
        return
    if mode == 'tmdb_remove_from_list':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_remove_from_list_dialog(params.get('tmdb_id'), params.get('type'))
        return

    if mode == 'add_favorite':
        from resources.lib import tmdb_api
        tmdb_api.add_favorite(params)
        return
    if mode == 'remove_favorite':
        from resources.lib import tmdb_api
        tmdb_api.remove_favorite(params)
        return
    if mode == 'list_favorites':
        from resources.lib import tmdb_api
        tmdb_api.list_favorites(params.get('type'))
        return

    if mode == 'mark_watched':
        from resources.lib import trakt_sync
        trakt_sync.mark_as_watched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return
        
    if mode == 'mark_unwatched':
        from resources.lib import trakt_sync
        trakt_sync.mark_as_unwatched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'remove_progress':
        from resources.lib import trakt_api
        trakt_api.remove_from_progress(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'tmdb_auth_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'tmdb_logout_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'trakt_auth_action':
        from resources.lib import trakt_api
        trakt_api.trakt_auth()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'trakt_revoke_action':
        from resources.lib import trakt_api
        trakt_api.trakt_revoke()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'trakt_sync_action':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'open_settings':
        xbmcaddon.Addon().openSettings()
        return

    if mode == 'clear_cache_action':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'upload_log':
        from resources.lib import utils
        utils.upload_logfile()
        return

    if mode == 'show_donate':
        from resources.lib import utils
        utils.show_donate_link()
        return

    if mode == 'manual_trakt_backup':
        from resources.lib import utils
        utils.perform_trakt_backup(manual=True)
        return

    if mode == 'settings':
        xbmcaddon.Addon().openSettings()
        return
    if mode == 'clear_all_cache':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
        xbmc.executebuiltin("Container.Refresh")
        return
    if mode == 'clear_cache':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
        return
    if mode == 'clear_list_cache':
        from resources.lib import tmdb_api
        tmdb_api.clear_list_cache(params)
        return
    if mode == 'clear_tmdb_lists_cache':
        from resources.lib import tmdb_api
        tmdb_api.clear_tmdb_lists_cache(params)
        return

    if mode == 'clear_sources_context':
        from resources.lib.cache import MainCache
        import os
        
        tmdb_id = params.get('tmdb_id')
        c_type = params.get('type')
        title = params.get('title', 'Item')
        season = params.get('season')
        episode = params.get('episode')
        
        addon = xbmcaddon.Addon()
        icon_path = os.path.join(addon.getAddonInfo('path'), 'icon.png')
        
        dialog = xbmcgui.Dialog()
        opts = [f"Clear cache for: [B][COLOR FF6AFB92]{title}[/COLOR][/B]", "[B][COLOR red]Clear ALL sources cache[/COLOR][/B]"]
        ret = dialog.contextmenu(opts)
        
        cache_db = MainCache()
        
        if ret == 0:
            if c_type == 'tv' and season and episode:
                search_pattern = f"src_{tmdb_id}_{c_type}_s{season}e{episode}"
            else:
                search_pattern = f"src_{tmdb_id}_{c_type}"

            try:
                cache_db.dbcur.execute("DELETE FROM sources_cache WHERE id = ?", (search_pattern,))
                cache_db.dbcon.commit()
                
                xbmcgui.Dialog().notification(
                    "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
                    f"Cache cleared for: [B][COLOR FF6AFB92]{title}[/COLOR][/B]",
                    icon_path,
                    3000,
                    False
                )
            except Exception as e:
                log(f"[CACHE] Error clearing cache: {e}", xbmc.LOGERROR)
            
        elif ret == 1:
            try:
                cache_db.dbcur.execute("DELETE FROM sources_cache")
                cache_db.dbcon.commit()
                
                xbmcgui.Dialog().notification(
                    "Cache Cleared",
                    "All sources have been deleted.",
                    icon_path,
                    3000,
                    False
                )
            except Exception as e:
                log(f"[CACHE] Error clearing cache full: {e}", xbmc.LOGERROR)
            
        return

    if mode == 'initiate_download':
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        from resources.lib import player
        player.initiate_download(params)
        return
        
    if mode == 'stop_download_action':
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        from resources.lib import player
        player.stop_download_action(params)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'downloads_menu':
        from resources.lib import utils
        utils.build_downloads_list(params)
        return

    if mode == 'delete_download':
        from resources.lib import utils
        utils.delete_download_folder(params)
        return
        
    if mode == 'rename_download':
        from resources.lib import utils
        utils.rename_download_folder(params)
        return

# =============================================================================
# SERVICE
# =============================================================================

def run_service():
    try:
        from resources.lib.config import ADDON
    except:
        return

    class TMDbMonitor(xbmc.Monitor):
        def __init__(self):
            xbmc.Monitor.__init__(self)
            self.first_run = True
            self.update_context_menu_property()
            
            try:
                from resources.lib.utils import check_addon_update
                check_addon_update()
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Error la verificarea de update: {e}", xbmc.LOGERROR)

        def onSettingsChanged(self):
            self.update_context_menu_property()
        try:
            from resources.lib.utils import reset_debug_cache
            reset_debug_cache()
        except:
            pass
        
        try:
            from resources.lib.scrapers import reset_debug_cache as reset_scrapers_debug
            reset_scrapers_debug()
        except:
            pass

        def update_context_menu_property(self):
            window = xbmcgui.Window(10000)
            
            if ADDON.getSetting('enable_global_context') == 'true':
                window.setProperty('TMDbMovies.ContextMenu', 'true')
            else:
                window.clearProperty('TMDbMovies.ContextMenu')

            if ADDON.getSetting('enable_extended_context') == 'true':
                window.setProperty('TMDbMovies.ExtendedContext', 'true')
            else:
                window.clearProperty('TMDbMovies.ExtendedContext')

        def run(self):
            if self.waitForAbort(5):
                return
                
            self.clear_temp_subs()
            self.cleanup_downloads()
            
            if self.first_run:
                self.sync_worker()
                self.first_run = False
                
            while not self.abortRequested():
                if self.waitForAbort(1800):
                    break
                self.sync_worker()

        def clear_temp_subs(self):
            try:
                temp_path = xbmcvfs.translatePath('special://temp/')
                dirs, files = xbmcvfs.listdir(temp_path)
                for f in files:
                    if f.endswith(('.srt', '.ssa', '.smi', '.sub', '.idx')) or f.startswith('SALTSSubs_'):
                        xbmcvfs.delete(temp_path + f)
                xbmc.log("[TMDb Movies] Cleaning Service Finished", xbmc.LOGINFO)
            except Exception as e:
                pass

        def cleanup_downloads(self):
            try:
                from resources.lib.downloader import cleanup_empty_download_folders
                cleanup_empty_download_folders()
            except:
                pass

        def sync_worker(self):
            try:
                profile = xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))
                token_path = os.path.join(profile, 'trakt_token.json')
                
                if os.path.exists(token_path):
                    xbmc.log("[TMDb Movies] TraktMonitor Service Update - Starting background sync...", xbmc.LOGINFO)
                    from resources.lib import trakt_sync
                    trakt_sync.sync_full_library(silent=True)
                    xbmc.log("[TMDb Movies] TraktMonitor Service Update - Successs. Next Update in 30 minutes...", xbmc.LOGINFO)
                else:
                    xbmc.log("[TMDb Movies] TraktMonitor Service Update - Aborted. No Trakt Account Active. Next Update in 30 minutes...", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[TMDb Movies] TraktMonitor Service Update - Failed: {e}", xbmc.LOGERROR)

    TMDbMonitor().run()


def run_script():
    """Handler pentru RunScript (apelat din settings.xml)."""
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value
    
    mode = params.get('mode')
    if mode:
        if mode == 'trakt_auth':
            from resources.lib import trakt_api
            trakt_api.trakt_auth()
        elif mode == 'trakt_revoke':
            from resources.lib import trakt_api
            trakt_api.trakt_revoke()
        elif mode == 'trakt_sync':
            from resources.lib import trakt_sync
            trakt_sync.sync_full_library(silent=False, force=True)
        elif mode == 'tmdb_auth':
            from resources.lib import tmdb_api
            tmdb_api.tmdb_auth()
        elif mode in ('tmdb_revoke', 'tmdb_logout'):
            from resources.lib import tmdb_api
            tmdb_api.tmdb_logout()
        elif mode == 'clear_all_cache':
            from resources.lib.utils import clear_all_caches_with_notification
            clear_all_caches_with_notification()
