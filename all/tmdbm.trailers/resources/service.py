import os
import sys
import threading
import time

import xbmc
import xbmcgui

_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB_PATH = os.path.join(_ADDON_ROOT, 'resources', 'lib')
if _ADDON_ROOT not in sys.path:
    sys.path.insert(0, _ADDON_ROOT)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

import config

_HEADING = '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]'
_UP_LABEL = '[B][COLOR FF00CED1]UP Next[/COLOR][/B]'
_UP_NEXT_SECONDS = 15
_UP_NEXT_DURATION = 15000
_POLL_SECONDS = 0.5
_POLL_SECONDS_NEAR_END = 0.25


def notify(message, image='', time_ms=_UP_NEXT_DURATION):
    try:
        xbmcgui.Dialog().notification(_HEADING, message,
                                      image or config.addon_icon(), time_ms)
    except Exception as exc:
        config.log('notification failed: {}'.format(exc))


def _remaining_seconds(player):
    try:
        total = float(player.getTotalTime())
        elapsed = float(player.getTime())
        if total > elapsed >= 0:
            return total - elapsed
    except Exception:
        pass
    try:
        value = xbmc.getInfoLabel('Player.TimeRemaining').strip().lstrip('-')
        parts = [int(part) for part in value.split(':')]
        if parts and all(part >= 0 for part in parts):
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + part
            return float(seconds)
    except Exception:
        pass
    return None


def _show_up_next(player, shown):
    from music import queue
    tracks = queue.active_tracks()
    if len(tracks) < 2:
        return shown, None
    try:
        if not player.isPlayingVideo():
            return shown, None
    except Exception:
        return shown, None
    index = queue.position()
    upcoming = queue.next_after(index)
    if not upcoming:
        return shown, None
    key = '{}:{}'.format(index, upcoming.get('video_id'))
    if key == shown:
        return shown, None
    remaining = _remaining_seconds(player)
    if remaining is None or remaining <= 0 or remaining > _UP_NEXT_SECONDS:
        return shown, remaining
    message = '{}: [COLOR yellow]{}[/COLOR]'.format(
        _UP_LABEL, upcoming.get('title') or upcoming.get('video_id') or '')
    notify(message, upcoming.get('image') or '')
    config.log('UP Next announced at {:.1f}s remaining: {}'.format(
        remaining, upcoming.get('video_id')))
    return key, remaining


def _refill_music_queue(player, position=None):
    return


def queue_active():
    try:
        from music import queue
        return queue.is_active()
    except Exception:
        return False


class _Observer(xbmc.Player):

    def __init__(self):
        xbmc.Player.__init__(self)
        self._advanced_at = 0.0
        self.was_playing = False

    def onPlayBackEnded(self):
        if not queue_active():
            return
        if _native_active():
            return
        if getattr(self, 'tmdb_owns', False):
            return
        if time.time() - self._advanced_at < 10:
            return
        _play_next(self, 'callback')

    def onPlayBackStopped(self):
        # Kodi fires Stopped right after Ended when nothing is queued in the
        # Kodi playlist. Clearing here would kill the queue one track early, so
        # an advance that we just started owns the stop event.
        try:
            from music import queue
            if not queue.is_active():
                return
            if time.time() - self._advanced_at < 20:
                config.log('Stop ignored, the queue continues')
                return
            queue.cancel()
            config.log('Queue cleared by Stop')
        except Exception as exc:
            config.log('stop handler failed: {}'.format(exc))


def _oauth_file():
    return os.path.join(config.ADDON_PROFILE, 'youtube_oauth.json')


def _play_next(observer, why):
    """Start the next track of the queue. Used by the callback and by the poll
    loop, so autoplay does not depend on the playback-ended event alone."""
    from music import queue
    if not queue.is_active():
        return False
    upcoming = queue.advance()
    if not upcoming:
        config.log('Queue finished ({})'.format(why))
        return False
    observer._advanced_at = time.time()
    try:
        import lists
        from urllib.parse import urlencode
        query = lists.entry_params(upcoming)
        query['mode'] = 'queue_play'
        xbmc.executebuiltin('PlayMedia(plugin://tmdbm.trailers/?{})'.format(
            urlencode(query)))
        config.log('Queue advanced to {} ({})'.format(
            upcoming.get('video_id'), why))
        return True
    except Exception as exc:
        config.log('queue advance failed: {}'.format(exc))
        queue.clear()
        return False


