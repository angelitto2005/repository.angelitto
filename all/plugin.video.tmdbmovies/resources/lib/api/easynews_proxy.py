"""Loopback proxy for EasyNews Direct playback.

Kodi and subtitle add-ons log the playing path, so the EasyNews login must not
be part of it.  Kodi reads a token URL from 127.0.0.1; only this server adds the
Basic authorization on the upstream request.
"""

import atexit
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import requests

PORT_PROPERTY = 'tmdbmovies.easynews.port'
PORT_RANGE = tuple(range(47341, 47351))
TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')
MAX_SESSIONS = 8
SESSION_TTL = 6 * 3600
RESOLVED_TTL = 600
TAIL_BYTES = 512 * 1024
USER_AGENT = 'TMDbMovies'
CONTENT_TYPES = ('.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.webm', '.m4v')
UPSTREAM_HEADERS = ('Content-Type', 'Content-Length', 'Content-Range',
                    'Last-Modified', 'ETag')

_LOCK = threading.Lock()
_SESSIONS = {}
_RESOLVED = {}
_SERVER = None
_PORT = 0
_CLEANED = [False]
_LOCAL = requests.Session()
_LOCAL.trust_env = False


def _log(message, level='info'):
    try:
        import xbmc
        code = xbmc.LOGERROR if level == 'error' else xbmc.LOGINFO
        xbmc.log('[TMDb Movies] [EASYNEWS-PROXY] ' + str(message), code)
    except Exception:
        pass


def _publish(port):
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        if port:
            window.setProperty(PORT_PROPERTY, str(port))
        else:
            window.clearProperty(PORT_PROPERTY)
    except Exception:
        pass


def _published_port():
    try:
        import xbmcgui
        value = (xbmcgui.Window(10000).getProperty(PORT_PROPERTY) or '').strip()
        return int(value) if value else 0
    except Exception:
        return 0


def _easynews_url(url):
    try:
        parts = urllib.parse.urlsplit(url or '')
    except Exception:
        return False
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and (host == 'easynews.com' or host.endswith('.easynews.com'))


def _authorization():
    try:
        from resources.lib.api.easynews_direct import configured, _auth_header
        if not configured():
            return ''
        return _auth_header()
    except Exception:
        return ''


def _stream_name(remote_url):
    try:
        path = urllib.parse.urlsplit(remote_url).path
        name = urllib.parse.unquote(path.rsplit('/', 1)[-1]) or 'video.mkv'
    except Exception:
        name = 'video.mkv'
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', name).strip() or 'video.mkv'
    if os.path.splitext(name)[1].lower() not in CONTENT_TYPES:
        name += '.mkv'
    return name[:180]


def _local_url(port, token, remote_url):
    return 'http://127.0.0.1:%d/en/%s/%s' % (
        port, token, urllib.parse.quote(_stream_name(remote_url), safe=''))


def _parse_range(value):
    value = (value or '').strip()
    if not value.lower().startswith('bytes=') or ',' in value:
        return None
    spec = value[6:].strip()
    if '-' not in spec:
        return None
    first, last = spec.split('-', 1)
    try:
        start = int(first)
        end = int(last) if last.strip() else None
    except (TypeError, ValueError):
        return None
    if start < 0 or (end is not None and end < start):
        return None
    return start, end


def _content_range_total(value):
    match = re.match(r'bytes\s+\d+-\d+/(\d+|\*)', value or '')
    if not match or match.group(1) == '*':
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _request_headers(range_value=''):
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
    }
    if range_value:
        headers['Range'] = range_value
    return headers


def _follow(session, method, url, headers, timeout=(10, 12), on_resolved=None):
    """Open the upstream response, following only EasyNews redirects."""
    current = url
    for _hop in range(6):
        outgoing = dict(headers)
        auth = _authorization() if _easynews_url(current) else ''
        if auth:
            outgoing['Authorization'] = auth
        else:
            outgoing.pop('Authorization', None)
        host = urllib.parse.urlsplit(current).hostname or '?'
        started = time.time()
        try:
            response = session.request(
                method, current, headers=outgoing, stream=True,
                allow_redirects=False, timeout=timeout, verify=True)
        except Exception as error:
            _log('upstream %s %s failed: %s after %.1fs'
                 % (method, host, type(error).__name__, time.time() - started),
                 'warning')
            return None
        _log('upstream %s %s -> %d in %.1fs'
             % (method, host, response.status_code, time.time() - started))
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get('Location') or ''
            response.close()
            if not location:
                return None
            current = urllib.parse.urljoin(current, location)
            if not _easynews_url(current):
                _log('redirect outside EasyNews refused', 'warning')
                return None
            if response.status_code == 303:
                method = 'GET'
            continue
        if on_resolved is not None:
            try:
                on_resolved(current)
            except Exception:
                pass
        return response
    return None


