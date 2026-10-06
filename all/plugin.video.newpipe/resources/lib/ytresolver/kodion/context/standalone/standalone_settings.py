# -*- coding: utf-8 -*-
"""
    Standalone Settings implementation (JSON file backed) for ytresolver
"""
from __future__ import absolute_import, division, unicode_literals

import json
import os
from ...settings.abstract_settings import AbstractSettings


class StandaloneSettings(AbstractSettings):
    def __init__(self, config_path=None):
        super(StandaloneSettings, self).__init__()
        self._config_path = config_path or os.path.join(os.getcwd(), 'config.json')
        self._store = {}
        self.load()

    def load(self):
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._store = json.load(f)
            except Exception:
                self._store = {}

    def save(self):
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._store, f, indent=2)
        except Exception:
            pass

    DEFAULT_SETTINGS = {
        'kodion.video.quality.isa': True,
        'kodion.mpd.videos': True,
        'kodion.mpd.quality.selection': 4,
        'kodion.video.quality': 1080,
        'kodion.support.alternative_player': True,
        'kodion.video.quality.mpd': 4,
    }

    @classmethod
    def flush(cls, xbmc_addon=None):
        pass

    def get_bool(self, setting, default=False, echo_level=2):
        if setting in self.DEFAULT_SETTINGS and default is False:
            default = self.DEFAULT_SETTINGS[setting]
        val = self._store.get(setting, default)
        if isinstance(val, str):
            return val.lower() in ('true', '1', 'yes')
        return bool(val)

    def set_bool(self, setting, value, echo_level=2):
        self._store[setting] = bool(value)
        self.save()
        return self._store[setting]

    def get_int(self, setting, default=-1, converter=None, echo_level=2):
        if setting in self.DEFAULT_SETTINGS and default == -1:
            default = self.DEFAULT_SETTINGS[setting]
        val = self._store.get(setting, default)
        try:
            val = int(val)
        except (ValueError, TypeError):
            val = default
        if converter:
            val = converter(val)
        return val

    def set_int(self, setting, value, echo_level=2):
        try:
            self._store[setting] = int(value)
        except (ValueError, TypeError):
            pass
        self.save()
        return self._store.get(setting, value)

    def get_string(self, setting, default='', echo_level=2):
        val = self._store.get(setting, default)
        return str(val) if val is not None else default

    def set_string(self, setting, value, echo_level=2):
        self._store[setting] = str(value)
        self.save()
        return self._store[setting]

    def get_string_list(self, setting, default=None, echo_level=2):
        if default is None:
            default = []
        val = self._store.get(setting, default)
        if isinstance(val, list):
            return [str(v) for v in val]
        return default

    def set_string_list(self, setting, value, echo_level=2):
        if isinstance(value, (list, tuple)):
            self._store[setting] = [str(v) for v in value]
        self.save()
        return self._store.get(setting, value)

    def open_settings(self):
        pass
