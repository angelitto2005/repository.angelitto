# -*- coding: utf-8 -*-

"""Stop the add-on's background work the instant Kodi is asked to exit.

Kodi's ``CPythonInvoker`` does not let an invocation go while any thread of its
interpreter is alive: it spins in a 100 ms loop logging ``waiting on thread
<id>``, and five seconds later it force-kills the interpreter (``script didn't
stop in 5 seconds - let's kill it``). For the service that means the whole
application looks hung, and the kill is exactly what leaves Kodi stuck.

A worker blocked in a socket read cannot notice the abort by itself: the
prefetch cache refresh of version 1.0.40 was still fetching several seconds
into the stop -

    waiting on thread 30500
    cache: _trailers refreshed in the background
    waiting on thread 25856
    script didn't stop in 5 seconds - let's kill it

- because a pending ``requests`` call only returns when its own timeout runs
out. Python cannot cancel that read, so this module keeps the sockets the
add-on has opened and closes them as soon as abort is requested: the blocked
read returns at once, the worker raises ``Aborted``, its handler logs nothing
and the thread is gone in milliseconds instead of seconds.

Only sockets of this interpreter are touched, and only after Kodi asked to
abort - playback is Kodi's own, so nothing here can interrupt a clip.
"""

import socket
import threading
import time

_ABORT = [False]
_INSTALLED = [False]
_WATCHER = [None]
_WORKERS = [0]
_LOCK = threading.Lock()
_SOCKETS = set()
_MONITOR = []


class Aborted(OSError):
    """Raised inside a worker once Kodi is going away.

    An OSError on purpose: socket code expects that family, so a worker that
    only catches OSError still ends cleanly instead of dying on a traceback.
    """


def _monitor():
    if not _MONITOR:
        try:
            import xbmc
            _MONITOR.append(xbmc.Monitor())
        except Exception:
            _MONITOR.append(None)
    return _MONITOR[0]


def aborting():
    """True once Kodi has been asked to stop."""
    if _ABORT[0]:
        return True
    mon = _monitor()
    if mon is None:
        return False
    try:
        return bool(mon.abortRequested())
    except Exception:
        return False


def check():
    """End the calling worker if Kodi is going away."""
    if aborting():
        raise Aborted('Kodi is shutting down')


def is_abort(exc):
    """True when a failure is only the shutdown guard at work, not an error.

    requests and urllib3 wrap the socket we closed into their own exception
    (ConnectionError, ProtocolError, MaxRetryError), so by the time a worker
    sees it the type says nothing about us. During an abort any such failure
    is the guard doing its job, and logging it would put four fake errors in
    kodi.log on every exit.
    """
    if isinstance(exc, Aborted):
        return True
    return aborting()


def sleep(seconds):
    """Sleep, but wake the moment Kodi is asked to stop.

    Used where the add-on waits between requests (the scraper paces its pages):
    a plain ``time.sleep`` there is one more thing the exit has to wait for.
    """
    deadline = time.time() + max(0.0, float(seconds or 0))
    while True:
        check()
        left = deadline - time.time()
        if left <= 0:
            return
        time.sleep(min(0.2, left))


def _remember(sock):
    with _LOCK:
        if len(_SOCKETS) > 512:
            # Long sessions open and close hundreds of connections; the closed
            # ones are useless for the abort below, so drop them first.
            for item in list(_SOCKETS):
                try:
                    if item.fileno() < 0:
                        _SOCKETS.discard(item)
                except Exception:
                    _SOCKETS.discard(item)
        _SOCKETS.add(sock)


def abort_now():
    """Flag the shutdown and wake every socket a worker may be blocked on."""
    _ABORT[0] = True
    with _LOCK:
        sockets = list(_SOCKETS)
        _SOCKETS.clear()
    for sock in sockets:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
    return len(sockets)


def _patch_socket():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_accept = socket.socket.accept
    original_getaddrinfo = socket.getaddrinfo

    def _connect(self, address):
        if _ABORT[0]:
            raise Aborted('Kodi is shutting down')
        original_connect(self, address)
        _remember(self)

    def _connect_ex(self, address):
        if _ABORT[0]:
            raise Aborted('Kodi is shutting down')
        result = original_connect_ex(self, address)
        if result == 0:
            _remember(self)
        return result

    def _accept(self):
        connection, address = original_accept(self)
        _remember(connection)
        return connection, address

    def _getaddrinfo(host, port, *args, **kwargs):
        if _ABORT[0]:
            raise Aborted('Kodi is shutting down')
        return original_getaddrinfo(host, port, *args, **kwargs)

    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.socket.accept = _accept
    socket.getaddrinfo = _getaddrinfo


def _patch_ssl():
    """HTTPS is a wrapped socket, and the wrapper hides the real one.

    ``ssl.SSLSocket`` takes the file descriptor away from the plain socket
    (``detach``), so the socket tracked at connect time would be a dead handle.
    The wrapped object is tracked instead, and shutting that down wakes a
    pending ``recv`` exactly the same way.
    """
    try:
        import ssl
    except Exception:
        return
    original_wrap = ssl.SSLContext.wrap_socket

    def _wrap_socket(self, *args, **kwargs):
        if _ABORT[0]:
            raise Aborted('Kodi is shutting down')
        wrapped = original_wrap(self, *args, **kwargs)
        _remember(wrapped)
        return wrapped

    ssl.SSLContext.wrap_socket = _wrap_socket


def install():
    """Hook the sockets once per interpreter. Cheap and idempotent."""
    with _LOCK:
        if _INSTALLED[0]:
            return
        _INSTALLED[0] = True
    try:
        _patch_socket()
    except Exception:
        pass
    try:
        _patch_ssl()
    except Exception:
        pass


def worker(target, args=(), name=None):
    """Run ``target`` as a background thread the abort can cut short.

    The watcher below lives exactly as long as such a worker does. It must not
    outlive it: at the end of a *normal* run Kodi's invoker waits for the other
    threads of the interpreter with no timeout at all (PythonInvoker.cpp, "make
    sure all sub threads have finished"), so a permanently parked thread would
    make every listing hang once its work was done.
    """
    def _run():
        try:
            target(*args)
        finally:
            with _LOCK:
                _WORKERS[0] = max(0, _WORKERS[0] - 1)

    with _LOCK:
        _WORKERS[0] += 1
        start = _WATCHER[0] is None
        if start:
            watcher = threading.Thread(target=_watch, name='shutdown-guard')
            watcher.daemon = True
            _WATCHER[0] = watcher
    if start:
        watcher.start()
    thread = threading.Thread(target=_run, name=name or 'guarded-worker')
    thread.daemon = True
    thread.start()
    return thread


def _watch():
    mon = _monitor()
    aborted = False
    while True:
        with _LOCK:
            if _WORKERS[0] <= 0:
                _WATCHER[0] = None
                return
        try:
            if mon is None:
                time.sleep(0.25)
                aborted = aborting()
            else:
                aborted = bool(mon.waitForAbort(0.25))
        except Exception:
            time.sleep(0.25)
            aborted = aborting()
        if aborted:
            break
    with _LOCK:
        _WATCHER[0] = None
    closed = abort_now()
    try:
        import config
        config.log('shutdown guard: {} socket(s) closed'.format(closed))
    except Exception:
        pass