def _close(token):
    with _LOCK:
        info = _SESSIONS.pop(token, None)
    if info:
        try:
            info['session'].close()
        except Exception:
            pass


def _close_all():
    with _LOCK:
        tokens = list(_SESSIONS)
    for token in tokens:
        _close(token)


def _prune():
    now = time.time()
    stale = []
    with _LOCK:
        for token, info in _SESSIONS.items():
            if now - info['last'] > SESSION_TTL:
                stale.append(token)
        wanted = len(_SESSIONS) - len(stale)
        if wanted > MAX_SESSIONS:
            oldest = sorted((info['last'], token) for token, info in _SESSIONS.items()
                            if token not in stale)
            stale.extend(token for _stamp, token in oldest[:wanted - MAX_SESSIONS])
    for token in stale:
        _close(token)


def _register(remote_url):
    token = os.urandom(16).hex()
    session = requests.Session()
    session.trust_env = False
    info = {
        'url': remote_url,
        'session': session,
        'created': time.time(),
        'last': time.time(),
        'head': None,
        'resolved': None,
    }
    with _LOCK:
        _SESSIONS[token] = info
    _prune()
    return token


def _resolved_key(info):
    return hashlib.sha1(str(info.get('url') or '').encode('utf-8')).hexdigest()


def _remember_resolved(info, url):
    now = time.time()
    key = _resolved_key(info)
    with _LOCK:
        info['resolved'] = (url, now)
        _RESOLVED[key] = (url, now)
        if len(_RESOLVED) > 32:
            oldest = sorted(_RESOLVED, key=_RESOLVED.get)[:len(_RESOLVED) - 32]
            for stale in oldest:
                _RESOLVED.pop(stale, None)


def _resolved_url(info):
    key = _resolved_key(info)
    with _LOCK:
        resolved = info.get('resolved')
        if not resolved or time.time() - resolved[1] >= RESOLVED_TTL:
            resolved = _RESOLVED.get(key)
            if resolved and time.time() - resolved[1] < RESOLVED_TTL:
                info['resolved'] = resolved
            else:
                resolved = None
    return resolved[0] if resolved else ''


def _forget_resolved(info):
    key = _resolved_key(info)
    with _LOCK:
        info['resolved'] = None
        _RESOLVED.pop(key, None)


def _fetch_tail(info, total):
    """Read the last MB before Kodi opens the file.

    Kodi always asks for a tail range when seekable=1. EasyNews often stalls
    when that tail request runs at the same time as the full GET. Fetch it once
    here, on a closed connection, and later serve it from memory.
    """
    if total <= TAIL_BYTES * 2:
        return False
    start = total - TAIL_BYTES
    headers = _request_headers('bytes=%d-%d' % (start, total - 1))
    session = requests.Session()
    session.trust_env = False
    started = time.time()
    response = None
    try:
        response = _follow(session, 'GET', _resolved_url(info) or info['url'],
                           headers, timeout=(4, 5),
                           on_resolved=lambda final: _remember_resolved(info, final))
        if response is None or response.status_code != 206:
            return False
        content_range = response.headers.get('Content-Range') or ''
        if not content_range.startswith('bytes %d-' % start):
            return False
        values = {name: response.headers.get(name) for name in UPSTREAM_HEADERS}
        pieces = []
        received = 0
        for piece in response.iter_content(128 * 1024):
            if not piece:
                continue
            pieces.append(piece)
            received += len(piece)
            if received >= TAIL_BYTES:
                break
        body = b''.join(pieces)[:TAIL_BYTES]
        if len(body) < 128 * 1024:
            return False
        with _LOCK:
            info['tail'] = (start, total, body, values)
        _log('tail prefetch %d bytes in %.1fs' % (len(body), time.time() - started))
        return True
    except Exception as error:
        _log('tail prefetch failed: %s' % type(error).__name__)
        return False
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        session.close()


def _cached_tail(info, start, end):
    with _LOCK:
        cached = info.get('tail')
    if not cached:
        return None
    tail_start, total, body, values = cached
    if start < tail_start or start >= total:
        return None
    if end is None:
        end = total - 1
    if end < start or end >= total:
        return None
    offset = start - tail_start
    data = body[offset:offset + (end - start + 1)]
    if len(data) != end - start + 1:
        return None
    headers = dict(values)
    headers['Content-Length'] = str(len(data))
    headers['Content-Range'] = 'bytes %d-%d/%d' % (start, end, total)
    return headers, data


