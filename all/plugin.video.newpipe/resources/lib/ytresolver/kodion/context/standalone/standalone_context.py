# -*- coding: utf-8 -*-
"""
    StandaloneContext implementation for ytresolver
"""
from __future__ import absolute_import, division, unicode_literals

import os
from ..abstract_context import AbstractContext
from .standalone_settings import StandaloneSettings
from .standalone_ui import StandaloneUI
from ...json_store.access_manager import AccessManager
from ...json_store.api_keys import APIKeyStore


class DummyPlaylistPlayer(object):
    def clear(self): pass
    def unshuffle(self): pass
    def add(self, item): pass
    def size(self): return 0
    def get_position(self): return (0, 0)
    def get_item_path(self, pos): return ""
    def play_playlist_item(self, pos, defer=False): return ""


class StandaloneContext(AbstractContext):
    def __init__(self, path='/', params=None, plugin_id='ytresolver', data_dir=None, config_file=None, video_codecs=None):
        super(StandaloneContext, self).__init__(path=path, params=params, plugin_id=plugin_id)
        self._data_dir = data_dir or os.path.join(os.getcwd(), 'data')
        os.makedirs(self._data_dir, exist_ok=True)
        self._settings = StandaloneSettings(config_path=config_file)
        self._ui = StandaloneUI()
        self._playlist_player = DummyPlaylistPlayer()
        self._video_codecs = list(video_codecs) if video_codecs is not None else None

    def get_settings(self, refresh=False):
        if refresh:
            self._settings.load()
        return self._settings

    def get_ui(self):
        return self._ui

    def get_playlist_player(self, playlist_type=None):
        return self._playlist_player

    def get_data_path(self, create=True):
        if create:
            os.makedirs(self._data_dir, exist_ok=True)
        return self._data_dir

    def reload_access_manager(self):
        self._access_manager = AccessManager(context=self)
        return self._access_manager

    def reload_api_store(self):
        self._api_store = APIKeyStore(context=self)
        return self._api_store

    def localize(self, text_id, *args, **kwargs):
        if isinstance(text_id, int):
            return str(text_id)
        if args or kwargs:
            try:
                return text_id.format(*args, **kwargs)
            except Exception:
                return text_id
        return str(text_id)

    @staticmethod
    def format_date_short(date_obj, str_format=None):
        str_format = str_format or '%Y-%m-%d'
        return date_obj.strftime(str_format) if date_obj else ''

    @staticmethod
    def format_time(time_obj, str_format=None):
        str_format = str_format or '%H:%M:%S'
        return time_obj.strftime(str_format) if time_obj else ''

    @staticmethod
    def get_language():
        return 'en'

    @classmethod
    def get_language_name(cls, lang_id=None):
        return 'English'

    @classmethod
    def get_player_language(cls):
        return 'en'

    @classmethod
    def get_subtitle_language(cls):
        return 'en'

    def use_inputstream_adaptive(self, prompt=False):
        return '21.5.0'

    def inputstream_adaptive_capabilities(self, capability=None):
        if capability:
            if self._video_codecs is not None:
                return capability in self.inputstream_adaptive_capabilities()
            return True
        caps = {
            'drm', 'live', 'timeshift', 'vtt', 'ttml', 'config_prop',
            'manifest_config_prop', 'vorbis', 'opus', 'mp4a', 'ac-3',
            'ec-3', 'dts'
        }
        if self._video_codecs is not None:
            for c in self._video_codecs:
                caps.add(c)
                if c == 'vp9':
                    caps.add('vp9.2')
        else:
            caps.update(['avc1', 'av01', 'vp9', 'vp9.2'])
        return frozenset(caps)

    @staticmethod
    def inputstream_adaptive_auto_stream_selection():
        return True

    has_ipc = False

    def ipc_exec(self, action, data=None, timeout=5, payload=None, raise_exc=False):
        return False

    def send_notification(self, action, data=None):
        pass

    def tear_down(self):
        pass
