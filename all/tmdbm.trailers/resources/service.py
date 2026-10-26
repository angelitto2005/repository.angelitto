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
_UP_NEXT_SECONDS = 15
_UP_NEXT_DURATION = 15000
_POLL_SECONDS = 0.5
_POLL_SECONDS_NEAR_END = 0.25
_PREFETCH_DONE = [False]


def notify(message, image='', time_ms=_UP_NEXT_DURATION):
    try:
        xbmcgui.Dialog().notification(_HEADING, message,
                                      image or config.addon_icon(), time_ms,
                                      sound=False)
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


def _own_playback():
    try:
        return 'tmdbm.trailers' in (
            xbmc.getInfoLabel('Player.Filenameandpath') or '')
    except Exception:
        return False


def _show_up_next(player, shown):
    from music import queue
    tracks = queue.active_tracks()
    if len(tracks) < 2:
        return shown, None
    if not _own_playback():
        return shown, None
    try:
        if not player.isPlayingVideo():
            return shown, None
    except Exception:
        return shown, None
    index = queue.position()
    mode = _repeat_mode()
    if mode == 'one' and 0 <= index < len(tracks):
        upcoming = tracks[index]
    else:
        upcoming = queue.next_after(index)
        if not upcoming and tracks and mode == 'all':
            upcoming = tracks[0]
    if not upcoming:
        return shown, None
    key = '{}:{}'.format(index, upcoming.get('video_id'))
    if key == shown:
        return shown, None
    remaining = _remaining_seconds(player)
    if remaining is None or remaining <= 0 or remaining > _UP_NEXT_SECONDS:
        return shown, remaining
    import lists
    message = '[B][COLOR FF00CED1]{}[/COLOR][/B]: [COLOR yellow][B]{}[/B][/COLOR]'.format(
        config.T(32161), lists.clean_title(upcoming.get('title'))
        or upcoming.get('video_id') or '')
    notify(message, upcoming.get('image') or '')
    config.log('UP Next announced at {:.1f}s remaining: {}'.format(
        remaining, upcoming.get('video_id')))
    return key, remaining


def _refill_music_queue(player, position=None):
    try:
        _refill_tail(player, position)
    except Exception as exc:
        config.log('music tail refill check failed: {}'.format(exc))


_REFILL = {'busy': False}
_REFILL_WINDOW = _UP_NEXT_SECONDS + 5


def _refill_tail(player, position=None):
    from music import queue
    state = queue.active()
    tracks = state.get('tracks') or []
    if state.get('mode') != 'active':
        return
    if (state.get('kind') or 'music') != 'music':
        return
    if len(tracks) < 2 or _repeat_mode():
        return
    if not _own_playback():
        return
    try:
        if not player.isPlayingVideo():
            return
    except Exception:
        return
    try:
        pos = int(queue.position() if position is None else position)
    except (TypeError, ValueError):
        return
    if pos < 0 or pos != len(tracks) - 1:
        return
    remaining = _remaining_seconds(player)
    if remaining is None or remaining <= 0 or remaining > _REFILL_WINDOW:
        return
    if _REFILL['busy']:
        return
    _REFILL['busy'] = True
    anchor = (tracks[-1] or {}).get('video_id')
    thread = threading.Thread(target=_refill_tail_bg,
                              args=(state.get('started'), anchor, pos))
    thread.daemon = True
    thread.start()


def _refill_tail_bg(started, anchor, pos):
    try:
        from music import queue
        fresh = queue.refetch_remaining('music')
        if not fresh:
            return
        state = queue.active()
        tracks = state.get('tracks') or []
        try:
            current = int(state.get('pos') or 0)
        except (TypeError, ValueError):
            current = -1
        if (state.get('mode') != 'active' or state.get('started') != started
                or current != pos or not tracks
                or tracks[-1].get('video_id') != anchor):
            return
        added = queue.append_remaining(fresh, started)
        if not added:
            return
        if _native_active():
            import lists
            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            for track in added:
                playlist.add(lists.queue_play_url(track),
                             lists.playlist_item(track))
        config.log('Music tail extended with {} tracks'.format(len(added)))
    except Exception as exc:
        config.log('music tail refill failed: {}'.format(exc))
    finally:
        _REFILL['busy'] = False


_SHARED_PROXY = {'done': False}


