"""Usenet statistics: per day, per provider and per indexer.

The compact storage and counters are adapted from Lucent Video (MIT),
used with permission.

Only counters are kept: no titles, no links, no keys and no account names.
One small JSON file in the add-on profile. Indexer counters are written at
once; provider counters are buffered and flushed once a minute so playback
never waits for the disk. Old days are removed and the file stays under
MAX_BYTES.

Indexer fields: searches, search seconds, failed searches, results, NZBs
fetched, NZBs that could be played and NZBs that could not.
Provider fields: bytes, articles, missing articles, errors, reply count and
reply seconds, busy seconds.
"""

import atexit
import json
import os
import threading
import time

from . import config

FILE = "usenet_stats.json"
KEEP_DAYS = 400
MAX_BYTES = 2 * 1024 * 1024
FLUSH_EVERY = 60

P_FIELDS = ("b", "a", "m", "e", "ln", "ls", "busy")
I_FIELDS = ("s", "ss", "se", "r", "g", "ok", "bad")

_lock = threading.Lock()
_pending = {}
_state = {"flushed": time.time()}


def _log(message):
    try:
        import xbmc
        xbmc.log("[TMDb Movies] [UsenetStats] " + str(message), xbmc.LOGWARNING)
    except Exception:
        pass


def _day(at=None):
    return time.strftime("%Y-%m-%d", time.localtime(at or time.time()))


def _path():
    try:
        return config.data_file(FILE)
    except Exception:
        return ""


def _load():
    path = _path()
    if not path:
        return {"v": 1, "days": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"v": 1, "days": {}}
    if not isinstance(data, dict) or data.get("v") != 1:
        return {"v": 1, "days": {}}
    if not isinstance(data.get("days"), dict):
        data["days"] = {}
    return data


def _save(data):
    path = _path()
    if not path:
        return False
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        temp = path + ".part"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"), sort_keys=True)
        os.replace(temp, path)
        return True
    except Exception as error:
        _log("not saved (%s)" % type(error).__name__)
        return False


def _trim(data):
    days = data.get("days") or {}
    oldest = _day(time.time() - KEEP_DAYS * 86400)
    for day in [item for item in days if item < oldest]:
        del days[day]
    try:
        encoded = json.dumps(data, separators=(",", ":"))
        while len(days) > 1 and len(encoded) > MAX_BYTES:
            del days[min(days)]
            encoded = json.dumps(data, separators=(",", ":"))
    except Exception:
        pass


