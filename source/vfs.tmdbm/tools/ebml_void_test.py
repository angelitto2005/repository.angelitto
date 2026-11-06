"""Build EBML Void and zero-filled variants of a Matroska file and play them in Kodi."""

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'void-test')
BASE = os.path.join(WORK, 'base.mkv')
LOG = r'C:\Users\Angelitto\AppData\Roaming\Kodi\kodi.log'
JSONRPC = 'http://127.0.0.1:8080/jsonrpc'

SEGMENT = bytes.fromhex('18538067')
CLUSTER = bytes.fromhex('1f43b675')
TIMECODE = b'\xe7'
SIMPLE = b'\xa3'
GROUP = b'\xa0'


def id_length(first):
    if first >= 0x80:
        return 1
    if first >= 0x40:
        return 2
    if first >= 0x20:
        return 3
    return 4


def read_size(data, pos):
    first = data[pos]
    length = 1
    mask = 0x80
    while length <= 8 and not first & mask:
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError('bad size at %d' % pos)
    value = first & (mask - 1)
    for index in range(1, length):
        value = (value << 8) | data[pos + index]
    if value == (1 << (7 * length)) - 1:
        return None, length
    return value, length


def elements(data, start, end):
    pos = start
    while pos < end:
        length = id_length(data[pos])
        ident = data[pos:pos + length]
        size, extra = read_size(data, pos + length)
        body = pos + length + extra
        total = end - pos if size is None else size + length + extra
        if total <= 0 or pos + total > end:
            raise ValueError('element overruns at %d' % pos)
        yield ident, pos, body, total, size
        pos += total


def segment(data):
    pos = 0
    while pos < len(data):
        length = id_length(data[pos])
        ident = data[pos:pos + length]
        size, extra = read_size(data, pos + length)
        body = pos + length + extra
        if ident == SEGMENT:
            return body, len(data) if size is None else min(len(data), body + size)
        if size is None:
            break
        pos = body + size
    raise SystemExit('no Segment in %s' % BASE)


def clusters(data):
    start, end = segment(data)
    found = []
    for ident, pos, body, total, size in elements(data, start, end):
        if ident != CLUSTER:
            continue
        timecode = None
        children = []
        for cid, cpos, cbody, ctotal, csize in elements(data, body, pos + total):
            children.append((cid, cpos, ctotal))
            if cid == TIMECODE and timecode is None and csize is not None:
                timecode = int.from_bytes(data[cbody:cbody + csize], 'big')
        found.append({'start': pos, 'total': total, 'timecode': timecode, 'children': children})
    return found


def make_void(total):
    for length in range(1, 9):
        size = total - 1 - length
        if 0 <= size <= (1 << (7 * length)) - 2:
            raw = bytearray(size.to_bytes(length, 'big'))
            raw[0] |= 0x80 >> (length - 1)
            filler = b'\xec' + bytes(raw) + b'\x00' * size
            if len(filler) != total:
                raise ValueError('void length mismatch')
            parsed, used = read_size(filler, 1)
            if parsed != size or used != length:
                raise ValueError('void self-check failed')
            return filler
    raise ValueError('cannot void %d bytes' % total)


