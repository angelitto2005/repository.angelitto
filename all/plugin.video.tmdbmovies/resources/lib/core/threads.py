"""Give our background threads a moment to finish before the script returns.

Kodi's invoker keeps waiting for every Python thread a script started, once the
script itself has returned, and kills the invocation when that wait passes five
seconds ("script didn't stop in 5 seconds - let's kill it"). Waiting here, while
the script is still the one in charge, turns that hidden delay into a bounded
one and leaves nothing behind for Kodi to wait for.

Threads that are meant to outlive a single invocation are skipped, but they are
reported with the line they are sitting in: that is what says why Kodi still
waits for them at exit.
"""

import sys
import threading
import time

# The player monitor and the local HTTP server live as long as playback does, so
# waiting for them here would block the script for the whole film.
SKIP = ('PLAYER-MONITOR', 'UsenetHTTP', 'UsenetRead', 'UsenetAbort')


def _where(thread):
    """'file.py:123 in function <- caller' for a live thread."""
    try:
        frame = sys._current_frames().get(thread.ident)
    except Exception:
        return 'no frame'
    parts = []
    while frame is not None and len(parts) < 4:
        name = frame.f_code.co_filename.replace(chr(92), '/').rsplit('/', 1)[-1]
        parts.append('%s:%d in %s' % (name, frame.f_lineno, frame.f_code.co_name))
        frame = frame.f_back
    return ' <- '.join(parts) or 'no frame'


def settle(seconds=2.0):
    """Join every other thread we started, up to `seconds`. Returns what is left."""
    deadline = time.time() + seconds
    me = threading.current_thread()
    remaining = []
    for thread in threading.enumerate():
        if thread is me or not thread.is_alive():
            continue
        if thread.name.startswith(SKIP):
            remaining.append('%s [%s]' % (thread.name, _where(thread)))
            continue
        left = deadline - time.time()
        if left > 0:
            thread.join(left)
        if thread.is_alive():
            remaining.append('%s [%s]' % (thread.name, _where(thread)))
    return remaining