def _update(change):
    lock_path = (_path() or "") + ".lock"
    lock_file = None
    if lock_path:
        try:
            folder = os.path.dirname(lock_path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            end = time.time() + 3
            while time.time() < end:
                try:
                    lock_file = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    try:
                        if time.time() - os.path.getmtime(lock_path) > 15:
                            os.remove(lock_path)
                            continue
                    except OSError:
                        pass
                    time.sleep(0.05)
                except OSError:
                    break
        except Exception:
            lock_file = None
    try:
        with _lock:
            data = _load()
            days = data.setdefault("days", {})
            change(days)
            _trim(data)
            return _save(data)
    except Exception as error:
        _log("update failed (%s)" % type(error).__name__)
        return False
    finally:
        if lock_file is not None:
            try:
                os.close(lock_file)
                os.remove(lock_path)
            except OSError:
                pass


def _add(bucket, name, values):
    entry = bucket.setdefault(name, {})
    for field, value in values.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number:
            entry[field] = round(entry.get(field, 0) + number, 3)


def provider(host, **values):
    host = str(host or "").strip()
    if not host:
        return
    with _lock:
        entry = _pending.setdefault(host, {})
        for field, value in values.items():
            if field not in P_FIELDS:
                continue
            try:
                entry[field] = entry.get(field, 0) + float(value)
            except (TypeError, ValueError):
                continue
    flush()


def flush(force=False):
    if not force and time.time() - _state["flushed"] < FLUSH_EVERY:
        return
    _state["flushed"] = time.time()
    with _lock:
        pending = dict(_pending)
        _pending.clear()
    if not pending:
        return
    day = _day()

    def change(days):
        bucket = days.setdefault(day, {}).setdefault("p", {})
        for host, values in pending.items():
            _add(bucket, host, values)

    if not _update(change):
        with _lock:
            for host, values in pending.items():
                entry = _pending.setdefault(host, {})
                for field, value in values.items():
                    entry[field] = entry.get(field, 0) + value


def indexer(name, **values):
    name = str(name or "").strip()
    if not name:
        return
    day = _day()

    def change(days):
        _add(days.setdefault(day, {}).setdefault("i", {}), name, values)

    _update(change)


def clear():
    with _lock:
        _pending.clear()

    def change(days):
        days.clear()

    _update(change)


def size():
    path = _path()
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def _vfs_files():
    folder = config.profile_dir() + "usenet-vfs/"
    if not folder or not os.path.isdir(folder):
        return folder, []
    try:
        names = [name for name in os.listdir(folder)
                 if name.startswith("vfs_stats_") and name.endswith(".log")]
    except Exception:
        return folder, []
    return folder, [os.path.join(folder, name) for name in names]


def import_vfs():
    """Merge the provider counters written by vfs.tmdbm, then remove those files."""
    _folder, paths = _vfs_files()
    if not paths:
        return 0
    entries = {}
    imported = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except Exception:
            continue
        valid = bool(lines) and lines[0].strip() == "tmdbm-stats 1"
        day = ""
        hosts = {}
        if valid:
            for line in lines[1:]:
                parts = line.split("\t")
                if not parts:
                    continue
                if parts[0] == "D" and len(parts) >= 2:
                    day = parts[1].strip()
                elif parts[0] == "P" and len(parts) >= 9 and day:
                    host = parts[1].strip()
                    if not host:
                        continue
                    try:
                        values = {"b": int(float(parts[2])),
                                  "a": int(float(parts[3])),
                                  "m": int(float(parts[4])),
                                  "e": int(float(parts[5])),
                                  "ln": int(float(parts[6])),
                                  "ls": float(parts[7]),
                                  "busy": float(parts[8])}
                    except (TypeError, ValueError):
                        continue
                    if any(values.values()):
                        _add(hosts, host, values)
        imported.append(path)
        if len(day) == 10 and day[4] == "-" and day[7] == "-" and hosts:
            bucket = entries.setdefault(day, {})
            for host, fields in hosts.items():
                _add(bucket, host, fields)

    def change(days):
        for day, hosts in entries.items():
            target = days.setdefault(day, {}).setdefault("p", {})
            for host, fields in hosts.items():
                _add(target, host, fields)

    ok = _update(change) if entries else True
    if ok:
        for path in imported:
            try:
                os.remove(path)
            except OSError:
                pass
    return len(imported)


def summary(days_back=30):
    flush(force=True)
    import_vfs()
    data = _load()
    days = data.get("days") or {}
    if days_back:
        first = _day(time.time() - (days_back - 1) * 86400)
        chosen = sorted(day for day in days if day >= first)
        span = [_day(time.time() - number * 86400)
                for number in range(days_back - 1, -1, -1)]
    else:
        chosen = sorted(days)
        span = []
        if chosen:
            start = time.mktime(time.strptime(chosen[0], "%Y-%m-%d"))
            number = 0
            while True:
                day = _day(start + number * 86400 + 3600)
                span.append(day)
                if day >= _day() or number > KEEP_DAYS + 2:
                    break
                number += 1
    providers, indexers = {}, {}
    for day in chosen:
        values = days.get(day) or {}
        for host, fields in (values.get("p") or {}).items():
            _add(providers, host, fields)
        for name, fields in (values.get("i") or {}).items():
            _add(indexers, name, fields)
    per_day = []
    for day in span:
        provider_totals = (days.get(day) or {}).get("p") or {}
        per_day.append((day, sum(float(item.get("b", 0) or 0)
                                 for item in provider_totals.values())))
    totals = {"bytes": sum(item.get("b", 0) for item in providers.values()),
              "searches": sum(item.get("s", 0) for item in indexers.values()),
              "nzbs": sum(item.get("g", 0) for item in indexers.values()),
              "ok": sum(item.get("ok", 0) for item in indexers.values()),
              "bad": sum(item.get("bad", 0) for item in indexers.values())}
    return {"days": per_day, "providers": providers, "indexers": indexers,
            "totals": totals, "storage": size()}


def _flush_exit():
    try:
        flush(force=True)
    except Exception:
        pass


atexit.register(_flush_exit)
