# -*- coding: utf-8 -*-
"""
Watched Status Provider abstraction layer.
Dispatching intre Trakt si MDBList in functie de setarea watched_status_provider.
"""

import os
import xbmc
import xbmcvfs

from resources.lib.config import ADDON, ADDON_PATH, MDBLIST_API_URL

# FARA cache la nivel de modul: Kodi reutilizeaza procesul Python al addon-ului
# intre navigari, deci un cache permanent (ex. _PROVIDER_CACHE) ar ramane STALE
# cand providerul se schimba din Setari — UI-ul ar continua sa citeasca vechiul
# provider pana la restart. ADDON.getSetting e deja mtime-validat in config.py
# (re-parseaza settings.xml doar cand fisierul se schimba) — citirea directa
# e ieftina (un stat + lookup) si mereu actuala.

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
    """Detecteaza daca suntem pe Home/widget (nu in interiorul addonului).
    La fel ca POV: daca Container.PluginName NU e addonul nostru, suntem pe
    Home/widget -> trebuie UpdateLibrary (nu Container.Refresh, care nu atinge
    widget-urile de pe Home). La orice eroare presupunem Home (sigur: UpdateLibrary
    e nevinovat, doar emite OnUpdate)."""
    try:
        return 'tmdbmovies' not in xbmc.getInfoLabel('Container.PluginName')
    except:
        return True

def widget_refresh():
    """Reimprospateaza TOATE widget-urile din skin (AF3 asculta de evenimentul
    VideoLibrary.OnUpdate). UpdateLibrary(video, special://skin/foo) e trucul POV:
    path-ul nu exista deci nu scaneaza nimic real, dar Kodi emite OnUpdate -> toate
    widget-urile (Next Episodes, In Progress, etc.) se re-randa in ~5s.
    Fara asta, Container.Refresh doar reimprospateaza containerul activ, NU widget-urile
    de pe Home -> cerculetul de resume ramane pana la restart Kodi (vezi Android/AF3)."""
    try:
        xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')
    except:
        pass

def refresh_ui():
    """Refresh UI in functie de context: pe Home/widget -> UpdateLibrary (toate
    widget-urile), in interiorul addonului -> Container.Refresh (containerul activ)."""
    try:
        if _on_home_widget():
            widget_refresh()
        else:
            xbmc.executebuiltin('Container.Refresh')
    except:
        pass

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
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib.trakt_sync import mark_as_watched_internal
        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_trakt=sync_provider, refresh_ui=do_refresh)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import mark_as_watched_internal
        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_mdblist=sync_provider, refresh_ui=do_refresh)
    else:
        from resources.lib.simkl_sync import mark_as_watched_internal
        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_simkl=sync_provider, refresh_ui=do_refresh)
    _invalidate_fast_cache()
    if do_refresh: refresh_ui()

def dispatch_mark_unwatched(tmdb_id, content_type, season=None, episode=None, sync_provider=True, do_refresh=True):
    prov = _get_provider_raw()
    if prov == 'trakt':
        from resources.lib.trakt_sync import mark_as_unwatched_internal
        mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_trakt=sync_provider, refresh_ui=do_refresh)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import mark_as_unwatched_internal
        mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_mdblist=sync_provider, refresh_ui=do_refresh)
    else:
        from resources.lib.simkl_sync import mark_as_unwatched_internal
        mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_simkl=sync_provider, refresh_ui=do_refresh)
    _invalidate_fast_cache()
    if do_refresh: refresh_ui()

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
    """Sterge bookmark-ul de resume din baza video Kodi (MyVideos*.db) pentru acest item.
    Fara asta, dupa "Delete Resume" din context menu, dialogul NATIV de resume ar mai aparea
    la click (GetResumeString citeste bookmark-ul din baza Kodi, nu progress-ul local).
    Context menu-ul trimite type=episode, dar URL-ul din baza Kodi are type=tv."""
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
    # Sincronizam TOTI serviciile autorizate: providerul activ primul (date
    # interferente + non-interferente + TMDb), apoi celelalte servicii, daca sunt
    # autorizate — gate-ul intern din fiecare sync_full_library exclude datele
    # interferente (watched/playback/upnext) ale serviciilor inactive, deci intra
    # doar datele lor proprii (watchlist/dropped/ratings/collection etc).
    # Locks separate per serviciu — fara blocaje; fara creds, functiile fac early return.
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