def _end_watch_advance(player, observer, remaining):
    from music import queue
    if _native_active():
        return
    if remaining is None or remaining <= 0 or remaining > 3:
        return
    try:
        if not player.isPlayingVideo():
            return
    except Exception:
        return
    if not queue.is_active():
        return
    if queue.next_after(queue.position()) is None:
        return
    if time.time() - observer._advanced_at < 10:
        return
    _play_next(observer, 'end-watch')


def _watchdog_advance(player, observer, was_playing):
    """Fallback: the track reached its end but nothing started the next one."""
    if _native_active():
        return
    if not was_playing or not observer.was_playing:
        return
    try:
        if player.isPlayingVideo():
            return
        total = float(player.getTotalTime() or 0.0)
    except Exception:
        return
    if total <= 0:
        return
    if time.time() - observer._advanced_at < 2:
        return
    _play_next(observer, 'watchdog')


def _native_state():
    try:
        from music import queue
        state = queue.active()
        if not state.get('tracks') or state.get('mode') != 'active':
            return None
        if xbmc.PlayList(xbmc.PLAYLIST_VIDEO).size() <= 1:
            return None
        return state
    except Exception:
        return None


def _native_active():
    return _native_state() is not None


def _start_pending_playlist():
    from music import queue
    tracks = queue.consume_pending()
    if not tracks:
        return False
    try:
        import lists
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        for track in tracks:
            playlist.add(lists.queue_play_url(track), lists.playlist_item(track))
        xbmc.Player().play(playlist)
        config.log('Native playlist started: {} tracks'.format(len(tracks)))
        return True
    except Exception as exc:
        queue.clear()
        config.log('native playlist failed: {}'.format(exc))
        return False


def _sync_native_position():
    state = _native_state()
    if not state:
        return
    try:
        pos = int(xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition())
    except Exception:
        return
    if 0 <= pos < len(state.get('tracks') or []):
        from music import queue
        queue.set_position(pos)


_extend = {'busy': False}


def _maybe_extend_playlist():
    state = _native_state()
    if not state:
        return
    try:
        pos = int(xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition())
    except Exception:
        return
    if pos < 0 or len(state.get('tracks') or []) - (pos + 1) > 2:
        return
    if not (state.get('listing') or {}).get('mode') or state.get('exhausted'):
        return
    if _extend['busy']:
        return
    _extend['busy'] = True
    thread = threading.Thread(target=_extend_playlist_bg,
                              args=(state.get('started'),))
    thread.daemon = True
    thread.start()


def _extend_playlist_bg(started):
    try:
        import lists
        from music import queue
        from browse import constants
        state = queue.active()
        fresh = lists.append_next_page(state.get('listing'), started,
                                       constants.results_per_page())
        if not fresh:
            return
        current = queue.active()
        if not current.get('tracks') or current.get('started') != started:
            return
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        for track in fresh:
            playlist.add(lists.queue_play_url(track), lists.playlist_item(track))
        config.log('Playlist extended with {} tracks'.format(len(fresh)))
    except Exception as exc:
        config.log('playlist extend failed: {}'.format(exc))
    finally:
        _extend['busy'] = False


def _locale_key():
    """Raw localisation settings, without importing the scraper stack."""
    return '{}|{}|{}|{}'.format(
        config.get_setting('content_country', '35'),
        config.get_setting('content_language', '2'),
        config.get_setting('content_country_custom', ''),
        config.get_setting('content_language_custom', ''))


def _watch_locale(previous):
    """Country or language changed: drop our own cache and refresh the screen."""
    current = _locale_key()
    if previous and current != previous:
        _reset_browse_state(current)
    return current


_LOCALE_SEEN = []
_LAST_FLAGS = {}


def _settings_snapshot():
    try:
        from browse import constants
        return {'shuffle': bool(constants.shuffle_play()),
                'autoplay': bool(constants.autoplay_next())}
    except Exception:
        return {}


def _reset_browse_state(current):
    try:
        from browse import constants
        constants.reset_cache()
    except Exception as exc:
        config.log('locale cache reset failed: {}'.format(exc))
    try:
        import store
        from music import queue
        queue.save_pool([])
        store.set_state('list_context', {})
        store.set_state('list_route', {})
    except Exception as exc:
        config.log('locale state reset failed: {}'.format(exc))
    config.log('Localisation changed, cache reset and refresh ({})'.format(
        current))
    xbmc.executebuiltin('Container.Refresh')