def _start_shared_proxy():
    """Publish the playback proxy from here, not from each plugin call.

    A plugin invocation cannot end while a thread of its interpreter is alive
    (Kodi waits on it in a 100 ms loop), and the proxy lives for the whole
    clip. Started here it belongs to the service, which lasts the session, so
    the plugin invocation finishes right after it resolved the stream.
    """
    if _SHARED_PROXY['done']:
        return
    _SHARED_PROXY['done'] = True
    try:
        import player as _player_module
        port = _player_module.start_shared_proxy()
        config.log('shared proxy on port {} (playback invocations can end '
                   'while it serves)'.format(port), always=True)
    except Exception as exc:
        config.log('shared proxy failed to start: {}'.format(exc))


def _bg_refresh_ok(folder_hint=''):
    """May this worker repaint the list? Same guard as router._bg_refresh_ok.

    The refresh is queued on the UI thread, so a blind one can land on a Stop
    that just closed the media window or on a Back that is already navigating -
    the crash seen on the Android box. Only repaint while the synced list is on
    screen and nothing is playing; the rows are in the store either way.
    """
    try:
        if xbmc.Player().isPlayingVideo():
            return False
    except Exception:
        pass
    try:
        if xbmc.getCondVisibility('System.HasModalDialog'):
            return False
    except Exception:
        pass
    if folder_hint:
        try:
            folder = xbmc.getInfoLabel('Container.FolderPath') or ''
            if folder_hint not in folder:
                config.log('sync refresh skipped (other list)')
                return False
        except Exception:
            return False
    return True


def _sync_library_bg():
    try:
        from account import youtube_sync
        summary = youtube_sync.sync_library()
    except Exception as exc:
        notify(config.T(32174).format(str(exc)[:120]))
        return
    notify(config.T(32191).format(
        summary.get('channels', 0), summary.get('videos', 0)),
        time_ms=6000)
    if _bg_refresh_ok('my_youtube'):
        xbmc.executebuiltin('Container.Refresh')


def _sync_after_connect():
    thread = threading.Thread(target=_sync_library_bg, daemon=True)
    thread.start()


def _remote_library_empty():
    """True when the account mirror holds nothing at all. After a cache
    clear the sync stamp can say 'synced recently' while every folder is
    empty, so the stamp alone must not block the refresh."""
    try:
        import store
        return not (store.get_library('subscription_feed')
                    or store.get_library('subscribed_channels')
                    or store.get_library('saved_playlists'))
    except Exception:
        return False


def _maybe_periodic_sync(syncing, force=False):
    if syncing['busy']:
        return
    try:
        import time
        import store
        from account import youtube_sync
        if not youtube_sync.status().get('connected'):
            return
        try:
            last = int(store.get_state('last_yt_sync').get('ts') or 0)
        except (TypeError, ValueError):
            last = 0
        age = time.time() - last
        empty = _remote_library_empty()
        if not force and age < 24 * 3600 and not empty:
            config.log('periodic sync: last run {:.1f}h ago (next in '
                       '{:.1f}h)'.format(age / 3600.0,
                                         (24 * 3600 - age) / 3600.0))
            return
        if force and age < 1800 and not empty:
            config.log('update sync: already synced {:.1f}h ago'.format(
                age / 3600.0))
            return
        config.log('update sync: refreshing the account now' if force
                   else 'periodic sync: mirror empty, refreshing now')
        syncing['busy'] = True
        thread = threading.Thread(target=_periodic_sync_bg, args=(syncing,),
                                  daemon=True)
        thread.start()
    except Exception as exc:
        config.log('periodic sync start failed: {}'.format(exc))


def _periodic_sync_bg(syncing):
    try:
        from account import youtube_sync
        summary = youtube_sync.sync_library()
    except Exception as exc:
        config.log('periodic sync failed: {}'.format(str(exc)[:120]))
        syncing['busy'] = False
        return
    syncing['busy'] = False
    config.log('periodic sync done: {0} channels, {1} videos'.format(
        summary.get('channels', 0), summary.get('videos', 0)))
    if _bg_refresh_ok('my_youtube'):
        xbmc.executebuiltin('Container.Refresh')


def queue_active():
    try:
        from music import queue
        return queue.is_active()
    except Exception:
        return False


_last_recover = [0.0]


def _error_stop(observer=None):
    try:
        if xbmc.getCondVisibility('Window.IsActive(okdialog)'):
            return True
    except Exception:
        pass
    try:
        if observer is not None and observer.was_playing:
            try:
                playing = observer.isPlayingVideo()
            except Exception:
                playing = False
            if not playing:
                return False
            total = float(observer.getTotalTime() or 0.0)
            if total <= 0:
                return True
    except Exception:
        pass
    return False


