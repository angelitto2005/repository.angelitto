"""Local checks for the native Usenet stream (no provider, no Kodi)."""

import base64
import os
import select
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, 'build', 'dist', 'tools', 'stream_test.exe')

SEG = 64 * 1024
COUNT = 400
TOTAL = SEG * COUNT
MAGIC = b'\x1a\x45\xdf\xa3'


def payload(index):
    seed = bytes((index * 37 + i * 11) & 0xFF for i in range(251))
    data = (seed * (SEG // len(seed) + 1))[:SEG]
    if index == 0:
        data = MAGIC + data[4:]
    return data


def yenc_article(data, start, total):
    encoded = bytearray()
    for value in data:
        value = (value + 42) & 0xFF
        if value in (0x00, 0x0A, 0x0D, 0x3D):
            encoded += b'=' + bytes(((value + 64) & 0xFF,))
        else:
            encoded.append(value)
    header = (b'=ybegin part=1 total=1 line=128 size=%d name=fake.mkv\r\n'
              b'=ypart begin=%d end=%d\r\n' % (total, start + 1, start + len(data)))
    footer = (b'\r\n=yend size=%d part=1 pcrc32=%08x\r\n'
              % (len(data), zlib.crc32(data) & 0xFFFFFFFF))
    return header + bytes(encoded) + footer


class FakeNntp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, articles, errors=None, drop_after=None):
        self.articles = articles
        self.errors = errors or {}
        self.batches = []
        self.requests = []
        self.lock = threading.Lock()
        self.delay = 0.0
        self.drop_after = drop_after
        socketserver.ThreadingTCPServer.__init__(self, ('127.0.0.1', 0), Handler)

    def handle_error(self, request, client_address):
        pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.sendall(b'200 fake ready\r\n')
            buffer = b''
            served = 0
            while True:
                pending = hasattr(self.request, 'pending') and self.request.pending() > 0
                ready = True if pending else select.select([self.request], [], [], 5)[0]
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
                deadline = time.time() + 0.03
                while time.time() < deadline:
                    pending = hasattr(self.request, 'pending') and self.request.pending() > 0
                    ready = True if pending else select.select([self.request], [], [],
                                                               0.005)[0]
                    if not ready:
                        break
                    chunk = self.request.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while b'\r\n' in buffer:
                        line, buffer = buffer.split(b'\r\n', 1)
                        lines.append(line.decode('latin-1'))
                if not lines:
                    continue
                bodies = [line for line in lines if line.upper().startswith('BODY ')]
                if bodies:
                    with self.server.lock:
                        self.server.batches.append(len(bodies))
                    if self.server.delay:
                        time.sleep(self.server.delay)
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
                            error = self.server.errors.get(mid)
                        if error is not None:
                            self.request.sendall(error + b'\r\n')
                        elif article is None:
                            self.request.sendall(b'430 no such article\r\n')
                        else:
                            self.request.sendall(b'222 0 ' + mid.encode('latin-1')
                                                 + b' article follows\r\n' + article + b'\r\n.\r\n')
                        served += 1
                        if self.server.drop_after and served >= self.server.drop_after:
                            return
                    elif upper == 'QUIT':
                        return
                    else:
                        self.request.sendall(b'500 unknown\r\n')
        except OSError:
            return


class FakeTlsNntp(FakeNntp):
    def __init__(self, articles, cert, key):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        FakeNntp.__init__(self, articles)

    def get_request(self):
        connection, address = super().get_request()
        return self.context.wrap_socket(connection, server_side=True), address


def articles_for(count, skip=()):
    found = {}
    for index in range(count):
        if index in skip:
            continue
        mid = 'a%04d@fake' % index
        found[mid] = yenc_article(payload(index), index * SEG, count * SEG)
    return found


def ids_for(count):
    return ['a%04d@fake' % index for index in range(count)]


def expected_file(count, holes=()):
    parts = []
    for index in range(count):
        parts.append(b'\x00' * SEG if index in holes else payload(index))
    return b''.join(parts)


def b64(text):
    return base64.b64encode(text.encode('ascii')).decode('ascii')


def write_plan(server_ports, ids, count, pipeline=2, connections=4, workers=4,
               total=None, length=None, hole_percent=2, hole_consecutive=4, tls=False,
               cacert=None):
    total = total if total is not None else count * SEG
    length = length if length is not None else total
    lines = ['tmdbm-plan 1', 'token test', 'name fake.mkv', 'container mkv',
             'length %d' % length, 'timeout 5', 'prefetch %d' % (256 * 1024),
             'cache %d' % (8 * 1024 * 1024), 'pipeline %d' % pipeline,
             'workers %d' % workers, 'holefilling 1',
             'holepercent %g' % hole_percent, 'holeconsecutive %d' % hole_consecutive]
    if cacert:
        lines.append('cacert %s' % cacert)
    for port, backup, label, limits in server_ports:
        lines.append('server 127.0.0.1 %d %d %d %d %s %s %s'
                     % (port, 1 if tls else 0, limits, 1 if backup else 0,
                        b64('u'), b64('p'), b64(label)))
    lines.append('part 0 0 %d %d' % (length, SEG))
    lines.extend('a 0 %s' % mid for mid in ids)
    return '\n'.join(lines) + '\n'


def run_plan(plan_text, offset=None, length=None, chunk=None):
    folder = tempfile.mkdtemp(prefix='tmdbusenet-')
    plan_path = os.path.join(folder, 'test.plan')
    dump_path = os.path.join(folder, 'dump.bin')
    with open(plan_path, 'w', newline='\n') as handle:
        handle.write(plan_text)
    command = [EXE, plan_path, '--dump', dump_path]
    if offset is not None:
        command += ['--offset', str(offset)]
    if length is not None:
        command += ['--length', str(length)]
    if chunk is not None:
        command += ['--chunk', str(chunk)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    found = b''
    if os.path.exists(dump_path):
        with open(dump_path, 'rb') as handle:
            found = handle.read()
    try:
        os.remove(plan_path)
        if os.path.exists(dump_path):
            os.remove(dump_path)
        os.rmdir(folder)
    except OSError:
        pass
    return result, found


def check(name, condition, detail=''):
    if not condition:
        raise AssertionError('%s FAILED %s' % (name, detail))
    print('  ok  %s' % name)


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()


def test_sequential():
    print('native, sequential')
    server = FakeNntp(articles_for(COUNT))
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 4)], ids_for(COUNT), COUNT)
        result, found = run_plan(plan)
        check('exit code', result.returncode == 0, result.stderr)
        expected = expected_file(COUNT)
        check('bytes intact', found == expected,
              'len %d vs %d' % (len(found), len(expected)))
        check('crc matches', ('crc32=%08x' % (zlib.crc32(expected) & 0xFFFFFFFF))
              in result.stdout, result.stdout)
        check('two BODYs per batch', max(server.batches) == 2, server.batches[:20])
        check('tail asked early', ids_for(COUNT)[-1] in server.requests)
        check('no missing', 'missing=0' in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()


def test_stale_connections():
    print('native, stale connections')
    server = FakeNntp(articles_for(COUNT), drop_after=20)
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 4)], ids_for(COUNT), COUNT)
        result, found = run_plan(plan)
        check('exit code', result.returncode == 0, result.stderr)
        expected = expected_file(COUNT)
        check('bytes intact', found == expected,
              'len %d vs %d' % (len(found), len(expected)))
        check('no missing', 'missing=0' in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()


def test_part_crc():
    print('native, short tail article with pcrc32 and crc32')
    count = 40
    tail = 1000
    length = (count - 1) * SEG + tail
    articles = articles_for(count - 1)
    last = payload(count - 1)[:tail]
    article = yenc_article(last, (count - 1) * SEG, length)
    whole = zlib.crc32(expected_file(count - 1) + last) & 0xFFFFFFFF
    articles['a%04d@fake' % (count - 1)] = article[:-2] + b' crc32=%08x\r\n' % whole
    server = FakeNntp(articles)
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 2)],
                          ids_for(count), count, total=length, length=length)
        result, found = run_plan(plan)
        expected = expected_file(count - 1) + last
        check('tail exit code', result.returncode == 0, result.stderr)
        check('tail bytes intact', found == expected,
              'len %d vs %d' % (len(found), len(expected)))
        check('tail no missing', 'missing=0' in result.stdout, result.stdout)
        check('tail crc matches', ('crc32=%08x' % (zlib.crc32(expected) & 0xFFFFFFFF))
              in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()


def test_seek():
    print('native, seek')
    server = FakeNntp(articles_for(COUNT))
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 4)], ids_for(COUNT), COUNT)
        offset = 280 * SEG + 1234
        wanted = expected_file(COUNT)[offset:offset + 512 * 1024]
        result, found = run_plan(plan, offset=offset, length=len(wanted))
        check('seek exit', result.returncode == 0, result.stderr)
        check('seek bytes', found == wanted, 'len %d vs %d' % (len(found), len(wanted)))
        check('seek crc', ('crc32=%08x' % (zlib.crc32(wanted) & 0xFFFFFFFF))
              in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()


def test_missing():
    print('native, missing article')
    hole = 17
    server = FakeNntp(articles_for(40, skip=(hole,)))
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 2)], ids_for(40), 40,
                          hole_percent=0, hole_consecutive=0)
        result, found = run_plan(plan)
        expected = expected_file(40, holes=(hole,))
        check('all bytes returned', found == expected,
              'len %d vs %d' % (len(found), len(expected)))
        check('hole zero-filled', 'missing=1' in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()


def test_backup():
    print('native, backup provider')
    hole = 5
    primary = FakeNntp(articles_for(20, skip=(hole,)))
    backup = FakeNntp(articles_for(20))
    serve(primary)
    serve(backup)
    try:
        plan = write_plan([(primary.server_address[1], False, 'primary', 4),
                           (backup.server_address[1], True, 'backup', 1)],
                          ids_for(20), 20, workers=1)
        result, found = run_plan(plan)
        expected = expected_file(20)
        check('whole file intact', found == expected,
              'len %d vs %d' % (len(found), len(expected)))
        check('no article lost', 'missing=0' in result.stdout, result.stdout)
        check('primary asked first', 'a%04d@fake' % hole in primary.requests)
        check('backup asked after 430', 'a%04d@fake' % hole in backup.requests)
    finally:
        for server in (primary, backup):
            server.shutdown()
            server.server_close()


def test_pipeline_one():
    print('native, pipeline 1')
    count = 60
    server = FakeNntp(articles_for(count))
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'fake', 3)],
                          ids_for(count), count, pipeline=1, workers=3)
        result, found = run_plan(plan)
        check('serial bytes', found == expected_file(count),
              'len %d vs %d' % (len(found), count * SEG))
        check('one BODY at a time', max(server.batches) == 1, server.batches[:20])
    finally:
        server.shutdown()
        server.server_close()


