import sys
import threading
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import os
import json
import time
from urllib.parse import parse_qsl, urlencode, quote, unquote
from resources.lib.config import provider_title, ADDON_PATH as CONFIG_ADDON_PATH

# =============================================================================
# CACHE GLOBAL PENTRU VITEZA
# =============================================================================
_addon = None
_handle = None
_profile = None
_art_path = None
_simkl_status_migrated = False

def _migrate_simkl_status():
    global _simkl_status_migrated
    if _simkl_status_migrated:
        return
    _simkl_status_migrated = True
    try:
        _a = get_addon()
        if _a.getSetting('simkl_status') == '' and not _a.getSetting('simkl_access_token'):
            _a.setSetting('simkl_status', 'Disconnected')
        if _a.getSetting('punchplay_status') == '' and not _a.getSetting('punchplay_access_token'):
            _a.setSetting('punchplay_status', 'Disconnected')
    except:
        pass

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
                from resources.lib.watched_provider import get_color as _get_prov_color
                li.setLabel('[B][COLOR {}]UP NEXT[/COLOR][/B]'.format(_get_prov_color()))
            except Exception:
                pass
        if mode in ('in_progress_movies', 'in_progress_tvshows', 'in_progress_episodes'):
            try:
                from resources.lib.watched_provider import get_color as _get_prov_color
                _clr = _get_prov_color()
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

