import sys
import threading
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import os
import json
from urllib.parse import parse_qsl, urlencode, quote, unquote

# =============================================================================
# CACHE GLOBAL PENTRU VITEZA
# =============================================================================
_addon = None
_handle = None
_profile = None
_art_path = None

def get_addon():
    global _addon
    if _addon is None:
        from resources.lib.config import ADDON
        _addon = ADDON
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
    """Parseaza parametrii din argv (plugin URL sau RunScript)."""
    if len(sys.argv) > 2 and sys.argv[2]:
        raw = sys.argv[2]
        if raw.startswith('?'):
            raw = raw[1:]
        return dict(parse_qsl(raw))
    if len(sys.argv) > 1 and sys.argv[1] and not sys.argv[1].lstrip('-').isdigit():
        return dict(parse_qsl(sys.argv[1]))
    return {}

# =============================================================================
# MENIU RAPID (OPTIMIZAT)
# =============================================================================

def build_fast_menu(items, content_type='', no_cache=False):
    """Construieste meniul RAPID fara import-uri externe."""
    import time
    _t0 = time.time()
    handle = get_handle()
    if handle < 0:
        return

    base_url = sys.argv[0]
    art_path = get_art_path()
    _t1 = time.time()
    listing = []
    
    for item in items:
        mode = item.get('mode')
        if not mode:
            continue
            
        url_params = {'mode': mode}
        for k, v in item.items():
            if k not in ['name', 'iconImage', 'mode', 'cm', 'info']:
                url_params[k] = v
        
        url = f"{base_url}?{urlencode(url_params)}"
        
        icon_name = item.get('iconImage', 'DefaultFolder.png')
        if icon_name.startswith(('http', 'special', 'Default')):
            icon = icon_name
        else:
            icon = art_path + icon_name

        li = xbmcgui.ListItem(label=item.get('name'))
        if mode == 'next_episodes':
            try:
                from resources.lib.watched_provider import is_mdblist as _is_mdb_prov
                if _is_mdb_prov():
                    li.setLabel('[B][COLOR FF33CCFF]UP NEXT[/COLOR][/B]')
                else:
                    li.setLabel('[B][COLOR pink]Next Episodes[/COLOR][/B]')
            except Exception:
                pass
        if mode in ('in_progress_movies', 'in_progress_tvshows', 'in_progress_episodes'):
            try:
                from resources.lib.watched_provider import is_mdblist as _is_mdb_prov
                _clr = 'lightskyblue' if _is_mdb_prov() else 'pink'
                li.setLabel('[B][COLOR {}]{}[/COLOR][/B]'.format(_clr, item.get('name')))
            except Exception:
                pass
        art = {'icon': icon, 'thumb': icon, 'poster': icon}
        if item.get('fanart'):
            art['fanart'] = item['fanart']
            art['landscape'] = item['fanart']
        li.setArt(art)
        
        if 'cm' in item:
            li.addContextMenuItems(item['cm'])
        
        info = item.get('info')
        if info:
            try:
                _tag = li.getVideoInfoTag()
                if info.get('mediatype'):
                    _tag.setMediaType(str(info['mediatype']))
                if info.get('title'):
                    _tag.setTitle(str(info['title']))
                if info.get('plot'):
                    _tag.setPlot(str(info['plot']))
            except:
                pass

        is_folder = item.get('folder', True)
        listing.append((url, li, is_folder))

    _t2 = time.time()
    xbmcplugin.addDirectoryItems(handle, listing, len(listing))
    if content_type:
        xbmcplugin.setContent(handle, content_type)
    xbmcplugin.endOfDirectory(handle, True, False, not no_cache)
    _t3 = time.time()
    # DEBUG TIMING (pastreaza — util la depanare lag pornire):
    # if len(listing) < 15:
    #     xbmc.log(f"[TIMING] build_fast_menu: prepare={int((_t1-_t0)*1000)}ms loop={int((_t2-_t1)*1000)}ms add={int((_t3-_t2)*1000)}ms total={int((_t3-_t0)*1000)}ms items={len(listing)}", xbmc.LOGINFO)

# =============================================================================
# MENIURI STATICE (CITITE LOCAL, FARA API)
# =============================================================================