class _LocaleMonitor(xbmc.Monitor):

    def onSettingsChanged(self):
        current = _locale_key()
        if not _LOCALE_SEEN:
            _LOCALE_SEEN.append(current)
        elif current != _LOCALE_SEEN[0]:
            _LOCALE_SEEN[0] = current
            _reset_browse_state(current)
        snap = _settings_snapshot()
        previous = _LAST_FLAGS.get('shuffle')
        _LAST_FLAGS.update(snap)
        if previous is not None and snap.get('shuffle') != previous:
            config.log('Shuffle flipped to {}'.format(
                'ON' if snap.get('shuffle') else 'OFF'))
            _apply_shuffle_live(bool(snap.get('shuffle')))


def _apply_shuffle_live(shuffle_on):
    from music import queue
    state = _native_state()
    if not state:
        return
    try:
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        pos = int(playlist.getposition())
    except Exception:
        return
    tracks = state.get('tracks') or []
    if pos < 0 or pos >= len(tracks):
        return
    old_tail = tracks[pos + 1:]
    if not old_tail:
        return
    if shuffle_on:
        new_tail = queue.reshuffle_tail(state.get('started'))
    else:
        import store
        import lists
        context = store.get_state('list_context').get('entries') or []
        order = [lists.video_id(entry.get('video_id')) for entry in context]
        new_tail = queue.reorder_tail(state.get('started'), order)
    if not new_tail:
        config.log('Shuffle flip: upcoming already in order')
        return
    try:
        import lists
        if int(playlist.getposition()) != pos:
            config.log('Shuffle flip skipped: track changed meanwhile')
            return
        for track in reversed(old_tail):
            playlist.remove(lists.queue_play_url(track))
        for track in new_tail:
            playlist.add(lists.queue_play_url(track), lists.playlist_item(track))
        if playlist.size() != len(queue.active_tracks()):
            config.log('Shuffle flip applied with size mismatch', xbmc.LOGWARNING)
        else:
            config.log('Shuffle live {}: {} upcoming reordered'.format(
                'ON' if shuffle_on else 'OFF', len(new_tail)))
    except Exception as exc:
        config.log('live shuffle failed: {}'.format(exc))


def run():
    monitor = _LocaleMonitor()
    player = xbmc.Player()
    observer = _Observer()
    observer.was_playing = False
    shown = ''
    config.log('Service started')
    try:
        from music import queue
        if not player.isPlayingVideo():
            queue.cancel()
    except Exception:
        pass
    watching = os.path.exists(_oauth_file())
    last_poll = 0.0
    locale_key = _locale_key()
    del _LOCALE_SEEN[:]
    _LOCALE_SEEN.append(locale_key)
    _LAST_FLAGS.update(_settings_snapshot())
    try:
        from playback import tmdb_autoplay_active
    except Exception:
        tmdb_autoplay_active = None
    wait = _POLL_SECONDS
    while not monitor.abortRequested():
        wait = _POLL_SECONDS
        try:
            locale_key = _watch_locale(locale_key)
            tmdb_owns = bool(tmdb_autoplay_active and tmdb_autoplay_active())
            observer.tmdb_owns = tmdb_owns
            if not tmdb_owns:
                _start_pending_playlist()
                _sync_native_position()
                shown, remaining = _show_up_next(player, shown)
                _maybe_extend_playlist()
                _end_watch_advance(player, observer, remaining)
                _watchdog_advance(player, observer, observer.was_playing)
            else:
                remaining = None
            _refill_music_queue(player)
            try:
                observer.was_playing = bool(player.isPlayingVideo())
            except Exception:
                observer.was_playing = False
            if remaining is not None and 0 < remaining <= _UP_NEXT_SECONDS * 2:
                wait = _POLL_SECONDS_NEAR_END
        except Exception as exc:
            config.log('up next check failed: {}'.format(exc))
        try:
            import time
            now = time.time()
            if not watching and now - last_poll >= 30:
                last_poll = now
                watching = os.path.exists(_oauth_file())
            if watching and now - last_poll >= 5:
                last_poll = now
                from account import youtube_sync
                result = youtube_sync.poll_pending_once()
                state = result.get('state')
                if state == 'authorized':
                    watching = False
                    notify('YouTube account connected. Opening My YouTube.')
                    xbmc.executebuiltin(
                        'Container.Update({}?mode=my_youtube,replace)'.format(
                            'plugin://tmdbm.trailers/'))
                elif state in ('expired', 'failed'):
                    watching = False
                    notify('The activation code expired' if state == 'expired'
                           else 'Account activation failed')
        except Exception as exc:
            config.log('login watcher: {}'.format(str(exc)[:120]))
        if monitor.waitForAbort(wait):
            break
    del observer


if __name__ == '__main__':
    run()