def make_certificate(folder):
    cert = os.path.join(folder, 'cert.pem')
    key = os.path.join(folder, 'key.pem')
    result = subprocess.run(
        ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', key, '-out', cert,
         '-days', '7', '-nodes', '-subj', '/CN=127.0.0.1',
         '-addext', 'subjectAltName=IP:127.0.0.1'],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('openssl certificate generation failed: ' + result.stderr[-300:])
    return cert, key


def test_tls():
    print('native, TLS')
    folder = tempfile.mkdtemp(prefix='tmdbusenet-tls-')
    cert, key = make_certificate(folder)
    count = 30
    server = FakeTlsNntp(articles_for(count), cert, key)
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'tls', 3)],
                          ids_for(count), count, tls=True, cacert=cert)
        result, found = run_plan(plan)
        check('tls exit code', result.returncode == 0, result.stderr)
        check('tls bytes intact', found == expected_file(count),
              'len %d vs %d' % (len(found), count * SEG))
        check('tls no missing', 'missing=0' in result.stdout, result.stdout)
        untrusted = write_plan([(server.server_address[1], False, 'tls', 3)],
                               ids_for(count), count, tls=True)
        rejected, _ = run_plan(untrusted)
        check('unknown CA rejected', rejected.returncode != 0, rejected.stdout)
        check('error names TLS', 'TLS' in rejected.stderr, rejected.stderr[-200:])
    finally:
        server.shutdown()
        server.server_close()
        for path in (cert, key):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


