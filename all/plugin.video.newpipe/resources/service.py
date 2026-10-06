# -*- coding: utf-8 -*-
"""Background helper for progressive playback and account-link completion.

This service does not use plugin.video.youtube. It only chooses Portuguese,
then English, when Kodi exposes multiple tracks on a direct Googlevideo stream.
"""

from __future__ import absolute_import

import json
import os
import sys

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

from resources.lib import youtube_sync


_AUDIO_PREFERENCE = (
    ('por', 'pt', 'portugu', 'brazil', 'brasil'),
    ('eng', 'en', 'ingl', 'english'),
)

_ACCOUNT_MENU_URL = 'plugin://plugin.video.newpipe/?action=subscriptions'


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


class _PlaybackObserver(xbmc.Player):

    def onAVStarted(self):
        self._configure_audio()

    def onPlayBackStarted(self):
        self._configure_audio()

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
    xbmc.log('[NewPipe Playback] helper progressivo iniciado', xbmc.LOGINFO)
    while not monitor.abortRequested():
        try:
            result = youtube_sync.poll_pending_once()
            last_login_error = ''
            if result.get('state') == 'authorized':
                # A TV browse can be slow or temporarily changed by YouTube.
                # The service only finalizes the device link; the person starts
                # the explicit Sync action from the account menu afterwards.
                # This prevents a background network request from freezing or
                # destabilizing Kodi immediately after QR approval.
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
        if monitor.waitForAbort(5):
            break
    del observer


if __name__ == '__main__':
    run()
