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
    return ('trakt', 'mdblist')[idx]

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

def get_provider():
    return _get_provider_raw()

def is_trakt():
    return _get_provider_raw() == 'trakt'

def is_mdblist():
    return _get_provider_raw() == 'mdblist'

def get_label():
    return ('Trakt', 'MDBList')[0 if is_trakt() else 1]

def get_color():
    return 'pink' if is_trakt() else 'lightskyblue'

def get_icon():
    name = 'trakt.png' if is_trakt() else 'mdblist.png'
    return os.path.join(ADDON_PATH, 'resources', 'media', name)

def get_status_setting():
    return 'trakt_status' if is_trakt() else 'mdblist_status'

def get_access_token_setting():
    return 'trakt_access_token' if is_trakt() else 'mdblist_access_token'

def get_refresh_token_setting():
    return 'trakt_refresh_token' if is_trakt() else 'mdblist_refresh_token'

def dispatch_mark_watched(tmdb_id, content_type, season=None, episode=None, notify=True, sync_provider=True, refresh_ui=True):
    if is_trakt():
        from resources.lib.trakt_sync import mark_as_watched_internal
        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_trakt=sync_provider, refresh_ui=refresh_ui)
    else:
        from resources.lib.mdblist_sync import mark_as_watched_internal
        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_mdblist=sync_provider, refresh_ui=refresh_ui)
    _invalidate_fast_cache()

def dispatch_mark_unwatched(tmdb_id, content_type, season=None, episode=None, sync_provider=True, refresh_ui=True):
    if is_trakt():
        from resources.lib.trakt_sync import mark_as_unwatched_internal
        mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_trakt=sync_provider, refresh_ui=refresh_ui)
    else:
        from resources.lib.mdblist_sync import mark_as_unwatched_internal
        mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_mdblist=sync_provider, refresh_ui=refresh_ui)
    _invalidate_fast_cache()

def dispatch_scrobble(action, tmdb_id, content_type, season, episode, progress):
    if is_trakt():
        from resources.lib.trakt_api import send_trakt_scrobble
        send_trakt_scrobble(action, tmdb_id, content_type, season, episode, progress)
    else:
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
    # 2. Server Trakt + stergere locala + clear fast cache + Container.Refresh
    from resources.lib.trakt_api import remove_from_progress
    remove_from_progress(tmdb_id, content_type, season, episode)
    # 3. Bookmark Kodi (dialogul nativ de resume nu mai trebuie sa apara la click)
    _kodi_delete_resume_bookmark(tmdb_id, content_type, season, episode)

def is_movie_watched(tmdb_id):
    if is_trakt():
        from resources.lib.trakt_sync import is_movie_watched as _chk
        return _chk(tmdb_id)
    else:
        from resources.lib.mdblist_sync import is_movie_watched as _chk
        return _chk(tmdb_id)

def is_episode_watched(tmdb_id, season, episode):
    if is_trakt():
        from resources.lib.trakt_sync import is_episode_watched as _chk
        return _chk(tmdb_id, season, episode)
    else:
        from resources.lib.mdblist_sync import is_episode_watched as _chk
        return _chk(tmdb_id, season, episode)

def get_episode_watched_count(tmdb_id):
    """Numar de episoade vizionate pentru un serial (provider-aware, int)."""
    if is_trakt():
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id)
    else:
        from resources.lib.mdblist_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)

def get_season_watched_count(tmdb_id, season):
    """Numar de episoade vizionate dintr-un sezon (provider-aware, int)."""
    if is_trakt():
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id, season)
    else:
        from resources.lib.mdblist_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)

def sync_full_library(silent=False, force=False):
    # Sincronizam TOTI serviciile autorizate: providerul activ primul (date
    # interferente + non-interferente + TMDb), apoi celalalt serviciu, daca e
    # autorizat — gate-ul intern din fiecare sync_full_library exclude datele
    # interferente (watched/playback/upnext) ale serviciului inactiv, deci intra
    # doar datele lui proprii (watchlist/favorites/liste/dropped/collection etc).
    # Locks separate ('tmdbmovies_sync_active' vs 'mdblist_sync_active') — fara
    # blocaje; fara creds, functiile fac early return.
    if is_trakt():
        from resources.lib.trakt_sync import sync_full_library as _trakt_sync
        from resources.lib.mdblist_sync import sync_full_library as _mdblist_sync
        _trakt_sync(silent=silent, force=force)
        try:
            _mdblist_sync(silent=silent, force=force)
        except Exception as e:
            xbmc.log(f"[MDB SYNC] MDBList secondary sync error: {e}", xbmc.LOGERROR)
    else:
        from resources.lib.mdblist_sync import sync_full_library as _mdblist_sync
        from resources.lib.trakt_sync import sync_full_library as _trakt_sync
        _mdblist_sync(silent=silent, force=force)
        try:
            _trakt_sync(silent=silent, force=force)
        except Exception as e:
            xbmc.log(f"[TRAKT SYNC] Trakt secondary sync error: {e}", xbmc.LOGERROR)

def get_watched_counts(tmdb_id, content_type, season=None):
    """Provider-aware watched count: {watched: int, total: int}"""
    if content_type == 'movie':
        return 1 if is_movie_watched(tmdb_id) else 0
    if is_trakt():
        from resources.lib import trakt_api
        if content_type == 'season' and season is not None:
            return trakt_api.get_watched_counts(tmdb_id, 'season', season)
        else:
            return trakt_api.get_watched_counts(tmdb_id, 'tv')
    else:
        from resources.lib.mdblist_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