def test_tls_many():
    print('native, TLS with 24 parallel connections')
    folder = tempfile.mkdtemp(prefix='tmdbusenet-tlsmany-')
    cert, key = make_certificate(folder)
    count = 384
    server = FakeTlsNntp(articles_for(count), cert, key)
    serve(server)
    try:
        plan = write_plan([(server.server_address[1], False, 'tls', 24)],
                          ids_for(count), count, tls=True, cacert=cert,
                          workers=24, connections=24)
        result, found = run_plan(plan)
        check('many exit code', result.returncode == 0, result.stderr)
        check('many bytes intact', found == expected_file(count),
              'len %d vs %d' % (len(found), count * SEG))
        check('many no missing', 'missing=0' in result.stdout, result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        for path in (cert, key):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


def test_benchmark():
    print('native, latency benchmark (30 ms per batch)')
    count = 60
    times = {}
    for pipeline in (1, 2):
        server = FakeNntp(articles_for(count))
        server.delay = 0.03
        serve(server)
        try:
            plan = write_plan([(server.server_address[1], False, 'fake', 3)],
                              ids_for(count), count, pipeline=pipeline, workers=3)
            started = time.time()
            result, found = run_plan(plan)
            times[pipeline] = time.time() - started
            check('benchmark pipeline %d bytes' % pipeline, found == expected_file(count),
                  result.stderr)
        finally:
            server.shutdown()
            server.server_close()
    print('  pipeline 1: %.2f s, pipeline 2: %.2f s (%d MB)'
          % (times[1], times[2], count * SEG // (1024 * 1024)))
    check('pipelining hides the round trip', times[2] < times[1] * 0.8, times)


def main():
    if not os.path.exists(EXE):
        raise SystemExit('build the project first: %s is missing' % EXE)
    test_sequential()
    test_stale_connections()
    test_part_crc()
    test_seek()
    test_missing()
    test_backup()
    test_pipeline_one()
    test_tls()
    test_tls_many()
    test_benchmark()
    print('ALL NATIVE TESTS PASSED')


if __name__ == '__main__':
    main()
