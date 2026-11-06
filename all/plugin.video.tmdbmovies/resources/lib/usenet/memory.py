"""What happened to a release the last time it was tried.

The source list is rebuilt on every search, so a release that refused to play
would be offered again and again, and one that played would look identical to a
fresh result. This keeps a small, bounded memory in the profile: a release that
served bytes is PLAYED, one whose articles were gone is UNAVAILABLE.

Failures expire after a week, because a repost of the same title is a different
upload with the same name. Played marks last longer: they are only a hint.
"""

import json
import os
import threading
import time

from . import config

FILE = 'usenet_releases.json'
KEEP = 400
FAIL_TTL = 7 * 86400
PLAYED_TTL = 30 * 86400

_LOCK = threading.Lock()


def _load():
    try:
        with open(config.data_file(FILE), encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    path = config.data_file(FILE)
    if not path:
        return
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except Exception:
        pass


def mark(key, state):
    """Remember 'played' or 'failed' for this NBZ key (md5 of its link)."""
    if not key or state not in ('played', 'failed'):
        return
    now = time.time()
    with _LOCK:
        data = _load()
        data[key] = {'state': state, 'at': now}
        if len(data) > KEEP:
            newest = sorted(data.items(), key=lambda item: item[1].get('at', 0), reverse=True)
            data = dict(newest[:KEEP])
        _save(data)


def state(key):
    """'played', 'failed' or '' - old entries are ignored, not deleted."""
    if not key:
        return ''
    entry = _load().get(key)
    if not isinstance(entry, dict):
        return ''
    kind = entry.get('state') or ''
    try:
        age = time.time() - float(entry.get('at') or 0)
    except Exception:
        return ''
    if kind == 'failed' and age > FAIL_TTL:
        return ''
    if kind == 'played' and age > PLAYED_TTL:
        return ''
    return kind


def forget(key):
    if not key:
        return
    with _LOCK:
        data = _load()
        if data.pop(key, None) is not None:
            _save(data)
