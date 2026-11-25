"""Is the release still on the provider?

STAT asks the server "do you have article X" without downloading anything, so
this costs no indexer quota and no bandwidth. The check uses several
connections at once, stops after HEALTH_SECONDS and asks the backup provider
for whatever the primary misses. Articles that are gone are the slow ones to
ask about (the server looks them up and answers 430), so the first article is
asked first: if it is missing everywhere the release cannot be opened at all.
"""

import json
import os
import re
import threading
import time

from . import config, nntp, nzb, tracks, yenc

OK_TTL = 12 * 3600
DEAD_TTL = 24 * 3600
PARTIAL_TTL = 30 * 60
DOVI_TTL = 14 * 86400
DOVI_UNKNOWN_TTL = 86400
HEALTH_SECONDS = 20
HEALTH_WORKERS = 8
HEALTH_BACKUP_WORKERS = 4
HEALTH_CHUNK = 500
SAMPLE = 40
SAMPLE_GONE = 0.10
FILL_SHARE = 0.02
FILL_RUN = 4
DOVI_LIMIT = 3
DOVI_BYTES = 3 * 1024 * 1024
DOVI_MORE = 12 * 1024 * 1024

_LOCK = threading.Lock()


def _hlog(message):
    try:
        import xbmc
        xbmc.log('[TMDb Movies] [UsenetHealth] ' + str(message), xbmc.LOGINFO)
    except Exception:
        pass


def _ttl(key, value):
    if value.get('status') == 'dead':
        return DEAD_TTL
    if value.get('status') == 'partial':
        return PARTIAL_TTL
    if str(key).startswith('dovi:'):
        return DOVI_TTL if value.get('dovi') else DOVI_UNKNOWN_TTL
    return OK_TTL


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
                if now - value.get('at', 0) < _ttl(key, value))
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(kept, handle)
        os.replace(temp, path)
    except Exception:
        pass


def cached(key):
    if not key:
        return None
    with _LOCK:
        value = _load().get(key)
    if not value:
        return None
    if time.time() - value.get('at', 0) > _ttl(key, value):
        return None
    return value


def remember(key, verdict):
    if not key:
        return
    with _LOCK:
        data = _load()
        data[key] = dict(verdict, at=time.time())
        _save(data)


def media_ids(files, media, kind):
    """The articles of the chosen release: one video, or every archive volume."""
    if media is None or kind not in ('video', 'rar', '7z'):
        return []
    if kind == 'video':
        segments = media.segments
    elif kind == 'rar':
        segments = [item for volume in nzb.rar_volumes(files, media)
                    for item in volume.segments]
    else:
        segments = [item for volume in nzb.seven_volumes(files, media)
                    for item in volume.segments]
    return [item[2] for item in segments]


def is_dv(stream):
    """Does the release name or its tags say Dolby Vision?"""
    info = stream.get('info') if isinstance(stream, dict) else None
    tags = info.get('tags') if isinstance(info, dict) else None
    text = ' '.join([str(stream.get('title') or ''), str(stream.get('name') or '')]
                    + ([str(tag) for tag in tags] if isinstance(tags, (list, tuple)) else []))
    return bool(re.search(r'(?<![A-Za-z0-9])(?:DV|DOVI|DOLBY[ ._-]?VISION|FEL|MEL|P7)(?![A-Za-z0-9])',
                          text, re.I))


def _spread(items, count):
    total = len(items)
    if total <= count:
        return list(items)
    step = (total - 1) / float(max(1, count - 1))
    return [items[int(round(index * step))] for index in range(count)]


def _connection(provider, timeout):
    return nntp.Connection(provider.get('host') or '',
                           int(provider.get('port') or 563),
                           provider.get('user') or '',
                           provider.get('password') or '',
                           provider.get('ssl', True), timeout)


def _first_state(message_id, providers, deadline):
    missing = False
    unanswered = False
    for provider in providers:
        left = deadline - time.time()
        if left <= 0:
            unanswered = True
            break
        connection = None
        try:
            connection = _connection(provider, max(1, min(10, left)))
            code = connection.stat(message_id)
        except Exception:
            unanswered = True
            continue
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        if code == nntp.OK_STAT:
            return 'present'
        if code in nntp.MISSING_CODES:
            missing = True
        else:
            unanswered = True
    return 'unknown' if unanswered else ('missing' if missing else 'unknown')