class _Observer(xbmc.Player):

    def __init__(self):
        xbmc.Player.__init__(self)
        self._advanced_at = 0.0
        self.was_playing = False

    def onPlayBackEnded(self):
        try:
            from music import queue as _q
            if (_q.active() or {}).get('mode') == 'pending':
                return
        except Exception:
            pass
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
            state = queue.active() or {}
            try:
                age = time.time() - float(state.get('started') or 0)
            except (TypeError, ValueError):
                age = 1e9
            if state.get('mode') == 'pending' or age < 10:
                config.log('Stop ignored, queue switching')
                return
            if time.time() - self._advanced_at < 20:
                config.log('Stop ignored, the queue continues')
                return
            if _error_stop(self) and time.time() - _last_recover[0] > 30:
                _last_recover[0] = time.time()
                config.log('Stop looks like a failed open, skipping ahead')
                _play_next(self, 'error-skip')
                return
            queue.cancel()
            config.log('Queue cleared by Stop')
        except Exception as exc:
            config.log('stop handler failed: {}'.format(exc))


def _oauth_file():
    return os.path.join(config.ADDON_PROFILE, 'youtube_oauth.json')


def _repeat_mode():
    try:
        if xbmc.getCondVisibility('Playlist.IsRepeatOne'):
            return 'one'
        if xbmc.getCondVisibility('Playlist.IsRepeat'):
            return 'all'
    except Exception:
        pass
    return ''


_ADVANCE_LOCK = threading.Lock()
_ADVANCE = {'busy': False}
_LAST_PLAYMEDIA = [0.0]


def _play_next(observer, why):
    """Start the next track of the queue. Used by the callback and by the poll
    loop, so autoplay does not depend on the playback-ended event alone."""
    from music import queue
    if not queue.is_active():
        return False
    with _ADVANCE_LOCK:
        now = time.time()
        if (_ADVANCE['busy'] or now - observer._advanced_at < 1
                or now - _LAST_PLAYMEDIA[0] < 2):
            config.log('Queue advance skipped ({}), already starting'.format(why))
            return False
        _ADVANCE['busy'] = True
        observer._advanced_at = now
    try:
        state = queue.active() or {}
        prev_tracks = list(state.get('tracks') or [])
        try:
            prev_pos = int(state.get('pos') or 0)
        except (TypeError, ValueError):
            prev_pos = 0
        upcoming = queue.advance()
        tag = ''
        if not upcoming and prev_tracks:
            mode = _repeat_mode()
            if mode == 'one' and 0 <= prev_pos < len(prev_tracks):
                queue.set_active(prev_tracks, kind=state.get('kind') or 'music',
                                 pos=prev_pos, listing=state.get('listing'))
                upcoming = prev_tracks[prev_pos]
                tag = ' (repeat one)'
            elif mode == 'all':
                queue.set_active(prev_tracks, kind=state.get('kind') or 'music',
                                 pos=0, listing=state.get('listing'))
                upcoming = prev_tracks[0]
                tag = ' (repeat all)'
        if not upcoming:
            config.log('Queue finished ({})'.format(why))
            return False
        try:
            import lists
            from urllib.parse import urlencode
            query = lists.entry_params(upcoming)
            query['mode'] = 'queue_play'
            xbmc.executebuiltin('PlayMedia(plugin://tmdbm.trailers/?{})'.format(
                urlencode(query)))
            _LAST_PLAYMEDIA[0] = time.time()
            config.log('Queue advanced to {} ({}{})'.format(
                upcoming.get('video_id'), why, tag))
            _maybe_inject_related(upcoming)
            return True
        except Exception as exc:
            config.log('queue advance failed: {}'.format(exc))
            queue.clear()
            return False
    finally:
        with _ADVANCE_LOCK:
            _ADVANCE['busy'] = False


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
        if not _own_playback():
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
        pos = int(queue.position())
    except (TypeError, ValueError):
        pos = 0
    try:
        import lists
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        items = []
        for track in tracks:
            li = lists.playlist_item(track)
            playlist.add(lists.queue_play_url(track), li)
            items.append(li)
        if 0 < pos < len(items):
            import json as _js
            opened = xbmc.executeJSONRPC(_js.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Player.Open',
                'params': {'item': {'playlistid': 1, 'position': pos}}}))
            try:
                _ok = _js.loads(opened).get('result') == 'OK'
            except Exception:
                _ok = False
            if not _ok:
                xbmc.Player().play(playlist)
        else:
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
        config.get_setting('content_country', '35', _use_snapshot=False),
        config.get_setting('content_language', '2', _use_snapshot=False),
        config.get_setting('content_country_custom', '', _use_snapshot=False),
        config.get_setting('content_language_custom', '', _use_snapshot=False))


