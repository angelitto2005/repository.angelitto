# -*- coding: utf-8 -*-
"""
Watched Status Provider abstraction layer.
Dispatching intre Trakt si MDBList in functie de setarea watched_status_provider.
"""

import os
import threading
import xbmc
import xbmcvfs

from resources.lib.config import ADDON, ADDON_PATH, MDBLIST_API_URL

def _get_provider_raw():
    try:
        idx = int(ADDON.getSetting('watched_status_provider') or '0')
    except:
        idx = 0
    return ('trakt', 'mdblist', 'simkl')[idx]

def clear_cache():
    """No-op pastrat pentru compatibilitate (nu mai exista cache de invalidat)."""
    pass

def _invalidate_fast_cache():
    """Invalideaza fast cache-ul RAM (listele re-build din DB cu watched status proaspat)."""
    try:
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
    except:
        pass

def _on_home_widget():
    try:
        return 'tmdbmovies' not in xbmc.getInfoLabel('Container.PluginName')
    except:
        return True

def widget_refresh():
    try:
        xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')
    except:
        pass

def refresh_ui():
    try:
        if _on_home_widget():
            widget_refresh()
        else:
            xbmc.executebuiltin('Container.Refresh')
    except:
        pass

_WATCHED_MARK_PROVIDERS = ('trakt', 'mdblist', 'simkl')

_WATCHED_MARK_COLORS = {'trakt': 'pink', 'mdblist': 'lightskyblue', 'simkl': 'mediumpurple'}

_WATCHED_MARK_LABELS = {
    'trakt': '[B][COLOR pink]Trakt[/COLOR][/B]',
    'mdblist': '[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
    'simkl': '[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
}

_WATCHED_MARK_TOGGLES = {
    'trakt': 'watched_mark_trakt',
    'mdblist': 'watched_mark_mdblist',
    'simkl': 'watched_mark_simkl',
}


def _connected_mark_providers():
    connected = []
    try:
        from resources.lib import trakt_api
        if trakt_api.get_trakt_token():
            connected.append('trakt')
    except Exception:
        pass
    try:
        from resources.lib import mdblist
        if mdblist.is_authenticated():
            connected.append('mdblist')
    except Exception:
        pass
    try:
        from resources.lib import simkl
        if simkl.is_authenticated():
            connected.append('simkl')
    except Exception:
        pass
    return connected


def _mark_targets():
    try:
        mode = ADDON.getSetting('watched_mark_mode') or '0'
    except Exception:
        mode = '0'
    if mode not in ('1', '2'):
        return None
    connected = _connected_mark_providers()
    if mode == '1':
        targets = list(connected)
    else:
        targets = []
        for prov in connected:
            try:
                if ADDON.getSetting(_WATCHED_MARK_TOGGLES[prov]) == 'true':
                    targets.append(prov)
            except Exception:
                pass
    prov = _get_provider_raw()
    if prov in connected and prov not in targets:
        targets.append(prov)
    return [p for p in _WATCHED_MARK_PROVIDERS if p in targets]


def _split_colored(word, provs):
    n = len(provs)
    base, extra = divmod(len(word), n)
    out = ''
    pos = 0
    for i, p in enumerate(provs):
        ln = base + (1 if i < extra else 0)
        out += '[COLOR %s]%s[/COLOR]' % (_WATCHED_MARK_COLORS[p], word[pos:pos + ln])
        pos += ln
    return out


def mark_menu_label(is_watched):
    targets = _mark_targets()
    if targets is None:
        return None
    ordered = [p for p in _WATCHED_MARK_PROVIDERS if p in targets]
    if not ordered:
        return None
    if is_watched:
        return '[B][COLOR FFE41B17]Mark [/COLOR]%s[/B]' % _split_colored('Unwatched', ordered)
    return '[B][COLOR FF6AFB92]Mark [/COLOR]%s[/B]' % _split_colored('Watched', ordered)


