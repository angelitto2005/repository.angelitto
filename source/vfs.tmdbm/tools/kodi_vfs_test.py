"""Play a real file through vfs.tmdbm in a running Kodi (fake NNTP server)."""

import base64
import json
import os
import select
import socketserver
import sys
import threading
import time
import urllib.request
import zlib

KODI = r'C:\Users\Angelitto\AppData\Roaming\Kodi'
PROFILE = os.path.join(KODI, 'userdata')
PLAN_DIR = os.path.join(PROFILE, 'addon_data', 'plugin.video.tmdbmovies', 'usenet-vfs')
SAMPLE = os.path.join(PROFILE, 'addon_data', 'plugin.video.tmdbmovies', 'vfs-test',
                      'sample.mp4')
LOG = os.path.join(KODI, 'kodi.log')
JSONRPC = 'http://127.0.0.1:8080/jsonrpc'
TOKEN = 'cafebabe12345678'
SEG = 64 * 1024


class FakeNntp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, articles):
        self.articles = articles
        self.requests = []
        self.batches = []
        self.lock = threading.Lock()
        socketserver.ThreadingTCPServer.__init__(self, ('127.0.0.1', 0), Handler)

    def handle_error(self, request, client_address):
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.sendall(b'200 fake ready\r\n')
            buffer = b''
            while True:
                ready, _, _ = select.select([self.request], [], [], 10)
                if not ready:
                    return
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                buffer += chunk
                lines = []
                while b'\r\n' in buffer:
                    line, buffer = buffer.split(b'\r\n', 1)
                    lines.append(line.decode('latin-1'))
                bodies = [line for line in lines if line.upper().startswith('BODY ')]
                if bodies:
                    with self.server.lock:
                        self.server.batches.append(len(bodies))
                for line in lines:
                    upper = line.upper()
                    if upper.startswith('AUTHINFO USER'):
                        self.request.sendall(b'381 password required\r\n')
                    elif upper.startswith('AUTHINFO PASS'):
                        self.request.sendall(b'281 ok\r\n')
                    elif upper.startswith('BODY '):
                        mid = line[5:].strip().strip('<>')
                        with self.server.lock:
                            self.server.requests.append(mid)
                            article = self.server.articles.get(mid)
                        if article is None:
                            self.request.sendall(b'430 no such article\r\n')
                        else:
                            self.request.sendall(b'222 0 ' + mid.encode('latin-1')
                                                 + b' article follows\r\n' + article
                                                 + b'\r\n.\r\n')
                    elif upper == 'QUIT':
                        return
                    else:
                        self.request.sendall(b'500 unknown\r\n')
        except OSError:
            return


def yenc_article(data, start, total):
    encoded = bytearray()
    for value in data:
        value = (value + 42) & 0xFF
        if value in (0x00, 0x0A, 0x0D, 0x3D):
            encoded += b'=' + bytes(((value + 64) & 0xFF,))
        else:
            encoded.append(value)
    header = (b'=ybegin part=1 total=1 line=128 size=%d name=sample.mp4\r\n'
              b'=ypart begin=%d end=%d\r\n' % (total, start + 1, start + len(data)))
    footer = (b'\r\n=yend size=%d part=1 pcrc32=%08x\r\n'
              % (len(data), zlib.crc32(data) & 0xFFFFFFFF))
    return header + bytes(encoded) + footer


def articles_for(blob):
    found = {}
    total = len(blob)
    for index, start in enumerate(range(0, total, SEG)):
        found['k%04d@fake' % index] = yenc_article(blob[start:start + SEG], start, total)
    return found


def b64(text):
    return base64.b64encode(text.encode('ascii')).decode('ascii')


def write_plan(port, blob, connections=8):
    lines = ['tmdbm-plan 1', 'token ' + TOKEN, 'name sample.mp4', 'container mp4',
             'length %d' % len(blob), 'timeout 10', 'prefetch 4194304',
             'cache 33554432', 'pipeline 2', 'workers %d' % connections,
             'holefilling 1', 'holepercent 2', 'holeconsecutive 4',
             'server 127.0.0.1 %d 0 %d 0 %s %s %s'
             % (port, connections, b64('u'), b64('p'), b64('fake')),
             'part 0 0 %d %d' % (len(blob), SEG)]
    lines.extend('a 0 %s' % mid for mid in sorted(articles_for(blob)))
    os.makedirs(PLAN_DIR, exist_ok=True)
    path = os.path.join(PLAN_DIR, TOKEN + '.plan')
    with open(path, 'w', newline='\n') as handle:
        handle.write('\n'.join(lines) + '\n')
    first = blob[:SEG]
    with open(os.path.join(PLAN_DIR, TOKEN + '.first'), 'wb') as handle:
        handle.write(('tmdbm-first 1 k0000@fake %d %08x\n'
                      % (len(first), zlib.crc32(first) & 0xFFFFFFFF)).encode('ascii'))
        handle.write(first)
    return path