def _stat_set(provider, ids, workers, deadline, stop):
    """Check ids over several connections; returns (seen, missing, errors)."""
    chunks = [ids[at:at + HEALTH_CHUNK] for at in range(0, len(ids), HEALTH_CHUNK)]
    if not chunks:
        return set(), set(), set()
    queue = list(chunks)
    lock = threading.Lock()
    seen, missing, errors = set(), set(), set()

    def worker():
        connection = None
        try:
            while True:
                if stop and stop():
                    return
                left = deadline - time.time()
                if left <= 0:
                    return
                with lock:
                    if not queue:
                        return
                    chunk = queue.pop(0)
                try:
                    if connection is None:
                        connection = _connection(provider, max(1, min(10, left)))
                    replies = connection.stat_many(chunk)
                except Exception:
                    with lock:
                        queue.insert(0, chunk)
                    try:
                        if connection is not None:
                            connection.close()
                    except Exception:
                        pass
                    connection = None
                    time.sleep(0.1)
                    continue
                with lock:
                    for message_id, code in replies:
                        seen.add(message_id)
                        if code in nntp.MISSING_CODES:
                            missing.add(message_id)
                        elif code != nntp.OK_STAT:
                            errors.add(message_id)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    limit = max(1, int(provider.get('connections') or workers))
    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, min(workers, limit, len(chunks))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.1, deadline - time.time() + 1.0))
    with lock:
        return set(seen), set(missing), set(errors)


def _check_on(providers, ids, workers, deadline, stop):
    """Check on the primary providers first, then the missing ones on the backups."""
    ids = list(ids)
    seen, missing, errors = set(), set(), set()
    primaries = [provider for provider in providers if not provider.get('backup')]
    backups = [provider for provider in providers if provider.get('backup')]
    for provider in primaries:
        if stop and stop():
            return seen, missing, errors
        todo = [item for item in ids if item not in seen]
        if not todo or deadline - time.time() <= 0:
            break
        found, gone, bad = _stat_set(provider, todo, workers, deadline, stop)
        seen |= found
        missing |= gone
        errors |= bad
    if missing and backups:
        todo = sorted(missing)
        for provider in backups:
            if stop and stop():
                break
            if deadline - time.time() <= 0:
                break
            found, gone, bad = _stat_set(provider, todo, HEALTH_BACKUP_WORKERS,
                                         deadline, stop)
            for message_id in todo:
                if message_id in found and message_id not in gone and message_id not in bad:
                    missing.discard(message_id)
                    errors.discard(message_id)
            seen |= found
            errors |= bad
            missing |= gone
            todo = sorted(missing)
            if not todo:
                break
    return seen, missing, errors


def _longest_run(ids, missing):
    index = dict((message_id, number) for number, message_id in enumerate(ids))
    spots = sorted(index[message_id] for message_id in missing if message_id in index)
    run = longest = 0
    for number, spot in enumerate(spots):
        run = run + 1 if number and spot == spots[number - 1] + 1 else 1
        longest = max(longest, run)
    return longest


def _result(total, ids, seen, missing, errors, complete, started, status=None):
    checked = len(seen)
    gone = len(missing)
    present = max(0, checked - gone - len(errors))
    pct = int(100.0 * present / checked) if checked else 0
    longest = _longest_run(ids, missing)
    if status is None:
        if not checked:
            status = 'unknown'
        elif not complete and gone == 0:
            status = 'partial'
        elif gone <= max(1, int(total * FILL_SHARE)) and longest <= FILL_RUN:
            status = 'ok' if gone == 0 and complete else 'partial'
        else:
            status = 'bad'
    return {'status': status, 'pct': pct, 'checked': checked, 'total': total,
            'present': present, 'gone': gone, 'errors': len(errors),
            'longest': longest, 'complete': complete,
            'seconds': round(time.time() - started, 1)}


