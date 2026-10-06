# -*- coding: utf-8 -*-
"""
    Standalone UI implementation (Headless/No-OP) for ytresolver
"""
from __future__ import absolute_import, division, unicode_literals

from ...ui.abstract_context_ui import AbstractContextUI
from ...logging import getLogger

class DummyProgressDialog(object):
    def __init__(self, heading, message=''):
        self.heading = heading
        self.message = message
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def reset_total(self, total):
        pass
    def update(self, steps=1):
        pass
    def is_canceled(self):
        return False


class StandaloneUI(AbstractContextUI):
    log = getLogger(__name__)

    def __init__(self):
        super(StandaloneUI, self).__init__()
        self._properties = {}

    def create_progress_dialog(self, heading, message='', background=False, message_template=None):
        return DummyProgressDialog(heading, message)

    @staticmethod
    def on_keyboard_input(title, default='', hidden=False):
        return default

    @staticmethod
    def on_numeric_input(title, default=''):
        return default

    @staticmethod
    def on_yes_no_input(title, text, nolabel='', yeslabel=''):
        return True

    @staticmethod
    def on_ok(title, text):
        pass

    def on_remove_content(self, name):
        return True

    def on_delete_content(self, name):
        return True

    def on_clear_content(self, name):
        return True

    @staticmethod
    def on_select(title, items=None, preselect=-1, use_details=False):
        return 0 if items else -1

    def show_notification(self, message, header='', image_uri='', time_ms=5000, audible=True):
        self.log.info("[Notification] %s: %s", header, message)

    @staticmethod
    def on_busy():
        pass

    def refresh_container(self, force=False, stacklevel=None):
        pass

    def focus_container(self, container_id=None, position=None):
        pass

    @staticmethod
    def get_infobool(name):
        return False

    @staticmethod
    def get_infolabel(name):
        return ""

    def get_container(self, container_type=True, check_ready=False, stacklevel=None):
        return {"id": 0, "path": "", "is_plugin": False}

    @classmethod
    def get_container_id(cls, container_type=True):
        return 0

    @classmethod
    def get_container_bool(cls, name, container_id=True, strict=True, stacklevel=None):
        return False

    @classmethod
    def get_container_info(cls, name, container_id=True, stacklevel=None):
        return ""

    @classmethod
    def get_listitem_info(cls, name, container_id=True, stacklevel=None):
        return ""

    @classmethod
    def get_listitem_property(cls, name, container_id=True, stacklevel=None):
        return ""

    def get_property(self, name, raw=False, process=None, default=None, as_bool=False):
        val = self._properties.get(name, default)
        if as_bool and isinstance(val, str):
            return val.lower() in ('true', '1')
        return val

    def set_property(self, name, value=True, raw=False, process=None, log_redact=False):
        if process:
            value = process(value)
        self._properties[name] = value
        return value

    def clear_property(self, name, raw=False):
        if name in self._properties:
            del self._properties[name]
        return True

    def pop_property(self, name, raw=False, process=None, default=None, as_bool=False):
        val = self.get_property(name, raw=raw, process=process, default=default, as_bool=as_bool)
        self.clear_property(name, raw=raw)
        return val

    def busy_dialog_active(self):
        return False
