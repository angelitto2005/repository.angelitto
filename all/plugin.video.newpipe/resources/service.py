# -*- coding: utf-8 -*-
"""Background helper for progressive playback and account-link completion.

This service does not use plugin.video.youtube. It only chooses Portuguese,
then English, when Kodi exposes multiple tracks on a direct Googlevideo stream.
"""

from __future__ import absolute_import

import json
import os
import sys
import time

import xbmc
import xbmcgui

# Kodi executes a service extension with ``resources/`` as the script path,
# unlike main.py which starts at the add-on root. Add that root explicitly so
# ``resources.lib`` can always be imported on Android as well as desktop Kodi.
_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADDON_ROOT not in sys.path:
    sys.path.insert(0, _ADDON_ROOT)
_LIBRARY_PATH = os.path.join(_ADDON_ROOT, 'resources', 'lib')
if _LIBRARY_PATH not in sys.path:
    sys.path.insert(0, _LIBRARY_PATH)

from resources.lib import random_music
from resources.lib import ui
from resources.lib import youtube_sync


_AUDIO_PREFERENCE = (
    ('por', 'pt', 'portugu', 'brazil', 'brasil'),
    ('eng', 'en', 'ingl', 'english'),
)

_ACCOUNT_MENU_URL = 'plugin://plugin.video.newpipe/?action=subscriptions'
_NEXT_MUSIC_PREVIEW_SECONDS = 15
_NEXT_MUSIC_PREVIEW_DURATION = 5500


def _open_account_menu():
    """Replace the QR submenu with the account menu after authorization."""
    try:
        xbmc.executebuiltin('Container.Update({0},replace)'.format(
            _ACCOUNT_MENU_URL))
        xbmc.log('[NewPipe YouTube] menu de sincronização aberto', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NewPipe YouTube] não foi possível abrir o menu da conta: {0}'.format(exc),
                 xbmc.LOGWARNING)


def _rpc(method, params):
    try:
        result = xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
        }))
        return json.loads(result).get('result')
    except Exception:
        return None


def _select_audio_track():
    data = _rpc('Player.GetProperties', {
        'playerid': 1,
        'properties': ['audiostreams', 'currentaudiostream'],
    })
    if not data:
        return

    tracks = data.get('audiostreams') or []
    if not tracks:
        return
    current = data.get('currentaudiostream') or {}
    current_index = current.get('index', -1)

    selected = None
    for group in _AUDIO_PREFERENCE:
        for track in tracks:
            text = '{0} {1}'.format(
                track.get('language') or '', track.get('name') or '').lower()
            if any(token in text for token in group):
                selected = track
                break
        if selected:
            break

    selected = selected or tracks[0]
    index = selected.get('index', 0)
    if index != current_index or current_index < 0:
        _rpc('Player.SetAudioStream', {'playerid': 1, 'stream': index})


def _remaining_seconds(player):
    """Return current remaining time, including a label fallback for HLS."""
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


def _show_music_up_next(player, shown_key=''):
    """Show Kodi's native mini notification shortly before a queued song ends."""
    tracks = random_music.queue_tracks()
    if len(tracks) < 2:
        return ''
    try:
        if not player.isPlayingVideo():
            return shown_key
    except Exception:
        return shown_key
    position = random_music.queue_position()
    if position < 0:
        return shown_key
    upcoming = random_music.next_after(position)
    if not upcoming:
        return shown_key

    key = '{0}:{1}'.format(position, upcoming.get('video_id', ''))
    if key == shown_key:
        return shown_key
    remaining = _remaining_seconds(player)
    if remaining is None or remaining <= 0 or remaining > _NEXT_MUSIC_PREVIEW_SECONDS:
        return shown_key

    title = upcoming.get('title') or upcoming.get('video_id') or ''
    message = ui.text(30196, 'Up next: {0}').format(title)
    try:
        xbmcgui.Dialog().notification(
            'NewPipe MOD', message, upcoming.get('image') or '',
            _NEXT_MUSIC_PREVIEW_DURATION)
        xbmc.log('[NewPipe Random music] próxima faixa mostrada: {0}'.format(
            upcoming.get('video_id', '')), xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NewPipe Random music] prévia não exibida: {0}'.format(exc),
                 xbmc.LOGWARNING)
    return key


def _start_pending_music_playlist():
    """Start one complete native Kodi playlist after the source card exits."""
    tracks = random_music.consume_playlist_start()
    if not tracks:
        return False
    try:
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        for track in tracks:
            item = xbmcgui.ListItem(label=track.get('title') or track.get('video_id') or '')
            image = track.get('image') or ''
            if image:
                try:
                    item.setArt({'thumb': image, 'icon': image, 'fanart': image})
                except Exception:
                    pass
            try:
                item.setProperty('IsPlayable', 'true')
            except Exception:
                pass
            playlist.add(random_music.plugin_url(track), item)
        xbmc.Player().play(playlist)
        xbmc.log('[NewPipe Random music] playlist Kodi iniciada: {0} faixas'.format(
            len(tracks)), xbmc.LOGINFO)
        return True
    except Exception as exc:
        random_music.clear_queue()
        xbmc.log('[NewPipe Random music] playlist não iniciou: {0}'.format(exc),
                 xbmc.LOGWARNING)
        return False


class _PlaybackObserver(xbmc.Player):

    def __init__(self):
        super(_PlaybackObserver, self).__init__()

    def onAVStarted(self):
        self._configure_audio()

    def onPlayBackStarted(self):
        self._configure_audio()

    def onPlayBackStopped(self):
        """Treat an explicit Kodi Stop as cancellation of Random music."""
        if random_music.is_playlist_active() and random_music.cancel():
            xbmc.log('[NewPipe Random music] fila cancelada pelo botão Stop', xbmc.LOGINFO)

    def _configure_audio(self):
        try:
            current = self.getPlayingFile()
        except Exception:
            current = ''
        if 'googlevideo' not in (current or '').lower():
            return
        xbmc.sleep(1200)
        _select_audio_track()


def run():
    monitor = xbmc.Monitor()
    observer = _PlaybackObserver()
    last_login_error = ''
    last_poll = 0
    last_preview = ''
    xbmc.log('[NewPipe Playback] helper progressivo iniciado', xbmc.LOGINFO)
    while not monitor.abortRequested():
        _start_pending_music_playlist()
        last_preview = _show_music_up_next(observer, last_preview)
        if time.time() - last_poll >= 5:
            last_poll = time.time()
            try:
                result = youtube_sync.poll_pending_once()
                last_login_error = ''
                if result.get('state') == 'authorized':
                    xbmcgui.Dialog().notification(
                        'NewPipe MOD', 'Conta YouTube ligada. A abrir o menu de sincronização.',
                        time=6000)
                    _open_account_menu()
                elif result.get('state') == 'expired':
                    xbmcgui.Dialog().notification(
                        'NewPipe', 'O código de ligação do YouTube expirou', time=5000)
                elif result.get('state') == 'failed':
                    message = result.get('message', 'erro desconhecido')
                    if message != last_login_error:
                        xbmc.log('[NewPipe YouTube] ligação falhou: {0}'.format(message), xbmc.LOGWARNING)
                        last_login_error = message
            except Exception as exc:
                message = str(exc)
                if message != last_login_error:
                    xbmc.log('[NewPipe YouTube] serviço de ligação: {0}'.format(message), xbmc.LOGWARNING)
                    last_login_error = message
        if monitor.waitForAbort(0.25):
            break
    del observer


if __name__ == '__main__':
    run()
