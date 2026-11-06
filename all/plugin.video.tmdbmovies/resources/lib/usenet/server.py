"""The local HTTP server that turns an NZB into something Kodi can play.

Kodi asks for a file and seeks inside it; this server answers those Range
requests from the Usenet articles behind the NZB, so nothing is downloaded to
disk first. It runs in the add-on service (the plugin process does not live long
enough), and the port is published as a window property so the plugin can find
it.

Routes:
    GET /ping                     -> 'tmdbmovies-usenet'
    GET /prepare/<key>            -> JSON: open the release, pick the video,
                                     confirm the container (also a quick health
                                     check, it reads the first article)
    GET|HEAD /stream/<key>/<name> -> the video, with Range support (seeking)
    GET /close/<key>              -> close the release and its connections
"""

import json
import os
import re
import socket
import threading
import time
from concurrent.futures import CancelledError
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import quote, urlparse
from urllib.request import urlopen

from . import config, engine, indexer

PORT_PROPERTY = 'tmdbmovies.usenet.port'
PORT_RANGE = tuple(range(47321, 47332))
KEY_RE = re.compile(r'^[0-9a-f]{32}$')
CONTENT_TYPES = {'mkv': 'video/x-matroska', 'mp4': 'video/mp4', 'avi': 'video/x-msvideo',
                 'ts': 'video/mp2t', 'rar': 'video/x-matroska', 'iso': 'application/x-iso9660-image'}

_LOCK = threading.Lock()
_SESSIONS = {}
_SERVER = None
_PORT = 0


# -- windows property ----------------------------------------------------------

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


def _log(message, level=None):
    try:
        import xbmc
        xbmc.log('[TMDb Movies] [Usenet] ' + message,
                 xbmc.LOGERROR if level == 'error' else xbmc.LOGINFO)
    except Exception:
        pass


def _frame(error):
    """The add-on line that raised, so a bare 'timed out' stops being anonymous."""
    try:
        import traceback
        steps = traceback.extract_tb(error.__traceback__)
        own = [step for step in steps if 'usenet' in step.filename.replace('\\', '/').lower()]
        step = (own or steps)[-1]
        return ' (%s:%d)' % (os.path.basename(step.filename), step.lineno)
    except Exception:
        return ''


def port():
    return _PORT


# -- sessions ------------------------------------------------------------------

def _touch(session):
    session.last_read = time.time()
    return session


def _existing(key):
    with _LOCK:
        session = _SESSIONS.get(key)
    return _touch(session) if session else None


def _close_others(keep_key):
    """One release at a time: an old session must not hold connections or threads."""
    with _LOCK:
        stale = [key for key in _SESSIONS if key != keep_key]
        closed = [_SESSIONS.pop(key) for key in stale]
    for session in closed:
        session.close()
    if closed:
        _log('closed %d previous release session(s)' % len(closed))


def open_session(key):
    """(session, info, error)."""
    session = _existing(key)
    if session:
        return session, dict(session.info(), ok=True, key=key), ''
    path = config.nzb_path(key)
    if not path or not os.path.exists(path):
        return None, None, 'the NZB is no longer in the profile - pick the source again'
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except Exception as exc:
        return None, None, 'the NZB could not be read (%s)' % exc
    providers = config.primary_providers() + config.backup_providers()
    try:
        session = engine.Session(key, data, providers, config.player_options())
        info = session.prepare()
    except engine.SessionError as exc:
        if getattr(exc, 'bad_nzb', False):
            try:
                os.remove(path)
            except Exception:
                pass
        return None, None, str(exc)
    except Exception as exc:
        return None, None, 'the release could not be opened (%s)' % str(exc)[:90]
    info['key'] = key
    with _LOCK:
        _SESSIONS[key] = session
    _close_others(key)
    return session, info, ''


def close_session(key):
    with _LOCK:
        session = _SESSIONS.pop(key, None)
    if session:
        session.close()
        return True
    return False


