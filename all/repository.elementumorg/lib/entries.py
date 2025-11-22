import json
import os
import sys
from collections import OrderedDict
from zipfile import ZipFile

import xbmcgui

from lib.kodi import ADDON_DATA, ADDON_NAME, translate, notification, get_repository_port, translatePath
from lib.platform.core import PLATFORM, dump_platform
from lib.repository import validate_schema
from lib.utils import str_to_unicode, request

if not os.path.exists(ADDON_DATA):
    os.makedirs(ADDON_DATA)

ENTRIES_PATH = os.path.join(ADDON_DATA, "entries.json")
if not os.path.exists(ENTRIES_PATH):
    with open(ENTRIES_PATH, "w") as _f:
        _f.write("[]")


class Entries(object):
    def __init__(self, path=ENTRIES_PATH):
        self._path = path
        self._data = OrderedDict()
        if os.path.exists(self._path):
            self.load()

    def clear(self):
        self._data.clear()

    def length(self):
        return len(self._data)

    @property
    def ids(self):
        return list(self._data)

    def remove(self, addon_id):
        self._data.pop(addon_id)

    def load(self):
        with open(self._path) as f:
            self.add_entries_from_data(json.load(f))

    def save(self):
        with open(self._path, "w") as f:
            json.dump(list(self._data.values()), f)

    def add_entries_from_file(self, path):
        if path.endswith(".zip"):
            with ZipFile(path) as zip_file:
                for name in zip_file.namelist():
                    if name.endswith(".json"):
                        self.add_entries_from_data(json.loads(zip_file.read(name)))
        elif path.endswith(".json"):
            with open(path) as f:
                self.add_entries_from_data(json.load(f))
        else:
            raise ValueError("Unknown file extension. Supported extensions are .json and .zip")

    def add_entries_from_data(self, data):
        validate_schema(data)
        for entry in data:
            self._data[entry["id"]] = entry


def update_repository(notify=False):
    with request("http://127.0.0.1:{}/update".format(get_repository_port()), timeout=2) as r:
        if notify:
            notification(translate(30013 if r.status_code == 200 else 30014))


def import_entries():
    path = str_to_unicode(translatePath(xbmcgui.Dialog().browse(1, translate(30002), "files", ".json|.zip")))
    if path:
        entries = Entries()
        entries.add_entries_from_file(path)
        entries.save()
        update_repository()
        notification(translate(30012))


def delete_entries():
    entries = Entries()
    if entries.length() == 0:
        notification(translate(30010))
    else:
        selected = xbmcgui.Dialog().multiselect(translate(30003), entries.ids)
        if selected:
            for index in selected:
                entries.remove(index)
            entries.save()
            update_repository()
            notification(translate(30011))


def clear_entries():
    entries = Entries()
    if entries.length() == 0:
        notification(translate(30010))
    else:
        entries.clear()
        entries.save()
        update_repository()
        notification(translate(30011))


def about():
    xbmcgui.Dialog().textviewer(translate(30006), "[B]{}[/B]\n\nDetected platform: {}\n\n{}".format(
        ADDON_NAME, PLATFORM.name(), dump_platform()))


def run():
    methods = ("import_entries", "delete_entries", "clear_entries", "update_repository", "about")
    if len(sys.argv) == 1:
        selected = xbmcgui.Dialog().select(ADDON_NAME, [translate(30002 + i) for i in range(len(methods))])
    elif len(sys.argv) == 2:
        method = sys.argv[1]
        try:
            selected = methods.index(method)
        except ValueError:
            raise NotImplementedError("Unknown method '{}'".format(method))
    else:
        raise NotImplementedError("Unknown arguments")

    if selected == 0:
        import_entries()
    elif selected == 1:
        delete_entries()
    elif selected == 2:
        clear_entries()
    elif selected == 3:
        update_repository(True)
    elif selected == 4:
        about()