def _fanout_mark(watched, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh):
    targets = [p for p in _WATCHED_MARK_PROVIDERS if p in (providers or [])]
    if not targets:
        return []
    done = []
    lock = threading.Lock()

    def _one(prov):
        try:
            if watched:
                if prov == 'trakt':
                    from resources.lib.trakt_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_trakt=sync_provider, refresh_ui=False)
                elif prov == 'mdblist':
                    from resources.lib.mdblist_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_mdblist=sync_provider, refresh_ui=False)
                else:
                    from resources.lib.simkl_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_simkl=sync_provider, refresh_ui=False)
            else:
                if prov == 'trakt':
                    from resources.lib.trakt_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_trakt=sync_provider, refresh_ui=False)
                elif prov == 'mdblist':
                    from resources.lib.mdblist_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_mdblist=sync_provider, refresh_ui=False)
                else:
                    from resources.lib.simkl_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_simkl=sync_provider, refresh_ui=False)
            with lock:
                done.append(prov)
        except Exception:
            pass

    workers = [threading.Thread(target=_one, args=(p,), daemon=True) for p in targets]
    for t in workers:
        t.start()
    for t in workers:
        t.join(30)
    _refresh_tmdb_up_next(tmdb_id)
    _invalidate_fast_cache()
    ordered_done = [p for p in _WATCHED_MARK_PROVIDERS if p in done]
    if notify:
        import xbmcgui
        _icon = os.path.join(ADDON_PATH, 'icon.png')
        if ordered_done:
            _names = ' + '.join(_WATCHED_MARK_LABELS[p] for p in ordered_done)
            if watched:
                _lbl = '[B]Mark %s[/B]' % _split_colored('Watched', ordered_done)
            else:
                _lbl = '[B]Mark %s[/B]' % _split_colored('Unwatched', ordered_done)
            xbmcgui.Dialog().notification('[B][COLOR yellow]All Providers[/COLOR][/B]', '%s on %s' % (_lbl, _names), _icon, 5000, False)
        else:
            xbmcgui.Dialog().notification('[B][COLOR yellow]All Providers[/COLOR][/B]', 'No provider updated', _icon, 5000, False)
    if do_refresh:
        refresh_ui()
    return ordered_done


def mark_watched_on_providers(tmdb_id, content_type, season=None, episode=None, providers=None, notify=True, sync_provider=True, do_refresh=True):
    return _fanout_mark(True, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh)


def mark_unwatched_on_providers(tmdb_id, content_type, season=None, episode=None, providers=None, notify=True, sync_provider=True, do_refresh=True):
    return _fanout_mark(False, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh)

def get_provider():
    return _get_provider_raw()

def is_trakt():
    return _get_provider_raw() == 'trakt'

def is_mdblist():
    return _get_provider_raw() == 'mdblist'

def is_simkl():
    return _get_provider_raw() == 'simkl'

def get_label():
    return ('Trakt', 'MDBList', 'Simkl')[('trakt', 'mdblist', 'simkl').index(_get_provider_raw())]

def get_color():
    return {'trakt': 'pink', 'mdblist': 'lightskyblue', 'simkl': 'mediumpurple'}[_get_provider_raw()]

def get_icon():
    name = {'trakt': 'trakt.png', 'mdblist': 'mdblist.png', 'simkl': 'simkl.png'}[_get_provider_raw()]
    return os.path.join(ADDON_PATH, 'resources', 'media', name)

def get_status_setting():
    return {'trakt': 'trakt_status', 'mdblist': 'mdblist_status', 'simkl': 'simkl_status'}[_get_provider_raw()]

def get_access_token_setting():
    return {'trakt': 'trakt_access_token', 'mdblist': 'mdblist_access_token', 'simkl': 'simkl_access_token'}[_get_provider_raw()]

def get_refresh_token_setting():
    return {'trakt': 'trakt_refresh_token', 'mdblist': 'mdblist_refresh_token', 'simkl': 'simkl_access_token'}[_get_provider_raw()]

def get_source_module():
    """Returneaza modulul de date (trakt_sync | mdblist_sync | simkl_sync) al providerului activ."""
    prov = _get_provider_raw()
    if prov == 'simkl':
        return __import__('resources.lib.simkl_sync', fromlist=['simkl_sync'])
    if prov == 'mdblist':
        return __import__('resources.lib.mdblist_sync', fromlist=['mdblist_sync'])
    return __import__('resources.lib.trakt_sync', fromlist=['trakt_sync'])

def dispatch_mark_watched(tmdb_id, content_type, season=None, episode=None, notify=True, sync_provider=True, do_refresh=True):
    targets = _mark_targets()
    prov = _get_provider_raw()
    if targets is None or targets == [prov]:
        if prov == 'trakt':
            from resources.lib.trakt_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_trakt=sync_provider, refresh_ui=do_refresh)
        elif prov == 'mdblist':
            from resources.lib.mdblist_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_mdblist=sync_provider, refresh_ui=do_refresh)
        else:
            from resources.lib.simkl_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_simkl=sync_provider, refresh_ui=do_refresh)
        _refresh_tmdb_up_next(tmdb_id)
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    if not targets:
        return
    mark_watched_on_providers(tmdb_id, content_type, season, episode, providers=targets, notify=notify, sync_provider=sync_provider, do_refresh=do_refresh)