# -- request handling ----------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'tmdbmovies-usenet'

    def end_headers(self):
        """One response per connection: the player reconnects when it needs more."""
        self.send_header('Connection', 'close')
        self.close_connection = True
        BaseHTTPRequestHandler.end_headers(self)

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

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

    def _route(self, head):
        parts = [piece for piece in urlparse(self.path).path.split('/') if piece]
        if not parts:
            return self._text(404, 'not found')
        if parts[0] == 'ping':
            return self._text(200, 'tmdbmovies-usenet')
        if len(parts) < 2 or not KEY_RE.match(parts[1]):
            return self._text(400, 'bad key')
        key = parts[1]
        if parts[0] == 'prepare':
            return self._prepare(key)
        if parts[0] == 'stream':
            return self._stream(key, head)
        if parts[0] == 'close':
            return self._json({'ok': close_session(key)})
        return self._text(404, 'not found')

    def _prepare(self, key):
        session, info, error = open_session(key)
        if error:
            return self._json({'ok': False, 'reason': error})
        return self._json(info)

    def _stream(self, key, head):
        session, info, error = open_session(key)
        if error:
            return self._text(503, error)
        length = session.length
        content_type = CONTENT_TYPES.get(session.container, 'video/x-matroska')
        start, end, status = 0, length - 1, 200
        header = self.headers.get('Range') or ''
        if header.lower().startswith('bytes='):
            spec = header[6:].split(',')[0].strip()
            first, _, last = spec.partition('-')
            try:
                if first:
                    start = int(first)
                    if last:
                        end = min(int(last), length - 1)
                elif last:
                    start = max(0, length - int(last))
            except ValueError:
                start, end = 0, length - 1
            if start >= length or start > end:
                self.send_response(416)
                self.send_header('Content-Range', 'bytes */%d' % length)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status = 206
        count = end - start + 1
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(count))
        if status == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, length))
        self.end_headers()
        if head:
            return
        self._body(session, start, count)

    def _body(self, session, start, count):
        output = self.wfile
        sent = [0]

        def sink(piece):
            sent[0] += len(piece)
            output.write(piece)

        started = time.time()
        problem = ''
        try:
            session.read(start, count, sink)
        except (BrokenPipeError, ConnectionResetError):
            problem = 'the player closed the connection'
        except (socket.timeout, TimeoutError):
            problem = 'the player stopped reading'
        except CancelledError:
            problem = 'the release session was closed'
        except engine.SessionError as exc:
            problem = 'release stopped: %s' % str(exc)[:120]
            _log('stream stopped: %s' % str(exc)[:160], 'warning')
        except Exception as exc:
            problem = 'read failed: %s' % str(exc)[:110]
            _log('stream error: %s%s' % (str(exc)[:140], _frame(exc)), 'error')
        else:
            try:
                output.flush()
            except Exception:
                pass
        stats = session.stats()
        elapsed = max(0.001, time.time() - started)
        rate = sent[0] / 1024.0 / elapsed
        detail = '%.0f ms/article, %d read error(s), %s' % (
            stats['avg_ms'], stats['read_errors'], stats['provider'])
        _log('served %d of %d bytes from %d in %.1fs (%.0f KB/s) - %s%s%s'
             % (sent[0], count, start, elapsed, rate, detail,
                (' - %d article(s) missing' % session.missing) if session.missing else '',
                (' - ' + problem) if problem else ''))


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """A player that hangs up is normal: a traceback for it is only noise."""
        import sys
        error = sys.exc_info()[1]
        if isinstance(error, (socket.timeout, ConnectionResetError, BrokenPipeError,
                              ConnectionAbortedError)):
            return
        _log('request error from %s: %s' % (client_address, error), 'error')


_CLEANUP_DONE = [False]


def _cleanup(reason):
    """Kodi waits at most 5s at exit: leave nothing behind that can hold it."""
    if _CLEANUP_DONE[0]:
        return
    _CLEANUP_DONE[0] = True
    try:
        running = [thread for thread in threading.enumerate()
                   if thread is not threading.current_thread()]
        alive = [thread.name for thread in running if not thread.daemon]
        daemons = len(running) - len(alive)
        # every one of them, with its id: the log then names the thread Kodi waits for
        detail = ['%s#%s%s' % (thread.name, thread.ident,
                                '' if thread.daemon else ' (NON-DAEMON)')
                  for thread in running]
    except Exception:
        alive, daemons, detail = [], 0, []
    stop()
    _log('cleanup (%s) - non-daemon threads left: %s (%d daemon threads still winding down)'
         % (reason, ', '.join(sorted(alive)) or 'none', daemons))
    if detail:
        _log('cleanup (%s) - threads alive: %s' % (reason, ', '.join(detail)))


def _watch_abort():
    """Kodi is closing: stop the server before its invoker starts waiting for us.

    The local HTTP server lives in the same interpreter as every plugin script, so
    Kodi waits for it when a script ends and kills the script after five seconds.
    Stopping it the moment the abort is requested makes that wait disappear.
    """
    try:
        import xbmc
        monitor = xbmc.Monitor()
        if monitor.waitForAbort(0):
            _log('Kodi is closing - stopping the server now')
            _cleanup('abort')
    except Exception:
        pass


def _register_cleanup():
    try:
        import atexit
        atexit.register(_cleanup, 'exit')
    except Exception:
        pass


def start():
    """Bind to the first free port. Safe to call more than once."""
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is not None:
            return True
    for candidate in PORT_RANGE:
        try:
            server = _ThreadedServer(('127.0.0.1', candidate), _Handler)
        except OSError:
            continue
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2},
                                  name='UsenetHTTP', daemon=True)
        thread.start()
        watcher = threading.Thread(target=_watch_abort, name='UsenetAbort', daemon=True)
        watcher.start()
        with _LOCK:
            _SERVER = server
            _PORT = candidate
        _publish(candidate)
        config.cleanup_nzb()
        _register_cleanup()
        return True
    return False


def ensure_running():
    if _SERVER is not None and _PORT:
        return _PORT
    return _PORT if start() else 0


def stop():
    global _SERVER, _PORT
    with _LOCK:
        server, _SERVER = _SERVER, None
        _PORT = 0
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        session.close()
    _publish(0)
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    _log('server stopped')


# -- what the plugin calls -----------------------------------------------------

def prepare_stream(nzb_url):
    """Download the NZB if needed and return (local_url, error)."""
    if not nzb_url:
        return '', 'this source has no NZB link'
    key = config.nzb_key(nzb_url)
    if not indexer.fetch_nzb(nzb_url, key):
        return '', 'the NZB could not be downloaded from the indexer'
    active = ensure_running()
    if not active:
        return '', 'the local Usenet server could not start (is the add-on service running?)'
    try:
        with urlopen('http://127.0.0.1:%d/prepare/%s' % (active, key), timeout=45) as response:
            answer = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        return '', 'the Usenet engine did not answer (%s)' % str(exc)[:70]
    if not answer.get('ok'):
        close_session(key)
        return '', answer.get('reason') or 'the release could not be opened'
    name = answer.get('name') or 'video.mkv'
    return 'http://127.0.0.1:%d/stream/%s/%s' % (active, key, quote(name)), ''
