"""Is the release still on the provider?

STAT asks the server "do you have article X" without downloading anything, so
this costs no indexer quota and no bandwidth. Articles that are *gone* are the
slow ones to ask about (the server looks them up and answers 430), so the check
asks for the first article alone first: if that one is missing the release
cannot be opened at all and there is no point asking more.
"""

import json
import os
import threading
import time

from . import config, nntp, nzb

OK_TTL = 12 * 3600
DEAD_TTL = 24 * 3600
FIRST_SAMPLE = 1
SAMPLES = 24
_LOCK = threading.Lock()


def _load():
    path = config.data_file('usenet_health.json')
    if not path:
        return {}
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    path = config.data_file('usenet_health.json')
    if not path:
        return
    now = time.time()
    kept = dict((key, value) for key, value in data.items()
                if now - value.get('at', 0) < (DEAD_TTL if value.get('status') == 'dead' else OK_TTL))
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(kept, handle)
        os.replace(temp, path)
    except Exception:
        pass


def cached(key):
    with _LOCK:
        value = _load().get(key)
    if not value:
        return None
    ttl = DEAD_TTL if value.get('status') == 'dead' else OK_TTL
    if time.time() - value.get('at', 0) > ttl:
        return None
    return value


def remember(key, verdict):
    with _LOCK:
        data = _load()
        data[key] = dict(verdict, at=time.time())
        _save(data)


def _sample(segments, count):
    total = len(segments)
    if total <= count:
        return list(segments)
    step = (total - 1) / float(max(1, count - 1))
    picked = sorted(set(int(round(index * step)) for index in range(count)))
    return [segments[index] for index in picked]


def check(files, provider, deep=SAMPLES):
    """{'status': ok|partial|dead|empty, 'pct': int, 'checked': n}."""
    media, kind = nzb.pick_media(files)
    if media is None:
        return {'status': 'empty', 'pct': 0, 'checked': 0}
    segments = [item[2] for item in media.segments]
    if kind == 'rar':
        volumes = nzb.rar_volumes(files)
        if len(volumes) > 1:
            segments = [item[2] for volume in volumes for item in volume.segments]
    if not segments:
        return {'status': 'empty', 'pct': 0, 'checked': 0}

    connection = nntp.Connection(provider['host'], provider['port'], provider.get('user', ''),
                                 provider.get('password', ''), provider.get('ssl', True),
                                 provider.get('timeout') or 20)
    try:
        first = connection.stat_many(segments[:FIRST_SAMPLE])
        if first and first[0][1] != nntp.OK_STAT:
            return {'status': 'dead', 'pct': 0, 'checked': 1}
        more = _sample(segments, deep)
        codes = [code for _, code in connection.stat_many(more)]
    finally:
        connection.close()
    if not codes:
        return {'status': 'dead', 'pct': 0, 'checked': 1}
    good = sum(1 for code in codes if code == nntp.OK_STAT)
    pct = int(round(100.0 * good / len(codes)))
    return {'status': 'ok' if good == len(codes) else 'partial', 'pct': pct, 'checked': len(codes)}


def check_cached(key, files, provider, deep=SAMPLES):
    verdict = cached(key)
    if verdict is not None:
        return verdict
    try:
        verdict = check(files, provider, deep)
    except Exception as exc:
        return {'status': 'unknown', 'pct': 0, 'checked': 0, 'reason': str(exc)[:80]}
    remember(key, verdict)
    return verdict
