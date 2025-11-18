import time
from operator import attrgetter
from threading import Lock


class _CacheValue(object):
    __slots__ = ["_value", "_modified"]

    def __init__(self, value):
        self._value = value
        self._modified = time.time()

    @property
    def modified(self):
        return self._modified

    @property
    def value(self):
        return self._value

    def expired(self, ttl):
        return time.time() - self._modified > ttl

    def update(self):
        self._modified = time.time()


class _HashedTuple(tuple):
    __hash_value = None

    def __hash__(self):
        hash_value = self.__hash_value
        if hash_value is None:
            self.__hash_value = hash_value = super(_HashedTuple, self).__hash__()
        return hash_value

    def __getstate__(self):
        return {}


def _make_key(args, kwargs, typed, kwd_mark=(_HashedTuple,), fast_types=(int, str)):
    """
    Make a cache key from optionally typed positional and keyword arguments

    The key is constructed in a way that is flat as possible rather than
    as a nested structure that would take more memory.

    If there is only a single argument and its data type is known to cache
    its hash value, then that argument is returned without a wrapper.  This
    saves space and improves lookup speed.
    """
    key = args
    sorted_kwargs = tuple(sorted(kwargs.items()))
    if sorted_kwargs:
        key += kwd_mark + sorted_kwargs
    if typed:
        key += tuple(type(v) for v in args)
        if sorted_kwargs:
            key += tuple(type(v) for _, v in sorted_kwargs)
    elif len(key) == 1 and type(key[0]) in fast_types:
        return key[0]
    return _HashedTuple(key)


class LoadingCache(object):
    __slots__ = ["_func", "_store", "_ttl", "_max_size", "_typed", "_lru", "_get_modifier", "_lock"]

    def __init__(self, func, ttl_seconds=60 * 60, max_size=128, typed=False, lru=False):
        self._func = func
        self._store = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._typed = typed
        self._lru = lru
        self._get_modifier = attrgetter("modified")
        self._lock = Lock()

    def get(self, *args, **kwargs):
        key = _make_key(args, kwargs, self._typed)
        with self._lock:
            cache_entry = self._store.get(key)  # type: _CacheValue
            if cache_entry is None:
                # Check cache size first and clean if necessary
                if len(self._store) >= self._max_size:
                    min_key = min(self._store, key=self._get_modifier)
                    del self._store[min_key]
                result = self._func(*args, **kwargs)
                self._store[key] = _CacheValue(result)
            elif cache_entry.expired(self._ttl):
                result = self._func(*args, **kwargs)
                self._store[key] = _CacheValue(result)
            else:
                if self._lru:
                    cache_entry.update()
                result = cache_entry.value

        return result

    def clear(self):
        with self._lock:
            self._store.clear()