def check_ids(ids, providers, seconds=HEALTH_SECONDS, key='', stop=None,
              full=True):
    """An availability check for a release, from a list of article ids.

    full=False stops after the first article and the spread sample: a cold
    play does not wait for every article, deeper gaps are left to the player.
    """
    ids = [str(item).strip().strip('<>') for item in ids if item]
    total = len(ids)
    if not total:
        return {'status': 'empty', 'pct': 0, 'checked': 0, 'total': 0,
                'present': 0, 'gone': 0, 'errors': 0, 'longest': 0,
                'complete': True, 'seconds': 0.0}
    known = cached(key)
    if known is not None:
        return known
    providers = [provider for provider in providers or [] if provider]
    if not providers:
        return {'status': 'unknown', 'pct': 0, 'checked': 0, 'total': total,
                'present': 0, 'gone': 0, 'errors': 0, 'longest': 0,
                'complete': False, 'seconds': 0.0}
    started = time.time()
    deadline = started + max(3, int(seconds or HEALTH_SECONDS))

    state = _first_state(ids[0], providers, deadline)
    if state == 'missing':
        result = _result(total, ids, {ids[0]}, {ids[0]}, set(), False, started, 'dead')
        remember(key, result)
        return result
    if state == 'unknown':
        return {'status': 'unknown', 'pct': 0, 'checked': 0, 'total': total,
                'present': 0, 'gone': 0, 'errors': 0, 'longest': 0,
                'complete': False, 'seconds': round(time.time() - started, 1)}

    sample = _spread(ids, SAMPLE)
    seen, missing, errors = _check_on(providers, sample, 1, deadline, stop)
    if len(missing) > max(2, int(len(sample) * SAMPLE_GONE)):
        result = _result(total, ids, seen, missing, errors, False, started, 'dead')
        remember(key, result)
        return result
    if stop and stop():
        return {'status': 'stopped', 'pct': 0, 'checked': len(seen), 'total': total,
                'present': 0, 'gone': len(missing), 'errors': len(errors),
                'longest': 0, 'complete': False,
                'seconds': round(time.time() - started, 1)}
    if not full:
        complete = len(seen) >= total
        result = _result(total, ids, seen, missing, errors, complete, started)
        if complete or result['status'] in ('dead', 'bad'):
            remember(key, result)
        return result

    seen, missing, errors = _check_on(providers, ids, HEALTH_WORKERS, deadline, stop)
    if stop and stop():
        return {'status': 'stopped', 'pct': 0, 'checked': len(seen), 'total': total,
                'present': 0, 'gone': len(missing), 'errors': len(errors),
                'longest': 0, 'complete': False,
                'seconds': round(time.time() - started, 1)}
    complete = len(seen) >= total
    result = _result(total, ids, seen, missing, errors, complete, started)
    if complete or result['status'] in ('bad', 'partial'):
        remember(key, result)
    return result


def _read_articles(segments, providers, limit):
    """The first `limit` decoded bytes of a file, from one provider."""
    for provider in providers:
        connection = None
        try:
            connection = _connection(provider, 10)
            out, total = [], 0
            for segment in segments:
                raw = connection.body(segment[2])
                data = yenc.decode(raw)['data']
                if not data:
                    continue
                out.append(data)
                total += len(data)
                if total >= limit:
                    break
            return b''.join(out)
        except Exception:
            continue
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
    return b''


def _dovi_probe(files, media, kind, providers):
    """'fel', 'mel', 'p7' or '' from the first megabytes of the video."""
    try:
        offset = 0
        if kind == 'video':
            segments = media.segments
            data = _read_articles(segments, providers, DOVI_BYTES)
        elif kind == 'rar':
            volumes = nzb.rar_volumes(files, media)
            if not volumes:
                return ''
            segments = volumes[0].segments
            head = _read_articles(segments, providers, DOVI_BYTES)
            layout = nzb.rar_layout(head)
            offset = int(layout.get('offset') or 0)
            if offset >= len(head):
                return ''
            data = _read_articles(segments, providers, DOVI_MORE + offset)[offset:]
        else:
            return ''
        if data[:4] != b'\x1a\x45\xdf\xa3':
            return ''
        found = tracks.read(data)
        if (not found or not found.get('video')) and len(data) < DOVI_MORE:
            if kind == 'video':
                data = _read_articles(segments, providers, DOVI_MORE)
            else:
                data = _read_articles(segments, providers, DOVI_MORE + offset)[offset:]
            found = tracks.read(data)
        if not found or found.get('dv') != 7 or not found.get('video'):
            return ''
        number, nal_size = found['video']
        label = tracks.dolby(data, number, nal_size, found['after'])
        if not label and len(data) < DOVI_MORE:
            if kind == 'video':
                data = _read_articles(segments, providers, DOVI_MORE)
            else:
                data = _read_articles(segments, providers, DOVI_MORE + offset)[offset:]
            label = tracks.dolby(data, number, nal_size, found['after'])
        return label or 'p7'
    except Exception:
        return ''