def _watch_locale(previous):
    """Country or language changed: drop our own cache and refresh the screen."""
    current = _locale_key()
    if previous and current != previous:
        _reset_browse_state(current)
    return current


_LOCALE_SEEN = []
_UI_LANG_SEEN = []
_LAST_FLAGS = {}


def _settings_snapshot():
    try:
        from browse import constants
        return {'mode': constants.playback_mode(),
                'autoplay': bool(constants.autoplay_next())}
    except Exception:
        return {}


_LAST_LOCALE_RESET = [0.0]
_LAST_REFRESH = [0.0]
_IP_SETTING_SEEN = []


def _reset_browse_state(current):
    try:
        from browse import constants
        constants.reset_cache()
    except Exception as exc:
        config.log('locale cache reset failed: {}'.format(exc))
    try:
        from browse import charts as _charts
        _charts._visitor['value'] = ''
        _charts._visitor['ts'] = 0.0
    except Exception as exc:
        config.log('locale visitor reset failed: {}'.format(exc))
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


def _publish_locale(current):
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty('tmdbm.trailers.locale', current)
    except Exception as exc:
        config.log('locale publish failed: {}'.format(exc))


def _publish_settings():
    try:
        import json as _js
        import xbmcgui
        data = {}
        for key in config.SNAPSHOT_KEYS:
            try:
                data[key] = str(config.get_setting(key, '', _use_snapshot=False))
            except Exception:
                data[key] = ''
        xbmcgui.Window(10000).setProperty(
            config.SNAPSHOT_PROP, _js.dumps(data, separators=(',', ':')))
    except Exception as exc:
        config.log('settings snapshot failed: {}'.format(exc))


def _adopt_native_order():
    try:
        import json as _js
        res = xbmc.executeJSONRPC(_js.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Playlist.GetItems',
            'params': {'playlistid': 1, 'properties': ['file']}}))
        items = (_js.loads(res).get('result') or {}).get('items') or []
    except Exception:
        return
    from urllib.parse import urlparse, parse_qs
    native_ids = []
    for item in items:
        try:
            query = parse_qs(urlparse(item.get('file') or '').query)
            native_ids.append((query.get('video_id') or [''])[0])
        except Exception:
            native_ids.append('')
    try:
        pos = int(xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition())
    except Exception:
        return
    try:
        from music import queue
        if queue.adopt_order(native_ids, pos):
            config.log('adopted native playlist order')
    except Exception as exc:
        config.log('adopt native order failed: {}'.format(exc))


class _LocaleMonitor(xbmc.Monitor):

    def onNotification(self, sender, method, data):
        try:
            if method != 'Player.OnPropertyChanged':
                return
            import json as _js
            payload = _js.loads(data or '{}')
            props = payload.get('property') or {}
            if 'shuffled' not in props:
                return
            player = payload.get('player') or {}
            if 'playerid' in player and int(player['playerid']) != 1:
                return
        except Exception:
            return
        _adopt_native_order()

    def onSettingsChanged(self):
        current = _locale_key()
        _publish_locale(current)
        _publish_settings()
        try:
            ui_code = str(config.get_setting('ui_language', 'auto',
                                             _use_snapshot=False) or 'auto')
        except Exception:
            ui_code = 'auto'
        if not _UI_LANG_SEEN:
            _UI_LANG_SEEN.append(ui_code)
        elif ui_code != _UI_LANG_SEEN[0]:
            _UI_LANG_SEEN[0] = ui_code
            import time as _time4
            if _time4.time() - _LAST_REFRESH[0] >= 3:
                _LAST_REFRESH[0] = _time4.time()
                try:
                    from browse import constants as _constants
                    _constants.reset_cache()
                except Exception as exc:
                    config.log('ui language cache reset failed: {}'.format(exc))
                config.log('UI language changed to {}, refresh'.format(ui_code))
                xbmc.executebuiltin('Container.Refresh')
        try:
            # Network family applies to the whole process, so a change in
            # settings takes effect now instead of after a Kodi restart. A
            # manual choice also forgets what auto had learned earlier.
            chosen = config.ip_family_setting()
            if _IP_SETTING_SEEN and chosen != _IP_SETTING_SEEN[0]:
                config.forget_learned_ip_family()
            _IP_SETTING_SEEN[:] = [chosen]
            config.enforce_ip_family()
        except Exception:
            pass
        did_reset = False
        if not _LOCALE_SEEN:
            _LOCALE_SEEN.append(current)
        elif current != _LOCALE_SEEN[0]:
            _LOCALE_SEEN[0] = current
            import time as _time2
            if _time2.time() - _LAST_LOCALE_RESET[0] >= 3:
                _LAST_LOCALE_RESET[0] = _time2.time()
                _LAST_REFRESH[0] = _time2.time()
                _reset_browse_state(current)
                did_reset = True
        snap = _settings_snapshot()
        previous = _LAST_FLAGS.get('mode')
        _LAST_FLAGS.update(snap)
        if previous is not None and snap.get('mode') != previous:
            config.log('Playback mode changed to {}'.format(snap.get('mode')))
            _apply_mode_live(snap.get('mode'))
        if not did_reset:
            import time as _time3
            if _time3.time() - _LAST_REFRESH[0] >= 3:
                _LAST_REFRESH[0] = _time3.time()
                xbmc.executebuiltin('Container.Refresh')


