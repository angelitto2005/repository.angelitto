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
            if k not in ['name', 'iconImage', 'mode', 'cm', 'folder']:  # ✅ Adăugat 'folder'
                url_params[k] = v
        
        url = f"{base_url}?{urlencode(url_params)}"
        
        icon_name = item.get('iconImage', 'DefaultFolder.png')
        if icon_name.startswith(('http', 'special', 'Default')):
            icon = icon_name
        else:
            icon = art_path + icon_name

        li = xbmcgui.ListItem(label=item.get('name'))
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
        
        if 'cm' in item:
            li.addContextMenuItems(item['cm'])

        # ✅ FIX: Respectăm câmpul 'folder' din item (default True)
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
                tmdb_user = data.get('username', 'Conectat')
    except:
        pass

    if tmdb_user:
        items.append({'name': f'[B][COLOR FF00CED1]TMDB: {tmdb_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Deconectare TMDB[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'tmdb_logout_action', 'folder': False})  # ✅
    else:
        items.append({'name': '[B][COLOR FF00CED1]Conectare TMDB[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'tmdb_auth_action', 'folder': False})  # ✅

    items.append({'name': '[B][COLOR FF00CED1]Autorizare TMDb v4 (Seriale)[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'tmdb_auth_v4_action', 'folder': False})

    # Trakt Status
    trakt_user = None
    try:
        with open(profile + 'trakt_token.json', 'r') as f:
            data = json.load(f)
            if data.get('access_token'):
                trakt_user = addon.getSetting('trakt_status').replace('Conectat: ', '') or 'User'
    except:
        pass

    if trakt_user and trakt_user != 'Neconectat':
        items.append({'name': f'[B][COLOR pink]Trakt: {trakt_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Deconectare Trakt[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'trakt_revoke_action', 'folder': False})  # ✅
        items.append({'name': '[B][COLOR FF6698FF]Sincronizare Totală[/COLOR][/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'trakt_sync_action', 'folder': False})  # ✅
    else:
        items.append({'name': '[B][COLOR pink]Conectare Trakt[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'trakt_auth_action', 'folder': False})  # ✅

    items.append({'name': 'Setări Addon', 'iconImage': 'DefaultAddonService.png', 'mode': 'open_settings', 'folder': False})  # ✅
    items.append({'name': '[B][COLOR orange]Șterge Tot Cache-ul[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_cache_action', 'folder': False})  # ✅
    
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
                            'folder': True  # ✅ Căutarea returnează rezultate (folder)
                        })
        except:
            pass
    
    items.append({'name': '[B][COLOR FFF535AA]Clear Search History[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_search_history', 'folder': False})  # ✅ E acțiune
    return items


# =============================================================================
# ROUTER PRINCIPAL
# =============================================================================

def run_plugin():
    params = get_params()
    mode = params.get('mode')
    handle = get_handle()

    # =========================================================================
    # 1. MENIURI STATICE (INSTANT - fără API calls)
    # =========================================================================
    if not mode:
        from resources.lib import menus
        build_fast_menu(menus.root_list)
        return

# --- MODIFICARE PENTRU VITEZA LA BACK ---
    if mode == 'movies_menu':
        from resources.lib import menus
        # Pornim warmup-ul doar dacă au trecut mai mult de 5 minute de la ultimul
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
    # ----------------------------------------

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
            {'name': '[B][COLOR FF00CED1]TMDB Lists[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_my_lists'}
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

    # =========================================================================
    # 2. NOOP (pentru items non-clickable)
    # =========================================================================
    if mode == 'noop':
        return

    # =========================================================================
    # 3. IN PROGRESS
    # =========================================================================
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

    # =========================================================================
    # 4. CONSTRUIRE LISTE (MOVIE/TV)
    # =========================================================================
    if mode == 'build_movie_list':
        from resources.lib import tmdb_api
        tmdb_api.build_movie_list(params)
        return
    if mode == 'build_tvshow_list':
        from resources.lib import tmdb_api
        tmdb_api.build_tvshow_list(params)
        return

    # =========================================================================
    # 5. TMDB LISTS & ACCOUNT
    # =========================================================================
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
# --- TMDB SUBMENUS (STATIC PENTRU VITEZA) ---
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

    # =========================================================================
    # 6. TRAKT AUTH & SYNC
    # =========================================================================
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
    if mode == 'trakt_sync_db':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    # =========================================================================
    # 7. TRAKT LISTS & MENIURI
    # =========================================================================
# --- MODIFICARE MENIURI TRAKT PENTRU VITEZA ---
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
# ----------------------------------------------
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
    # --- TRAKT SUBMENUS (STATIC PENTRU VITEZA) ---
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

# --- MODIFICARE: TRAKT MY LISTS ULTRA-SPEED ---
    if mode == 'trakt_my_lists':
        from resources.lib import trakt_sync
        from resources.lib.utils import read_json
        from resources.lib.config import TRAKT_TOKEN_FILE
        
        # Verificăm token-ul direct din fișier (fără module API)
        token_data = read_json(TRAKT_TOKEN_FILE)
        if not token_data or not token_data.get('access_token'):
            build_fast_menu([{'name': '[B][COLOR pink]Conectare Trakt[/COLOR][/B]', 'mode': 'trakt_auth_action', 'iconImage': 'DefaultUser.png', 'folder': False}])
            return
            
        # Meniuri statice
        items = [
            {'name': '[B]Watchlist[/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_watchlist_menu'},
            {'name': '[B]Favorites[/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_menu'},
            {'name': '[B]History[/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_history_menu'}
        ]
        
        # Citim listele personale direct din SQL (Viteză maximă)
        user_lists = trakt_sync.get_lists_from_db()
        if user_lists:
            items.append({'name': '[B][COLOR pink]--- My Lists ---[/COLOR][/B]', 'mode': 'noop', 'iconImage': 'DefaultUser.png', 'folder': False})
            for lst in user_lists:
                items.append({
                    'name': f"[B]{lst['name']}[/B] [B][COLOR FFFDBD01]({lst['item_count']})[/COLOR][/B]",
                    'mode': 'trakt_list_items',
                    'list_type': 'user_list',
                    'slug': lst['ids']['slug'], # Doar slug-ul e necesar pentru SQL lookup
                    'iconImage': 'trakt.png'
                })
        
        items.append({'name': 'Liked Lists', 'iconImage': 'trakt.png', 'mode': 'trakt_liked_lists'})
        build_fast_menu(items)
        return
    # ----------------------------------------------

    # =========================================================================
    # 8. TMDB AUTH
    # =========================================================================
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

    # =========================================================================
    # 9. SEARCH
    # =========================================================================
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

    # =========================================================================
    # 10. NAVIGATORS
    # =========================================================================
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

    # =========================================================================
    # 11. PLAYER & RESOLVE (IMPORTANT!)
    # =========================================================================
    if mode == 'sources':
        from resources.lib import player
        player.list_sources(params)
        return
    if mode == 'tmdb_resolve':
        from resources.lib import player
        player.tmdb_resolve_dialog(params)
        return

    # =========================================================================
    # 12. DETAILS & EPISODES
    # =========================================================================
    if mode == 'details':
        from resources.lib import tmdb_api
        tmdb_api.show_details(params.get('tmdb_id'), params.get('type'))
        return
    if mode == 'episodes':
        from resources.lib import tmdb_api
        tmdb_api.list_episodes(params.get('tmdb_id'), params.get('season'), params.get('tv_show_title'))
        return

    # =========================================================================
    # 13. INFO DIALOGS (NU FAC endOfDirectory!)
    # =========================================================================
    if mode == 'show_info':
        from resources.lib import tmdb_api
        tmdb_api.show_info_dialog(params)
        return
    if mode == 'global_info':
        from resources.lib import tmdb_api
        tmdb_api.show_global_info(params)
        return

    # =========================================================================
    # 14. CONTEXT MENUS
    # =========================================================================
    if mode == 'trakt_context_menu':
        from resources.lib import trakt_api
        trakt_api.show_trakt_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', '')
        )
        return
    if mode == 'tmdb_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', '')
        )
        return

    # =========================================================================
    # MY PLAYS MENU (Adaugat Nou)
    # =========================================================================
    if mode == 'show_my_plays_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_my_plays_menu(params)
        return

    # =========================================================================
    # 15. TMDB ACTIONS (Watchlist, Favorites, Lists)
    # =========================================================================
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

    # =========================================================================
    # 16. LOCAL FAVORITES
    # =========================================================================
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

# =========================================================================
    # 17. WATCHED STATUS (REPARAT)
    # =========================================================================
    if mode == 'mark_watched':
        # MODIFICARE: Importăm din trakt_sync, nu din trakt_api
        from resources.lib import trakt_sync
        trakt_sync.mark_as_watched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return
        
    if mode == 'mark_unwatched':
        # MODIFICARE: Importăm din trakt_sync
        from resources.lib import trakt_sync
        trakt_sync.mark_as_unwatched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    # =========================================================================
    # 18. REMOVE FROM PROGRESS
    # =========================================================================
    if mode == 'remove_progress':
        from resources.lib import trakt_api
        trakt_api.remove_from_progress(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    # =========================================================================
    # 19. SETTINGS ACTIONS (din meniul settings sau din settings.xml)
    # =========================================================================
    if mode == 'tmdb_auth_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
        xbmc.executebuiltin("Container.Refresh")
        # ✅ FIX: Nu mai facem endOfDirectory - e acțiune, nu folder
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

    # =========================================================================
    # 20. CACHE MANAGEMENT
    # =========================================================================
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

# =========================================================================
# 21. CLEAR SOURCES CONTEXT (Versiunea Finala - Film & Episod)
# =========================================================================
    if mode == 'clear_sources_context':
        from resources.lib.cache import MainCache
        import os
        
        tmdb_id = params.get('tmdb_id')
        c_type = params.get('type')
        title = params.get('title', 'Item')
        season = params.get('season')
        episode = params.get('episode')
        
        # Path corect la icon.png (lângă service.py)
        addon = xbmcaddon.Addon()
        icon_path = os.path.join(addon.getAddonInfo('path'), 'icon.png')
        
        dialog = xbmcgui.Dialog()
        opts = [f"Clear cache for: [B][COLOR FF6AFB92]{title}[/COLOR][/B]", "[B][COLOR red]Clear ALL sources cache[/COLOR][/B]"]
        ret = dialog.contextmenu(opts)
        
        cache_db = MainCache()
        
        if ret == 0:
            # Construim cheia exactă
            if c_type == 'tv' and season and episode:
                # Cheie episod: src_ID_tv_sXeY
                search_pattern = f"src_{tmdb_id}_{c_type}_s{season}e{episode}"
            else:
                # Cheie film: src_ID_movie
                search_pattern = f"src_{tmdb_id}_{c_type}"

            try:
                # Folosim = pentru potrivire exacta
                cache_db.dbcur.execute("DELETE FROM sources_cache WHERE id = ?", (search_pattern,))
                cache_db.dbcon.commit()
                
                # Notificare FĂRĂ sunet (parametrul sound=False)
                xbmcgui.Dialog().notification(
                    "[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]",                      # Titlu
                    f"Cache cleared for: [B][COLOR FF6AFB92]{title}[/COLOR][/B]",   # Mesaj
                    icon_path,                             # Icon
                    3000,                                  # 3 secunde
                    False                                  # FĂRĂ SUNET
                )
            except Exception as e:
                log(f"[CACHE] Eroare ștergere cache: {e}", xbmc.LOGERROR)
            
        elif ret == 1:
            # Sterge tot tabelul surse
            try:
                cache_db.dbcur.execute("DELETE FROM sources_cache")
                cache_db.dbcon.commit()
                
                # Notificare FĂRĂ sunet
                xbmcgui.Dialog().notification(
                    "Cache Cleared",                     # Titlu
                    "Toate sursele au fost șterse.",    # Mesaj
                    icon_path,                            # Icon
                    3000,                                 # 3 secunde
                    False                                 # FĂRĂ SUNET
                )
            except Exception as e:
                log(f"[CACHE] Eroare ștergere cache complet: {e}", xbmc.LOGERROR)
            
        return

# =========================================================================
    # 22. DOWNLOAD MANAGER (Apelare din UTILS)
    # =========================================================================
    
    if mode == 'initiate_download':
        from resources.lib import player
        player.initiate_download(params)
        return
        
    if mode == 'stop_download_action':
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

        def onSettingsChanged(self):
            self.update_context_menu_property()
        # ✅ RESETARE CACHE DEBUG LA SCHIMBAREA SETĂRILOR
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
            
            # 1. Pentru TMDb INFO (existent)
            if ADDON.getSetting('enable_global_context') == 'true':
                window.setProperty('TMDbMovies.ContextMenu', 'true')
            else:
                window.clearProperty('TMDbMovies.ContextMenu')

            # 2. Pentru Extended Info (NOU)
            if ADDON.getSetting('enable_extended_context') == 'true':
                window.setProperty('TMDbMovies.ExtendedContext', 'true')
            else:
                window.clearProperty('TMDbMovies.ExtendedContext')

        def run(self):
            if self.waitForAbort(5):
                return
            if self.first_run:
                self.sync_worker()
                self.first_run = False
            while not self.abortRequested():
                if self.waitForAbort(1800):
                    break
                self.sync_worker()

        def sync_worker(self):
            try:
                profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
                token_path = os.path.join(profile, 'trakt_token.json')
                if os.path.exists(token_path):
                    from resources.lib import trakt_sync
                    trakt_sync.sync_full_library(silent=True)
            except:
                pass

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


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Apelat ca serviciu (la pornirea Kodi)
        run_service()
    elif len(sys.argv) > 1 and '=' in sys.argv[1]:
        # Apelat prin RunScript cu parametri (mode=xxx)
        run_script()
    else:
        # Apelat ca plugin
        run_plugin()