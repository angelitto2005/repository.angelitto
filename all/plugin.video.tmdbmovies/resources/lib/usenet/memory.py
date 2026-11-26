"""Give the RAM back after watching: the release kept open for an instant restart
drops its buffered articles a dozen seconds after a stop, then its connections
after a long idle. The plan stays, so the next open is still fast. Measured on
Android from /proc/meminfo; nothing happens while a player holds media or an Up
Next prompt is on screen.
"""
import gc
import threading
import time

import xbmc

WAIT = 12.0          # seconds without playback before the buffers go
BUFFER_IDLE = 15.0   # only releases nobody read for this long
CLOSE_IDLE = 300.0   # the whole release (and its connections) after this long
POLL = 2.0
GUARD_PROPS = ('tmdbmovies.post_stop_prompt_open', 'tmdbmovies.post_stop_prompt',
               'tmdbmovies.binge_open')

_started = {'flag': False}


def _log(message):
    try:
        xbmc.log('[TMDb Movies] [MEMORY] %s' % message, xbmc.LOGINFO)
    except Exception:
        pass


def available_mb():
    """MemAvailable in MB, or None where /proc/meminfo is not there (Windows)."""
    try:
        with open('/proc/meminfo') as handle:
            for line in handle:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _waiting_play():
    """A prompt is on screen or a play request is pending: it may start in a
    second, so nothing is touched yet."""
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
    except Exception:
        return False
    return any((window.getProperty(name) or '').strip() for name in GUARD_PROPS)


def _tidy(full):
    from . import server
    before = available_mb()
    released = server.trim_idle(BUFFER_IDLE)
    closed = server.close_idle(CLOSE_IDLE) if full else 0
    if not released and not closed:
        return
    gc.collect()
    parts = []
    if released:
        parts.append('%.0f MB of buffered articles dropped' % (released / 1048576.0))
    if closed:
        parts.append('%d release(s) closed' % closed)
    after = available_mb()
    if before is not None and after is not None:
        parts.append('%d MB -> %d MB free' % (before, after))
    _log('; '.join(parts))


def _loop(monitor):
    idle_since = 0.0
    buffers_done = False
    closed_done = False
    while not monitor.abortRequested():
        try:
            busy = xbmc.getCondVisibility('Player.HasMedia')
        except Exception:
            busy = False
        if busy:
            idle_since, buffers_done, closed_done = 0.0, False, False
        else:
            now = time.time()
            if not idle_since:
                idle_since = now
            idle = now - idle_since
            if idle >= WAIT and not _waiting_play():
                if monitor.abortRequested():
                    break
                if not buffers_done:
                    buffers_done = True
                    _tidy(False)
                elif not closed_done and idle >= CLOSE_IDLE:
                    closed_done = True
                    _tidy(True)
        if monitor.waitForAbort(POLL):
            break


def start():
    """Started once from run_service: the release lives in the service process."""
    if _started['flag']:
        return False
    _started['flag'] = True
    try:
        monitor = xbmc.Monitor()
        threading.Thread(target=_loop, args=(monitor,), name='UsenetMemory',
                         daemon=True).start()
        return True
    except Exception as error:
        _log('loop did not start: %s' % type(error).__name__)
        return False