def _apply_mode_live(mode):
    if mode == 'shuffle':
        _apply_shuffle_live(True)
    elif mode == 'off':
        _apply_shuffle_live(False)
    elif mode == 'related':
        _seed_related_live()


def _seed_related_live():
    from music import queue
    state = queue.active()
    tracks = state.get('tracks') or []
    if not tracks or (state.get('listing') or {}).get('mode') == 'local_playlist':
        return
    try:
        pos = int(state.get('pos') or 0)
    except (TypeError, ValueError):
        pos = 0
    current = tracks[pos] if 0 <= pos < len(tracks) else tracks[0]
    old_tail = tracks[pos + 1:]
    fresh = queue.replace_tail(current.get('video_id'), size=10)
    if not fresh:
        return
    try:
        import lists
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        for track in reversed(old_tail):
            try:
                playlist.remove(lists.queue_play_url(track))
            except Exception:
                pass
        for track in fresh:
            playlist.add(lists.queue_play_url(track), lists.playlist_item(track))
        config.log('Related live: {} tracks replace {}'.format(len(fresh), len(old_tail)))
    except Exception as exc:
        config.log('related live failed: {}'.format(exc))


def _maybe_inject_related(upcoming):
    try:
        from browse import constants
        if constants.playback_mode() != 'related':
            return
        import store
        from music import queue
        if (store.get_state('list_route') or {}).get('mode') == 'local_playlist':
            return
        state = queue.active() or {}
        if (state.get('listing') or {}).get('mode') == 'local_playlist':
            return
        fresh = queue.inject_related((upcoming or {}).get('video_id'))
        if not fresh:
            return
        import lists
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        for track in fresh:
            playlist.add(lists.queue_play_url(track), lists.playlist_item(track))
    except Exception as exc:
        config.log('related inject failed: {}'.format(exc))


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


def _prefetch_lists_bg(delay):
    """Warm the heavy listings shortly after start.

    Opt-in, because these are real requests: doing them at start instead of on
    open keeps the first entry instant, but if a listing is never opened its
    request was spent for nothing. We hold off a little so the start itself
    stays quick, and skip it entirely while something is playing so we never
    compete with playback for the connection.
    """
    if xbmc.Monitor().waitForAbort(delay):
        return
    try:
        player = xbmc.Player()
        if player.isPlayingVideo():
            config.log('prefetch: skipped, something is playing')
            return
    except Exception:
        pass
    try:
        import router
        router.warm_first_pages()
    except Exception as exc:
        config.log('prefetch failed: {}'.format(str(exc)[:160]))
        return
    try:
        import store
        from browse import constants
        # Feed off in Settings > Menu: it is not reachable from the root any
        # more, so do not spend a request per subscription on warming it.
        if not config.menu_enabled('feed'):
            config.log('prefetch: Feed is off in Settings > Menu, skipped')
            return
        subscriptions = store.get_subscriptions()
        if not subscriptions:
            config.log('prefetch: no subscriptions, feed skipped')
            return
        need = 2 * constants.results_per_page() + 1
        entries, _exhausted = router._collect_feed(
            need, constants.feed_per_channel())
        config.log('prefetch: feed warmed ({} entries)'.format(len(entries)),
                   always=True)
    except Exception as exc:
        config.log('prefetch feed failed: {}'.format(str(exc)[:160]),
                   xbmc.LOGWARNING, always=True)


