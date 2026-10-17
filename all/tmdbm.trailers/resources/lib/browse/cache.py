# -*- coding: utf-8 -*-

'''
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import functools
import time
import os
import threading
try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

ENABLED = True
SECONDS = 1
MINUTES = 60

# One refresh per cache key at a time: several listings can be opened while the
# same entry is being refetched, and each of them would otherwise start its own.
_REFRESH_LOCK = threading.Lock()
_REFRESHING = set()


def _aborting():
    try:
        import xbmc
        return bool(xbmc.Monitor().abortRequested())
    except Exception:
        return False


def _log(msg):
    try:
        import config
        config.log('cache: ' + msg, always=True)
    except Exception:
        pass


def _refresh_in_background(cache, func, name, args, kwargs, eff):
    """Fetch an expired entry again, behind the listing that was just painted.

    The thread is a daemon and checks for shutdown before it starts and before
    it saves, so closing Kodi is not held up by it. SystemExit is not caught:
    Kodi ends an interpreter with one and a bare except would swallow it,
    leaving the thread alive.
    """
    key = cache._get_filename(name, args, kwargs)
    with _REFRESH_LOCK:
        if key in _REFRESHING:
            return False
        _REFRESHING.add(key)

    def _run():
        try:
            if _aborting():
                return
            payload = func(*args, **kwargs)
            if not _aborting():
                cache._save(name, args, kwargs, payload)
                _log('{} refreshed in the background'.format(name))
        except Exception as exc:  # SystemExit passes through on purpose
            _log('background refresh of {} failed: {}'.format(name, exc))
        finally:
            with _REFRESH_LOCK:
                _REFRESHING.discard(key)

    thread = threading.Thread(target=_run, name='cache-refresh')
    thread.daemon = True
    thread.start()
    return True


# hashlib and pickle only matter once a listing is cached, and both are
# expensive to import (hashlib alone loads the OpenSSL bindings), so they are
# pulled in on first use instead of on every listing.

def _debug_bypass():
    try:
        import config
        return bool(config.get_bool('debug', False))
    except Exception:
        return False


class FunctionCache:

    def __init__(self, path, protocol=None):

        self.path = path

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        self.protocol = protocol

    def reset_cache(self):

        """Empty the cache and keep the folder usable.

        shutil.rmtree removes the directory itself. Without recreating it
        every later save failed silently and no list was cached again, so
        every folder entry downloaded from YouTube all over again.
        """
        import shutil
        try:
            shutil.rmtree(self.path, ignore_errors=True)
            if not os.path.exists(self.path):
                os.makedirs(self.path)
            return True
        except Exception:
            return False

    def _get_filename(self, name, args, kwargs):

        import hashlib

        _name = hashlib.md5(name.encode('utf-8')).hexdigest()
        _args = hashlib.md5(str(args).encode('utf-8')).hexdigest()
        _kwargs = hashlib.md5(str(kwargs).encode('utf-8')).hexdigest()

        return _name + _args + _kwargs

    def _load(self, name, args=None, kwargs=None, limit=60):
        if not ENABLED or limit <= 0:
            return False, None

        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        now = time.time()
        max_age = now - limit

        filename = os.path.join(self.path, self._get_filename(name, args, kwargs))
        if os.path.exists(filename):
            if xbmcvfs:
                mtime = xbmcvfs.Stat(filename).st_mtime()
            else:
                mtime = os.path.getmtime(filename)

            if mtime >= max_age:
                import pickle
                with open(filename, 'rb') as file_handle:
                    payload = file_handle.read()

                try:
                    return True, pickle.loads(payload)
                except Exception:
                    return False, None

        return False, None

    def _load_stale(self, name, args=None, kwargs=None, oldest=0):
        """Read a copy that is past its time, age permitting.

        This is what lets an expired listing paint at once instead of waiting
        on YouTube: the copy on disk is returned whatever its age, up to
        `oldest` seconds, and the caller refreshes it behind the listing.
        """
        if not ENABLED:
            return False, None

        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        filename = os.path.join(self.path, self._get_filename(name, args, kwargs))
        if not os.path.exists(filename):
            return False, None

        if xbmcvfs:
            mtime = xbmcvfs.Stat(filename).st_mtime()
        else:
            mtime = os.path.getmtime(filename)
        if oldest and time.time() - mtime > oldest:
            return False, None

        import pickle
        try:
            with open(filename, 'rb') as file_handle:
                return True, pickle.loads(file_handle.read())
        except Exception:
            return False, None

    def _save(self, name, args=None, kwargs=None, result=None):

        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        try:
            import pickle
            if self.protocol is None:
                self.protocol = pickle.HIGHEST_PROTOCOL
            payload = pickle.dumps(result, protocol=self.protocol)

            filename = os.path.join(self.path, self._get_filename(name, args, kwargs))
            # Written aside and moved into place, because a background refresh
            # can save while a listing is being read, and a half written file
            # would make that listing fail instead of being slightly old.
            aside = filename + '.tmp'
            with open(aside, 'wb') as file_handle:
                file_handle.write(payload)
            os.replace(aside, filename)

            return True

        except:  # pylint: disable=bare-except
            return False

    def cache_method(self, limit, limit_mode=MINUTES):

        """
        Uses pickle to cache a class method's returned result. Limit is in seconds, limit_mode is the multiplier
        :param limit: int
        :param limit_mode: int
        :return: bytes
        """

        limit = limit * limit_mode

        def wrap(func):

            @functools.wraps(func)
            def memoizer(*args, **kwargs):
                if args:
                    klass, rargs = args[0], args[1:]
                    name = '%s.%s.%s' % (klass.__module__, klass.__class__.__name__, func.__name__)
                else:
                    name = func.__name__
                    rargs = args

                eff = 0 if _debug_bypass() else limit
                cached, payload = self._load(name, rargs, kwargs, limit=eff)
                if cached:
                    return payload

                payload = func(*args, **kwargs)
                if ENABLED and eff > 0:
                    self._save(name, rargs, kwargs, payload)

                return payload

            return memoizer

        return wrap

    def cache_function(self, limit, limit_mode=MINUTES, stale=False,
                       stale_max_hours=6):

        """
        Uses pickle to cache a function's returned result. Limit is in seconds, limit_mode is the multiplier
        :param limit: int
        :param limit_mode: int
        :param stale: bool - when the entry is past its time, hand back the copy
        on disk right away and refresh it behind the listing, so opening a
        listing never waits on YouTube once it has been seen
        :param stale_max_hours: int - never serve a copy older than this
        :return: bytes
        """

        limit = limit * limit_mode

        def wrap(func):

            @functools.wraps(func)
            def memoizer(*args, **kwargs):
                name = func.__name__

                eff = 0 if _debug_bypass() else limit
                cached, payload = self._load(name, args, kwargs, limit=eff)
                if cached:
                    return payload

                if stale and ENABLED and eff > 0:
                    found, old = self._load_stale(
                        name, args, kwargs,
                        oldest=stale_max_hours * 60 * MINUTES)
                    if found:
                        _refresh_in_background(self, func, name, args, kwargs,
                                               eff)
                        return old

                payload = func(*args, **kwargs)
                if ENABLED and eff > 0:
                    self._save(name, args, kwargs, payload)

                return payload

            return memoizer

        return wrap