def rpc(method, params=None):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        payload['params'] = params
    request = urllib.request.Request(JSONRPC, data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as answer:
        body = json.loads(answer.read().decode('utf-8'))
    if 'error' in body:
        raise RuntimeError('%s: %s' % (method, body['error']))
    return body.get('result')


def active_player():
    players = rpc('Player.GetActivePlayers') or []
    for player in players:
        if player.get('type') == 'video':
            return player['playerid']
    return None


def properties(player):
    return rpc('Player.GetProperties', {'playerid': player,
                                        'properties': ['percentage', 'speed', 'time',
                                                       'totaltime']})


def check(name, condition, detail=''):
    if not condition:
        raise AssertionError('%s FAILED %s' % (name, detail))
    print('  ok  %s' % name)


def wait_playing(deadline):
    player = None
    while time.time() < deadline:
        try:
            player = active_player()
        except Exception:
            player = None
        if player is not None:
            try:
                info = properties(player)
            except Exception:
                info = None
            if info and info.get('speed', 0) > 0:
                return player, info
        time.sleep(0.4)
    return player, None


def recent_log(offset):
    if not os.path.exists(LOG):
        return []
    with open(LOG, 'rb') as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(offset if offset <= size else 0)
        text = handle.read().decode('utf-8', 'replace')
    return [line.rstrip() for line in text.splitlines()
            if 'tmdbm' in line.lower() or 'stream:' in line or 'stream closed' in line]


def wait_log(needle, start, deadline):
    while time.time() < deadline:
        if any(needle in line for line in recent_log(start)):
            return True
        time.sleep(0.4)
    return False


def main():
    if not os.path.exists(SAMPLE):
        raise SystemExit('missing sample: %s' % SAMPLE)
    with open(SAMPLE, 'rb') as handle:
        blob = handle.read()
    articles = articles_for(blob)
    print('sample.mp4: %d bytes, %d articles of %d KB'
          % (len(blob), len(articles), SEG // 1024))

    server = FakeNntp(articles)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log_offset = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    plan_path = write_plan(server.server_address[1], blob)
    print('plan: %s' % plan_path)

    try:
        check('kodi answers', rpc('JSONRPC.Ping') == 'pong')
        existing = active_player()
        if existing is not None:
            rpc('Player.Stop', {'playerid': existing})
            time.sleep(1.0)
        opened = rpc('Player.Open', {'item': {'file': 'tmdbm://%s/sample.mp4' % TOKEN}})
        check('open accepted', opened == 'OK', opened)
        player, info = wait_playing(time.time() + 25)
        check('playback started', player is not None and info is not None, info)
        print('  playing: %.1f%% of %s, speed %s'
              % (info['percentage'], info['totaltime'], info['speed']))
        check('duration known', info['totaltime']['seconds'] > 0, info['totaltime'])
        deadline = time.time() + 10
        while time.time() < deadline and info['percentage'] <= 1:
            time.sleep(0.4)
            info = properties(player)
        check('progress advances', info['percentage'] > 1, info['percentage'])
        rpc('Player.Seek', {'playerid': player, 'value': {'percentage': 50.0}})
        deadline = time.time() + 5
        after = properties(player)
        while time.time() < deadline and after['percentage'] < 45:
            time.sleep(0.4)
            after = properties(player)
        print('  after seek: %.1f%% at %s' % (after['percentage'], after['time']))
        check('seek moved forward', after['percentage'] >= 45, after['percentage'])
        check('still playing', after['speed'] > 0, after['speed'])
        rpc('Player.Stop', {'playerid': player})
        time.sleep(1.0)
        check('playback stopped', active_player() is None)
        with server.lock:
            asked = len(server.requests)
            asked_ids = list(server.requests)
            deepest = max((int(mid[1:5]) for mid in server.requests
                           if mid.startswith('k')), default=-1)
            batches = list(server.batches)
        print('  server: %d articles asked, last index %d of %d, batches %s'
              % (asked, deepest, len(articles) - 1, sorted(set(batches))))
        check('first article came from the plan cache',
              not any(mid.lower().startswith('k0000') for mid in asked_ids),
              asked_ids[:5])
        check('tail was prefetched', deepest >= len(articles) - 2, deepest)
        check('engine closed', wait_log('stream closed', log_offset, time.time() + 8))
        lines = recent_log(log_offset)
        print('  log:')
        for line in lines[-25:]:
            print('    ' + line)
        check('addon opened the stream', any('vfs.tmdbm: open' in line for line in lines))
        check('engine started', any('stream:' in line and 'provider' in line for line in lines))
        check('first article primed', any('first article came from the plan cache' in line
                                          for line in lines))
        opens = [line for line in lines if 'vfs.tmdbm: open' in line]
        check('one stream opened', len(opens) == 1, opens)
        check('sidecar probes ignored', all('sample.mp4' in line for line in opens), opens)
        print('KODI VFS TEST PASSED')
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        try:
            os.remove(plan_path)
        except OSError:
            pass
        try:
            os.remove(os.path.join(PLAN_DIR, TOKEN + '.first'))
        except OSError:
            pass


if __name__ == '__main__':
    main()
