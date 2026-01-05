import sys
import os

def run_service():
    import xbmc
    import xbmcgui

    class TMDbMonitor(xbmc.Monitor):
        def __init__(self):
            xbmc.Monitor.__init__(self)
            self.first_run = True

        def run(self):
            if self.waitForAbort(5): return

            if self.first_run:
                self.sync_worker()
                self.first_run = False

            while not self.abortRequested():
                if self.waitForAbort(1800): break
                self.sync_worker()

        def sync_worker(self):
            try:
                from resources.lib import trakt_api
                token = trakt_api.get_trakt_token()
                if token:
                    from resources.lib import trakt_sync
                    trakt_sync.sync_full_library(silent=True)
            except:
                pass

    TMDbMonitor().run()


def run_script():
    """Handler pentru RunScript (apelat din settings.xml)"""
    # Parsăm argumentele din RunScript
    # Format: RunScript(addon_id, mode=value, param=value, ...)
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value
    
    mode = params.get('mode')
    if mode:
        _process_script_action(mode, params)


def _process_script_action(mode, params):
    """Procesează acțiunile apelate prin RunScript."""
    import xbmc
    import xbmcgui
    
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
        
    elif mode == 'tmdb_revoke' or mode == 'tmdb_logout':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()
        
    elif mode == 'clear_all_cache':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()


def run_plugin():
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    mode = params.get('mode')

    # --- MENIURI STATICE (INSTANT - fără API calls) ---
    if not mode:
        from resources.lib import tmdb_api
        tmdb_api.main_menu()
        return
        
    if mode == 'movies_menu':
        from resources.lib import tmdb_api
        tmdb_api.movies_menu()
        return
        
    if mode == 'tv_menu':
        from resources.lib import tmdb_api
        tmdb_api.tv_menu()
        return
        
    if mode == 'search_menu':
        from resources.lib import tmdb_api
        tmdb_api.search_menu()
        return
        
    if mode == 'favorites_menu':
        from resources.lib import tmdb_api
        tmdb_api.favorites_menu()
        return
        
    if mode == 'my_lists_menu':
        from resources.lib import tmdb_api
        tmdb_api.my_lists_menu()
        return
        
    if mode == 'settings_menu':
        from resources.lib import tmdb_api
        tmdb_api.settings_menu()
        return

    # --- RESTUL MODURILOR (lazy import) ---
    _route_mode(mode, params)