def build():
    data = open(BASE, 'rb').read()
    found = clusters(data)
    target = min(found, key=lambda item: abs((item['timecode'] or 0) - 8000))
    blocks = [index for index, child in enumerate(target['children']) if child[0] in (SIMPLE, GROUP)]
    print('clusters=%d target_timecode=%s start=%d size=%d children=%d blocks=%d'
          % (len(found), target['timecode'], target['start'], target['total'],
             len(target['children']), len(blocks)))
    if len(blocks) < 3:
        raise SystemExit('target cluster has too few blocks')
    print('children: %s' % [(cid.hex(), cpos, ctotal) for cid, cpos, ctotal in target['children'][:10]])

    cluster_end = target['start'] + target['total']
    tail_start = target['children'][blocks[2]][1]
    child_start = target['children'][blocks[0]][1]
    child_end = target['children'][blocks[2]][1]
    index = found.index(target)
    span = found[index:index + 5]
    if len(span) == 5:
        big_start = span[0]['start']
        big_end = span[-1]['start'] + span[-1]['total']
    else:
        big_start = big_end = target['start']

    regions = {
        'void_top': (target['start'], target['total'], make_void(target['total'])),
        'zero_top': (target['start'], target['total'], b'\x00' * target['total']),
        'void_tail': (tail_start, cluster_end - tail_start, make_void(cluster_end - tail_start)),
        'zero_tail': (tail_start, cluster_end - tail_start, b'\x00' * (cluster_end - tail_start)),
        'void_child': (child_start, child_end - child_start, make_void(child_end - child_start)),
        'zero_child': (child_start, child_end - child_start, b'\x00' * (child_end - child_start)),
        'void_big': (big_start, big_end - big_start, make_void(big_end - big_start)),
        'zero_big': (big_start, big_end - big_start, b'\x00' * (big_end - big_start)),
    }
    manifest = {'base': 12.0}
    limit = min(18.0, (target['timecode'] or 0) / 1000.0 + 3.0)
    for name, (start, total, filler) in regions.items():
        if len(filler) != total:
            raise SystemExit('%s filler length mismatch' % name)
        path = os.path.join(WORK, name + '.mkv')
        with open(path, 'wb') as handle:
            handle.write(data[:start])
            handle.write(filler)
            handle.write(data[start + total:])
        manifest[name] = limit
        print('%s: %d bytes at %d, limit %.1fs' % (name, total, start, limit))
    with open(os.path.join(WORK, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=1)
    return manifest


def call(method, params=None, timeout=15):
    payload = json.dumps({'jsonrpc': '2.0', 'method': method,
                          'params': params or {}, 'id': 1}).encode()
    request = urllib.request.Request(JSONRPC, payload, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def seconds(value):
    return value['hours'] * 3600 + value['minutes'] * 60 + value['seconds'] + value['milliseconds'] / 1000.0


def stop_all():
    try:
        for player in call('Player.GetActivePlayers')['result']:
            call('Player.Stop', {'playerid': player['playerid']})
    except Exception:
        pass


def play(path, limit):
    stop_all()
    time.sleep(1.2)
    try:
        offset = os.path.getsize(LOG)
    except OSError:
        offset = 0
    response = None
    for attempt in range(3):
        response = call('Player.Open', {'item': {'file': path}})
        if 'error' not in response:
            break
        time.sleep(1.5)
    if response is None or 'error' in response:
        print('%-11s open failed: %s' % (os.path.basename(path), response))
        return {'file': os.path.basename(path), 'started': False, 'best': 0.0,
                'reason': 'open failed', 'errors': []}
    opened = time.time()
    best = 0.0
    started = False
    reason = 'timeout'
    while time.time() - opened < 25:
        time.sleep(0.4)
        players = call('Player.GetActivePlayers')['result']
        if not players:
            if started:
                reason = 'stopped'
                break
            if time.time() - opened > 8:
                reason = 'did not start'
                break
            continue
        started = True
        props = call('Player.GetProperties', {'playerid': players[0]['playerid'],
                                              'properties': ['time', 'speed', 'percentage']})['result']
        current = seconds(props['time'])
        best = max(best, current)
        if current >= limit:
            reason = 'passed'
            break
    stop_all()
    time.sleep(0.8)
    text = ''
    try:
        with open(LOG, 'rb') as handle:
            handle.seek(offset)
            text = handle.read().decode('utf-8', 'replace')
    except OSError:
        pass
    errors = [line.strip() for line in text.splitlines()
              if 'matroska' in line.lower() or 'EBML' in line or 'emux' in line
              or 'rror' in line or 'ailed' in line]
    print('%-11s started=%s best=%.2fs reason=%-12s errors=%d'
          % (os.path.basename(path), started, best, reason, len(errors)))
    for line in errors[:10]:
        print('    ' + line)
    return {'file': os.path.basename(path), 'started': started, 'best': best,
            'reason': reason, 'errors': errors}


def main():
    if not os.path.exists(BASE):
        raise SystemExit('missing base file: %s' % BASE)
    manifest = build()
    if 'play' not in sys.argv:
        return
    results = []
    order = [name for name in sys.argv[1:] if name != 'play'] or [
        'base', 'void_top', 'zero_top', 'void_tail', 'zero_tail',
        'void_child', 'zero_child', 'void_big', 'zero_big']
    for name in order:
        path = BASE if name == 'base' else os.path.join(WORK, name + '.mkv')
        results.append(play(path, manifest[name]))
    print()
    for item in results:
        print('%-11s %-12s %.2fs' % (item['file'], item['reason'], item['best']))


if __name__ == '__main__':
    main()
