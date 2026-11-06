"""Kodi must never wait for our threads at exit.

A non-daemon thread anywhere in the plugin process makes CPython wait for it
when the script is torn down, which shows up as "CPythonInvoker ... script
didn't stop in 5 seconds - let's kill it" and leaves Kodi hanging. This forces
every thread created after install() to be a daemon, whoever creates it.
"""

import os
import threading

_MARK = '_tmdbmovies_daemon_guard'


def install():
    """Make every thread in this interpreter a daemon (idempotent)."""
    if getattr(threading, _MARK, False):
        return False
    original = threading.Thread.__init__

    def patched(self, *args, **kwargs):
        # The hourglass is the bug, not the feature: nothing we start may hold
        # Kodi open when the player is gone.
        kwargs['daemon'] = True
        original(self, *args, **kwargs)

    threading.Thread.__init__ = patched
    setattr(threading, _MARK, True)
    try:
        import xbmc
        xbmc.log('[TMDb Movies] [DAEMON-GUARD] every thread is daemon (pid %d)' % os.getpid(),
                 xbmc.LOGINFO)
    except Exception:
        pass
    return True