def get_settings_menu_items():
    """Construieste meniul de setari citind fisierele local."""
    items = []
    profile = get_profile()
    addon = get_addon()
    
    # TMDB Status
    tmdb_user = None
    try:
        with open(profile + 'tmdb_v4_token.json', 'r') as f:
            data = json.load(f)
            if data.get('access_token'):
                tmdb_user = data.get('username', 'Connected')
    except:
        pass

    if tmdb_user:
        items.append({'name': f'[B][COLOR FF00CED1]TMDB: {tmdb_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect TMDB[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'tmdb_logout_action', 'folder': False})
    else:
        items.append({'name': '[B][COLOR FF00CED1]Connect TMDB[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'tmdb_auth_action', 'folder': False})

    # Trakt Status
    trakt_user = None
    token = addon.getSetting('trakt_access_token')
    if token:
        raw_status = addon.getSetting('trakt_status')
        if raw_status.startswith('Conectat: '):
            addon.setSetting('trakt_status', raw_status.replace('Conectat: ', 'Connected: '))
        trakt_user = raw_status.replace('Conectat: ', '').replace('Connected: ', '') or 'User'

    if trakt_user and trakt_user != 'Disconnected':
        items.append({'name': f'[B][COLOR pink]Trakt: {trakt_user}[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect Trakt[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'trakt_revoke_action', 'folder': False})
    else:
        items.append({'name': '[B][COLOR pink]Connect Trakt[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'trakt_auth_action', 'folder': False})

    # MDBList Status
    mdblist_token = addon.getSetting('mdblist_access_token')
    mdblist_api_key = addon.getSetting('mdblist_api')
    mdblist_username = addon.getSetting('mdblist_username') or ''
    mdblist_status_raw = addon.getSetting('mdblist_status') or 'Disconnected'

    if mdblist_token or mdblist_api_key:
        display_name = mdblist_username or mdblist_status_raw.replace('Connected: ', '')
        items.append({'name': f'[B][COLOR lightskyblue]MDBList: {display_name}[/COLOR][/B]', 'iconImage': 'mdblist.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect MDBList[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'mdblist_revoke', 'folder': False})
    else:
        items.append({'name': '[B][COLOR lightskyblue]Connect MDBList[/COLOR][/B]', 'iconImage': 'mdblist.png', 'mode': 'mdblist_auth', 'folder': False})

    if (trakt_user and trakt_user != 'Disconnected') or mdblist_token or mdblist_api_key:
        items.append({'name': '[B][COLOR FF6AFB92]Smart Sync[/COLOR][/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'trakt_sync_smart_action', 'folder': False})
        items.append({'name': '[B][COLOR cyan]Full Sync (Force)[/COLOR][/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'trakt_sync_action', 'folder': False})

    items.append({'name': 'Addon Settings', 'iconImage': 'DefaultAddonService.png', 'mode': 'open_settings', 'folder': False})
    items.append({'name': '[B][COLOR orange]Delete All Cache[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_cache_action', 'folder': False})
    
    items.append({'name': '[B][COLOR FF7B68EE]Upload Kodi Log to Pastebin[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'upload_log', 'folder': False})
    items.append({'name': '[B][COLOR FF6AFB92]Support the Project (Donate)[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'show_donate', 'folder': False})
        
    return items

def get_search_menu_items():
    """Construieste meniul de cautare cu istoric."""
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
    global _handle
    import time
    _t0 = time.time()
    _handle = None
    params = get_params()
    mode = params.get('mode')
    handle = get_handle()

    # Sync HANDLE across modules if already imported (stale copies with reuselanguageinvoker)
    if 'resources.lib.config' in sys.modules:
        sys.modules['resources.lib.config'].HANDLE = handle
    for _mod in ('resources.lib.tmdb_api', 'resources.lib.trakt_api'):
        if _mod in sys.modules:
            try:
                sys.modules[_mod].HANDLE = handle
            except:
                pass

    # Sync PAGE_LIMIT module-level copies (config.py __getattr__ face restul)
    if 'resources.lib.config' in sys.modules:
        try:
            _pl = sys.modules['resources.lib.config'].PAGE_LIMIT  # → __getattr__
        except:
            _pl = 20
        for _mod in ('resources.lib.tmdb_api', 'resources.lib.trakt_api'):
            if _mod in sys.modules:
                try:
                    sys.modules[_mod].PAGE_LIMIT = _pl
                except:
                    pass

    if not mode:
        _t1 = time.time()
        from resources.lib import menus
        _t2 = time.time()
        build_fast_menu(menus.root_list)
        _t3 = time.time()
        # DEBUG TIMING (pastreaza — util la depanare lag pornire):
        # xbmc.log(f"[TIMING] root menu: import={int((_t2-_t1)*1000)}ms build={int((_t3-_t2)*1000)}ms total={int((_t3-_t0)*1000)}ms", xbmc.LOGINFO)
        return

    if mode == 'color_picker':
        from resources.lib.color_picker import pick_color
        pick_color(params.get('setting', ''))
        return

    if mode == 'clear_provider_cache':
        # Apelat din settings.xml onchange la schimbarea watched_status_provider.
        # Curata TOATE cache-urile; sync-ul principal e declansat de TMDbMonitor
        # (procesul service, long-lived) — thread-ul de aici e doar fallback
        # (deduplicat de lock-ul tmdbmovies_sync_active din sync_full_library).
        try:
            from resources.lib.config import clear_settings_cache
            clear_settings_cache()
        except:
            pass
        from resources.lib.watched_provider import clear_cache
        clear_cache()
        try:
            xbmc.executebuiltin('Container.Refresh')
        except:
            pass
        def _provider_switch_sync():
            try:
                xbmc.sleep(2000)
                from resources.lib.config import clear_settings_cache as _csc
                from resources.lib.watched_provider import clear_cache as _cc, get_provider as _gp, sync_full_library as _sfl
                _csc()
                _cc()
                _prov = _gp()
                xbmc.log(f"[TMDb Movies] clear_provider_cache fallback sync -> {_prov} (force). Starting...", xbmc.LOGINFO)
                try:
                    xbmc.executebuiltin('Container.Refresh')
                except:
                    pass
                _sfl(silent=True, force=True)
                xbmc.log(f"[TMDb Movies] clear_provider_cache fallback sync ({_prov}) complete.", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Provider switch sync error: {e}", xbmc.LOGERROR)
        threading.Thread(target=_provider_switch_sync, daemon=True).start()
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

    if mode == 'actors_menu':
        from resources.lib import tmdb_api
        tmdb_api.build_actors_list({'action': 'popular'})
        return

    if mode == 'play_trailer':
        video_id = params.get('video_id')
        if video_id:
            from resources.lib.trailer_player import play_trailer
            play_trailer(video_id)
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

    if mode == 'build_actors_list':
        from resources.lib import tmdb_api
        tmdb_api.build_actors_list(params)
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
        build_fast_menu(menus.tmdb_watchlist_list_menu())
        return
    if mode == 'tmdb_favorites_menu':
        from resources.lib import menus
        build_fast_menu(menus.tmdb_favorites_list_menu())
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
    if mode == 'trakt_account_info':
        from resources.lib import trakt_api
        trakt_api.trakt_account_info()
        return
    if mode == 'trakt_sync':
        from resources.lib.watched_provider import sync_full_library
        sync_full_library(silent=False, force=True)
        return
    if mode == 'trakt_sync_smart':
        from resources.lib.watched_provider import sync_full_library
        sync_full_library(silent=False, force=False)
        return
    if mode == 'trakt_sync_db':
        from resources.lib import trakt_sync
        trakt_sync.sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return
    if mode == 'run_import':
        from resources.lib.history_import import run_import
        run_import(get_addon().getSetting('import_selector'))
        return
    if mode == 'tmdb_refresh_lists':
        # Refresh DOAR contul TMDb (watchlist/favorites/liste/recommendations) — fara sync Trakt
        from resources.lib import trakt_sync, tmdb_api
        if not tmdb_api.get_tmdb_session():
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
            return
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Syncing TMDb...", tmdb_api.TMDB_ICON, 2000, False)
        trakt_sync.sync_tmdb_only(silent=True, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return
    if mode == 'trakt_main_menu':
        from resources.lib import menus
        from resources.lib.watched_provider import is_mdblist as _is_mdblist_provider
        _items = menus.trakt_main_list
        if _is_mdblist_provider():
            _items = [it for it in _items if it.get('mode') != 'next_episodes']
        build_fast_menu(_items)
        return

    if mode == 'trakt_movies_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_movies_list, no_cache=True)
        return

    if mode == 'trakt_tv_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_tv_list, no_cache=True)
        return

    if mode == 'trakt_public_lists_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_public_list)
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
        build_fast_menu(menus.trakt_favorites_list_menu())
        return
    if mode == 'trakt_watchlist_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_watchlist_list_menu())
        return
    if mode == 'trakt_history_menu':
        from resources.lib import menus
        build_fast_menu(menus.trakt_history_list_menu())
        return
    if mode == 'trakt_dropped_shows':
        from resources.lib import trakt_api
        trakt_api.trakt_dropped_shows_list(params)
        return
    if mode == 'trakt_period_dialog':
        from resources.lib import trakt_api
        trakt_api.trakt_period_dialog(params)
        return
    if mode == 'trakt_calendar_menu':
        from resources.lib import trakt_api
        trakt_api.trakt_calendar_menu(params)
        return
    if mode == 'trakt_calendar':
        from resources.lib import trakt_api
        trakt_api.trakt_calendar(params)
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
        
        token = get_addon().getSetting('trakt_access_token')
        if not token:
            build_fast_menu([{'name': '[B][COLOR pink]Connect Trakt[/COLOR][/B]', 'mode': 'trakt_auth_action', 'iconImage': 'DefaultUser.png', 'folder': False}])
            return
            
        hidden_count = 0
        try:
            from resources.lib import trakt_sync as _ts
            if os.path.exists(_ts.DB_PATH):
                _conn = _ts.get_connection()
                _c = _conn.cursor()
                _c.execute("SELECT COUNT(*) FROM trakt_hidden_shows")
                hidden_count = _c.fetchone()[0] or 0
                _conn.close()
        except Exception:
            import traceback
            xbmc.log("[TMDb Movies] [MENU] trakt_my_lists count EXCEPTION: " + traceback.format_exc(), xbmc.LOGERROR)
            hidden_count = 0

        items = [
            {'name': '[B][COLOR pink]Account Info[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_account_info', 'folder': False},
            {'name': '[B][COLOR FFCCCCFF]Watchlist[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_watchlist_menu'},
            {'name': '[B][COLOR FFCCCCFF]Favorites[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_menu'},
            {'name': '[B][COLOR red]Dropped Shows[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % hidden_count, 'iconImage': 'trakt.png', 'mode': 'trakt_dropped_shows'},
            {'name': '[B][COLOR FFCCCCFF]History[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_history_menu'}
        ]
        
        user_lists = trakt_sync.get_lists_from_db()
        if user_lists:
            items.append({'name': '[B][COLOR pink]--- My Lists ---[/COLOR][/B]', 'mode': 'noop', 'iconImage': 'DefaultUser.png', 'folder': False})
            for lst in user_lists:
                plot_text = lst.get('description', '') or '%s (%d items)' % (lst['name'], lst['item_count'])
                items.append({
                    'name': f"[B][COLOR FFCCCCFF]{lst['name']}[/B] [B][COLOR FFFDBD01]({lst['item_count']})[/COLOR][/B]",
                    'mode': 'trakt_list_items',
                    'list_type': 'user_list',
                    'slug': lst['ids']['slug'],
                    'iconImage': lst.get('icon', 'trakt.png'),
                    'fanart': lst.get('fanart', ''),
                    'info': {'mediatype': 'video', 'title': lst['name'], 'plot': plot_text}
                })
        
        items.append({'name': '[B][COLOR FFCCCCFF]Liked Lists[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_liked_lists'})
        build_fast_menu(items, no_cache=True)
        return

    if mode == 'tmdb_auth':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_auth()
        return
    if mode in ('tmdb_logout', 'tmdb_revoke'):
        from resources.lib import tmdb_api
        tmdb_api.tmdb_logout()
        return

    if mode == 'perform_search':
        from resources.lib import tmdb_api
        tmdb_api.perform_search(params)
        return
    
    if mode == 'perform_actor_search':
        from resources.lib import tmdb_api
        tmdb_api.perform_actor_search(params)
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
    if mode == 'multiselect_genres':
        from resources.lib import tmdb_api
        tmdb_api.multiselect_genres(params)
        return
    if mode == 'navigator_years':
        from resources.lib import tmdb_api
        tmdb_api.navigator_years(params)
        return
    if mode == 'navigator_providers':
        from resources.lib import tmdb_api
        tmdb_api.navigator_providers(params)
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
    if mode == 'list_by_provider':
        from resources.lib import tmdb_api
        tmdb_api.list_by_provider(params)
        return
    if mode == 'list_highest_revenue':
        from resources.lib import tmdb_api
        tmdb_api.list_highest_revenue(params)
        return
    if mode == 'list_most_voted':
        from resources.lib import tmdb_api
        tmdb_api.list_most_voted(params)
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
        player.list_sources(params)
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
    if mode == 'actor_dialog':
        actor_id = params.get('actor_id')
        if actor_id:
            from resources.lib.context.extended_info_mod import (
                ActorInfo, play_youtube_and_return, run_extended_info,
                handle_next_info, NAVIGATION_STACK,
                XML_ACTOR_INFO, ADDON_PATH
            )
            NAVIGATION_STACK.clear()
            NAVIGATION_STACK.append({'type': 'actor', 'actor_id': actor_id})
            wd = ActorInfo(XML_ACTOR_INFO, ADDON_PATH, actor_id=actor_id)
            wd.doModal()
            while wd.next_info:
                next_type, next_data = wd.next_info
                wd.next_info = None
                if next_type == 'youtube_play':
                    del wd
                    play_youtube_and_return(next_data)
                    wd = ActorInfo(XML_ACTOR_INFO, ADDON_PATH, actor_id=actor_id)
                    wd.doModal()
                elif next_type == 'media':
                    del wd
                    run_extended_info(next_data['id'], next_data['type'], clear_stack=False)
                    return
                elif next_type == 'actor':
                    del wd
                    actor_id = next_data
                    NAVIGATION_STACK.append({'type': 'actor', 'actor_id': actor_id})
                    wd = ActorInfo(XML_ACTOR_INFO, ADDON_PATH, actor_id=actor_id)
                    wd.doModal()
            NAVIGATION_STACK.clear()
        return

    if mode == 'extended_info':
        tmdb_id = params.get('tmdb_id')
        mtype = params.get('type', 'movie')
        if tmdb_id:
            from resources.lib.context.extended_info_mod import run_extended_info
            run_extended_info(tmdb_id, mtype)
        return

    if mode == 'mdblist_auth':
        from resources.lib.mdblist_api import mdblist_auth
        mdblist_auth()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'mdblist_revoke':
        from resources.lib.mdblist_api import mdblist_revoke
        mdblist_revoke()
        return

    if mode == 'mdblist_sync':
        from resources.lib.mdblist_sync import sync_full_library
        sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'mdblist_sync_smart':
        from resources.lib.mdblist_sync import sync_full_library
        sync_full_library(silent=False, force=False)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'mdblist_rating':
        from resources.lib.mdblist_api import prompt_mdblist_rating
        prompt_mdblist_rating(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode'),
            params.get('title', '')
        )
        return

    if mode == 'mdblist_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_mdblist_context_menu(
            params.get('tmdb_id'),
            params.get('imdb_id'),
            params.get('type'),
            params.get('title', ''),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'mdblist_mark_dropped':
        from resources.lib.mdblist_sync import drop_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
        if drop_show(params.get('tmdb_id'), params.get('title', '')):
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "Show dropped", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'mdblist_unmark_dropped':
        from resources.lib.mdblist_sync import restore_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
        if restore_show(params.get('tmdb_id')):
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "Show restored", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode and mode.startswith('mdblist_'):
        if mode == 'mdblist_upnext':
            # MDB Up Next = aceeasi functie dinamica ca TV Shows → Next Episodes
            from resources.lib import trakt_api
            trakt_api.get_next_episodes()
            return
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

    if mode == 'all_providers_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_all_providers_context_menu(
            params.get('tmdb_id'),
            params.get('imdb_id'),
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

    if mode == 'add_rating':
        from resources.lib import tmdb_api
        tmdb_api.prompt_add_rating_picker(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode'),
            params.get('title', '')
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
        from resources.lib.watched_provider import dispatch_mark_watched
        dispatch_mark_watched(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return
        
    if mode == 'mark_unwatched':
        from resources.lib.watched_provider import dispatch_mark_unwatched
        dispatch_mark_unwatched(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'remove_progress':
        from resources.lib.watched_provider import dispatch_remove_progress
        import threading
        content_type = params.get('type', 'movie')
        tmdb_id = params.get('tmdb_id')
        season = params.get('season')
        episode = params.get('episode')
        
        # 0. Capturam calea folderului ACUM, in contextul RunPlugin (fereastra e
        #    inca activa). Daca o citim in thread dupa 300ms, pe AF3 returneaza
        #    des gol / neactualizata -> refresh-ul nu face nimic.
        current_path = xbmc.getInfoLabel('Container.FolderPath') or ''
        xbmc.log(f"[TMDb Movies] [RESUME] remove_progress: path capturat = {current_path}", xbmc.LOGINFO)
        
        # 0b. Pentru EPISOADE, reconstruim URL-ul episoadelor DOAR cand path-ul
        #     capturat e gol (widget/subcontainer pe AF3). Daca suntem deja intr-o
        #     lista plugin (Next Episodes / sezon / details), pastram path-ul — DAR
        #     refresh-ul se face cu Container.Refresh (in-place, pastreaza Back),
        #     nu cu Container.Update(path,replace), care strict navigarea inapoi
        #     (Back salta direct la root in loc de show/sezon) pe AF3.
        refresh_path = current_path
        if content_type == 'episode' and tmdb_id and season and not current_path.startswith('plugin://'):
            try:
                tv_title = params.get('tv_show_title') or params.get('title')
                if not tv_title:
                    from resources.lib import trakt_sync
                    _sd = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'tv')
                    if _sd:
                        tv_title = _sd.get('name') or _sd.get('title') or ''
                from urllib.parse import urlencode as _ue
                refresh_path = f"{sys.argv[0]}?{_ue({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(season), 'tv_show_title': tv_title or 'Show'})}"
                xbmc.log(f"[TMDb Movies] [RESUME] remove_progress: URL episoade construit = {refresh_path}", xbmc.LOGINFO)
            except Exception as _e:
                xbmc.log(f"[TMDb Movies] [RESUME] Eroare la construirea URL episoade: {_e}", xbmc.LOGERROR)

        # 1. Stergem progresul local si de pe servere
        dispatch_remove_progress(tmdb_id, content_type, season, episode)
        
        # 2. Refresh agresiv in background
        def delayed_refresh(folder_path):
            # Asteptam ca meniul contextual sa se inchida complet
            xbmc.sleep(500)
            try:
                if folder_path.startswith('plugin://'):
                    # Suntem deja in containerul plugin -> refresh in place.
                    # Container.Refresh re-invoce lista curenta FARA sa modifice
                    # istoricul de navigare (Back ramane pe show -> trending).
                    xbmc.log(f"[TMDb Movies] [RESUME] Container.Refresh (in-place) path={folder_path}", xbmc.LOGINFO)
                    xbmc.executebuiltin("Container.Refresh")
                else:
                    xbmc.log(f"[TMDb Movies] [RESUME] Container.Update fallback: {folder_path}", xbmc.LOGINFO)
                    xbmc.executebuiltin(f'Container.Update("{folder_path}",replace)')
            except Exception as e:
                xbmc.log(f"[TMDb Movies] [RESUME] Eroare la refresh: {e}", xbmc.LOGERROR)
                xbmc.executebuiltin("Container.Refresh")

        threading.Thread(target=delayed_refresh, args=(refresh_path,), daemon=True).start()
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
        from resources.lib.watched_provider import sync_full_library
        sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'trakt_sync_smart_action':
        from resources.lib.watched_provider import sync_full_library
        sync_full_library(silent=False, force=False)
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

    if mode == 'manual_mdblist_backup':
        from resources.lib import utils
        utils.perform_mdblist_backup(manual=True)
        return

    if mode == 'library_sync':
        from resources.lib import library
        library.sync_library(force=True)
        return
    if mode == 'library_select_lists':
        from resources.lib import library
        library.select_tmdb_lists_dialog()
        return
    if mode == 'library_browse_dest':
        from resources.lib import library
        library.browse_destination()
        return
    if mode == 'library_clear':
        from resources.lib import library
        library.clear_library()
        return
    if mode == 'add_to_library':
        from resources.lib import library
        tmdb_id_a = params.get('tmdb_id')
        type_a = params.get('type')
        title_a = params.get('title')
        if library.is_in_library(tmdb_id_a, type_a):
            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies Library[/COLOR][/B]',
                                           f'[B][COLOR yellow]{title_a}[/COLOR][/B] already in library',
                                           library.ADDON_ICON)
            return
        library.add_to_library(
            tmdb_id=tmdb_id_a,
            media_type=type_a,
            title=title_a,
            year=params.get('year'),
            season=params.get('season'),
            episode=params.get('episode')
        )
        xbmc.executebuiltin('Container.Refresh')
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

def _maybe_refresh_widgets_after_sync():
    """Refresh widget-urile de pe Home dupa un sync automat reusit, DOAR daca
    setarea 'Attempt to Refresh Widgets After Refresh' e activa (default false).
    La fel ca POV (trakt.sync_refresh_widgets): fara asta, widget-urile AF3 (Next
    Episodes, In Progress, etc.) raman stale dupa ce sync-ul aduce watched/resume
    de pe server — doar restart/refresh manual le improspata."""
    try:
        from resources.lib.config import ADDON
        if ADDON.getSetting('trakt_sync_refresh_widgets') == 'true':
            from resources.lib.watched_provider import widget_refresh
            widget_refresh()
            xbmc.log("[TMDb Movies] TraktMonitor Service Update - Widget Refresh Performed", xbmc.LOGINFO)
        else:
            xbmc.log("[TMDb Movies] TraktMonitor Service Update - Widget Refresh Disabled. Skipping", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[TMDb Movies] TraktMonitor Service Update - Widget Refresh Failed: {e}", xbmc.LOGERROR)

def run_service():
    try:
        from resources.lib.config import ADDON
    except:
        return

    # --- STARTUP WARMUP: incarcam cache-urile inainte ca utilizatorul sa apese orice ---
    try:
        from resources.lib.cache import warm_ram_pool_from_db
        warm_ram_pool_from_db()
    except:
        pass
    try:
        from resources.lib.trakt_sync import warm_tv_meta_cache_from_db
        warm_tv_meta_cache_from_db()
    except:
        pass
    # ---------------------------------------------------------------------------------

    class TMDbMonitor(xbmc.Monitor):
        def __init__(self):
            xbmc.Monitor.__init__(self)
            self.first_run = True
            self.update_context_menu_property()
            
            self._version_changed = False
            try:
                from resources.lib.utils import check_addon_update
                if check_addon_update():
                    self._version_changed = True
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Error la verificarea de update: {e}", xbmc.LOGERROR)
            try:
                from resources.lib.watched_provider import get_provider as _gp0
                self._last_provider = _gp0()
            except:
                self._last_provider = None
            self._provider_pending = False

        def onWindowActivated(self, windowId):
            # Cand se inchide dialogul de setari, fereastra de dedesubt se reactiveaza.
            # Kodi restaureaza containerele vizitate din memorie (fara re-invocarea
            # plugin-ului) — deci dupa o schimbare de provider, fortam refresh-ul
            # la prima activare a unei ferestre (ex. inchiderea setarilor).
            if self._provider_pending:
                self._provider_pending = False
                def _do_refresh():
                    try:
                        xbmc.sleep(400)
                        xbmc.executebuiltin('Container.Refresh')
                    except:
                        pass
                threading.Thread(target=_do_refresh, daemon=True).start()

        def onSettingsChanged(self):
            self.update_context_menu_property()
            # Clear fast cache — toate setarile iau efect instant
            try:
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
            except:
                pass
            # Re-parse settings.xml → Window Property (bypass RLI stale cache)
            try:
                from resources.lib.config import clear_settings_cache
                clear_settings_cache()
            except:
                pass
            # Clear watched provider cache (provider switching takes effect immediately)
            try:
                from resources.lib.watched_provider import clear_cache as clear_provider_cache
                clear_provider_cache()
            except:
                pass
            # --- DETECTIE SCHIMBARE PROVIDER (watched_status_provider) ---
            # Sync-ul ruleaza in procesul SERVICE (long-lived) — thread-urile daemon
            # dintr-un apel RunPlugin mor cu procesul pluginului (router.py SystemExit).
            try:
                from resources.lib.watched_provider import get_provider as _get_prov
                _current = _get_prov()
                if self._last_provider is not None and _current != self._last_provider:
                    xbmc.log(f"[TMDb Movies] Watched provider changed: {self._last_provider} -> {_current}. Scheduling full sync...", xbmc.LOGINFO)
                    self._provider_pending = True

                    def _provider_switch_sync():
                        try:
                            xbmc.sleep(2000)
                            from resources.lib.config import clear_settings_cache as _csc
                            from resources.lib.watched_provider import clear_cache as _cc, get_provider as _gp, sync_full_library as _sfl
                            _csc()
                            _cc()
                            _prov = _gp()
                            xbmc.log(f"[TMDb Movies] Provider switch sync -> {_prov} (force). Starting...", xbmc.LOGINFO)
                            try:
                                if _prov == 'trakt':
                                    from resources.lib.trakt_api import get_trakt_token as _tok
                                    _connected = bool(_tok())
                                else:
                                    _connected = bool(get_addon().getSetting('mdblist_access_token') or get_addon().getSetting('mdblist_api'))
                                if not _connected:
                                    _name = 'Trakt' if _prov == 'trakt' else 'MDBList'
                                    _clr = 'pink' if _prov == 'trakt' else 'lightskyblue'
                                    xbmcgui.Dialog().notification(f'[B][COLOR {_clr}]{_name}[/COLOR][/B]',
                                                                  f'Provider switched to [B]{_name}[/B], but {_name} is not connected. Connect it in Settings!',
                                                                  xbmcgui.NOTIFICATION_WARNING, 6000, False)
                            except:
                                pass
                            try:
                                xbmc.executebuiltin('Container.Refresh')
                            except:
                                pass
                            _sfl(silent=True, force=True)
                            xbmc.log(f"[TMDb Movies] Provider switch sync ({_prov}) complete.", xbmc.LOGINFO)
                            try:
                                xbmc.executebuiltin('Container.Refresh')
                            except:
                                pass
                        except Exception as e:
                            xbmc.log(f"[TMDb Movies] Provider switch sync error: {e}", xbmc.LOGERROR)
                    threading.Thread(target=_provider_switch_sync, daemon=True).start()
                self._last_provider = _current
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Provider switch detection error: {e}", xbmc.LOGERROR)
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

            if ADDON.getSetting('enable_trailer_context') == 'true':
                window.setProperty('TMDbMovies.TrailerContext', 'true')
            else:
                window.clearProperty('TMDbMovies.TrailerContext')

            if ADDON.getSetting('enable_library_context') == 'true':
                window.setProperty('TMDbMovies.LibraryContext', 'true')
            else:
                window.clearProperty('TMDbMovies.LibraryContext')

        def run(self):
            # --- Auto-sync check at startup (before delay) ---
            try:
                from resources.lib.library import check_auto_sync
                check_auto_sync(startup=True)
            except:
                pass

            _SYNC_DELAYS = [5, 60, 300, 600, 900, 1800]
            try:
                _delay_idx = int(ADDON.getSetting('trakt_sync_delay') or '0')
                _delay = _SYNC_DELAYS[_delay_idx]
            except:
                _delay = 5

            # Force immediate sync if version changed
            if getattr(self, '_version_changed', False):
                _delay = 5

            if self.waitForAbort(_delay):
                return
                
            self.clear_temp_subs()
            self.cleanup_downloads()
            
            # Prefetch popular metadata into RAM for instant browsing
            try:
                from resources.lib.cache import _ensure_ram_cache_ver, ram_cache_get_tvshow, ram_cache_set_tvshow
                _ensure_ram_cache_ver()
                from resources.lib import trakt_sync
                from resources.lib.tmdb_api import get_tmdb_item_details, get_tmdb_movies_standard, get_tmdb_tv_standard
                from resources.lib.cache import cache_object
                xbmc.log("[TMDb Movies] Prefetching popular metadata into RAM...", xbmc.LOGINFO)
                # TV shows metadata + list cache
                for action in ('tmdb_tv_trending_week', 'tmdb_tv_popular'):
                    results = trakt_sync.get_tmdb_from_db(action, 1)
                    if not results:
                        data = cache_object(get_tmdb_tv_standard, f'{action}_1_en-US', [action, 1], expiration=12)
                        if data: results = data.get('results', [])
                    if results:
                        for item in results[:20]:
                            tid = str(item.get('id', ''))
                            if tid and not ram_cache_get_tvshow(tid):
                                get_tmdb_item_details(tid, 'tv')
                # Movies metadata + list cache
                for action in ('tmdb_movies_trending_week', 'tmdb_movies_popular'):
                    results = trakt_sync.get_tmdb_from_db(action, 1)
                    if not results:
                        data = cache_object(get_tmdb_movies_standard, f'{action}_1_en-US', [action, 1], expiration=12)
                        if data: results = data.get('results', [])
                    if results:
                        for item in results[:20]:
                            mid = str(item.get('id', ''))
                            if mid and not ram_cache_get_tvshow(mid):
                                get_tmdb_item_details(mid, 'movie')
                xbmc.log("[TMDb Movies] RAM prefetch complete", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[TMDb Movies] RAM prefetch error: {e}", xbmc.LOGINFO)
            
            if self.first_run:
                self.sync_worker()
                self.first_run = False
                
            while not self.abortRequested():
                if self.waitForAbort(1800):
                    break
                self.sync_worker()
                try:
                    from resources.lib.library import check_auto_sync
                    check_auto_sync()
                except:
                    pass

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
                # --- Trakt auto-sync (daemon thread — nu blocheaza shutdown-ul) ---
                trakt_token = get_addon().getSetting('trakt_access_token')
                if trakt_token:
                    xbmc.log("[TMDb Movies] TraktMonitor Service Update - Starting background sync...", xbmc.LOGINFO)

                    def _run_trakt():
                        try:
                            from resources.lib import trakt_sync
                            trakt_sync.sync_full_library(silent=True, force=getattr(self, '_version_changed', False))
                            xbmc.log("[TMDb Movies] TraktMonitor Service Update - Success. Next Update in 30 minutes...", xbmc.LOGINFO)
                            _maybe_refresh_widgets_after_sync()
                        except Exception as e:
                            xbmc.log(f"[TMDb Movies] TraktMonitor Service Update - Failed: {e}", xbmc.LOGERROR)
                    threading.Thread(target=_run_trakt, daemon=True).start()
                else:
                    xbmc.log("[TMDb Movies] TraktMonitor Service Update - Aborted. No Trakt Account Active. Next Update in 30 minutes...", xbmc.LOGINFO)

                # --- MDBList auto-sync (daca exista creds; gating-ul intern al sync-ului
                # decide ce sectiuni se importa in functie de providerul de watched status) ---
                if get_addon().getSetting('mdblist_access_token') or get_addon().getSetting('mdblist_api'):
                    xbmc.log("[TMDb Movies] MDBListMonitor Service Update - Starting background sync...", xbmc.LOGINFO)

                    def _run_mdblist():
                        try:
                            from resources.lib.mdblist_sync import sync_full_library
                            sync_full_library(silent=True, force=getattr(self, '_version_changed', False))
                            xbmc.log("[TMDb Movies] MDBListMonitor Service Update - Success.", xbmc.LOGINFO)
                            _maybe_refresh_widgets_after_sync()
                        except Exception as e:
                            xbmc.log(f"[TMDb Movies] MDBListMonitor Service Update - Failed: {e}", xbmc.LOGERROR)
                    threading.Thread(target=_run_mdblist, daemon=True).start()
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Monitor Service Update - Failed: {e}", xbmc.LOGERROR)

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
        elif mode == 'subtitle_service':
            from resources.lib.subtitle.subtitles import run_wyzie_service
            imdb_id = params.get('imdb_id')
            season = int(params.get('season', 0)) or None
            episode = int(params.get('episode', 0)) or None
            run_wyzie_service(imdb_id, season, episode)
        elif mode == 'background_warmup':
            from resources.lib.tmdb_api import run_background_warmup_sync
            run_background_warmup_sync(params.get('type', 'movie'))
        elif mode == 'mdblist_auth':
            from resources.lib.mdblist_api import mdblist_auth
            mdblist_auth()
        elif mode == 'mdblist_revoke':
            from resources.lib.mdblist_api import mdblist_revoke
            mdblist_revoke()
        elif mode == 'mdblist_sync':
            from resources.lib.mdblist_sync import sync_full_library
            sync_full_library(silent=False, force=True)
        elif mode == 'mdblist_sync_smart':
            from resources.lib.mdblist_sync import sync_full_library
            sync_full_library(silent=False, force=False)
        elif mode == 'clear_all_cache':
            from resources.lib.utils import clear_all_caches_with_notification
            clear_all_caches_with_notification()
        elif mode == 'color_picker':
            from resources.lib.color_picker import pick_color
            pick_color(params.get('setting', ''))
