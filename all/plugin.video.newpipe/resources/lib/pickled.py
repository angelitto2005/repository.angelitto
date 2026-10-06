# -*- coding: utf-8 -*-

'''
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import functools
import time
import hashlib
import os
import shutil
import pickle
try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

ENABLED = True
SECONDS = 1
MINUTES = 60


# Functions below shamelessly taken and adapted from ResolveURL, so thanks to all of its contributors

class FunctionCache:

    def __init__(self, path, protocol=pickle.HIGHEST_PROTOCOL):
        
        self.path = path

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        self.protocol = protocol

    def reset_cache(self):

        try:
            shutil.rmtree(self.path)
            return True
        except Exception as e:
            return False

    def _get_filename(self, name, args, kwargs):

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
                with open(filename, 'rb') as file_handle:
                    payload = file_handle.read()

                return True, pickle.loads(payload)

        return False, None

    def _save(self, name, args=None, kwargs=None, result=None):

        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        try:
            payload = pickle.dumps(result, protocol=self.protocol)

            filename = os.path.join(self.path, self._get_filename(name, args, kwargs))
            with open(filename, 'wb') as file_handle:
                file_handle.write(payload)

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

                cached, payload = self._load(name, rargs, kwargs, limit=limit)
                if cached:
                    return payload

                payload = func(*args, **kwargs)
                if ENABLED and limit > 0:
                    self._save(name, rargs, kwargs, payload)

                return payload

            return memoizer

        return wrap

    def cache_function(self, limit, limit_mode=MINUTES):

        """
        Uses pickle to cache a function's returned result. Limit is in seconds, limit_mode is the multiplier
        :param limit: int
        :param limit_mode: int
        :return: bytes
        """

        limit = limit * limit_mode

        def wrap(func):

            @functools.wraps(func)
            def memoizer(*args, **kwargs):
                name = func.__name__

                cached, payload = self._load(name, args, kwargs, limit=limit)
                if cached:
                    return payload

                payload = func(*args, **kwargs)
                if ENABLED and limit > 0:
                    self._save(name, args, kwargs, payload)

                return payload

            return memoizer

        return wrap
