"""Play a plan written by the Python add-on through vfs.tmdbm (fake NNTP server).

This exercises resources/lib/usenet/vfs.py for real: only the NNTP session is
faked, so the plan text, the percent-encoded name and the token are exactly
what the plugin produces in Kodi. The plan is then opened through JSON-RPC.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time
from urllib.parse import quote

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import kodi_vfs_test as base

ADDON = r'C:\Users\Angelitto\AppData\Roaming\Kodi\addons\plugin.video.tmdbmovies'
sys.path.insert(0, ADDON)
import resources.lib.usenet.vfs as writer

PROFILE_ADDON = os.path.join(base.PROFILE, 'addon_data', 'plugin.video.tmdbmovies')
NAME = 'Film \u0218ir de Test.mp4'
NZB_URL = 'http://fake.invalid/test.nzb'
TOKEN = hashlib.md5(NZB_URL.encode('utf-8')).hexdigest()


def b64_parts(blob, articles):
    return {
        'id': 0,
        'segments': sorted(articles),
        'skip': 0,
        'length': len(blob),
        'part_size': base.SEG,
    }


class FakeSession:
    SessionError = Exception

    def __init__(self, key, data, providers, options):
        self.key = key
        self.container = 'mp4'
        self.length = BLOB_LENGTH
        self.timeout = int(options.get('timeout') or 20)
        self.prefetch_bytes = int(options.get('prefetch_bytes') or 12 * 1048576)
        self.cache_limit = int(options.get('cache_bytes') or 36 * 1048576)
        self.pipeline = 2
        self.worker_target = 8
        self.hole_filling = bool(options.get('hole_filling', True))
        self.hole_percent = float(options.get('hole_percent') or 0)
        self.hole_consecutive = int(options.get('hole_consecutive') or 0)
        self.parts = [b64_parts_blob]
        self.warm = WARM

    def prepare(self):
        return {'ok': True, 'container': 'mp4', 'length': BLOB_LENGTH, 'name': NAME,
                'rar': False}

    def first_article(self):
        return FIRST

    first_crc_ok = True

    def close(self):
        pass


class FakeEngine:
    Session = FakeSession
    SessionError = Exception


class FakeConfig:
    @staticmethod
    def flag(key, default=False):
        return True

    @staticmethod
    def profile_dir():
        return PROFILE_ADDON.replace('\\', '/') + '/'

    @staticmethod
    def nzb_key(url):
        return TOKEN

    @staticmethod
    def nzb_path(key):
        return os.path.join(NZB_DIR, key + '.nzb')

    @staticmethod
    def primary_providers():
        return [{'host': '127.0.0.1', 'port': PORT[0], 'ssl': False, 'connections': 8,
                 'backup': False, 'user': '', 'password': '', 'label': 'fake'}]

    @staticmethod
    def backup_providers():
        return []

    @staticmethod
    def player_options():
        return {'timeout': 10, 'prefetch_bytes': 4 * 1048576, 'cache_bytes': 32 * 1048576,
                'hole_filling': True, 'hole_percent': 2, 'hole_consecutive': 4}


class FakeIndexer:
    @staticmethod
    def fetch_nzb(url, key=None, timeout=25):
        with open(FakeConfig.nzb_path(key), 'wb') as handle:
            handle.write(b'fake nzb')
        return True


class FakeMemory:
    @staticmethod
    def mark(key, state):
        pass


def main():
    global BLOB_LENGTH, b64_parts_blob, NZB_DIR, PORT, FIRST, WARM
    if not os.path.exists(base.SAMPLE):
        raise SystemExit('missing sample: %s' % base.SAMPLE)
    with open(base.SAMPLE, 'rb') as handle:
        blob = handle.read()
    BLOB_LENGTH = len(blob)
    FIRST = blob[:base.SEG]
    articles = base.articles_for(blob)
    b64_parts_blob = b64_parts(blob, articles)
    WARM = [(index, 'k%04d@fake' % index, blob[index * base.SEG:(index + 1) * base.SEG])
            for index in range(1, 4)]

    server = base.FakeNntp(articles)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    PORT = [server.server_address[1]]
    NZB_DIR = tempfile.mkdtemp(prefix='tmdbm-plan-')

    writer.config = FakeConfig
    writer.engine = FakeEngine
    writer.indexer = FakeIndexer
    writer.memory = FakeMemory

    expected = 'tmdbm://%s/%s' % (TOKEN, quote(NAME))
    log_offset = os.path.getsize(base.LOG) if os.path.exists(base.LOG) else 0
    plan_path = os.path.join(PROFILE_ADDON, 'usenet-vfs', TOKEN + '.plan')

    try:
        url, why, retry = writer.prepare_stream(NZB_URL)
        base.check('writer returned a url', url == expected, (url, why))
        print('  url: %s' % url)
        with open(plan_path, encoding='utf-8') as handle:
            text = handle.read()
        base.check('plan has the token', 'token ' + TOKEN in text)
        base.check('plan keeps the name', 'name ' + NAME in text)
        base.check('empty credentials stay in columns', '==== ==== ' in text, text)
        base.check('plan has every article', text.count('\na 0 ') == len(articles),
                   text.count('\na 0 '))
        first_path = os.path.join(PROFILE_ADDON, 'usenet-vfs', TOKEN + '.first')
        with open(first_path, 'rb') as handle:
            cached = handle.read()
        header, cached_data = cached.split(b'\n', 1)
        base.check('first article cached', cached_data == FIRST, len(cached_data))
        base.check('cache header', header.startswith(
            b'tmdbm-first 1 k0000@fake %d ' % len(FIRST)), header[:80])

        warm_path = os.path.join(PROFILE_ADDON, 'usenet-vfs', TOKEN + '.first2')
        with open(warm_path, 'rb') as handle:
            warm_file = handle.read()
        warm_lines = warm_file.split(b'\n', 4)
        base.check('warm header',
                   warm_lines[0] == b'tmdbm-warm 1 3 %d' % (3 * base.SEG), warm_lines[0])
        base.check('warm entry ids',
                   warm_lines[1].startswith(b'1 k0001@fake %d ' % base.SEG) and
                   warm_lines[2].startswith(b'2 k0002@fake %d ' % base.SEG) and
                   warm_lines[3].startswith(b'3 k0003@fake %d ' % base.SEG),
                   warm_lines[1:4])
        base.check('warm bytes', warm_lines[4] == blob[base.SEG:4 * base.SEG],
                   len(warm_lines[4]))

        base.check('kodi answers', base.rpc('JSONRPC.Ping') == 'pong')
        existing = base.active_player()
        if existing is not None:
            base.rpc('Player.Stop', {'playerid': existing})
            time.sleep(1.0)
        opened = base.rpc('Player.Open', {'item': {'file': url}})
        base.check('open accepted', opened == 'OK', opened)
        player, info = base.wait_playing(time.time() + 25)
        base.check('playback started', player is not None and info is not None, info)
        print('  playing: %.1f%% of %s, speed %s'
              % (info['percentage'], info['totaltime'], info['speed']))
        base.check('duration known', info['totaltime']['seconds'] > 0, info['totaltime'])
        deadline = time.time() + 10
        while time.time() < deadline and info['percentage'] <= 1:
            time.sleep(0.4)
            info = base.properties(player)
        base.check('progress advances', info['percentage'] > 1, info['percentage'])
        base.rpc('Player.Seek', {'playerid': player, 'value': {'percentage': 50.0}})
        deadline = time.time() + 5
        after = base.properties(player)
        while time.time() < deadline and after['percentage'] < 45:
            time.sleep(0.4)
            after = base.properties(player)
        base.check('seek moved forward', after['percentage'] >= 45, after['percentage'])
        base.rpc('Player.Stop', {'playerid': player})
        time.sleep(1.0)
        base.check('playback stopped', base.active_player() is None)
        lines = base.recent_log(log_offset)
        print('  log:')
        for line in lines[-15:]:
            print('    ' + line)
        base.check('addon opened the encoded name',
                   any('vfs.tmdbm: open' in line for line in lines))
        base.check('first article reused', any('plan cache' in line for line in lines))
        base.check('warm articles reused',
                   any('warm articles came from the plan cache' in line for line in lines))
        # 0.1.6 keeps the stream warm for 45 s, so closing is expected after that.
        base.check('engine closed after idle TTL',
                   base.wait_log('stream closed', log_offset, time.time() + 55))
        print('PYTHON PLAN TEST PASSED')
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
            os.remove(os.path.join(PROFILE_ADDON, 'usenet-vfs', TOKEN + '.first'))
        except OSError:
            pass
        try:
            os.remove(os.path.join(PROFILE_ADDON, 'usenet-vfs', TOKEN + '.first2'))
        except OSError:
            pass
        shutil.rmtree(NZB_DIR, ignore_errors=True)


BLOB_LENGTH = 0
b64_parts_blob = None
NZB_DIR = ''
PORT = [0]
FIRST = b''
WARM = []

if __name__ == '__main__':
    main()