def get_providers_menu_items():
    """Construieste directorul Providers - cei 4 provideri (cele 8 setari conectare)."""
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
        items.append({'name': f'[B][COLOR FF00CED1]TMDB: {tmdb_user}[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'noop', 'folder': False})
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
        items.append({'name': f'[B][COLOR pink]Trakt: {trakt_user}[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'noop', 'folder': False})
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
        items.append({'name': '[B][COLOR lightskyblue]Connect MDBList[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'mdblist_auth', 'folder': False})

    # Simkl Status
    simkl_token = addon.getSetting('simkl_access_token')
    simkl_username = addon.getSetting('simkl_username') or ''
    if simkl_token:
        if not simkl_username:
            try:
                from resources.lib.simkl_api import SIMKLAPI
                _sk_info = SIMKLAPI().get_user_info()
                if isinstance(_sk_info, dict) and _sk_info.get('username'):
                    simkl_username = _sk_info['username']
                    addon.setSetting('simkl_username', simkl_username)
                    addon.setSetting('simkl_status', f'Connected: {simkl_username}')
            except:
                pass
        display_name = simkl_username or 'Connected'
        items.append({'name': f'[B][COLOR mediumpurple]Simkl: {display_name}[/COLOR][/B]', 'iconImage': 'simkl.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect Simkl[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'simkl_revoke', 'folder': False})
    else:
        items.append({'name': '[B][COLOR mediumpurple]Connect Simkl[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'simkl_auth', 'folder': False})

    # PunchPlay Status
    punchplay_token = addon.getSetting('punchplay_access_token')
    punchplay_username = addon.getSetting('punchplay_username') or ''
    if punchplay_token:
        if not punchplay_username:
            try:
                from resources.lib.punchplay_api import PunchplayAPI
                _pp_info = PunchplayAPI().get_user_info()
                if isinstance(_pp_info, dict) and _pp_info.get('username'):
                    punchplay_username = _pp_info['username']
                    addon.setSetting('punchplay_username', punchplay_username)
                    addon.setSetting('punchplay_status', f'Connected: {punchplay_username}')
            except:
                pass
        display_name = punchplay_username or 'Connected'
        items.append({'name': f'[B][COLOR FFFF6600]PunchPlay: {display_name}[/COLOR][/B]', 'iconImage': 'punchplay.png', 'mode': 'noop', 'folder': False})
        items.append({'name': '[B][COLOR FFF535AA]Disconnect PunchPlay[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'punchplay_revoke', 'folder': False})
    else:
        items.append({'name': '[B][COLOR FFFF6600]Connect PunchPlay[/COLOR][/B]', 'iconImage': 'DefaultUser.png', 'mode': 'punchplay_auth', 'folder': False})

    # Kodi (Local): mereu conectat, fara cont — rand status informativ
    items.append({'name': '[B][COLOR FFF70D1A]Kodi (Local): Connected[/COLOR][/B]', 'iconImage': 'kodi.png', 'mode': 'noop', 'folder': False})

    return items


def _is_local_provider_active():
    try:
        from resources.lib.watched_provider import get_provider as _gp
        return _gp() == 'local'
    except Exception:
        return False


def get_settings_menu_items():
    """Construieste meniul Settings - providerii grupati in directorul Providers."""
    items = []
    addon = get_addon()
    items.append({'name': '[B]Addon Settings[/B]', 'iconImage': 'DefaultAddonService.png', 'mode': 'open_settings', 'folder': False})
    items.append({'name': '[B]My Providers[/B]', 'iconImage': 'DefaultAddonWebSkin.png', 'mode': 'providers_menu'})
    try:
        _inv_state = (addon.getSetting('reuse_language_invoker') or 'true').strip().lower()
    except:
        _inv_state = 'true'
    _inv_label = '[B]Reuse Language Invoker: [/B]' + ('[B][COLOR FF6AFB92]ON[/COLOR][/B]' if _inv_state == 'true' else '[B][COLOR FFF535AA]OFF[/COLOR][/B]')
    items.append({'name': _inv_label, 'iconImage': 'DefaultAddonService.png', 'mode': 'toggle_language_invoker', 'folder': False})
    trakt_user = None
    token = addon.getSetting('trakt_access_token')
    if token:
        raw_status = addon.getSetting('trakt_status')
        trakt_user = raw_status.replace('Conectat: ', '').replace('Connected: ', '') or 'User'
    mdblist_token = addon.getSetting('mdblist_access_token')
    mdblist_api_key = addon.getSetting('mdblist_api')
    simkl_token = addon.getSetting('simkl_access_token')
    punchplay_token = addon.getSetting('punchplay_access_token')
    if (trakt_user and trakt_user != 'Disconnected') or mdblist_token or mdblist_api_key or simkl_token or punchplay_token or _is_local_provider_active():
        # Cand nu exista niciun provider online, butoanele promit un sync care nu aduce
        # nimic vizibil - etichetam explicit ca ruleaza doar pe baza locala.
        _local_only = ''
        try:
            _online = bool(trakt_user and trakt_user != 'Disconnected') or bool(mdblist_token) or bool(mdblist_api_key) or bool(simkl_token) or bool(punchplay_token)
            if not _online:
                _local_only = ' [B][COLOR FFF70D1A](Kodi Local)[/COLOR][/B]'
        except Exception:
            _local_only = ''
        items.append({'name': '[B][COLOR FF6AFB92]Smart Sync[/COLOR][/B]' + _local_only, 'iconImage': 'DefaultAddonsUpdates.png', 'mode': 'trakt_sync_smart_action', 'folder': False})
        items.append({'name': '[B][COLOR cyan]Full Sync (Force)[/COLOR][/B]' + _local_only, 'iconImage': 'DefaultAddonsUpdates.png', 'mode': 'trakt_sync_action', 'folder': False})
    items.append({'name': '[B][COLOR orange]Delete All Cache[/COLOR][/B]', 'iconImage': 'DefaultAddonNone.png', 'mode': 'clear_cache_action', 'folder': False})
    items.append({'name': '[B][COLOR FF87CEEB]Open Kodi Log File[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'view_kodi_log', 'folder': False})
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

def _youtube_fmt_dur(sec):
    try:
        sec = int(sec)
    except:
        return ''
    if sec <= 0:
        return ''
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    if h:
        return '{}:{:02d}:{:02d}'.format(h, m, s)
    return '{}:{:02d}'.format(m, s)


def _youtube_plot(channel='', views='', date='', dur='', desc=''):
    if date and date in views:
        date = ''
    lines = []
    if channel:
        lines.append('[B][COLOR FF00CED1]' + channel + '[/COLOR][/B]')
    stats = []
    if views:
        stats.append('[B][COLOR FFFFD700]' + views + '[/COLOR][/B]')
    if date:
        stats.append('[B][COLOR FFFF69B4]' + date + '[/COLOR][/B]')
    if dur:
        stats.append('[B][COLOR FF87CEEB]' + dur + '[/COLOR][/B]')
    if stats:
        lines.append(' - '.join(stats))
    head = '\n'.join(lines)
    if desc:
        return (head + '\n\n' + desc) if head else desc
    return head


def _youtube_queue_entry(vid, title, views='', date='', dur=''):
    from resources.lib.trailer_player import get_trailer_url
    from resources.lib.context.extended_info_mod import get_youtube_video_meta
    try:
        m = get_youtube_video_meta(vid) or {}
    except:
        m = {}
    ch = m.get('channel') or ''
    desc = m.get('description') or ''
    mdate = m.get('published_date') or ''
    try:
        dur_sec = int(m.get('duration_sec') or 0)
    except:
        dur_sec = 0
    plot = _youtube_plot(channel=ch, views=views, date=(mdate or date), dur=(_youtube_fmt_dur(dur_sec) or dur), desc=desc)
    try:
        url = get_trailer_url(vid, title=title or vid, plot=plot or None, studio=ch or None)
    except:
        return None
    if not url:
        return None
    li = xbmcgui.ListItem(label=title or vid)
    tb = f"https://img.youtube.com/vi/{vid}/mqdefault.jpg"
    li.setArt({'icon': tb, 'thumb': tb, 'poster': tb})
    try:
        tag = li.getVideoInfoTag()
        tag.setTitle(title or vid)
        if plot:
            tag.setPlot(plot)
        if ch:
            tag.setStudios([ch])
        if dur_sec:
            tag.setDuration(dur_sec)
        if mdate:
            tag.setPremiered(mdate)
    except:
        pass
    return (url, li)


def _yt_icon():
    try:
        return os.path.join(get_addon().getAddonInfo('path'), 'icon.png')
    except:
        return ''


def _yt_hist_file():
    try:
        return get_profile() + 'youtube_search_history.json'
    except:
        return ''


def _yt_hist_load():
    try:
        with open(_yt_hist_file(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get('query')]
    except:
        pass
    return []


def _yt_hist_save(hist):
    try:
        with open(_yt_hist_file(), 'w', encoding='utf-8') as f:
            json.dump(hist[:20], f)
        return True
    except:
        return False


def _yt_hist_add(query, ctx):
    if not query:
        return
    hist = [h for h in _yt_hist_load() if h.get('query') != query]
    item = {'query': query}
    for k in ('tmdb_id', 'type', 'title', 'year', 'season'):
        if ctx.get(k):
            item[k] = ctx[k]
    hist.insert(0, item)
    _yt_hist_save(hist)


def _yt_hist_remove(query):
    _yt_hist_save([h for h in _yt_hist_load() if h.get('query') != query])


def _yt_hist_rename(old_q, new_q):
    if not new_q or new_q == old_q:
        return False
    hist = _yt_hist_load()
    for h in hist:
        if h.get('query') == old_q:
            h['query'] = new_q
            break
    else:
        return False
    _yt_hist_save(hist)
    return True


def _yt_hist_clear():
    _yt_hist_save([])


def _yt_results_params(query, ctx):
    rp = {'mode': 'youtube_results', 'query': query, 'tmdb_id': ctx.get('tmdb_id') or '', 'type': ctx.get('type') or '', 'title': ctx.get('title') or '', 'year': ctx.get('year') or ''}
    if ctx.get('season'):
        rp['season'] = ctx['season']
    return rp


def _youtube_autoplay_loop(seen_ids, order):
    import time
    try:
        _ap = xbmc.Player()
        _apl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        _rel_cache = {}
        _idle = 0
        _cool = 0
        xbmc.log(f"[TMDb Movies] [YOUTUBE] autoplay loop started ({len(order)} queued)", xbmc.LOGINFO)
        while True:
            if xbmc.getInfoLabel('Window(10000).Property(TMDbMovies.YoutubeAutoplay)') != 'true':
                xbmc.log("[TMDb Movies] [YOUTUBE] autoplay loop exit: flag off", xbmc.LOGINFO)
                return
            if not _ap.isPlayingVideo():
                _idle += 1
                if _idle > 18:
                    try:
                        xbmcgui.Window(10000).clearProperty('TMDbMovies.YoutubeAutoplay')
                    except:
                        pass
                    xbmc.log("[TMDb Movies] [YOUTUBE] autoplay loop exit: idle", xbmc.LOGINFO)
                    return
                time.sleep(5)
                continue
            _idle = 0
            try:
                _pos = _apl.getposition()
                _size = _apl.size()
            except:
                time.sleep(5)
                continue
            if _pos < 0 or _size - (_pos + 1) > 3:
                time.sleep(5)
                continue
            if _cool > 0:
                _cool -= 1
                time.sleep(5)
                continue
            try:
                from resources.lib.context.extended_info_mod import get_youtube_related
            except:
                time.sleep(5)
                continue
            xbmc.log(f"[TMDb Movies] [YOUTUBE] autoplay topup pos={_pos} size={_size}", xbmc.LOGINFO)
            _need = 5
            _fetches = 0
            for _probe in reversed(order[-8:]):
                if _need <= 0:
                    break
                _rel = _rel_cache.get(_probe)
                if _rel is None:
                    if _fetches >= 3:
                        continue
                    _fetches += 1
                    try:
                        _rel = get_youtube_related(_probe, 10)
                    except Exception as _e:
                        xbmc.log(f"[TMDb Movies] [YOUTUBE] autoplay probe error: {_e}", xbmc.LOGWARNING)
                        _rel = []
                    if _rel:
                        _rel_cache[_probe] = _rel
                for _rd in _rel:
                    if _need <= 0:
                        break
                    _rv = (_rd.get('id') or '') if isinstance(_rd, dict) else ''
                    if not _rv or _rv in seen_ids:
                        continue
                    seen_ids.add(_rv)
                    order.append(_rv)
                    try:
                        _entry = _youtube_queue_entry(_rv, _rd.get('title'), _rd.get('views'), _rd.get('date'), _rd.get('duration'))
                        if not _entry:
                            continue
                        _eu, _eli = _entry
                        _apl.add(url=_eu, listitem=_eli)
                        _need -= 1
                    except:
                        continue
            xbmc.log(f"[TMDb Movies] [YOUTUBE] autoplay topup done: +{5 - _need}", xbmc.LOGINFO)
            if _need >= 5:
                _cool = 11
            time.sleep(5)
    except:
        return

def run_plugin():
    global _handle
    import time
    _t0 = time.time()
    _handle = None
    params = get_params()
    mode = params.get('mode')
    handle = get_handle()
    _migrate_simkl_status()

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
        build_fast_menu(menus.root_menu(), no_cache=True)
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
        # FARA Container.Refresh aici: monitorul face unul dupa sync, iar
        # onWindowActivated inca unul (cu cooldown) — 4-5 refresh-uri simultane
        # produceau ping-pong de reincarcari = spinner infinit la navigare.
        try:
            from resources.lib.config import clear_settings_cache
            clear_settings_cache()
        except:
            pass
        from resources.lib.watched_provider import clear_cache
        clear_cache()
        def _provider_switch_sync():
            try:
                xbmc.sleep(2000)
                from resources.lib.config import clear_settings_cache as _csc
                from resources.lib.watched_provider import clear_cache as _cc, get_provider as _gp, sync_full_library as _sfl
                _csc()
                _cc()
                _prov = _gp()
                xbmc.log(f"[TMDb Movies] clear_provider_cache fallback sync -> {_prov} (force). Starting...", xbmc.LOGINFO)
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

    if mode == 'providers_menu':
        build_fast_menu(get_providers_menu_items())
        return

    if mode == 'search_menu':
        build_fast_menu(get_search_menu_items())
        return

    if mode == 'hindi_movies_menu':
        from resources.lib import menus
        build_fast_menu(menus.hindi_movies_list)
        return

    if mode == 'detonate':
        from resources.lib.detonate import list_years
        list_years()
        return

    if mode == 'detonate_all':
        from resources.lib.detonate import list_all
        list_all()
        return

    if mode == 'detonate_year':
        from resources.lib.detonate import list_year
        list_year(params.get('year', ''))
        return

    if mode == 'detonate_folder':
        from resources.lib.detonate import list_folder
        list_folder(params.get('link', ''))
        return

    if mode == 'detonate_play':
        from resources.lib.detonate import play_movie
        play_movie(params.get('link', ''), params.get('tmdb_id', ''))
        return

    if mode == 'detonate_clear_cache':
        from resources.lib.detonate import clear_detonate_cache
        ok = clear_detonate_cache()
        _icon = get_addon().getAddonInfo('icon')
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
            '[B][COLOR FFCCCCFF]Detonate: [COLOR FFFF5555]' + ('Cleared cache.' if ok else 'No cache file found.') + '[/COLOR][/B]',
            _icon, 2500)
        return

    if mode == 'detonate_worker':
        # Sarcina de fundal lansata prin RunPlugin (invocare separata,
        # fire-and-forget): prefetch metadate sau refresh foldere cloud.
        action = params.get('action', '')
        from resources.lib import detonate
        links = detonate.get_links()
        if not links:
            return
        if action == 'refresh':
            detonate.run_background_refresh(links)
        else:
            detonate.run_meta_prefetch(links)
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
        try:
            xbmcgui.Window(10000).clearProperty('TMDbMovies.YoutubeAutoplay')
        except:
            pass
        if video_id:
            from resources.lib.trailer_player import play_trailer
            _tid = params.get('tmdb_id') or params.get('tmdb')
            _dbtype = params.get('dbtype')
            _ttl = params.get('title')
            _yr = params.get('year')
            if not _tid or not _dbtype or not _ttl:
                _tid = _tid or xbmc.getInfoLabel('ListItem.UniqueID(tmdb)') or ''
                _dbtype = _dbtype or xbmc.getInfoLabel('ListItem.DBTYPE').lower().strip() or ''
                _ttl = _ttl or xbmc.getInfoLabel('ListItem.Title') or ''
                _yr = _yr or xbmc.getInfoLabel('ListItem.Year') or ''
            play_trailer(video_id, tmdb_id=_tid, dbtype=_dbtype,
                         title=_ttl, year=_yr, plot=params.get('plot'),
                         studio=params.get('studio'), tagline=params.get('tagline'),
                         genre=params.get('genre'))
        return

    if mode == 'youtube_search':
        _yts_list = []
        _yts_art = get_art_path()
        _yts_ctx = {'tmdb_id': params.get('tmdb_id') or '', 'type': params.get('type') or '', 'title': params.get('title') or '', 'year': params.get('year') or ''}
        if params.get('season'):
            _yts_ctx['season'] = params.get('season')
        _yts_newp = dict({'mode': 'youtube_search_title'}, **_yts_ctx)
        _yts_new_li = xbmcgui.ListItem(label='[B]Search Now[/B]')
        _yts_new_li.setArt({'icon': _yts_art + 'search_movie.png', 'thumb': _yts_art + 'search_movie.png'})
        _yts_list.append((f"{sys.argv[0]}?{urlencode(_yts_newp)}", _yts_new_li, False))
        _yts_emptyp = dict({'mode': 'youtube_search_empty'}, **_yts_ctx)
        _yts_empty_li = xbmcgui.ListItem(label='[B]Empty Search[/B]')
        _yts_empty_li.setArt({'icon': _yts_art + 'search_movie.png', 'thumb': _yts_art + 'search_movie.png'})
        _yts_list.append((f"{sys.argv[0]}?{urlencode(_yts_emptyp)}", _yts_empty_li, False))
        _yts_hist = _yt_hist_load()[:20]
        for _hh in _yts_hist:
            _hq = _hh.get('query') or ''
            if not _hq:
                continue
            _hli = xbmcgui.ListItem(label=_hq)
            _hli.setArt({'icon': _yts_art + 'search_history.png', 'thumb': _yts_art + 'search_history.png'})
            _hli.addContextMenuItems([
                ('Rename', f"RunPlugin({sys.argv[0]}?{urlencode({'mode': 'youtube_history_rename', 'query': _hq})})"),
                ('Delete', f"RunPlugin({sys.argv[0]}?{urlencode({'mode': 'youtube_history_delete', 'query': _hq})})")])
            _yts_list.append((f"{sys.argv[0]}?{urlencode(_yt_results_params(_hq, _hh))}", _hli, True))
        if _yts_hist:
            _yts_clear_li = xbmcgui.ListItem(label='[B][COLOR FFFF4444]Delete all history[/COLOR][/B]')
            _yts_clear_li.setArt({'icon': 'DefaultAddonNone.png', 'thumb': 'DefaultAddonNone.png'})
            _yts_list.append((f"{sys.argv[0]}?{urlencode({'mode': 'youtube_history_clear'})}", _yts_clear_li, False))
        xbmcplugin.addDirectoryItems(handle, _yts_list, len(_yts_list))
        xbmcplugin.endOfDirectory(handle)
        return

    if mode == 'youtube_search_title':
        _yt_title = params.get('title') or ''
        _yt_year = params.get('year') or ''
        _yt_init = f"{_yt_title} {_yt_year}".strip() if _yt_year else _yt_title
        _yt_q = xbmcgui.Dialog().input('Search Youtube', defaultt=_yt_init, type=xbmcgui.INPUT_ALPHANUM)
        if not _yt_q:
            return
        _yt_hist_add(_yt_q, params)
        xbmc.executebuiltin(f'Container.Update({sys.argv[0]}?{urlencode(_yt_results_params(_yt_q, params))})')
        return

    if mode == 'youtube_search_empty':
        _yt_q = xbmcgui.Dialog().input('Search Youtube', defaultt='', type=xbmcgui.INPUT_ALPHANUM)
        if not _yt_q:
            return
        _yt_hist_add(_yt_q, params)
        xbmc.executebuiltin(f'Container.Update({sys.argv[0]}?{urlencode(_yt_results_params(_yt_q, params))})')
        return

    if mode == 'youtube_history_rename':
        _hq = params.get('query') or ''
        if not _hq:
            return
        _nq = xbmcgui.Dialog().input('Rename search', defaultt=_hq, type=xbmcgui.INPUT_ALPHANUM)
        if _nq and _nq != _hq and _yt_hist_rename(_hq, _nq):
            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', 'Renamed', _yt_icon(), 2000, False)
            xbmc.executebuiltin('Container.Refresh')
        return

    if mode == 'youtube_history_delete':
        _hq = params.get('query') or ''
        if not _hq:
            return
        _yt_hist_remove(_hq)
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', 'Deleted', _yt_icon(), 2000, False)
        xbmc.executebuiltin('Container.Refresh')
        return

    if mode == 'youtube_history_clear':
        _yt_hist_clear()
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', 'History cleared', _yt_icon(), 2000, False)
        xbmc.executebuiltin('Container.Refresh')
        return

    if mode == 'youtube_results':
        _yt_q = params.get('query') or ''
        xbmc.log(f"[TMDb Movies] [YOUTUBE] results query=[{_yt_q}]", xbmc.LOGINFO)
        if _yt_q:
            from resources.lib.context.extended_info_mod import search_youtube_innertube
            _yt_found = search_youtube_innertube(_yt_q, 25)
            xbmc.log(f"[TMDb Movies] [YOUTUBE] found {len(_yt_found)} items", xbmc.LOGINFO)
        else:
            _yt_found = []
        if not _yt_found:
            if _yt_q:
                xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', 'No results found', _yt_icon(), 3000, False)
            xbmcplugin.endOfDirectory(handle)
            return
        try:
            from concurrent.futures import ThreadPoolExecutor, wait
            from resources.lib.context.extended_info_mod import get_youtube_video_meta
            _yt_meta = {}
            _yt_ex = ThreadPoolExecutor(max_workers=10)
            try:
                _yt_fm = {_yt_ex.submit(get_youtube_video_meta, _d.get('id')): _d.get('id') for _d in _yt_found if _d.get('id')}
                _yt_done, _ = wait(set(_yt_fm), timeout=8)
                for _f in _yt_done:
                    try:
                        _yt_meta[_yt_fm[_f]] = _f.result() or {}
                    except:
                        pass
            finally:
                try:
                    _yt_ex.shutdown(wait=False, cancel_futures=True)
                except:
                    pass
        except:
            _yt_meta = {}
        _yt_listing = []
        for _d in _yt_found:
            _yt_vid = _d.get('id') or ''
            _yt_t = _d.get('title') or _yt_vid
            _m = _yt_meta.get(_yt_vid) or {}
            _ch = _m.get('channel') or _d.get('channel') or ''
            _desc = _m.get('description') or ''
            _dur_raw = _d.get('duration') or ''
            try:
                _dur_sec = int(_m.get('duration_sec') or 0)
            except:
                _dur_sec = 0
            if not _dur_sec and _dur_raw:
                try:
                    from resources.lib.context.extended_info_mod import _yt_ts_to_seconds
                    _dur_sec = _yt_ts_to_seconds(_dur_raw)
                except:
                    pass
            _head_views = _d.get('views') or _d.get('views_text') or ''
            _head_date = _m.get('published_date') or _d.get('published') or ''
            _dur_txt = _dur_raw or _youtube_fmt_dur(_dur_sec)
            _plot = _youtube_plot(channel=_ch, views=_head_views, date=_head_date, dur=_dur_txt, desc=_desc)
            _yt_li = xbmcgui.ListItem(label=_yt_t)
            _yt_thumb = _d.get('thumb') or f"https://img.youtube.com/vi/{_yt_vid}/mqdefault.jpg"
            _yt_li.setArt({'icon': _yt_thumb, 'thumb': _yt_thumb, 'poster': _yt_thumb, 'fanart': f"https://img.youtube.com/vi/{_yt_vid}/sddefault.jpg"})
            try:
                _tag = _yt_li.getVideoInfoTag()
                _tag.setTitle(_yt_t)
                if _plot:
                    _tag.setPlot(_plot)
                if _ch:
                    _tag.setStudios([_ch])
                if _dur_sec:
                    _tag.setDuration(_dur_sec)
                if _m.get('published_date'):
                    _tag.setPremiered(_m['published_date'])
            except:
                pass
            _yt_li.setProperty('IsPlayable', 'true')
            _yt_p = {'mode': 'youtube_play', 'yt_src': 'search', 'video_id': _yt_vid, 'tmdb_id': params.get('tmdb_id') or '', 'type': params.get('type') or '', 'title': _yt_t, 'year': params.get('year') or ''}
            if params.get('season'):
                _yt_p['season'] = params.get('season')
            if _plot:
                _yt_p['plot'] = _plot[:2000]
            if _ch:
                _yt_p['studio'] = _ch
            _yt_listing.append((f"{sys.argv[0]}?{urlencode(_yt_p)}", _yt_li, False))
        xbmcplugin.addDirectoryItems(handle, _yt_listing, len(_yt_listing))
        xbmcplugin.setContent(handle, 'videos')
        xbmcplugin.endOfDirectory(handle)
        return

    if mode == 'youtube_play':
        from resources.lib.trailer_player import get_trailer_url
        _yp_vid = params.get('video_id')
        _yp_plot = params.get('plot') or ''
        _yp_studio = params.get('studio') or ''
        if _yp_vid and params.get('yt_src') == 'search' and get_addon().getSetting('youtube_autoplay') == 'true':
            _yp_first = get_trailer_url(_yp_vid, tmdb_id=params.get('tmdb_id'), dbtype=params.get('type'), title=params.get('title') or _yp_vid, year=params.get('year'), season=params.get('season'), plot=_yp_plot, studio=_yp_studio)
            if not _yp_first:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
                return
            xbmcplugin.setResolvedUrl(handle, True, xbmcgui.ListItem(path=_yp_first))
            _yp_seen = set([_yp_vid])
            _yp_order = [_yp_vid]
            try:
                from resources.lib.context.extended_info_mod import get_youtube_related
                _yp_rel = get_youtube_related(_yp_vid, 10)
            except:
                _yp_rel = []
            try:
                _yp_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                _yp_added = 0
                try:
                    from concurrent.futures import ThreadPoolExecutor, wait
                    _yp_ex = ThreadPoolExecutor(max_workers=5)
                    try:
                        _yp_want = []
                        for _rd in _yp_rel:
                            _rv = (_rd.get('id') or '') if isinstance(_rd, dict) else ''
                            if _rv and _rv not in _yp_seen:
                                _yp_seen.add(_rv)
                                _yp_order.append(_rv)
                                _yp_want.append(_rd)
                        _yp_fm = {_yp_ex.submit(_youtube_queue_entry, _rd.get('id'), _rd.get('title'), _rd.get('views'), _rd.get('date'), _rd.get('duration')): _rd.get('id') for _rd in _yp_want}
                        _yp_dn, _ = wait(set(_yp_fm), timeout=15)
                    finally:
                        try:
                            _yp_ex.shutdown(wait=False, cancel_futures=True)
                        except:
                            pass
                except:
                    _yp_dn = set()
                    _yp_fm = {}
                for _f in _yp_dn:
                    _rv = _yp_fm.get(_f, '')
                    try:
                        _entry = _f.result()
                    except:
                        _entry = None
                    if not _entry or not _rv:
                        continue
                    _eu, _eli = _entry
                    try:
                        _yp_pl.add(url=_eu, listitem=_eli)
                        _yp_added += 1
                    except:
                        continue
                xbmc.log(f"[TMDb Movies] [YOUTUBE] autoplay queued {_yp_added} after {_yp_vid}", xbmc.LOGINFO)
            except:
                pass
            xbmcgui.Window(10000).setProperty('TMDbMovies.YoutubeAutoplay', 'true')
            import threading as _yt_threading
            _yt_threading.Thread(target=_youtube_autoplay_loop, args=(_yp_seen, _yp_order), daemon=True).start()
            return
        _yp_url = get_trailer_url(params.get('video_id'), tmdb_id=params.get('tmdb_id'), dbtype=params.get('type'), title=params.get('title'), year=params.get('year'), season=params.get('season'), plot=_yp_plot, studio=_yp_studio)
        if _yp_url:
            xbmcplugin.setResolvedUrl(handle, True, xbmcgui.ListItem(path=_yp_url))
        else:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
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
    if mode == 'tmdb_account_info':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_account_info()
        return
    if mode == 'tmdb_calendar_my':
        from resources.lib import tmdb_api
        tmdb_api.tmdb_calendar_my()
        return
    if mode == 'tmdb_up_next':
        from resources.lib import tmdb_api
        tmdb_api.get_next_episodes({'use_tmdb': 'true'})
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
        run_import()
        return
    if mode == 'tmdb_refresh_lists':
        # Refresh DOAR contul TMDb (watchlist/favorites/liste/recommendations) — fara sync Trakt
        from resources.lib import trakt_sync, tmdb_api
        if not tmdb_api.get_tmdb_session():
            xbmcgui.Dialog().notification(provider_title('tmdb', name='TMDB'), "Not connected", xbmcgui.NOTIFICATION_WARNING)
            return
        xbmcgui.Dialog().notification(provider_title('tmdb', name='TMDB'), "Syncing TMDb...", tmdb_api.TMDB_ICON, 2000, False)
        trakt_sync.sync_tmdb_only(silent=True, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return
    if mode == 'trakt_main_menu':
        from resources.lib import menus
        from resources.lib.watched_provider import _get_provider_raw as _gp_raw
        _items = menus.trakt_main_list
        if _gp_raw() != 'trakt':
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
        _wl_total = 0
        _fav_total = 0
        _hist_total = 0
        try:
            from resources.lib import trakt_sync as _ts
            if os.path.exists(_ts.DB_PATH):
                _conn = _ts.get_connection()
                _c = _conn.cursor()
                _c.execute("SELECT COUNT(*) FROM trakt_hidden_shows")
                hidden_count = _c.fetchone()[0] or 0
                _c.execute("SELECT COUNT(*) FROM trakt_lists WHERE list_type='watchlist'")
                _wl_total = _c.fetchone()[0] or 0
                _c.execute("SELECT COUNT(*) FROM trakt_favorites")
                _fav_total = _c.fetchone()[0] or 0
                _c.execute("SELECT COUNT(*) FROM trakt_watched_movies")
                _hm = _c.fetchone()[0] or 0
                _c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM trakt_watched_episodes")
                _hs = _c.fetchone()[0] or 0
                _hist_total = _hm + _hs
                _conn.close()
        except Exception:
            import traceback
            xbmc.log("[TMDb Movies] [MENU] trakt_my_lists count EXCEPTION: " + traceback.format_exc(), xbmc.LOGERROR)
            hidden_count = 0

        items = [
            {'name': '[B][COLOR pink]Account Info[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_account_info', 'folder': False},
            {'name': '[B][COLOR FFCCCCFF]Watchlist[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % _wl_total, 'iconImage': 'trakt.png', 'mode': 'trakt_watchlist_menu'},
            {'name': '[B][COLOR FFCCCCFF]Favorites[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % _fav_total, 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_menu'},
            {'name': '[B][COLOR red]Dropped Shows[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % hidden_count, 'iconImage': 'trakt.png', 'mode': 'trakt_dropped_shows'},
            {'name': '[B][COLOR FFCCCCFF]History[/COLOR][/B] [B][COLOR FFFDBD01](%d)[/COLOR][/B]' % _hist_total, 'iconImage': 'trakt.png', 'mode': 'trakt_history_menu'}
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
            # season/episode/tv_name: fara ele, un rand de EPISOD ar deschide serialul.
            # (acelasi lucru il trimite si context item-ul 'TMDb Info' din context_extended.py)
            def _sel_int(val):
                try:
                    s = str(val).strip()
                    return int(s) if s.isdigit() else None
                except:
                    return None
            run_extended_info(
                tmdb_id, mtype,
                season=_sel_int(params.get('season')),
                episode=_sel_int(params.get('episode')),
                tv_name=params.get('tv_name') or params.get('title') or ''
            )
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
            xbmcgui.Dialog().notification(provider_title('mdblist'), "Show dropped", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'mdblist_unmark_dropped':
        from resources.lib.mdblist_sync import restore_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
        if restore_show(params.get('tmdb_id')):
            xbmcgui.Dialog().notification(provider_title('mdblist'), "Show restored", _icon, 3000, False)
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

    if mode == 'simkl_auth':
        from resources.lib.simkl_api import simkl_auth
        simkl_auth()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'simkl_revoke':
        from resources.lib.simkl_api import simkl_revoke
        simkl_revoke()
        return

    if mode == 'simkl_sync':
        from resources.lib.simkl_sync import sync_full_library
        sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'simkl_sync_smart':
        from resources.lib.simkl_sync import sync_full_library
        sync_full_library(silent=False, force=False)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'simkl_rating':
        from resources.lib.simkl_api import prompt_simkl_rating
        prompt_simkl_rating(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode'),
            params.get('title', '')
        )
        return

    if mode == 'simkl_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_simkl_context_menu(
            params.get('tmdb_id'),
            params.get('imdb_id'),
            params.get('type'),
            params.get('title', ''),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'simkl_mark_dropped':
        from resources.lib.simkl_sync import drop_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'simkl.png')
        if drop_show(params.get('tmdb_id'), params.get('title', '')):
            xbmcgui.Dialog().notification(provider_title('simkl'), "Show dropped", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'simkl_unmark_dropped':
        from resources.lib.simkl_sync import restore_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'simkl.png')
        if restore_show(params.get('tmdb_id')):
            xbmcgui.Dialog().notification(provider_title('simkl'), "Show restored", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode and mode.startswith('simkl_'):
        from resources.lib.simkl import handle_simkl_action, SIMKL_ACTIONS
        if mode in SIMKL_ACTIONS or mode in ('simkl_dropped_restore', 'simkl_connect', 'simkl_disconnect'):
            from resources.lib.config import ADDON
            handle_simkl_action({'action': mode, **params}, handle, sys.argv[0], ADDON)
        return

    if mode == 'punchplay_auth':
        from resources.lib.punchplay_api import punchplay_auth
        punchplay_auth()
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'punchplay_revoke':
        from resources.lib.punchplay_api import punchplay_revoke
        punchplay_revoke()
        return

    if mode == 'punchplay_sync':
        from resources.lib.punchplay_sync import sync_full_library
        sync_full_library(silent=False, force=True)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'punchplay_sync_smart':
        from resources.lib.punchplay_sync import sync_full_library
        sync_full_library(silent=False, force=False)
        xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'punchplay_rating':
        from resources.lib.punchplay_api import prompt_punchplay_rating
        prompt_punchplay_rating(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode'),
            params.get('title', '')
        )
        return

    if mode == 'punchplay_context_menu':
        from resources.lib import tmdb_api
        tmdb_api.show_punchplay_context_menu(
            params.get('tmdb_id'),
            params.get('imdb_id'),
            params.get('type'),
            params.get('title', ''),
            params.get('season'),
            params.get('episode')
        )
        return

    if mode == 'punchplay_mark_dropped':
        from resources.lib.punchplay_sync import drop_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'punchplay.png')
        if drop_show(params.get('tmdb_id'), params.get('title', '')):
            xbmcgui.Dialog().notification(provider_title('punchplay'), "Show dropped", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode == 'punchplay_unmark_dropped':
        from resources.lib.punchplay_sync import restore_show
        _icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'media', 'punchplay.png')
        if restore_show(params.get('tmdb_id')):
            xbmcgui.Dialog().notification(provider_title('punchplay'), "Show restored", _icon, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
        return

    if mode and mode.startswith('punchplay_'):
        from resources.lib.punchplay import handle_punchplay_action, PUNCHPLAY_ACTIONS
        if mode in PUNCHPLAY_ACTIONS or mode in ('punchplay_dropped_restore', 'punchplay_connect', 'punchplay_disconnect'):
            from resources.lib.config import ADDON
            handle_punchplay_action({'action': mode, **params}, handle, sys.argv[0], ADDON)
        return
    
    from resources.lib.debrid import handle_debrid_action, DEBRID_ACTIONS
    if mode in DEBRID_ACTIONS:
        from resources.lib.config import ADDON
        handle_debrid_action({'mode': mode, **params}, handle, sys.argv[0], ADDON)
        return
    if isinstance(mode, str) and mode.startswith('debrid_'):
        try:
            if int(handle) >= 0:
                xbmcplugin.endOfDirectory(int(handle), succeeded=False)
        except Exception:
            pass
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
            params.get('episode'),
            params.get('title', '')
        )
        return

    if mode == 'tmdb_rating':
        from resources.lib import tmdb_api
        tmdb_api.rate_tmdb_item(
            params.get('tmdb_id'),
            params.get('type'),
            params.get('season'),
            params.get('episode'),
            params.get('title', '')
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
        from resources.lib import my_plays
        my_plays.show_my_plays_menu(params)
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
        import threading as _th_sync
        def _bg_full_sync():
            try:
                sync_full_library(silent=False, force=True)
            except Exception as _e:
                xbmc.log(f'[TMDb Movies] background full sync error: {_e}', xbmc.LOGERROR)
            xbmc.executebuiltin('Container.Refresh')
        _th_sync.Thread(target=_bg_full_sync, daemon=True).start()
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                      'Full sync started in background...', os.path.join(CONFIG_ADDON_PATH, 'icon.png'), 2500, False)
        return

    if mode == 'trakt_sync_smart_action':
        from resources.lib.watched_provider import sync_full_library
        import threading as _th_sync2
        def _bg_smart_sync():
            try:
                sync_full_library(silent=False, force=False)
            except Exception as _e:
                xbmc.log(f'[TMDb Movies] background smart sync error: {_e}', xbmc.LOGERROR)
            xbmc.executebuiltin('Container.Refresh')
        _th_sync2.Thread(target=_bg_smart_sync, daemon=True).start()
        xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                      'Smart sync started in background...', os.path.join(CONFIG_ADDON_PATH, 'icon.png'), 2500, False)
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

    if mode == 'view_kodi_log':
        from resources.lib import utils
        utils.view_kodi_log()
        return

    if mode == 'toggle_language_invoker':
        from resources.lib import utils
        utils.toggle_language_invoker()
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

_forced_widget_refresh_done = [False]


def _maybe_refresh_widgets_after_sync(force=False):
    """Refresh widget-urile de pe Home dupa un sync automat reusit, DOAR daca
    setarea 'Attempt to Refresh Widgets After Refresh' e activa (default false).
    trakt.sync_refresh_widgets: fara asta, widget-urile AF3 (Next
    Episodes, In Progress, etc.) raman stale dupa ce sync-ul aduce watched/resume
    de pe server — doar restart/refresh manual le improspata.
    force=True = primul sync reusit dupa update de addon (_version_changed):
    refresh neconditionat o singura data pe sesiune, chiar cu setarea OFF —
    altfel Up Next ramane gol pana la restart (widgetul a randat in timpul
    rebuild-ului DB din sync-ul fortat si nu se mai re-invoca singur)."""
    try:
        from resources.lib.config import ADDON
        setting_on = ADDON.getSetting('trakt_sync_refresh_widgets') == 'true'
        if force and not setting_on:
            if _forced_widget_refresh_done[0]:
                xbmc.log("[TMDb Movies] TraktMonitor Service Update - Forced Widget Refresh already done this session. Skipping", xbmc.LOGINFO)
                return
            _forced_widget_refresh_done[0] = True
        if setting_on or force:
            from resources.lib.watched_provider import widget_refresh
            widget_refresh()
            xbmc.log("[TMDb Movies] TraktMonitor Service Update - Widget Refresh Performed", xbmc.LOGINFO)
        else:
            xbmc.log("[TMDb Movies] TraktMonitor Service Update - Widget Refresh Disabled. Skipping", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[TMDb Movies] TraktMonitor Service Update - Widget Refresh Failed: {e}", xbmc.LOGERROR)

_refresh_last_fired = [0.0]


def _deferred_plugin_refresh(delay_ms=700):
    # Container.Refresh amanat cu garda de context.
    # Race cunoscut (crash raportat pe AF3/Android): userul da OK in setari,
    # onWindowActivated programeaza refresh-ul, apoi apasa Back — refresh-ul
    # loveste containerul tocmani cand Kodi il distruge/reincarca -> segfault
    # nativ (fara traceback Python). Garzi: suntem inca intr-un container
    # tmdbmovies SI containerul nu e in plina incarcare (Container.IsUpdating).
    #
    # COOLDOWN GLOBAL: la schimbarea providerului pleaca 4-5 refresh-uri din
    # surse diferite (clear_provider_cache x2, monitor pre/post-sync,
    # onWindowActivated). Fiecare asteapta IsUpdating sa se elibereze si
    # trage refresh exact cand lista noua s-a terminat de incarcat -> Kodi o
    # reincarca -> urmatorul refresh asteapta din nou -> ping-pong de
    # reincarcari = spinner infinit (reproducibil si pe Estuary). Cooldown-ul
    # lasa maxim un refresh la 2.5s; celelalte surse il considera acoperit.
    def _run():
        try:
            if delay_ms:
                xbmc.sleep(int(delay_ms))
            try:
                if time.time() - _refresh_last_fired[0] < 2.5:
                    xbmc.log("[TMDb Movies] Deferred refresh SKIP (cooldown {:.1f}s)".format(
                        time.time() - _refresh_last_fired[0]), xbmc.LOGINFO)
                    return
                _plugin = xbmc.getInfoLabel('Container.PluginName') or ''
            except:
                return
            if 'tmdbmovies' not in _plugin.lower():
                xbmc.log("[TMDb Movies] Deferred refresh SKIP (outside plugin container)", xbmc.LOGINFO)
                return
            # Rezerva slotul de cooldown INAINTE de asteptarea IsUpdating,
            # altfel thread-urile care asteapta containerul il ocolesc.
            _refresh_last_fired[0] = time.time()
            _waited = 0
            for _ in range(30):
                try:
                    if not xbmc.getCondVisibility('Container.IsUpdating'):
                        break
                except:
                    return
                xbmc.sleep(100)
                _waited += 100
            else:
                xbmc.log("[TMDb Movies] Deferred refresh SKIP (IsUpdating >3s)", xbmc.LOGINFO)
                return
            xbmc.log("[TMDb Movies] Deferred refresh FIRE (waited {}ms)".format(_waited), xbmc.LOGINFO)
            xbmc.executebuiltin('Container.Refresh')
        except:
            pass
    threading.Thread(target=_run, daemon=True).start()

def _run_forced_post_update_sync(t_detect=0.0, monitor=None):
    """Rebuild complet datelor dupa update de addon, UNCONDITIONAL si IMEDIAT,
    in thread-uri daemon — NU depinde de waitForAbort(60) din run(), care pe
    Android e frecvent intrerupt de idle/background (run() iese inainte de
    sync_worker() -> cache-urile sterse de check_addon_update raman goale,
    Up Next gol pana la restart). Se cheama din TMDbMonitor.__init__ cand
    check_addon_update() detecteaza update.

    RUNEAZA PROVIDERII SECVENTIAL (unul dupa altul, intr-un SINGUR thread daemon),
    nu in paralel — altfel log-urile lor se amesteca si TMDb se dubleaza:
    sync_full_library(Trakt) include deja _sync_tmdb_data la final (trakt_sync.py:518),
    deci un thread TMDb separat ar rula in paralel cu cel inclus -> duplicat + amestec."""
    try:
        from resources.lib.config import ADDON as _A
    except Exception:
        return

    # Da-i Kodi cateva secunde sa termine remontarea addonului (fereastra in care
    # xbmcaddon arunca "Unknown addon id"). Sync-urile ruleaza oricum in thread-uri
    # daemon, independent de waitForAbort — deci intarzierea nu reintroduce bug-ul.
    try:
        xbmc.sleep(5000)
    except Exception:
        pass

    def _run_providers():
        # Post-update: dispatcherul UNIC secvential (Local -> TMDb -> Trakt ->
        # MDBList -> Simkl -> PunchPlay). TMDb nu mai depinde de tokenul Trakt;
        # providerii neconectati se sara elegant; o singura notificare finala.
        try:
            from resources.lib.watched_provider import sync_full_library as _disp
            _status = _disp(silent=True, force=True, post_update=True, update_stamp=t_detect)
        except Exception as e:
            _status = 'error'
            xbmc.log(f"[TMDb Movies] Post-update forced sync - Failed: {e}", xbmc.LOGERROR)
        if _status == 'ok':
            xbmc.log("[TMDb Movies] Post-update forced sync (dispatcher) - Success.", xbmc.LOGINFO)
            if monitor is not None:
                try:
                    monitor._post_update_forced_done = True
                except Exception:
                    pass
            _maybe_refresh_widgets_after_sync(force=True)
        else:
            xbmc.log("[TMDb Movies] Post-update forced sync - SKIPPED (status=%s)." % (_status,), xbmc.LOGINFO)
            _maybe_refresh_widgets_after_sync(force=False)

    threading.Thread(target=_run_providers, daemon=True).start()



def run_service():
    try:
        from resources.lib.config import ADDON
    except:
        return

    # --- GIL responsiveness (fix spinner-infinit dupa provider switch) ---
    # Kodi ruleaza serviciul + pluginul + callbackurile GUI in ACELASI
    # interpret Python (GIL partajat). Sync-ul de provider switch porneste
    # ~20 thread-uri care parseaza JSON-uri mari / scriu in DB si tin GIL-ul
    # in portii lungi; evenimentul GUI de 'director incarcat' (trimis de
    # endOfDirectory) nu mai ajunge sa fie procesat -> spinner permanent,
    # desi codul addonului a terminat corect. Debug logging masca problema
    # (I/O la fiecare log = eliberari frecvente de GIL). Interval mai mic =
    # toate thread-urile cedeaza GIL-ul des -> GUI-ul prinde rand.
    try:
        sys.setswitchinterval(0.001)
    except Exception:
        pass

    # --- Reuse Language Invoker drift check (addon updates overwrite addon.xml) ---
    try:
        from resources.lib import utils
        utils.check_language_invoker_mismatch()
    except:
        pass

    # --- PRE-IMPORT modulele grele in fundal (fix deadlock de import: Kodi
    # ruleaza toate invocarile in acelasi interpret; primul-import concomitent
    # navigare-user vs sync poate bloca permanent threadul pluginului) ---
    def _warm():
        try:
            xbmc.sleep(1500)  # lasa Kodi sa termine boot-ul
            from resources.lib.utils import warm_import_modules
            warm_import_modules()
        except Exception as e:
            xbmc.log("[TMDb Movies] Warm import error: {}".format(e), xbmc.LOGERROR)
    threading.Thread(target=_warm, daemon=True).start()

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
            # Atributele accesate de onSettingsChanged/onWindowActivated trebuie
            # initializate IMEDIAT (indeajuns de devreme ca niciun callback sa nu le
            # vada nedesetate). Kodi poate invoca onSettingsChanged in timp ce __init__
            # inca ruleaza (ex. la update: _run_forced_post_update_sync + check_addon_update
            # fac I/O lent) — fara defaults, callback-ul pica cu 'has no attribute'.
            self.first_run = True
            self._version_changed = False
            self._post_update_forced_done = False
            self._post_update_force_consumed = False
            self._provider_pending = False
            self._settings_pending = False
            self._last_provider = None
            self._last_tmdb_unstarted = None
            self.update_context_menu_property()

            try:
                from resources.lib.utils import check_addon_update
                if check_addon_update():
                    self._version_changed = True
                    try:
                        import time as _tu
                        _t_detect = _tu.time()
                    except Exception:
                        _t_detect = 0.0
                    _run_forced_post_update_sync(_t_detect, self)
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Error la verificarea de update: {e}", xbmc.LOGERROR)
            try:
                from resources.lib.watched_provider import get_provider as _gp0
                self._last_provider = _gp0()
            except:
                self._last_provider = None
            try:
                self._last_tmdb_unstarted = ADDON.getSetting('tmdb_upnext_show_unstarted')
            except:
                self._last_tmdb_unstarted = None
            try:
                from resources.lib.watched_provider import ensure_active_provider
                import threading as _th
                _th.Thread(target=ensure_active_provider, daemon=True).start()
            except:
                pass

        def onWindowActivated(self, windowId):
            # Cand se inchide dialogul de setari, fereastra de dedesubt se reactiveaza.
            # Kodi restaureaza containerele vizitate din memorie (fara re-invocarea
            # plugin-ului) — deci dupa o schimbare de setari (Menu show/hide etc.),
            # fortam refresh-ul la prima activare a unei ferestre (ex. inchiderea setarilor).
            if self._settings_pending or self._provider_pending:
                self._settings_pending = False
                self._provider_pending = False
                # Refresh amanat cu garda (vezi _deferred_plugin_refresh) —
                # Back imediat dupa OK in setari producea crash nativ pe AF3.
                _deferred_plugin_refresh(700)

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
                                elif _prov == 'simkl':
                                    from resources.lib.simkl_api import SIMKLAPI as _SKAPI
                                    _connected = _SKAPI().is_authenticated()
                                elif _prov == 'punchplay':
                                    from resources.lib.punchplay_api import PunchplayAPI as _PPAPI
                                    _connected = _PPAPI().is_authenticated()
                                elif _prov == 'local':
                                    _connected = True  # local: mereu conectat
                                else:
                                    _connected = bool(get_addon().getSetting('mdblist_access_token') or get_addon().getSetting('mdblist_api'))
                                if not _connected:
                                    _name = {'trakt': 'Trakt', 'mdblist': 'MDBList', 'simkl': 'Simkl', 'punchplay': 'PunchPlay', 'local': 'Kodi (Local)'}.get(_prov, _prov)
                                    _clr = {'trakt': 'pink', 'mdblist': 'lightskyblue', 'simkl': 'mediumpurple', 'punchplay': 'FFFF6600', 'local': 'FFF70D1A'}.get(_prov, 'yellow')
                                    # Iconita addonului din root (icon.png), cale statica
                                    # via ADDON_PATH — fara apeluri care pot esua in
                                    # thread-ul de service.
                                    _notif_icon = os.path.join(CONFIG_ADDON_PATH, 'icon.png')
                                    # POARTA (nu doar informare): userul NU poate ramine pe un
                                    # provider deconectat. Ori se conecteaza (si trece verificarea),
                                    # ori setarea revine automat la providerul anterior / la primul
                                    # provider CONECTAT gasit. Back/Esc (fara alegere) = tot revert.
                                    # Inainte raminea activat un provider mort, cu o simpla notificare.
                                    _NAMES = {'trakt': 'Trakt', 'mdblist': 'MDBList', 'simkl': 'Simkl', 'punchplay': 'PunchPlay', 'local': 'Kodi (Local)'}
                                    _CLRS = {'trakt': 'pink', 'mdblist': 'lightskyblue', 'simkl': 'mediumpurple', 'punchplay': 'FFFF6600', 'local': 'FFF70D1A'}

                                    def _is_conn(_p):
                                        # Verificare locala (fara retea) pe fiecare provider.
                                        try:
                                            if _p == 'local':
                                                return True  # local: mereu conectat
                                            if _p == 'trakt':
                                                from resources.lib.trakt_api import get_trakt_token as _t
                                                return bool(_t())
                                            if _p == 'mdblist':
                                                return bool(get_addon().getSetting('mdblist_access_token') or get_addon().getSetting('mdblist_api'))
                                            if _p == 'simkl':
                                                from resources.lib.simkl_api import SIMKLAPI as _S
                                                return _S().is_authenticated()
                                            if _p == 'punchplay':
                                                from resources.lib.punchplay_api import PunchplayAPI as _P
                                                return _P().is_authenticated()
                                        except Exception:
                                            return False
                                        return False

                                    _prev = getattr(self, '_last_provider', None)
                                    _can_revert = bool(_prev) and _prev != _prov
                                    _prev_name = _NAMES.get(_prev, _prev)
                                    _opts = [f'Connect {_name} now']
                                    if _can_revert:
                                        _opts.append(f'Keep {_prev_name} (without {_name})')
                                    try:
                                        _sel = xbmcgui.Dialog().select(f'{_name} is not connected', _opts)
                                    except Exception:
                                        _sel = 1 if _can_revert else -1
                                    _connected_now = False
                                    if _sel == 0:
                                        try:
                                            if _prov == 'trakt':
                                                from resources.lib.trakt_api import trakt_auth as _auth
                                            elif _prov == 'mdblist':
                                                from resources.lib.mdblist_api import mdblist_auth as _auth
                                            elif _prov == 'simkl':
                                                from resources.lib.simkl_api import simkl_auth as _auth
                                            else:
                                                from resources.lib.punchplay_api import punchplay_auth as _auth
                                            xbmc.log(f'[TMDb Movies] Provider switch: user chose to connect {_prov}.', xbmc.LOGINFO)
                                            _auth()
                                        except Exception as _ae:
                                            xbmc.log(f'[TMDb Movies] Provider switch: connect {_prov} failed: {_ae}', xbmc.LOGERROR)
                                        _csc()
                                        _cc()
                                        _connected_now = _is_conn(_prov)
                                        if not _connected_now:
                                            # Unele fluxuri de login scriu tokenurile cu o mica intirziere.
                                            xbmc.sleep(1000)
                                            _csc()
                                            _connected_now = _is_conn(_prov)
                                    if not _connected_now:
                                        # Back/Esc, "Keep ..." sau connect esuat -> revenim pe un
                                        # provider CONECTAT (cel anterior are prioritate).
                                        _order = []
                                        if _can_revert:
                                            _order.append(_prev)
                                        for _p in ('trakt', 'mdblist', 'simkl', 'punchplay', 'local'):
                                            if _p != _prov and _p not in _order:
                                                _order.append(_p)
                                        _target = None
                                        for _p in _order:
                                            if _is_conn(_p):
                                                _target = _p
                                                break
                                        if _target:
                                            try:
                                                _idx = ('trakt', 'mdblist', 'simkl', 'punchplay', 'local').index(_target)
                                            except Exception:
                                                _idx = 0
                                            try:
                                                get_addon().setSetting('watched_status_provider', str(_idx))
                                            except Exception as _se:
                                                xbmc.log(f'[TMDb Movies] Provider switch: revert setSetting failed: {_se}', xbmc.LOGERROR)
                                            _csc()
                                            _cc()
                                            _prov = _target
                                            self._last_provider = _target
                                            _t_name = _NAMES.get(_target, _target)
                                            xbmc.log(f'[TMDb Movies] Provider switch: reverted to {_target} ({_name} not connected).', xbmc.LOGINFO)
                                            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                                                          f'Kept [B][COLOR {_CLRS.get(_target, "yellow")}]{_t_name}[/COLOR][/B] - [B][COLOR {_clr}]{_name}[/COLOR][/B] is not connected.',
                                                                          _notif_icon, 5000, False)
                                        else:
                                            xbmc.log(f'[TMDb Movies] Provider switch: {_name} not connected and no other connected provider found.', xbmc.LOGWARNING)
                                            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                                                                          f'No account is connected. Connect [B][COLOR {_clr}]{_name}[/COLOR][/B] in Settings!',
                                                                          _notif_icon, 6000, False)
                            except:
                                pass
                            # FARA refresh inainte de sync: culorile/etichetele
                            # se actualizeaza prin cel de dupa sync. Inainte,
                            # refresh-ul loveste exact cand userul incepe sa
                            # navigheze -> containerul se reincarca sub el
                            # (spinner perceput la intrarea in ani).
                            _sfl(silent=True, force=True)
                            xbmc.log(f"[TMDb Movies] Provider switch sync ({_prov}) complete.", xbmc.LOGINFO)
                            try:
                                _deferred_plugin_refresh(0)
                            except:
                                pass
                        except Exception as e:
                            xbmc.log(f"[TMDb Movies] Provider switch sync error: {e}", xbmc.LOGERROR)
                    threading.Thread(target=_provider_switch_sync, daemon=True).start()
                # Re-citim providerul real: daca in threadul de mai sus userul a ales
                # "Keep <anterior>" (revert), aici nu mai pornim un sync pe cel nou.
                try:
                    self._last_provider = _get_prov()
                except Exception:
                    self._last_provider = _current
            except Exception as e:
                xbmc.log(f"[TMDb Movies] Provider switch detection error: {e}", xbmc.LOGERROR)
            try:
                from resources.lib.utils import reset_debug_cache
                reset_debug_cache()
            except:
                pass
        
            # --- DETECTIE SCHIMBARE tmdb_upnext_show_unstarted ---
            # Recompute TMDB Up Next in background (daemon thread) ca toggle-ul sa
            # ia efect instant, fara asteptarea sync-ului de 30 min.
            try:
                _cur_unstarted = ADDON.getSetting('tmdb_upnext_show_unstarted')
                if getattr(self, '_last_tmdb_unstarted', None) is not None and _cur_unstarted != self._last_tmdb_unstarted:
                    def _tmdb_upnext_recompute():
                        try:
                            xbmc.sleep(1500)
                            from resources.lib.config import TMDB_V4_TOKEN_FILE
                            if not os.path.exists(TMDB_V4_TOKEN_FILE):
                                return
                            from resources.lib import trakt_sync as _ts
                            _conn = _ts.get_connection()
                            _ts.sync_tmdb_up_next(_conn.cursor())
                            _conn.commit()
                            _conn.close()
                            xbmc.log(f"[TMDb Movies] TMDB Up Next recomputed (show_unstarted={_cur_unstarted}).", xbmc.LOGINFO)
                            try:
                                _deferred_plugin_refresh(0)
                            except:
                                pass
                        except Exception as _e:
                            xbmc.log(f"[TMDb Movies] TMDB Up Next recompute error: {_e}", xbmc.LOGERROR)
                    threading.Thread(target=_tmdb_upnext_recompute, daemon=True).start()
                self._last_tmdb_unstarted = _cur_unstarted
            except Exception:
                pass

            try:
                from resources.lib.scrapers import reset_debug_cache as reset_scrapers_debug
                reset_scrapers_debug()
            except:
                pass
            # Orice schimbare de setare → la inchiderea setarilor se face Container.Refresh
            # (see onWindowActivated) → directoarele/context menu-urile iau efect instant.
            self._settings_pending = True

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

            # Dupa update de addon: 60s (nu 5s) — Kodi mai termina CAddonMgr reload
            # (fereastra in care xbmcaddon arunca "Unknown addon id", vazuta in log-uri)
            # si userul apuca sa ajunga pe Home cu widgetul randat din datele persistente.
            if getattr(self, '_version_changed', False):
                _delay = 60

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
                # Flag-ul se seteaza doar la finalizarea cu succes a sync-ului fortat.
                # Daca daemonul inca ruleaza, sync_worker() loveste lock-ul si sare
                # curat (status locked) - fara sync dublu. Daca daemonul a murit,
                # flag-ul ramane False si first_run recupereaza cu sync normal.
                if not getattr(self, '_post_update_forced_done', False):
                    self.sync_worker()
                self.first_run = False
                
            while not self.abortRequested():
                # Fereastra GLISANTA 30 min: felii de 60s in loc de waitForAbort(1800)
                # orb. Fiecare sync incheiat (ok/error/noop, nu aborted) scrie
                # tmdbmovies_sync_attempt; last_sync se scrie doar pe ok.
                if self.waitForAbort(60):
                    break
                try:
                    _att = float(xbmcgui.Window(10000).getProperty('tmdbmovies_sync_attempt') or 0)
                except Exception:
                    _att = 0.0
                try:
                    _ok_ts = float(xbmcgui.Window(10000).getProperty('tmdbmovies_last_sync') or 0)
                except Exception:
                    _ok_ts = 0.0
                _last_sync_stamp = max(_att, _ok_ts)
                if _last_sync_stamp and (time.time() - _last_sync_stamp >= 1800):
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

        def _sync_force(self):
            if getattr(self, '_post_update_forced_done', False):
                return False
            if getattr(self, '_post_update_force_consumed', False):
                return False
            if getattr(self, '_version_changed', False):
                self._post_update_force_consumed = True
                return True
            return False

        def sync_worker(self):
            try:
                xbmc.log("[TMDb Movies] Monitor Service Update - Starting sequential sync (all providers)...", xbmc.LOGINFO)

                def _run_all():
                    try:
                        from resources.lib.watched_provider import sync_full_library
                        _st = sync_full_library(silent=True, force=self._sync_force(), source='auto')
                    except Exception as e:
                        _st = 'error'
                        xbmc.log(f"[TMDb Movies] Monitor Service Update - Failed: {e}", xbmc.LOGERROR)
                    if _st == 'ok':
                        xbmc.log("[TMDb Movies] Monitor Service Update - Success. Next check in 60s (rolling 30 min window)...", xbmc.LOGINFO)
                    else:
                        xbmc.log("[TMDb Movies] Monitor Service Update - SKIPPED (status=%s)." % (_st,), xbmc.LOGINFO)
                    _maybe_refresh_widgets_after_sync(force=(_st == 'ok'))
                threading.Thread(target=_run_all, daemon=True).start()
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