def _maybe_prefetch_lists():
    if _PREFETCH_DONE[0]:
        return
    try:
        if not config.get_bool('prefetch_lists', False):
            return
    except Exception:
        return
    _PREFETCH_DONE[0] = True
    thread = threading.Thread(target=_prefetch_lists_bg, args=(45,),
                              name='list-prefetch')
    thread.daemon = True
    thread.start()


def run():
    monitor = _LocaleMonitor()
    player = xbmc.Player()
    observer = _Observer()
    observer.was_playing = False
    shown = ''
    config.log('Service started')
    # The service talks to YouTube (update check, library sync, feed), so it
    # validates the pinned family here; importing config only applies it.
    try:
        config.enforce_ip_family()
    except Exception:
        pass
    _publish_locale(_locale_key())
    _publish_settings()
    _start_shared_proxy()
    updated = None
    try:
        import maintenance
        updated = maintenance.check_addon_update()
    except Exception as exc:
        config.log('update check failed: {}'.format(exc))
    try:
        import threading as _th

        def _netcheck_report():
            """Egress IP (v4 and v6), DNS family and the real JA3 of this
            device, in one block in kodi.log. Only with debug enabled, so a
            normal start stays quiet: this is the report to compare when one
            device gets the YouTube anti-bot gate and another does not."""
            try:
                if not config.get_bool('debug', False):
                    return
                import netcheck as _nc
                _nc.run()
            except Exception:
                pass

        _th.Thread(target=_netcheck_report, daemon=True).start()
    except Exception:
        pass
    try:
        from music import queue
        if not player.isPlayingVideo():
            queue.cancel()
    except Exception:
        pass
    _maybe_prefetch_lists()
    watching = os.path.exists(_oauth_file())
    last_poll = 0.0
    last_periodic = 0.0
    syncing = {'busy': False}
    locale_key = _locale_key()
    del _LOCALE_SEEN[:]
    _LOCALE_SEEN.append(locale_key)
    _LAST_FLAGS.update(_settings_snapshot())
    try:
        # Seed the network family so the first change after a restart is still
        # detected as a change (and clears what auto had learned).
        _IP_SETTING_SEEN[:] = [config.ip_family_setting()]
    except Exception:
        pass
    try:
        import time
        import store
        _last_ts = int(store.get_state('last_yt_sync').get('ts') or 0)
        _age_h = (time.time() - _last_ts) / 3600 if _last_ts else -1
        config.log('periodic sync: last run {} (next in {})'.format(
            '{:.1f}h ago'.format(_age_h) if _age_h >= 0 else 'never',
            '{:.1f}h'.format(max(0.0, 24 - _age_h)) if _age_h >= 0 else 'now'),
            always=True)
        if updated == 'upgrade':
            config.log('addon upgraded: refreshing the account now',
                       always=True)
            _maybe_periodic_sync(syncing, force=True)
    except Exception:
        pass
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
            try:
                _modal = bool(xbmcgui.Window(10000).getProperty(
                    'tmdbm.auth_modal_open'))
            except Exception:
                _modal = False
            if watching and not _modal and now - last_poll >= 5:
                last_poll = now
                from account import youtube_sync
                result = youtube_sync.poll_pending_once()
                state = result.get('state')
                if state == 'authorized':
                    watching = False
                    try:
                        if xbmc.getCondVisibility('Window.IsActive(slideshow)'):
                            xbmc.executebuiltin('Action(Back)')
                            xbmc.sleep(500)
                    except Exception:
                        pass
                    notify(config.T(32179))
                    _sync_after_connect()
                    xbmc.executebuiltin(
                        'Container.Update({}?mode=my_youtube,replace)'.format(
                            'plugin://tmdbm.trailers/'))
                elif state in ('expired', 'failed'):
                    watching = False
                    notify(config.T(32197) if state == 'expired'
                           else config.T(32196))
        except Exception as exc:
            config.log('login watcher: {}'.format(str(exc)[:120]))
        try:
            import time
            if time.time() - last_periodic >= 1800:
                last_periodic = time.time()
                _maybe_periodic_sync(syncing)
        except Exception as exc:
            config.log('periodic sync check failed: {}'.format(str(exc)[:120]))
        if monitor.waitForAbort(wait):
            break
    del observer
    try:
        import player as _player_module
        _player_module.stop_shared_proxy()
    except Exception as exc:
        config.log('shared proxy stop failed: {}'.format(exc))


if __name__ == '__main__':
    run()