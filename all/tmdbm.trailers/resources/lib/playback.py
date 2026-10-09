import xbmc
import xbmcgui
import xbmcplugin

import config
import lists


def _int_or_none(value):
    if value is None or str(value) == '':
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def play_kwargs(params):
    return {
        'title': params.get('title'),
        'genre': params.get('genre'),
        'year': params.get('year'),
        'tmdb_id': params.get('tmdb_id'),
        'dbtype': params.get('dbtype'),
        'season': _int_or_none(params.get('season')),
        'episode_num': _int_or_none(params.get('episode')),
        'plot': params.get('plot'),
        'studio': params.get('studio'),
        'tagline': params.get('tagline'),
        'lang': params.get('lang'),
        'channel': params.get('channel'),
        'views': params.get('views'),
        'vdate': params.get('vdate'),
        'dur': _int_or_none(params.get('dur')),
        'snippet': params.get('snippet'),
    }


_TMDB_AUTOPLAY_FLAG = 'TMDbMovies.YoutubeAutoplay'


def tmdb_autoplay_active():
    try:
        return xbmcgui.Window(10000).getProperty(_TMDB_AUTOPLAY_FLAG) == 'true'
    except Exception:
        return False


def clear_tmdb_autoplay():
    try:
        xbmcgui.Window(10000).clearProperty(_TMDB_AUTOPLAY_FLAG)
    except Exception:
        pass


def is_external_play(params):
    params = params or {}
    if params.get('tmdb_id') or params.get('dbtype'):
        return True
    return tmdb_autoplay_active()


def _shuffled(kept):
    from browse import constants
    if constants.shuffle_play() and len(kept) > 1:
        import random
        random.SystemRandom().shuffle(kept)
        return True
    return False


def _current_entry(params, video_id):
    return {
        'video_id': video_id,
        'title': params.get('title') or '',
        'image': lists.thumbnail(video_id),
        'duration': _int_or_none(params.get('dur')) or 0,
        'is_live': False,
        'channel': params.get('channel') or '',
        'channel_id': params.get('channel_id') or '',
        'views': params.get('views') or '',
        'vdate': params.get('vdate') or '',
        'snippet': params.get('snippet') or '',
    }


def _arm_queue(tracks, video_id, mode, current=None, pending=False,
               listing=None):
    from music import queue

    kept = [track for track in tracks if track.get('video_id') != video_id]
    if not kept:
        return None
    label = mode + '+shuffle' if _shuffled(kept) else mode
    current = dict(current or {})
    if not current.get('video_id'):
        current = {'video_id': video_id,
                   'title': (tracks[0].get('title') if tracks else '') or '',
                   'image': lists.thumbnail(video_id)}
    if pending:
        queue.set_pending([current] + kept, mode, listing)
    else:
        try:
            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        except Exception:
            pass
        queue.set_active([current] + kept, mode, pos=0, listing=listing)
    config.log('Queue armed: {} tracks ({})'.format(len(kept), label))
    return mode


def _maybe_arm_queue(params):
    """Arm autoplay for playback that did not come through start_queue.

    Order of preference: the list the user is browsing (same videos, same
    order), then a random music track when nothing was browsed here. Only the
    first video arms it, the following ones are played by the service.
    """
    from music import detect, queue

    video_id = lists.video_id(params.get('video_id'))
    if not video_id:
        return None
    if queue.is_active():
        config.log('Queue already running, autoplay left untouched')
        return None
    from browse import constants
    if not constants.autoplay_next():
        return None
    try:
        import store
        tracks, found = queue.build_context_queue(video_id)
        if found and tracks:
            return _arm_queue(tracks, video_id, 'next',
                              current=_current_entry(params, video_id),
                              listing=store.get_state('list_route'))
        title = params.get('title') or ''
        if not detect.looks_like_music({'title': title}):
            return None
        entry = {'video_id': video_id, 'title': title,
                 'channel': params.get('channel') or '',
                 'channel_id': params.get('channel_id') or '',
                 'snippet': params.get('snippet') or '',
                 'image': lists.thumbnail(video_id)}
        tracks = queue.build_music_queue(video_id, entry=entry)
        if not tracks:
            return None
        return _arm_queue(tracks, video_id, 'music', current=entry)
    except Exception as exc:
        config.log('queue arm failed: {}'.format(exc), xbmc.LOGERROR)
        return None


_ARMING = {'busy': False}


def resolve_play(handle, params, extra=None, arm=True):
    video_id = lists.video_id(params.get('video_id'))
    if not video_id:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return None
    try:
        import store
        store.add_history(lists.history_entry(params))
    except Exception:
        pass
    if arm and not _ARMING['busy']:
        _ARMING['busy'] = True
        try:
            _maybe_arm_queue(params)
        except Exception as exc:
            config.log('queue arm failed: {}'.format(exc), xbmc.LOGERROR)
        finally:
            _ARMING['busy'] = False
    try:
        from player import play_youtube
        kwargs = play_kwargs(params)
        if extra:
            kwargs.update(extra)
        li = play_youtube(video_id, **kwargs)
        xbmcplugin.setResolvedUrl(handle, True, li)
        return li
    except Exception as exc:
        config.log('playback failed for {}: {}'.format(video_id, exc),
                   xbmc.LOGERROR)
        import traceback
        config.log(traceback.format_exc(), xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return None


def start_queue(handle, params):
    """Arm a native Kodi playlist and return without resolving.

    The service starts the playlist once this route finished, like NewPipe:
    resolving the clicked card here as well would play it twice.
    """
    from music import queue
    import store

    video_id = lists.video_id(params.get('video_id'))
    queue.cancel()
    try:
        import store
        store.add_history(lists.history_entry(params))
    except Exception:
        pass
    tracks, found = queue.build_context_queue(video_id)
    if not found:
        tracks = queue.build_music_queue(video_id)
    kept = [track for track in tracks if track.get('video_id') != video_id]
    if not kept:
        return resolve_play(handle, params)
    clear_tmdb_autoplay()
    _arm_queue(tracks, video_id, 'next' if found else 'music',
               current=_current_entry(params, video_id), pending=True,
               listing=store.get_state('list_route') if found else None)
    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    return None