def dispatch_mark_unwatched(tmdb_id, content_type, season=None, episode=None, sync_provider=True, do_refresh=True):
    targets = _mark_targets()
    prov = _get_provider_raw()
    if targets is None or targets == [prov]:
        if prov == 'trakt':
            from resources.lib.trakt_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_trakt=sync_provider, refresh_ui=do_refresh)
        elif prov == 'mdblist':
            from resources.lib.mdblist_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_mdblist=sync_provider, refresh_ui=do_refresh)
        else:
            from resources.lib.simkl_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_simkl=sync_provider, refresh_ui=do_refresh)
        _refresh_tmdb_up_next(tmdb_id)
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    if not targets:
        return
    mark_unwatched_on_providers(tmdb_id, content_type, season, episode, providers=targets, notify=True, sync_provider=sync_provider, do_refresh=do_refresh)

def dispatch_scrobble(action, tmdb_id, content_type, season, episode, progress):
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib.trakt_api import send_trakt_scrobble
        send_trakt_scrobble(action, tmdb_id, content_type, season, episode, progress)
    elif prov == 'mdblist':
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        if action == 'stop' and (progress or 0) <= 0:
            api.scrobble_clear(content_type, tmdb_id, season, episode, silent_404=True)
        elif action == 'start' or action == 'scrobble':
            api.scrobble_start(content_type, tmdb_id, progress, season, episode)
        elif action == 'pause':
            api.scrobble_pause(content_type, tmdb_id, progress, season, episode)
        elif action == 'stop':
            api.scrobble_stop(content_type, tmdb_id, progress, season, episode)
            _invalidate_fast_cache()
    else:
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        if action == 'start' or action == 'scrobble':
            api.scrobble_start(content_type, tmdb_id, progress, season, episode)
        elif action == 'pause':
            api.scrobble_pause(content_type, tmdb_id, progress, season, episode)
        elif action == 'stop':
            api.scrobble_stop(content_type, tmdb_id, progress, season, episode)
            _invalidate_fast_cache()

def _kodi_delete_resume_bookmark(tmdb_id, content_type, season=None, episode=None):
    try:
        content_type = 'tv' if content_type in ('tv', 'episode') else 'movie'
        import glob
        import sqlite3
        db_dir = xbmcvfs.translatePath('special://userdata/Database/')
        dbs = glob.glob(os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            return
        db_path = max(dbs, key=os.path.getmtime)
        conn = sqlite3.connect(db_path, timeout=2)
        cur = conn.cursor()
        params = ['%mode=sources%', '%%tmdb_id=%s%%' % tmdb_id, '%%type=%s%%' % content_type]
        query = ("DELETE FROM bookmark WHERE type=1 AND idFile IN (SELECT idFile FROM files "
                 "WHERE strFilename LIKE ? AND strFilename LIKE ? AND strFilename LIKE ?")
        if content_type == 'tv' and season is not None and episode is not None:
            params += ['%%season=%s%%' % season, '%%episode=%s%%' % episode]
            query += " AND strFilename LIKE ? AND strFilename LIKE ?"
        query += ")"
        cur.execute(query, params)
        conn.commit()
        xbmc.log(f"[TMDb Movies] [RESUME] Bookmark Kodi sters: {cur.rowcount} rand(uri)", xbmc.LOGINFO)
        conn.close()
    except Exception as e:
        xbmc.log(f"[TMDb Movies] [RESUME] Bookmark Kodi stergere error: {e}", xbmc.LOGERROR)

def dispatch_remove_progress(tmdb_id, content_type='movie', season=None, episode=None):
    """Elimina resume-ul (toate serverele autorizate + tabela locala) si refresheaza."""
    # 1. Server MDBList (daca e autorizat) - 404 = sesiune inexistenta, nu e eroare
    try:
        from resources.lib.mdblist_api import MDBListAPI
        _api = MDBListAPI()
        if _api.is_authenticated():
            _api.scrobble_clear(content_type, tmdb_id, season, episode, silent_404=True)
    except Exception:
        pass
    # 1b. Server Simkl (daca e autorizat)
    try:
        from resources.lib.simkl_api import SIMKLAPI
        _api = SIMKLAPI()
        if _api.is_authenticated():
            _api.playback_remove(content_type, tmdb_id, season, episode)
    except Exception:
        pass
    # 2. Server Trakt + stergere locala + clear fast cache + Container.Refresh
    from resources.lib.trakt_api import remove_from_progress
    remove_from_progress(tmdb_id, content_type, season, episode)
    # 3. Bookmark Kodi (dialogul nativ de resume nu mai trebuie sa apara la click)
    _kodi_delete_resume_bookmark(tmdb_id, content_type, season, episode)
    # 4. Refresh widget-uri de pe Home (UpdateLibrary ca POV) — Container.Refresh din
    #    remove_from_progress doar reimprospateaza containerul activ, nu widget-urile.
    _invalidate_fast_cache()
    refresh_ui()

def is_movie_watched(tmdb_id):
    return get_source_module().is_movie_watched(tmdb_id)

def is_episode_watched(tmdb_id, season, episode):
    return get_source_module().is_episode_watched(tmdb_id, season, episode)

def get_episode_watched_count(tmdb_id):
    """Numar de episoade vizionate pentru un serial (provider-aware, int)."""
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)
    else:
        from resources.lib.simkl_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)