def _prepare_stream(info):
    """Resolve the CDN URL, HEAD metadata and tail before Kodi opens the file.

    members.easynews.com can take 10-20s to answer. Kodi's Stat/HEAD gives up
    at 20s, then opens the full GET; that is when the concurrent tail request
    used to stall both. Preparing here happens before the local URL is returned,
    so Kodi never times out and all later requests use the resolved CDN.
    """
    if info.get('prepared'):
        return
    info['prepared'] = True
    session = requests.Session()
    session.trust_env = False
    response = None
    started = time.time()
    try:
        upstream = _resolved_url(info) or info['url']
        response = _follow(session, 'HEAD', upstream, _request_headers(),
                           timeout=(8, 20),
                           on_resolved=lambda final: _remember_resolved(info, final))
        if response is None and upstream != info['url']:
            _forget_resolved(info)
            response = _follow(session, 'HEAD', info['url'], _request_headers(),
                               timeout=(8, 10),
                               on_resolved=lambda final: _remember_resolved(info, final))
        if response is None and upstream == info['url']:
            response = _follow(session, 'HEAD', info['url'], _request_headers(),
                               timeout=(8, 10),
                               on_resolved=lambda final: _remember_resolved(info, final))
        if response is not None and response.status_code in (401, 403, 410) \
                and upstream != info['url']:
            try:
                response.close()
            except Exception:
                pass
            _forget_resolved(info)
            upstream = info['url']
            response = _follow(session, 'HEAD', upstream, _request_headers(),
                               timeout=(8, 10),
                               on_resolved=lambda final: _remember_resolved(info, final))
        if response is None:
            return
        status = response.status_code
        if status not in (200, 206):
            _log('prepare HEAD HTTP %d' % status, 'warning')
            return
        values = {name: response.headers.get(name) for name in UPSTREAM_HEADERS}
        total = _content_range_total(values.get('Content-Range'))
        length = values.get('Content-Length') or ''
        if total is None and length.isdigit():
            total = int(length)
        with _LOCK:
            info['head'] = (status, values)
        try:
            response.close()
        except Exception:
            pass
        if total and total > TAIL_BYTES * 2:
            if not _fetch_tail(info, total):
                time.sleep(1.0)
                if not _fetch_tail(info, total):
                    _log('tail prefetch still unavailable - Kodi will retry live')
        _log('prepared in %.1fs (head, tail, CDN cache)' % (time.time() - started))
    except Exception as error:
        _log('prepare failed: %s' % type(error).__name__)
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        session.close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'tmdbmovies-easynews'

    def end_headers(self):
        self.send_header('Connection', 'close')
        self.close_connection = True
        BaseHTTPRequestHandler.end_headers(self)

    def log_message(self, *args):
        pass

    def _text(self, status, body):
        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except Exception:
            pass

    def _json(self, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if self.headers.get('Origin'):
            return self._text(403, 'forbidden')
        if path == '/open':
            return self._open()
        if path == '/close':
            _close_all()
            return self._json({'ok': True})
        return self._text(404, 'not found')

    def _route(self, head):
        path = urllib.parse.urlsplit(self.path).path
        parts = [piece for piece in path.split('/') if piece]
        if not parts:
            return self._text(404, 'not found')
        if parts[0] == 'ping':
            return self._text(200, 'tmdbmovies-easynews')
        if len(parts) >= 2 and parts[0] == 'en' and TOKEN_RE.match(parts[1]):
            return self._stream(parts[1], head)
        return self._text(404, 'not found')

    def _open(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length <= 0 or length > 16384:
                return self._text(400, 'bad body')
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            remote_url = payload.get('url') or ''
        except Exception:
            return self._text(400, 'bad body')
        if not _easynews_url(remote_url):
            return self._text(400, 'only EasyNews URLs are accepted')
        if not _authorization():
            return self._json({'ok': False, 'reason': 'EasyNews login is not configured'})
        token = _register(remote_url)
        with _LOCK:
            info = _SESSIONS.get(token)
        if info:
            _prepare_stream(info)
        tail_ok = bool(info and info.get('tail'))
        return self._json({'ok': True, 'url': _local_url(_PORT, token, remote_url),
                           'tail_ok': tail_ok})

    def _send_headers(self, status, values):
        self.send_response(status)
        for name in UPSTREAM_HEADERS:
            value = values.get(name)
            if value:
                self.send_header(name, value)
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()

    def _stream(self, token, head):
        try:
            threading.current_thread().name = 'EasyNewsStream'
        except Exception:
            pass
        with _LOCK:
            info = _SESSIONS.get(token)
            if info:
                info['last'] = time.time()
        if not info:
            return self._text(404, 'unknown stream')
        started = time.time()
        range_value = self.headers.get('Range') or ''
        if_range = self.headers.get('If-Range') or ''
        parsed = _parse_range(range_value)
        client_start = parsed[0] if parsed else 0
        client_end = parsed[1] if parsed else None
        # Kodi asks for the tail while the full GET is still open. EasyNews
        # occasionally hangs the second connection for 30s; a short timeout
        # and a fresh redirect find a healthy CDN node before Kodi gives up.
        small_range = bool(parsed and (parsed[0] > 0 or parsed[1] is not None))
        upstream_timeout = (8, 10) if small_range else (10, 12)
        if head and not range_value and not if_range:
            cached = info.get('head')
            if cached:
                self._send_headers(cached[0], cached[1])
                return
        if not head:
            cached_tail = _cached_tail(info, client_start, client_end)
            if cached_tail:
                values, data = cached_tail
                self._send_headers(206, values)
                try:
                    self.wfile.write(data)
                    _log('served %d bytes from tail cache range=%r'
                         % (len(data), range_value))
                except Exception:
                    pass
                return
        headers = _request_headers(range_value)
        if if_range:
            headers['If-Range'] = if_range
        _log('request %s range=%r if_range=%r'
             % ('HEAD' if head else 'GET', headers.get('Range'), if_range))
        upstream_url = _resolved_url(info) or info['url']
        remember = lambda final: _remember_resolved(info, final)
        response = None
        for attempt in range(2):
            response = _follow(info['session'], 'HEAD' if head else 'GET',
                               upstream_url, headers, timeout=upstream_timeout,
                               on_resolved=remember)
            if response is not None:
                break
            if attempt == 0:
                if upstream_url != info['url']:
                    _forget_resolved(info)
                    upstream_url = info['url']
                    _log('resolved CDN URL failed, retry original range=%r'
                         % headers.get('Range'))
                else:
                    _log('upstream retry range=%r' % headers.get('Range'))
        if response is None:
            return self._text(502, 'upstream unavailable')
        try:
            status = response.status_code
            if status in (401, 403, 410) and upstream_url != info['url']:
                try:
                    response.close()
                except Exception:
                    pass
                _forget_resolved(info)
                upstream_url = info['url']
                response = _follow(info['session'], 'HEAD' if head else 'GET',
                                   upstream_url, headers,
                                   timeout=upstream_timeout,
                                   on_resolved=remember)
                if response is None:
                    return self._text(502, 'upstream unavailable')
                status = response.status_code
            if status not in (200, 206, 416):
                _log('upstream answered HTTP %d' % status, 'warning')
                return self._text(502, 'upstream HTTP %d' % status)
            values = {name: response.headers.get(name) for name in UPSTREAM_HEADERS}
            _log('reply %d len=%s range=%s type=%s'
                 % (status, values.get('Content-Length'), values.get('Content-Range'),
                    values.get('Content-Type')))
            if head:
                if not range_value and not if_range:
                    info['head'] = (status, values)
                self._send_headers(status, values)
                return
            total = _content_range_total(values.get('Content-Range'))
            if total is None and status == 200:
                length = values.get('Content-Length') or ''
                if length.isdigit():
                    total = int(length)
            if client_end is not None:
                expected = client_end - client_start + 1
            elif total is not None:
                expected = total - client_start
            else:
                expected = None
            if expected is not None and expected < 0:
                expected = 0
            self._send_headers(status, values)
            sent = 0
            failures = 0
            current = response
            while True:
                attempt_sent = sent
                body_error = ''
                try:
                    for piece in current.iter_content(1024 * 1024):
                        if not piece:
                            continue
                        if expected is not None:
                            remaining = expected - sent
                            if remaining <= 0:
                                break
                            if len(piece) > remaining:
                                piece = piece[:remaining]
                        self.wfile.write(piece)
                        sent += len(piece)
                        if expected is not None and sent >= expected:
                            break
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    body_error = 'client'
                except Exception as error:
                    body_error = type(error).__name__
                    _log('stream error: %s after %.1fs sent %d range=%r'
                         % (body_error, time.time() - started, sent,
                            headers.get('Range')), 'warning')
                finally:
                    try:
                        current.close()
                    except Exception:
                        pass
                if body_error == 'client':
                    break
                if expected is not None and sent >= expected:
                    break
                if expected is None:
                    break
                if not body_error:
                    _log('stream ended early at %d of %d bytes' % (sent, expected),
                         'warning')
                if sent > attempt_sent:
                    failures = 0
                else:
                    failures += 1
                if failures >= (2 if small_range else 4):
                    break
                next_offset = client_start + sent
                resume_range = 'bytes=%d-' % next_offset
                if client_end is not None:
                    resume_range = 'bytes=%d-%d' % (next_offset, client_end)
                current = _follow(info['session'], 'GET',
                                  _resolved_url(info) or info['url'],
                                  _request_headers(resume_range),
                                  timeout=upstream_timeout,
                                  on_resolved=remember)
                if current is None:
                    _log('resume unavailable at %d' % next_offset, 'warning')
                    break
                if current.status_code != 206:
                    _log('resume answered HTTP %d at %d'
                         % (current.status_code, next_offset), 'warning')
                    try:
                        current.close()
                    except Exception:
                        pass
                    break
                content_range = current.headers.get('Content-Range') or ''
                if not content_range.startswith('bytes %d-' % next_offset):
                    _log('resume range mismatch: %s' % content_range, 'warning')
                    try:
                        current.close()
                    except Exception:
                        pass
                    break
                _log('stream resumed at %d after %d bytes' % (next_offset, sent))
            if sent:
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                elapsed = max(0.001, time.time() - started)
                _log('served %d bytes in %.1fs (%.1f MB/s)'
                     % (sent, elapsed, sent / 1048576.0 / elapsed))
        finally:
            try:
                response.close()
            except Exception:
                pass


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        import sys
        error = sys.exc_info()[1]
        if isinstance(error, (OSError, ValueError)):
            return
        _log('request error: %s' % type(error).__name__, 'warning')


def _watch_abort():
    try:
        import xbmc
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            if monitor.waitForAbort(1):
                break
        _shutdown('abort')
    except Exception:
        pass


def _shutdown(reason):
    if _CLEANED[0]:
        return
    _CLEANED[0] = True
    _stop_server()
    _close_all()
    _log('server stopped (%s)' % reason)


def _stop_server():
    global _SERVER, _PORT
    with _LOCK:
        server, _SERVER = _SERVER, None
        _PORT = 0
    _publish(0)
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass


def _register_cleanup():
    try:
        atexit.register(_shutdown, 'exit')
    except Exception:
        pass


def start():
    """Bind the first free loopback port.  Safe to call more than once."""
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is not None:
            return True
    for candidate in PORT_RANGE:
        try:
            server = _ThreadedServer(('127.0.0.1', candidate), _Handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2},
                         name='EasyNewsHTTP', daemon=True).start()
        threading.Thread(target=_watch_abort, name='EasyNewsAbort', daemon=True).start()
        with _LOCK:
            _SERVER = server
            _PORT = candidate
        _publish(candidate)
        _register_cleanup()
        return True
    return False


def ensure_running():
    port = _published_port()
    if port:
        try:
            answer = _LOCAL.get('http://127.0.0.1:%d/ping' % port, timeout=1)
            if answer.text.strip() == 'tmdbmovies-easynews':
                return port
        except Exception:
            pass
    if _PORT:
        return _PORT
    return _PORT if start() else 0


def playback_url(remote_url):
    """Return a clean loopback URL for an EasyNews direct URL, or '' on failure."""
    if not remote_url:
        return ''
    base, separator, tail = remote_url.partition('|')
    if not _easynews_url(base):
        return ''
    port = ensure_running()
    if not port:
        _log('local server is not running', 'error')
        return ''
    try:
        response = _LOCAL.post('http://127.0.0.1:%d/open' % port,
                               json={'url': base}, timeout=55)
        answer = response.json()
    except Exception as error:
        _log('register failed: %s' % type(error).__name__, 'error')
        return ''
    if not answer.get('ok') or not answer.get('url'):
        _log('register refused: %s' % (answer.get('reason') or 'unknown'), 'error')
        return ''
    local = answer['url'] + (separator + tail if separator else '')
    if answer.get('tail_ok') is False and 'seekable=0' not in local:
        if 'seekable=1' in local:
            local = local.replace('seekable=1', 'seekable=0')
        elif '|' in local:
            local += '&seekable=0'
        else:
            local += '|seekable=0'
        _log('tail cache unavailable - this attempt uses no-seek')
    return local


def close_all():
    port = _published_port()
    if port:
        try:
            _LOCAL.post('http://127.0.0.1:%d/close' % port, timeout=2)
        except Exception:
            pass
    _close_all()


def stop():
    _shutdown('service')