def _route_mode(mode, params):
    """Router pentru restul modurilor - lazy imports."""
    import xbmc
    import xbmcgui
    
    # --- IN PROGRESS ---
    if mode == 'in_progress_movies':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_movies(params)
    elif mode == 'in_progress_tvshows':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_tvshows(params)
    elif mode == 'in_progress_episodes':
        from resources.lib import tmdb_api
        tmdb_api.in_progress_episodes(params)

    # --- CONSTRUIRE LISTE ---
    elif mode == 'build_movie_list':
        from resources.lib import tmdb_api
        tmdb_api.build_movie_list(params)
    elif mode == 'build_tvshow_list':
        from resources.lib import tmdb_api
        tmdb_api.build_tvshow_list(params)

    # --- TMDB LISTS ---
    elif mode == 'tmdb_my_lists':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_my_lists()
    elif mode == 'tmdb_list_items':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_list_items(params)
    elif mode == 'tmdb_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_watchlist(params)
    elif mode == 'tmdb_favorites':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_favorites(params)
    elif mode == 'tmdb_edit_list':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_edit_list(params)

    # --- TMDB SUB-MENIURI ---
    elif mode == 'tmdb_watchlist_menu':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_watchlist_menu()
    elif mode == 'tmdb_favorites_menu':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_favorites_menu()
    elif mode == 'tmdb_recommendations_menu':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_recommendations_menu()
    elif mode == 'tmdb_account_recommendations':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_account_recommendations(params)

    # --- TRAKT AUTH & SYNC ---
    elif mode == 'trakt_auth':
        from resources.lib import trakt_api
        trakt_api.trakt_auth()
    elif mode == 'trakt_revoke':
        from resources.lib import trakt_api
        trakt_api.trakt_revoke()
    elif mode == 'trakt_sync':
        from resources.lib import trakt_api
        # Asta e sync-ul vechi, îl redirecționăm către cel nou cu force=True
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
    elif mode == 'trakt_sync_db':
        from resources.lib import trakt_sync
        # AICI E MODIFICAREA: force=True
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")

    # --- TRAKT LISTS ---
    elif mode == 'trakt_my_lists':
        from resources.lib import trakt_api
        trakt_api.trakt_my_lists()
    elif mode == 'trakt_list_items':
        from resources.lib import trakt_api
        trakt_api.trakt_list_items(params)
    elif mode == 'trakt_movies_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_movies_menu()
    elif mode == 'trakt_tv_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_tv_menu()
    # --- TRAKT DISCOVERY LISTS (NOU) ---
    elif mode == 'trakt_discovery_list':
        from resources.lib import trakt_api
        trakt_api.trakt_discovery_list(params)

    # --- TRAKT SUB-MENIURI ---
    elif mode == 'trakt_watchlist_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_watchlist_menu()
    elif mode == 'trakt_collection_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_collection_menu()
    elif mode == 'trakt_history_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_history_menu()
    elif mode == 'trakt_public_lists':
        from resources.lib import trakt_api
        trakt_api.trakt_public_lists(params)
    elif mode == 'trakt_liked_lists':
        from resources.lib import trakt_api
        trakt_api.trakt_liked_lists(params)
    elif mode == 'trakt_search_list':
        from resources.lib import trakt_api
        trakt_api.trakt_search_list(params)

    # --- TMDB AUTH ---
    elif mode == 'tmdb_auth':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
    elif mode == 'tmdb_logout' or mode == 'tmdb_revoke':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()

    # --- SEARCH ---
    elif mode == 'perform_search':
        from resources.lib import tmdb_api
        tmdb_api.perform_search(params)
    # AICI ADAUGI LINIILE NOI:
    elif mode == 'perform_search_query':
        from resources.lib import tmdb_api
        tmdb_api.perform_search_query(params)
    elif mode == 'delete_search':
        from resources.lib import tmdb_api
        tmdb_api.delete_search_item(params)
    elif mode == 'edit_search':
        from resources.lib import tmdb_api
        tmdb_api.edit_search_item(params)
    elif mode == 'clear_search_history':
        from resources.lib import tmdb_api
        tmdb_api.clear_search_history_action()

    # --- NAVIGATORS ---
    elif mode == 'navigator_genres':
        from resources.lib import tmdb_api
        tmdb_api.navigator_genres(params)
    elif mode == 'navigator_years':
        from resources.lib import tmdb_api
        tmdb_api.navigator_years(params)
    elif mode == 'navigator_languages':
        from resources.lib import tmdb_api
        tmdb_api.navigator_languages(params)
    elif mode == 'navigator_networks':
        from resources.lib import tmdb_api
        tmdb_api.navigator_networks(params)
    elif mode == 'navigator_because_you_watched':
        from resources.lib import tmdb_api
        tmdb_api.navigator_because_you_watched(params)
    elif mode == 'list_recommendations':
        from resources.lib import tmdb_api
        tmdb_api.list_recommendations(params)
    elif mode == 'list_by_genre':
        from resources.lib import tmdb_api
        tmdb_api.list_by_genre(params)
    elif mode == 'list_by_year':
        from resources.lib import tmdb_api
        tmdb_api.list_by_year(params)
    elif mode == 'list_by_language':
        from resources.lib import tmdb_api
        tmdb_api.list_by_language(params)
    elif mode == 'list_by_network':
        from resources.lib import tmdb_api
        tmdb_api.list_by_network(params)

    # --- PLAYER & RESOLVE ---
    elif mode == 'sources':
        from resources.lib import player
        player.list_sources(params)
    elif mode == 'tmdb_resolve':
        from resources.lib import player
        player.tmdb_resolve_dialog(params)

    # --- DETAILS ---
    elif mode == 'details':
        from resources.lib import tmdb_api
        tmdb_api.show_details(params.get('tmdb_id'), params.get('type'))
    elif mode == 'episodes':
        from resources.lib import tmdb_api
        tmdb_api.list_episodes(params.get('tmdb_id'), params.get('season'), params.get('tv_show_title'))

    # --- INFO DIALOG ---
    elif mode == 'show_info':
        from resources.lib import tmdb_api
        tmdb_api.show_info_dialog(params)

    # --- CONTEXT MENUS ---
    elif mode == 'trakt_context_menu':
        from resources.lib import trakt_api
        trakt_api.show_trakt_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', '')
        )
    elif mode == 'tmdb_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_context_menu(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('title', '')
        )

    # --- TMDB ACTIONS ---
    elif mode == 'tmdb_add_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.add_to_tmdb_watchlist(params.get('type'), params.get('tmdb_id'))
    elif mode == 'tmdb_remove_watchlist':
        from resources.lib import tmdb_api
        tmdb_api.remove_from_tmdb_watchlist(params.get('type'), params.get('tmdb_id'))
    elif mode == 'tmdb_add_favorites':
        from resources.lib import tmdb_api
        tmdb_api.add_to_tmdb_favorites(params.get('type'), params.get('tmdb_id'))
    elif mode == 'tmdb_remove_favorites':
        from resources.lib import tmdb_api
        tmdb_api.remove_from_tmdb_favorites(params.get('type'), params.get('tmdb_id'))
    elif mode == 'tmdb_add_to_list':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_add_to_list_dialog(params.get('tmdb_id'), params.get('type'))
    elif mode == 'tmdb_remove_from_list':
        from resources.lib import tmdb_api
        tmdb_api.show_tmdb_remove_from_list_dialog(params.get('tmdb_id'), params.get('type'))

    # --- LOCAL FAVORITES ---
    elif mode == 'add_favorite':
        from resources.lib import tmdb_api
        tmdb_api.add_favorite(params)
    elif mode == 'remove_favorite':
        from resources.lib import tmdb_api
        tmdb_api.remove_favorite(params)
    elif mode == 'list_favorites':
        from resources.lib import tmdb_api
        tmdb_api.list_favorites(params.get('type'))

    # --- WATCHED STATUS ---
    elif mode == 'mark_watched':
        from resources.lib import trakt_api
        trakt_api.mark_as_watched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
    elif mode == 'mark_unwatched':
        from resources.lib import trakt_api
        trakt_api.mark_as_unwatched_internal(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
    
    
    # =================================================================
    # ACȚIUNI DIN SETTINGS (cu endOfDirectory pentru a evita eroarea)
    # =================================================================
    elif mode == 'tmdb_auth_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'tmdb_logout_action':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'trakt_auth_action':
        from resources.lib import trakt_api
        trakt_api.trakt_auth()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'trakt_revoke_action':
        from resources.lib import trakt_api
        trakt_api.trakt_revoke()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'trakt_sync_action':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'open_settings':
        import xbmcaddon
        xbmcaddon.Addon().openSettings()
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        
    elif mode == 'clear_cache_action':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
        xbmc.executebuiltin("Container.Refresh")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    
    # --- REMOVE FROM PROGRESS ---
    elif mode == 'remove_progress':
        _remove_from_progress(params)

    # --- SETTINGS & CACHE ---
    elif mode == 'settings':
        import xbmcaddon
        xbmcaddon.Addon().openSettings()
    elif mode == 'clear_all_cache':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
        xbmc.executebuiltin("Container.Refresh")
    elif mode == 'clear_cache':
        from resources.lib.utils import clear_all_caches_with_notification
        clear_all_caches_with_notification()
    elif mode == 'clear_list_cache':
        from resources.lib import tmdb_api
        tmdb_api.clear_list_cache(params)
    elif mode == 'clear_tmdb_lists_cache':
        from resources.lib import tmdb_api
        tmdb_api.clear_tmdb_lists_cache(params)

    # --- NOOP ---
    elif mode == 'noop':
        pass


def _remove_from_progress(params):
    """Șterge un item din In Progress (playback)."""
    import xbmc
    import xbmcgui
    from resources.lib import trakt_api
    
    tmdb_id = params.get('tmdb_id')
    content_type = params.get('type')
    season = params.get('season')
    episode = params.get('episode')
    
    # Trimitem request la Trakt să șteargă din playback
    try:
        if content_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        else:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}
        
        result = trakt_api.trakt_api_request("/sync/playback/remove", method='POST', data=data)
        
        if result:
            xbmcgui.Dialog().notification("TMDb Movies", "Șters din In Progress", xbmcgui.NOTIFICATION_INFO, 2000)
        else:
            # Fallback: marcăm ca watched
            trakt_api.mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False)
            xbmcgui.Dialog().notification("TMDb Movies", "Marcat ca vizionat", xbmcgui.NOTIFICATION_INFO, 2000)
    except:
        pass
    
    xbmc.executebuiltin("Container.Refresh")


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Apelat ca serviciu (la pornirea Kodi)
        run_service()
    else:
        # Apelat ca plugin
        run_plugin()