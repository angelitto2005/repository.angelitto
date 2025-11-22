from tmdbhelper.lib.addon.logger import kodi_traceback
from tmdbhelper.lib.files.scache import SimpleCache
import jurialmunkey.bcache

use_simple_cache = jurialmunkey.bcache.use_simple_cache


class BasicCache(jurialmunkey.bcache.BasicCache):
    _queue_limit = 250
    _simplecache = SimpleCache

    @staticmethod
    def kodi_traceback(exc, log_msg):
        kodi_traceback(exc, log_msg)


class BasicCacheService(BasicCache):
    _queue_limit = 20