def get_watched_episodes_set(tmdb_id):
    prov = _get_provider_raw()
    tbl = {'trakt': 'trakt_watched_episodes', 'mdblist': 'mdblist_watched_episodes', 'simkl': 'simkl_watched_episodes'}[prov]
    res = {'set': set(), 'last': None, 'last_at': ''}
    try:
        mod = get_source_module()
        conn = mod.get_connection()
        cur = conn.cursor()
        cur.execute(f"SELECT season, episode, last_watched_at FROM {tbl} WHERE tmdb_id=?", (str(tmdb_id),))
        rows = cur.fetchall()
        conn.close()
        max_at = None
        for r in rows:
            s, e, at = r[0], r[1], r[2]
            if not s or not e:
                continue
            res['set'].add((int(s), int(e)))
            if at:
                if max_at is None or at > max_at[1]:
                    max_at = ((int(s), int(e)), at)
        if max_at:
            res['last'] = max_at[0]
            res['last_at'] = max_at[1]
    except Exception:
        pass
    return res

def get_watched_episodes_set_batch(tmdb_ids):
    prov = _get_provider_raw()
    tbl = {'trakt': 'trakt_watched_episodes', 'mdblist': 'mdblist_watched_episodes', 'simkl': 'simkl_watched_episodes'}[prov]
    result = {}
    ids = [str(x) for x in (tmdb_ids or []) if x]
    if not ids:
        return result
    for tid in ids:
        result[tid] = {'set': set(), 'last': None, 'last_at': ''}
    try:
        mod = get_source_module()
        conn = mod.get_connection()
        cur = conn.cursor()
        chunk_size = 400
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cur.execute(f"SELECT tmdb_id, season, episode, last_watched_at FROM {tbl} WHERE tmdb_id IN ({placeholders})", chunk)
            for row in cur.fetchall():
                tid, s, e, at = str(row[0]), row[1], row[2], row[3]
                if tid not in result:
                    continue
                if not s or not e:
                    continue
                result[tid]['set'].add((int(s), int(e)))
                if at:
                    cur_last = result[tid]['last_at']
                    if not cur_last or at > cur_last:
                        result[tid]['last'] = (int(s), int(e))
                        result[tid]['last_at'] = at
        conn.close()
    except Exception:
        pass
    return result

def _refresh_tmdb_up_next(tmdb_id):
    """Recalculeaza randul TMDB Up Next dupa mark watched/unwatched (daca TMDb e conectat)."""
    try:
        from resources.lib.config import TMDB_V4_TOKEN_FILE
        if os.path.exists(TMDB_V4_TOKEN_FILE):
            from resources.lib.trakt_sync import refresh_next_episode_tmdb
            refresh_next_episode_tmdb(tmdb_id)
    except Exception:
        pass

def get_season_watched_count(tmdb_id, season):
    """Numar de episoade vizionate dintr-un sezon (provider-aware, int)."""
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id, season)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)
    else:
        from resources.lib.simkl_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)

def sync_full_library(silent=False, force=False):
    prov = _get_provider_raw()
    from resources.lib.trakt_sync import sync_full_library as _trakt_sync
    from resources.lib.mdblist_sync import sync_full_library as _mdblist_sync
    from resources.lib.simkl_sync import sync_full_library as _simkl_sync

    order = [prov] + [p for p in ('trakt', 'mdblist', 'simkl') if p != prov]
    for p in order:
        try:
            if p == 'trakt':
                _trakt_sync(silent=silent, force=force)
            elif p == 'mdblist':
                _mdblist_sync(silent=silent, force=force)
            else:
                _simkl_sync(silent=silent, force=force)
        except Exception as e:
            xbmc.log(f'[{p.upper()} SYNC] secondary sync error: {e}', xbmc.LOGERROR)

def get_watched_counts(tmdb_id, content_type, season=None):
    """Provider-aware watched count: {watched: int, total: int}"""
    if content_type == 'movie':
        return 1 if is_movie_watched(tmdb_id) else 0
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib import trakt_api
        if content_type == 'season' and season is not None:
            return trakt_api.get_watched_counts(tmdb_id, 'season', season)
        else:
            return trakt_api.get_watched_counts(tmdb_id, 'tv')
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
    else:
        from resources.lib.simkl_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