def check_streams(streams, season=None, episode=None, limit=None, seconds=10,
                  articles=True, dovi=True, dovi_limit=DOVI_LIMIT,
                  progress=None, stop=None):
    """Check or label the Usenet releases of a result list.

    Only releases whose NZB is already saved (played before, warmed, or checked
    earlier) are touched: a list must never spend indexer grabs."""
    if not streams:
        return 0
    try:
        limit = max(1, int(limit or len(streams)))
    except Exception:
        limit = len(streams)
    providers = config.primary_providers() + config.backup_providers()
    if not providers:
        return 0
    seen = set()
    candidates = []
    for stream in streams:
        meta = stream.get('usenet') if isinstance(stream, dict) else None
        if not isinstance(meta, dict):
            continue
        url = str(meta.get('nzb_url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        candidates.append((stream, meta, url))
        if len(candidates) >= limit:
            break
    done = 0
    dovi_done = 0
    for stream, meta, url in candidates:
        if stop and stop():
            break
        _hlog('checking %s' % str(stream.get('name') or '')[:90])
        dv_stream = bool(dovi and is_dv(stream))
        if not articles and not dv_stream:
            continue
        result = {'status': 'unknown'}
        try:
            key = config.nzb_key(url)
            dovi_key = 'dovi:' + key
            known = cached(key) if articles else None
            known_dovi = cached(dovi_key) if dv_stream else None
            if known is not None:
                result = known
            if known_dovi is not None:
                result = dict(result, dovi=known_dovi.get('dovi') or '')
            need_check = bool(articles and known is None)
            dovi_wanted = bool(dv_stream and dovi_done < dovi_limit and
                               known_dovi is None)
            need_dovi = dovi_wanted
            path = config.nzb_path(key)
            saved = bool(path and os.path.exists(path))
            if (need_check or need_dovi) and not saved:
                _hlog('skip %s: NZB not saved (no indexer grab)' %
                      str(stream.get('name') or '')[:80])
            if (need_check or need_dovi) and saved:
                with open(path, 'rb') as handle:
                    data = handle.read()
                files = nzb.parse(data)
                media, kind = nzb.select_media(files, season, episode)
                if need_check:
                    ids = media_ids(files, media, kind)
                    if ids:
                        result = check_ids(ids, providers, seconds=seconds,
                                           key=key, stop=stop)
                        if known_dovi is not None and not result.get('dovi'):
                            result = dict(result,
                                          dovi=known_dovi.get('dovi') or '')
                if need_dovi:
                    label = _dovi_probe(files, media, kind, providers)
                    dovi_done += 1
                    if label:
                        result = dict(result, dovi=label)
                    try:
                        remember(dovi_key, {'status': 'unknown', 'dovi': label})
                    except Exception:
                        pass
        except Exception:
            result = {'status': 'unknown'}
        meta['health'] = result
        done += 1
        if progress:
            try:
                progress(done, len(candidates), stream, result)
            except Exception:
                pass
    return done


def playable(result):
    """A release may play when the gaps the check found are fillable."""
    if not result:
        return True
    return result.get('status') not in ('dead', 'bad')


def summary(result):
    if not result:
        return ''
    status = result.get('status')
    if status == 'dead':
        return 'MISSING'
    if status == 'bad':
        return '%d%% complete' % int(result.get('pct') or 0)
    if status == 'ok':
        return 'complete'
    if status == 'partial':
        return '%d%% complete' % int(result.get('pct') or 0)
    if status == 'stopped':
        return ''
    return 'not checked'
