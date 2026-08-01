# -*- coding: utf-8 -*-
"""
Watched Status Provider abstraction layer.
Dispatching între Trakt și MDBList în funcție de setarea watched_status_provider.
"""

import os

from resources.lib.config import ADDON, ADDON_PATH, MDBLIST_API_URL

# FĂRĂ cache la nivel de modul: Kodi reutilizează procesul Python al addon-ului
# între navigări, deci un cache permanent (ex. _PROVIDER_CACHE) ar rămâne STALE
# când providerul se schimbă din Setări — UI-ul ar continua să citească vechiul
# provider până la restart. ADDON.getSetting e deja mtime-validat în config.py
# (re-parsează settings.xml doar când fișierul se schimbă) — citirea directă
# e ieftină (un stat + lookup) și mereu actuală.

def _get_provider_raw():
    try:
        idx = int(ADDON.getSetting('watched_status_provider') or '0')
    except:
        idx = 0
    return ('trakt', 'mdblist')[idx]

def clear_cache():
    """No-op păstrat pentru compatibilitate (nu mai există cache de invalidat)."""
    pass

def _invalidate_fast_cache():
    """Invalidează fast cache-ul RAM (listele re-build din DB cu watched status proaspăt)."""
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
            api.scrobble_clear(content_type, tmdb_id, season, episode)
        elif action == 'start' or action == 'scrobble':
            api.scrobble_start(content_type, tmdb_id, progress, season, episode)
        elif action == 'pause':
            api.scrobble_pause(content_type, tmdb_id, progress, season, episode)
        elif action == 'stop':
            api.scrobble_stop(content_type, tmdb_id, progress, season, episode)
            _invalidate_fast_cache()

def dispatch_remove_progress(tmdb_id, content_type='movie', season=None, episode=None):
    """Elimină resume-ul (server + tabela locală) pe providerul activ."""
    if is_trakt():
        from resources.lib.trakt_api import remove_from_progress
        remove_from_progress(tmdb_id, content_type, season, episode)
    else:
        from resources.lib.mdblist_api import MDBListAPI
        try:
            MDBListAPI().scrobble_clear(content_type, tmdb_id, season, episode)
        except Exception:
            pass
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tmdb_id, content_type, season, episode)
    _invalidate_fast_cache()

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
    """Număr de episoade vizionate pentru un serial (provider-aware, int)."""
    if is_trakt():
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id)
    else:
        from resources.lib.mdblist_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)

def get_season_watched_count(tmdb_id, season):
    """Număr de episoade vizionate dintr-un sezon (provider-aware, int)."""
    if is_trakt():
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id, season)
    else:
        from resources.lib.mdblist_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)

def sync_full_library(silent=False, force=False):
    if is_trakt():
        from resources.lib.trakt_sync import sync_full_library as _sync
        _sync(silent=silent, force=force)
    else:
        from resources.lib.mdblist_sync import sync_full_library as _sync
        _sync(silent=silent, force=force)

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
