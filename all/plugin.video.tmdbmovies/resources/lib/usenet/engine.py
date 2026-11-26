"""One NZB as a byte stream.

The session is what turns "byte 1 234 567 of the film" into "articles 42, 43
and 44 of this release, here decoded": it knows the decoded size of a segment,
which segment covers an offset, and it keeps the last few MB in RAM so a seek
back a few seconds does not hit the network again.

Three shapes are supported:
  * a plain video file (mkv / mp4 / avi / ts) posted as segments;
  * a stored (uncompressed) RAR set, which is what scene TV releases use;
  * a stored 7z set: the 7z header is read, and the biggest file inside - the
    film - is served straight from the volumes when it is stored, not compressed.
    A password-protected 7z set whose files are only AES-wrapped (no
    compression) is decrypted block by block, so seeking still works.
Compressed archives cannot be read sequentially, so they are refused with a
clear reason instead of serving broken bytes.
"""

import queue
import threading
import time
import re
import os
import lzma
import struct
from collections import OrderedDict
from concurrent.futures import CancelledError, Future, as_completed

from . import config, disc, health, nntp, nzb, stats, yenc

HOLE_WARMUP = 20                # articles read before the percentage is trusted
DEFAULT_HOLE_PERCENT = 2.0      # of the articles read may be missing
DEFAULT_HOLE_CONSECUTIVE = 4    # missing articles in a row that already break a film
FAILURES_BEFORE_DOWN = 3        # connection errors in a row before the backup takes over
TRANSIENT_TRIES = 2             # a stalled connection gets one fresh retry
READ_CHUNK = 1024 * 1024
CRYPTO_CHUNK = 1024 * 1024      # plaintext decrypted per read; one block is 16 bytes
MAX_WORKERS = 48                # the box cannot feed more sockets than this
PIPELINE = 2                    # BODY commands per connection before the first answer is read
WORKER_MARGIN = 8               # extra articles queued so no worker sits idle
HARD_PREFETCH_BYTES = 96 * 1024 * 1024
CACHE_MARGIN_BYTES = 32 * 1024 * 1024
PREFETCH_PER_SLOT_BYTES = 1536 * 1024
JOIN_SECONDS = 0.6              # total time close() may spend joining its threads
SEEK_LOG_BYTES = 16 * 1024 * 1024   # a read this far from the last one is a seek
INDEX_TAIL_BYTES = 8 * 1024 * 1024  # Kodi reads the MKV index here; that is not a seek
WARM_ARTICLES = 4               # first articles kept beside the plan: the pool is still dialing when playback starts
LOW_CORE_CORES = 4                  # small Android boxes: more workers than this stop helping
LOW_CORE_WORKERS = 24               # ... but every configured connection may still feed a pipelined worker
LOW_CORE_PREFETCH_BYTES = 24 * 1024 * 1024
LOW_CORE_CACHE_BYTES = 36 * 1024 * 1024
PROFILE_AUTO = 0                    # cores decide (the old behaviour)
PROFILE_LOW = 1                     # force the small-box numbers
PROFILE_FAST = 2                    # force the large numbers
PROFILE_CUSTOM = 3                  # the sliders decide, no low-core clamp
PROFILE_NAMES = ('auto', 'low-end', 'fast', 'custom')
FAST_PREFETCH_BYTES = 64 * 1024 * 1024
FAST_CACHE_BYTES = 128 * 1024 * 1024


def _cores():
    try:
        return os.cpu_count() or LOW_CORE_CORES
    except Exception:
        return LOW_CORE_CORES


class SessionError(Exception):
    """The release cannot be played (and the reason is worth showing)."""


def _log(message, warning=False):
    try:
        import xbmc
        xbmc.log('[TMDb Movies] [Usenet] ' + message,
                 xbmc.LOGWARNING if warning else xbmc.LOGINFO)
    except Exception:
        pass


_ISO_ID = (b'CD001', b'BEA01', b'NSR02', b'NSR03')
_ISO_SECTOR = 32768
_INNER_RAR_NAME = re.compile(r'\.(?:part\d+\.rar|rar|r\d{2,3})$', re.I)
_INNER_SEVEN_NAME = re.compile(r'\.7z(?:\.\d+)?$', re.I)


def _seven_name_key(name):
    match = re.search(r'\.7z\.(\d+)$', name or '', re.I)
    return int(match.group(1)) if match else 0


def _sniff(data, start=0):
    if not data or start < 0:
        return ''
    at = start + _ISO_SECTOR
    if len(data) >= at + 6 and data[at + 1:at + 6] in _ISO_ID:
        return 'iso'
    if data[start:start + 4] == b'\x1a\x45\xdf\xa3':
        return 'mkv'
    if len(data) > start + 12 and data[start + 4:start + 8] == b'ftyp':
        return 'mp4'
    if data[start:start + 4] == b'RIFF' and data[start + 8:start + 12] == b'AVI ':
        return 'avi'
    if len(data) > start + 200 and data[start] == 0x47 and data[start + 188] == 0x47:
        return 'ts'
    if len(data) > start + 200 and data[start + 4] == 0x47 and data[start + 196] == 0x47:
        return 'ts'
    return ''


def _looks_image(data, start=0):
    chunk = data[start:start + 16]
    if chunk.startswith(b'\xff\xd8\xff'):
        return True
    if chunk.startswith(b'\x89PNG\r\n\x1a\n'):
        return True
    if chunk[:6] in (b'GIF87a', b'GIF89a'):
        return True
    if chunk[:2] == b'BM':
        return True
    if chunk[:4] == b'RIFF' and chunk[8:12] == b'WEBP':
        return True
    if chunk[:4] in (b'II*\x00', b'MM\x00*'):
        return True
    return False


def _vint_len(number):
    """Bytes a RAR5 variable-length integer takes (the volume number grows)."""
    length = 1
    while number >= 0x80:
        number >>= 7
        length += 1
    return length


class _Workers(object):
    """Daemon threads only: Kodi must never wait for a read that is still running.

    ThreadPoolExecutor keeps non-daemon threads, and threading._shutdown() joins
    them at interpreter exit - that is what leaves Kodi hanging for five seconds.
    These threads are daemon, and close() wakes them instead of letting a socket
    timeout hold the process.
    """

    def __init__(self, count, prefix='UsenetRead'):
        self.jobs = queue.Queue()
        self.threads = []
        self.closed = False
        self.lock = threading.Lock()
        for index in range(max(1, count)):
            thread = threading.Thread(target=self._loop, name='%s%d' % (prefix, index))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)

    def _loop(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            future, function, args = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args))
            except BaseException as error:
                future.set_exception(error)

    def submit(self, function, *args):
        future = Future()
        with self.lock:
            if self.closed:
                future.cancel()
                return future
            self.jobs.put((future, function, args))
        return future

    def close(self):
        """Drop queued work and give the running reads one short, shared budget."""
        with self.lock:
            self.closed = True
            while True:
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
                try:
                    job[0].cancel()
                except Exception:
                    pass
            for _ in self.threads:
                self.jobs.put(None)
        deadline = time.time() + JOIN_SECONDS
        for thread in self.threads:
            left = deadline - time.time()
            if left <= 0:
                break
            thread.join(left)

class _Pool(object):
    """The connections of one provider, capped at its limit."""

    def __init__(self, provider):
        self.provider = provider
        self.limit = max(1, int(provider.get('connections') or 4))
        self.idle = []
        self.count = 0
        self.dead = False
        self.failures = 0
        self.last_narrow = 0.0
        self.urgent = 0
        self.lock = threading.Lock()

    @property
    def label(self):
        return str(self.provider.get('label') or self.provider.get('host') or 'provider')

    def narrow(self):
        """The provider refused a connection: use fewer until it stops refusing."""
        with self.lock:
            now = time.time()
            if now - self.last_narrow < 1.0:
                return None
            self.last_narrow = now
            before = self.limit
            self.limit = max(1, min(self.limit - 1, max(1, self.count)))
            return self.limit if self.limit != before else None

    def has_room(self):
        """A connection is idle, or one more can be opened right now."""
        with self.lock:
            return not self.dead and (bool(self.idle) or self.count < self.limit)

    def acquire(self, urgent=False):
        """A connection for a prefetch or, with urgent, for the player right now.

        Prefetch sleeps a little longer while a read waits, so the article Kodi
        asked for takes the next free connection instead of competing with the
        eight articles read-ahead queued before it.
        """
        if urgent:
            with self.lock:
                self.urgent += 1
        try:
            while True:
                with self.lock:
                    if self.dead:
                        raise nntp.NntpError('provider is marked as down')
                    if self.idle:
                        return self.idle.pop()
                    if self.count < self.limit:
                        self.count += 1
                        break
                    wait = 0.05 if self.urgent and not urgent else 0.03
                time.sleep(wait)
            try:
                return nntp.Connection(self.provider['host'], self.provider['port'],
                                       self.provider.get('user', ''),
                                       self.provider.get('password', ''),
                                       self.provider.get('ssl', True),
                                       self.provider.get('timeout') or 20)
            except Exception:
                with self.lock:
                    self.count -= 1
                raise
        finally:
            if urgent:
                with self.lock:
                    self.urgent -= 1

    def release(self, connection):
        with self.lock:
            if self.dead:
                drop = True
            else:
                drop = False
                self.idle.append(connection)
        if drop:
            self.discard(connection)

    def discard(self, connection):
        try:
            connection.abort()
        except Exception:
            pass
        with self.lock:
            self.count = max(0, self.count - 1)

    def close(self):
        with self.lock:
            self.dead = True
            idle, self.idle = self.idle, []
            self.count = 0
        for connection in idle:
            try:
                connection.abort()
            except Exception:
                pass


class Session(object):
    def __init__(self, key, data, providers, options=None):
        self.key = key
        self.data = data
        self.options = options or {}
        self.pools = [_Pool(item) for item in providers if item]
        if not self.pools:
            raise SessionError('no Usenet provider is configured')
        connections = sum(pool.limit for pool in self.pools)
        cores = _cores()
        profile = int(self.options.get('profile') or PROFILE_AUTO)
        profile = max(PROFILE_AUTO, min(PROFILE_CUSTOM, profile))
        low_core = cores <= LOW_CORE_CORES
        worker_cap = MAX_WORKERS
        if profile == PROFILE_LOW or (profile == PROFILE_AUTO and low_core):
            worker_cap = min(worker_cap, LOW_CORE_WORKERS)
        self.worker_target = max(1, min(worker_cap, connections))
        self.pipeline = max(1, int(self.options.get('pipeline') or PIPELINE))
        self.timeout = int(self.options.get('timeout') or 20)
        prefetch = int(self.options.get('prefetch_bytes') or 12 * 1024 * 1024)
        cache = int(self.options.get('cache_bytes') or 36 * 1024 * 1024)
        if profile == PROFILE_LOW or (profile == PROFILE_AUTO and low_core):
            prefetch = min(prefetch, LOW_CORE_PREFETCH_BYTES)
            cache = min(cache, LOW_CORE_CACHE_BYTES)
        elif profile == PROFILE_FAST:
            prefetch = FAST_PREFETCH_BYTES
            cache = FAST_CACHE_BYTES
        self.prefetch_bytes = max(prefetch, min(HARD_PREFETCH_BYTES,
                                                self.worker_target * self.pipeline * PREFETCH_PER_SLOT_BYTES))
        self.cache_limit = max(cache, self.prefetch_bytes + CACHE_MARGIN_BYTES)
        self.profile = profile
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.lock = threading.RLock()
        self.parts = []
        self.length = 0
        self.plan_length = 0
        self.crypto = None
        self.container = ''
        self.hole_filling = bool(self.options.get('hole_filling', True))
        self.hole_percent = float(self.options.get('hole_percent',
                                     DEFAULT_HOLE_PERCENT) or 0)
        self.hole_consecutive = int(self.options.get('hole_consecutive',
                                                     DEFAULT_HOLE_CONSECUTIVE) or 0)
        self.missing = 0
        self.missing_report = []
        self.segments = 0
        self.missing_run = 0
        self.longest_run = 0
        self._served = None
        self.served_counts = {}
        self.served_bytes = {}
        self.served_seconds = {}
        self._primary_cleared = False
        self._closing = False
        self._generation = 0
        self._last_start = None
        self.article_seconds = 0.0
        self.read_errors = 0
        self._pending = {}
        self._tail_keys = set()
        self._pinned = set()
        self._workers = None
        self.media_name = ''
        self.inner_name = ''
        self.pack = {}
        self.last_read = time.time()
        self.prepared = False
        self.first_crc_ok = True
        self.warm = []
        self._heads = {}
        self._loading = {}

    # -- prepare -----------------------------------------------------------

    def _refused(self, pool):
        limit = pool.narrow()
        if limit:
            _log('%s refused a connection - using at most %d now' % (pool.label, limit),
                 warning=True)

    def _pool_order(self):
        """Primary first; a full provider steps aside for one with room.

        The backup is meant for failures, but when the primary refuses extra
        connections its pool fills and every worker waits on it while the
        other provider sits idle. Choosing by free capacity keeps both busy.
        """
        live = [pool for pool in self.pools if not pool.dead]
        for pool in live:
            if pool.has_room():
                return [pool] + [item for item in live if item is not pool]
        return live

    def _articles(self, message_ids, urgent=False):
        """The raw articles for a batch of ids, from the provider with room.

        The whole batch travels one connection: every BODY is sent before the
        first answer is read, so two articles cost roughly one round trip
        instead of two. A timeout or a dropped connection is retried once on a
        fresh connection; only a 430 is treated as a real hole, and that id
        stays for the backup provider. The result keeps the order given.
        """
        wanted = list(message_ids)
        found = [None] * len(wanted)
        left = list(range(len(wanted)))
        report = []
        for pool in self._pool_order():
            if not left:
                break
            if pool.dead:
                continue
            for attempt in range(TRANSIENT_TRIES):
                try:
                    connection = pool.acquire(urgent)
                except nntp.TooMany:
                    self._refused(pool)
                    if attempt + 1 < TRANSIENT_TRIES:
                        time.sleep(0.2)
                        continue
                    break
                except nntp.AuthError:
                    pool.dead = True
                    if not pool.provider.get('backup'):
                        config.mark_primary_down()
                    _log('%s refused the login - switching provider' % pool.label,
                         warning=True)
                    break
                except Exception as exc:
                    report.append('%s: %s' % (pool.label, type(exc).__name__))
                    break
                attempt_started = time.time()
                first_reply = []
                try:
                    replies = connection.body_many([wanted[slot] for slot in left],
                                                   timing=first_reply)
                except nntp.AuthError:
                    pool.discard(connection)
                    pool.dead = True
                    if not pool.provider.get('backup'):
                        config.mark_primary_down()
                    break
                except nntp.TooMany:
                    pool.discard(connection)
                    self._refused(pool)
                    if attempt + 1 < TRANSIENT_TRIES:
                        time.sleep(0.2)
                        continue
                    break
                except Exception as exc:
                    pool.discard(connection)
                    pool.failures += 1
                    report.append('%s: %s' % (pool.label, type(exc).__name__))
                    if attempt + 1 < TRANSIENT_TRIES:
                        continue
                    if (pool.failures >= FAILURES_BEFORE_DOWN
                            and not pool.provider.get('backup')):
                        config.mark_primary_down()
                    break
                pool.release(connection)
                pool.failures = 0
                elapsed = time.time() - attempt_started
                delivered = [(slot, reply[2]) for slot, reply in zip(left, replies)
                             if reply[2] is not None]
                if delivered:
                    delivered_bytes = sum(len(payload) for _slot, payload in delivered)
                    with self.lock:
                        seen = self.served_counts.get(pool.label, 0)
                        self.served_counts[pool.label] = seen + len(delivered)
                        self.served_bytes[pool.label] = (
                            self.served_bytes.get(pool.label, 0) + delivered_bytes)
                        self.served_seconds[pool.label] = (
                            self.served_seconds.get(pool.label, 0.0) + elapsed)
                        clear = (not pool.provider.get('backup')
                                 and not self._primary_cleared)
                        if clear:
                            self._primary_cleared = True
                    try:
                        stats.provider(pool.provider.get('host') or pool.label,
                                       b=delivered_bytes, a=len(delivered),
                                       m=len(replies) - len(delivered),
                                       ln=1,
                                       ls=(first_reply[0] - attempt_started
                                           if first_reply else elapsed),
                                       busy=elapsed)
                    except Exception:
                        pass
                    if not seen:
                        self._served = pool
                        config.mark_served(pool.provider)
                        _log('serving from %s' % pool.label)
                    if clear:
                        config.clear_primary_down()
                remaining = []
                for slot, reply in zip(left, replies):
                    if reply[2] is None:
                        remaining.append(slot)
                        report.append('%s: %d' % (pool.label, reply[1]))
                    else:
                        found[slot] = reply[2]
                left = remaining
                break
        self.missing_report = report
        return found

    def _article(self, message_id, urgent=False):
        return self._articles([message_id], urgent)[0]

    def _decode_first(self, segments):
        article = self._article(segments[0][2] if isinstance(segments[0], tuple) else segments[0])
        if article is None:
            detail = ', '.join(self.missing_report) or 'no provider answered'
            raise SessionError('the first article of this release is gone from the provider (%s)' % detail)
        try:
            return yenc.decode(article)
        except yenc.YencError as exc:
            raise SessionError('the provider did not send yEnc (%s)' % exc)

    def _split_size(self, part):
        """The exact file size of one numbered part, from its first article header."""
        segment = part.segments[0]
        message_id = segment[2] if isinstance(segment, tuple) else segment
        for pool in self._pool_order():
            if pool.dead:
                continue
            for attempt in range(TRANSIENT_TRIES):
                try:
                    connection = pool.acquire(True)
                except nntp.TooMany:
                    self._refused(pool)
                    break
                except nntp.AuthError:
                    pool.dead = True
                    if not pool.provider.get('backup'):
                        config.mark_primary_down()
                    _log('%s refused the login - switching provider' % pool.label,
                         warning=True)
                    break
                except Exception:
                    break
                try:
                    size = connection.head_size(message_id)
                except nntp.Missing:
                    pool.discard(connection)
                    break
                except Exception:
                    pool.discard(connection)
                    if attempt + 1 < TRANSIENT_TRIES:
                        continue
                    break
                pool.discard(connection)
                if size > 0:
                    return size
        raise SessionError('a numbered video part could not be sized')

    def _seven_read(self, volume_map, cache, offset, size):
        """Bytes from the concatenated 7z volumes, fetching only what is asked.

        Offsets are decoded bytes: the NZB lists yEnc article sizes, which are
        larger, and using those drifts until the header lands in the wrong article.
        """
        out = []
        while size > 0:
            low, high = 0, len(volume_map) - 1
            while low < high:
                middle = (low + high + 1) // 2
                if volume_map[middle]['start'] <= offset:
                    low = middle
                else:
                    high = middle - 1
            volume = volume_map[low]
            inside = offset - volume['start']
            segments = volume['file'].segments
            part = volume.get('part_size') or 0
            if inside < 0 or inside >= volume['size'] or not segments or part <= 0:
                break
            index = min(inside // part, len(segments) - 1)
            begin = inside - index * part
            progressed = False
            while size > 0 and inside < volume['size'] and index < len(segments):
                mid = segments[index][2]
                data = cache.get(mid)
                if data is None:
                    raw = self._article(mid)
                    if raw is None:
                        raise SessionError('a 7z header article is gone from the provider')
                    try:
                        data = yenc.decode(raw)['data']
                    except yenc.YencError as exc:
                        raise SessionError('the provider did not send yEnc (%s)' % exc)
                    cache[mid] = data
                if begin >= len(data):
                    step = max(1, part - begin)
                    offset += step
                    inside += step
                    index += 1
                    begin = 0
                    continue
                take = min(len(data) - begin, size, volume['size'] - inside)
                if take <= 0:
                    break
                out.append(data[begin:begin + take])
                size -= take
                offset += take
                inside += take
                index += 1
                begin = 0
                progressed = True
            if not progressed:
                break
        return b''.join(out)

    def _warm_front(self, segments, keep=True):
        """Keep the next few articles beside the first one.

        The reader is sequential: while the connection pool is still being
        dialed, one late article at the very start holds up the whole open
        even when everything after it has already arrived.
        """
        if keep:
            self.warm = []
        wanted = [(index, item[2] if isinstance(item, tuple) else item)
                  for index, item in enumerate(segments[1:WARM_ARTICLES], start=1)]
        if not wanted:
            return
        replies = self._articles([message_id for _index, message_id in wanted])
        collected = []
        for (index, message_id), article in zip(wanted, replies):
            if article is None:
                continue
            try:
                info = yenc.decode(article)
            except yenc.YencError:
                continue
            collected.append((index, message_id, info['data']))
            self._remember((0, index), info['data'])
        if keep:
            self.warm = collected

    def _warm_front_later(self, segments):
        """Fill the first articles behind the caller.

        An encrypted 7z is served by the local server and never gets a plan,
        so nothing waits on the warm articles: the player asks for them a few
        seconds later, by which time the cache has them.
        """
        try:
            self._workers_for_reads().submit(self._warm_front, list(segments), False)
        except Exception:
            pass

    def _warm_tail_later(self):
        """Size the last volume behind the caller, then fetch the tail article.

        _warm_tail reads the first article of the last volume only to learn its
        stride, and that read holds up the open for half a second. The tail is a
        prefetch, so the same work starts in a worker while the player is set up.
        """
        try:
            self._workers_for_reads().submit(self._warm_tail)
        except Exception:
            pass

    def _episode_guard(self, name):
        """A source that names another episode must not play the wrong one."""
        wrong = nzb.episode_mismatch(
            name, self.options.get('season'), self.options.get('episode'),
            self.options.get('alt_season'), self.options.get('alt_episode'))
        if not wrong:
            return
        try:
            wanted = 'S%02dE%02d' % (int(self.options.get('season')),
                                    int(self.options.get('episode')))
        except (TypeError, ValueError):
            wanted = 'the requested episode'
        raise SessionError('this release holds S%02dE%02d, not %s'
                           % (wrong[0], wrong[1], wanted))

    def _check_health(self, files, media, kind):
        """A quick STAT sample before opening: refuse a release the provider lost.
        The full check stays in the source list; waiting for it added 15-20 s here."""
        ids = health.media_ids(files, media, kind)
        if not ids:
            return
        result = health.check_ids(ids, [pool.provider for pool in self.pools],
                                  seconds=3, full=False,
                                  key=self.options.get('health_key') or self.key)
        if not result:
            return
        _log('health sample: %s, %d of %d articles checked, %d gone, %.1fs'
             % (result.get('status'), result.get('checked', 0),
                result.get('total', 0), result.get('gone', 0),
                result.get('seconds', 0)))
        if not health.playable(result):
            if result.get('status') == 'dead' and result.get('checked', 0) <= 1:
                raise SessionError('this release is gone from the provider '
                                   '(its first article is missing)')
            if result.get('status') == 'dead':
                raise SessionError('most articles of this release are gone from the provider')
            raise SessionError('this release is missing %d of %d articles on the provider'
                               % (result.get('gone', 0), result.get('total', 0)))

    def _wanted_pairs(self):
        pairs = []
        for season, episode in ((self.options.get('season'), self.options.get('episode')),
                                (self.options.get('alt_season'), self.options.get('alt_episode'))):
            try:
                pair = (int(season), int(episode))
            except (TypeError, ValueError):
                continue
            if pair not in pairs:
                pairs.append(pair)
        return pairs

    def _volume_bytes(self, volume, offset, length, head=b''):
        """Bytes from anywhere in one posted volume, before any part exists."""
        segments = volume.segments
        if not segments or offset < 0:
            return b''
        if not head:
            head = self._decode_first(segments).get('data') or b''
        part = len(head)
        if part <= 0:
            return b''
        out = []
        while length > 0:
            number, skip = divmod(offset, part)
            if number >= len(segments):
                break
            data = head if number == 0 else None
            if data is None:
                raw = self._article(segments[number][2])
                if raw is None:
                    break
                try:
                    data = yenc.decode(raw)['data']
                except yenc.YencError:
                    break
            chunk = data[skip:skip + length]
            if not chunk:
                break
            out.append(chunk)
            offset += len(chunk)
            length -= len(chunk)
        return b''.join(out)

    def _head_of(self, volume):
        """The first article of one volume, decoded once per session."""
        message = volume.segments[0][2]
        with self.lock:
            kept = self._heads.get(message)
            if kept is not None:
                return kept
            waiting = self._loading.get(message)
            owner = waiting is None
            if owner:
                waiting = threading.Event()
                self._loading[message] = waiting
        if not owner:
            # Another read is already fetching this article; do not download
            # the same 768 KB twice when the walk runs ahead of itself.
            waiting.wait(self.timeout + 5)
            with self.lock:
                kept = self._heads.get(message)
            if kept is not None:
                return kept
        try:
            info = self._decode_first(volume.segments)
            kept = (info.get('data') or b'', bool(info.get('crc_ok', True)))
            with self.lock:
                self._heads[message] = kept
            return kept
        finally:
            with self.lock:
                if self._loading.get(message) is waiting:
                    self._loading.pop(message, None)
            waiting.set()

    def _prefetch_heads(self, volumes, numbers):
        """Read the first article of these volumes in parallel.

        Locating an episode inside a season pack walks the volumes in order, and
        one round trip per volume is what makes that slow on a 40 volume set.
        """
        targets = []
        for number in numbers:
            if number >= len(volumes) or not volumes[number].segments:
                continue
            with self.lock:
                if volumes[number].segments[0][2] in self._heads:
                    continue
            targets.append(number)
        if not targets:
            return
        workers = self._workers_for_reads()
        futures = [workers.submit(self._head_of, volumes[number]) for number in targets]
        for future in futures:
            try:
                future.result()
            except Exception:
                continue

    def _rar_part_size(self, volume, index, layout):
        """Packed bytes of the film inside one volume, from its own header.

        Subjects that do not declare the decoded size make nzb.file_size
        report the encoded total, so lengths computed from it drift by a few
        KB per volume. The header inside the volume is exact.
        """
        fallback = int(layout.get('length') or 0)
        try:
            head, _crc = self._head_of(volume)
            entries = nzb.rar_entries(head)
        except Exception:
            return fallback
        for entry in entries:
            if entry.get('before'):
                size = int(entry.get('length') or 0)
                if size > 0:
                    self._remember((index, 0), head)
                    return size
        return fallback

    def _image_read(self, offset, count):
        """Bytes of the current plan, for the disc reader."""
        out = []
        while count > 0:
            index, local = self._locate(offset)
            if index >= len(self.parts):
                break
            part = self.parts[index]
            stride = self._part_size(part)
            room = min(count, part['length'] - local, stride * 2)
            if stride <= 0 or room <= 0:
                break
            position = part['skip'] + local
            number = position // stride
            if number >= len(part['segments']):
                break
            chunk = self._segment(part, number, self._generation)
            piece = chunk[position - number * stride:][:room]
            if not piece:
                break
            out.append(piece)
            offset += len(piece)
            count -= len(piece)
        return b''.join(out)

    def _slice_extents(self, extents):
        """The plan for a file that sits in pieces inside the current plan."""
        spans = []
        walked = 0
        for part in list(self.parts):
            spans.append((walked, walked + part['length'], part))
            walked += part['length']
        out = []
        for offset, length in extents:
            end = offset + length
            for start, stop, part in spans:
                low = max(offset, start)
                high = min(end, stop)
                if high <= low:
                    continue
                stride = self._part_size(part)
                if stride <= 0:
                    continue
                position = part['skip'] + low - start
                first = position // stride
                last = (part['skip'] + high - start - 1) // stride
                segments = part['segments'][first:last + 1]
                if not segments:
                    continue
                out.append({'id': 1000 + len(out), 'segments': segments,
                            'skip': position - first * stride,
                            'length': high - low, 'part_size': stride})
        return out

    def _disc_plan(self):
        """Serve the feature inside a disc image instead of the whole image."""
        image_length = self.length
        try:
            found = disc.feature(
                lambda offset, count: self._image_read(offset, count), image_length)
        except Exception as exc:
            raise SessionError('this disc image could not be read (%s)' % str(exc)[:80])
        if not found:
            raise SessionError('this disc image has no playable video inside')
        parts = self._slice_extents(found['extents'])
        if not parts:
            raise SessionError('the film on this disc lies outside the release')
        with self.lock:
            self.cache.clear()
            self.cache_bytes = 0
        self._pinned = set()
        self.parts = parts
        self.length = sum(part['length'] for part in parts)
        self.inner_name = found['name']
        self.container = 'm2ts' if found['name'].lower().endswith('.m2ts') else 'ts'
        self.part_size = 0
        try:
            head = self._decode_first(self.parts[0]['segments'])['data']
            self._pinned.add((self.parts[0]['id'], 0))
            self._remember((self.parts[0]['id'], 0), head)
        except Exception:
            pass
        _log('disc: %s, %.2f GB of a %.2f GB image, %d piece(s)'
             % (self.inner_name, self.length / 1073741824.0,
                image_length / 1073741824.0, len(found['extents'])))
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _archive_files(self, fmt):
        """(name, parts, length) for the stored files of this archive.

        The current plan is the archive itself, so the headers are read through
        it and every file comes back in storage order with its real offset.
        """
        spans = []
        walked = 0
        for part in self.parts:
            spans.append((walked, walked + part['length']))
            walked += part['length']
        files = []
        by_name = {}
        for start, stop in spans:
            head = self._image_read(start, 16384)
            if not head:
                continue
            try:
                batch = nzb.rar_entries(head)
            except nzb.Unsupported:
                break
            while batch:
                for entry in batch:
                    name = (entry.get('name') or '').strip()
                    length = int(entry.get('length') or 0)
                    offset = start + int(entry.get('offset') or 0)
                    if entry.get('before'):
                        item = by_name.get(name)
                        if item is not None and length > 0:
                            item['parts'].append((offset, length))
                            item['length'] += length
                        continue
                    if not name:
                        continue
                    item = {'name': name, 'parts': [(offset, length)] if length > 0 else [],
                            'length': length}
                    files.append(item)
                    by_name[name] = item
                last = batch[-1]
                if last.get('more'):
                    break
                following = int(last.get('offset') or 0) + int(last.get('length') or 0)
                if following <= 0 or start + following + 64 > stop:
                    break
                blob = self._image_read(start + following, 16384)
                if not blob:
                    break
                entry = nzb.rar_entry_at(blob, fmt)
                if entry is None:
                    break
                entry['offset'] = int(entry.get('offset') or 0) + following
                entry['next_offset'] = int(entry.get('next_offset') or 0) + following
                batch = [entry]
        return files

    def _outer_plan(self, volumes):
        """The whole outer archive as one plan: every volume from its first byte.

        The inner archive volumes are stored *inside* these bytes, so the nested
        reader has to see the outer headers as well; a plan made of the first
        stored file alone would hide all the other inner volumes.
        """
        sizes = {}
        unknown = [index for index, volume in enumerate(volumes[:400])
                   if not nzb.declared_size(volume)]
        if unknown:
            workers = self._workers_for_reads()
            futures = {workers.submit(self._split_size, volumes[index]): index
                       for index in unknown}
            for future in as_completed(futures):
                index = futures.pop(future)
                try:
                    sizes[index] = int(future.result() or 0)
                except Exception:
                    sizes[index] = 0
        parts = []
        total = 0
        for index, volume in enumerate(volumes[:400]):
            size = sizes.get(index) or nzb.file_size(volume)
            if size <= 0:
                raise SessionError('an outer archive volume could not be sized')
            parts.append({'id': index,
                          'segments': [item[2] for item in volume.segments],
                          'skip': 0, 'length': size, 'part_size': 0})
            total += size
        if not parts:
            raise SessionError('this release has no outer archive volume')
        with self.lock:
            self.cache.clear()
            self.cache_bytes = 0
        self._pinned = set()
        self.parts = parts
        self.length = total
        self.part_size = 0

    def _outer_nested(self, entries, head):
        """True when this RAR stores another archive instead of the film."""
        for entry in entries:
            name = entry.get('name') or ''
            if nzb.kind_of(name) == 'video' \
                    and int(entry.get('unp_size') or 0) >= nzb.MIN_INNER_VIDEO_BYTES:
                return False
        for entry in entries:
            name = entry.get('name') or ''
            if _INNER_RAR_NAME.search(name) or _INNER_SEVEN_NAME.search(name):
                if not entry.get('store'):
                    raise SessionError('the archive inside this RAR is compressed')
                return True
            offset = int(entry.get('offset') or 0)
            if int(entry.get('length') or 0) >= nzb.MIN_INNER_VIDEO_BYTES \
                    and 0 <= offset and offset + 8 <= len(head):
                magic = head[offset:offset + 8]
                if magic.startswith(nzb.RAR4) or magic.startswith(nzb.RAR5) \
                        or magic.startswith(nzb.SEVEN):
                    if not entry.get('store'):
                        raise SessionError('the archive inside this RAR is compressed')
                    return True
        return False

    @staticmethod
    def _archive_stem(name, kind):
        pattern = r'\.7z(?:\.\d+)?$' if kind == '7z' else \
            r'\.(?:part\d+\.rar|rar|r\d{2,3})$'
        return re.sub(pattern, '', (name or '').lower(), flags=re.I)

    def _inner_archive(self, files):
        """(kind, volumes) of the archive set stored inside the current plan."""
        wanted = set(self._wanted_pairs())
        best = None
        for kind, pattern in (('rar', _INNER_RAR_NAME), ('7z', _INNER_SEVEN_NAME)):
            groups = {}
            for item in files:
                if pattern.search(item['name'] or '') and item['parts']:
                    groups.setdefault(self._archive_stem(item['name'], kind), []).append(item)
            for volumes in groups.values():
                total = sum(volume['length'] for volume in volumes)
                if total < nzb.MIN_INNER_VIDEO_BYTES:
                    continue
                pairs = nzb.episode_pairs(
                    ' '.join(volume['name'] or '' for volume in volumes))
                score = (bool(wanted) and bool(wanted & set(pairs)), total)
                if best is None or score > best[0]:
                    best = (score, kind, volumes)
        if best is None:
            return '', []
        _score, kind, volumes = best
        if kind == 'rar':
            volumes.sort(key=lambda item: nzb.volume_key(item['name']))
        else:
            volumes.sort(key=lambda item: _seven_name_key(item['name']))
        return kind, volumes

    def _nested_plan(self):
        """The film inside a stored archive that was posted in the film's place."""
        head = self._image_read(0, 512)
        if head.startswith(nzb.RAR4) or head.startswith(nzb.RAR5):
            fmt = 4 if head.startswith(nzb.RAR4) else 5
            try:
                files = self._archive_files(fmt)
            except nzb.Unsupported as exc:
                raise SessionError(str(exc))
            kind, volumes = self._inner_archive(files)
            if not volumes:
                return self._plan_archive_itself(fmt)
            if kind == 'rar':
                return self._plan_inner_rar(volumes)
            return self._plan_inner_seven(volumes)
        if head.startswith(nzb.SEVEN):
            return self._plan_self_seven()
        raise SessionError('this release holds an archive inside an archive '
                           'that cannot be streamed')

    def _plan_archive_itself(self, fmt):
        """The current plan is one archive file: serve the film stored inside it."""
        head = self._image_read(0, 512)
        try:
            layout = nzb.rar_layout(head)
        except nzb.Unsupported as exc:
            raise SessionError('the archive inside this release: %s' % exc)
        if not layout.get('store'):
            raise SessionError('the archive inside this release is compressed')
        total = int(layout.get('unp_size') or 0)
        if total < nzb.MIN_INNER_VIDEO_BYTES:
            raise SessionError('the file inside this archive is too small to be the film')
        name = (layout.get('name') or '').strip()
        self._episode_guard(name)
        length = int(layout.get('length') or 0)
        if length < total:
            raise SessionError('the archive inside this release needs its other volumes')
        return self._install_inner([(int(layout['offset']), length)], total, name)

    def _plan_inner_rar(self, volumes):
        """A RAR set stored inside the current plan, served volume by volume."""
        try:
            layout = nzb.rar_layout(self._image_read(volumes[0]['parts'][0][0], 16384))
        except nzb.Unsupported as exc:
            raise SessionError('the archive inside this release: %s' % exc)
        if not layout.get('store'):
            raise SessionError('the archive inside this release is compressed')
        total = int(layout.get('unp_size') or 0)
        if total < nzb.MIN_INNER_VIDEO_BYTES:
            raise SessionError('the file inside this archive is too small to be the film')
        name = (layout.get('name') or '').strip()
        self._episode_guard(name)
        starts = []
        walked = 0
        for volume in volumes:
            starts.append(walked)
            walked += volume['length']

        def pieces(inner_start, size):
            """Outer ranges of one inner range, with every volume header taken out."""
            out = []
            while size > 0:
                number = 0
                while number + 1 < len(volumes) and starts[number + 1] <= inner_start:
                    number += 1
                local = inner_start - starts[number]
                for outer_start, outer_len in volumes[number]['parts']:
                    if local >= outer_len:
                        local -= outer_len
                        continue
                    take = min(size, outer_len - local)
                    out.append((outer_start + local, take))
                    inner_start += take
                    size -= take
                    break
                else:
                    raise SessionError('the volumes inside this release do not add up')
            return out

        extents = []
        remaining = total
        for index, volume in enumerate(volumes[:400]):
            start = starts[index]
            if not index:
                offset = int(layout['offset'])
                size = min(int(layout['length']), remaining)
            else:
                # Fiecare volum intern isi spune singur unde incepe partea lui,
                # deci nu trebuie ghicit din headerul primului volum.
                try:
                    entry = next((item for item in nzb.rar_entries(
                        self._image_read(volume['parts'][0][0], 16384))
                        if item.get('before')), None)
                except nzb.Unsupported:
                    entry = None
                if entry is None:
                    raise SessionError('the volumes inside this release do not add up')
                offset = int(entry['offset'])
                size = min(int(entry['length']), remaining)
            if size <= 0:
                raise SessionError('the volumes inside this release do not add up')
            extents.extend(pieces(start + offset, size))
            remaining -= size
            if remaining <= 0:
                break
        if remaining > 0:
            raise SessionError('the volumes inside this release are shorter than the film')
        return self._install_inner(extents, total, name)

    def _plan_inner_seven(self, volumes):
        """A 7z set stored inside the current plan, served straight from its volumes."""
        starts = []
        walked = 0
        for volume in volumes:
            starts.append(walked)
            walked += volume['length']
        total_archive = walked
        if total_archive < 32:
            raise SessionError('the 7z inside this release is empty')

        def pieces(inner_start, size):
            out = []
            while size > 0:
                number = 0
                while number + 1 < len(volumes) and starts[number + 1] <= inner_start:
                    number += 1
                local = inner_start - starts[number]
                for outer_start, outer_len in volumes[number]['parts']:
                    if local >= outer_len:
                        local -= outer_len
                        continue
                    take = min(size, outer_len - local)
                    out.append((outer_start + local, take))
                    inner_start += take
                    size -= take
                    break
                else:
                    raise SessionError('the 7z volumes inside this release do not add up')
            return out

        def read_inner(offset, size):
            out = []
            while size > 0:
                ranges = pieces(offset, size)
                if not ranges:
                    break
                moved = 0
                for outer_start, take in ranges:
                    chunk = self._image_read(outer_start, take)
                    if len(chunk) < take:
                        raise SessionError('the 7z inside this release could not be read')
                    out.append(chunk)
                    offset += take
                    size -= take
                    moved += take
                if not moved:
                    break
            return b''.join(out)

        head = read_inner(0, 32)
        if not head.startswith(nzb.SEVEN):
            raise SessionError('not a 7z archive inside this release')
        try:
            next_offset, next_size = struct.unpack_from('<QQ', head, 12)
            if next_size <= 0:
                raise SessionError('the 7z header is missing from the archive')
            tail = read_inner(32 + next_offset, next_size)
            if len(tail) < next_size:
                raise SessionError('the 7z header is incomplete - a volume is missing')
            header = nzb.seven_read_header(
                tail, lambda offset, size: read_inner(32 + offset, size))
            streams = nzb.seven_header_streams(header)
            names = nzb.seven_file_names(header)
            best, inner_name, ambiguous = nzb.seven_pick_stream(
                streams, names, self.options.get('season'), self.options.get('episode'),
                self.options.get('alt_season'), self.options.get('alt_episode'))
            if best is None and ambiguous:
                raise SessionError(
                    'the 7z archive holds several files and none is named S%02dE%02d'
                    % (int(self.options.get('season')), int(self.options.get('episode'))))
        except nzb.Unsupported as exc:
            raise SessionError(str(exc))
        except lzma.LZMAError:
            raise SessionError('the 7z header could not be decoded')
        except (struct.error, IndexError):
            raise SessionError('not a 7z archive inside this release')
        if not best:
            raise SessionError('this 7z archive is compressed - only stored 7z sets can be streamed')
        name = (inner_name or '').strip()
        self._episode_guard(name)
        start = 32 + best['offset']
        total = int(best['length'])
        extents = pieces(start, total)
        if not extents:
            raise SessionError('the 7z film lies outside this release')
        parts = self._slice_extents(extents)
        if not parts:
            raise SessionError('the 7z film lies outside this release')
        self._set_plan(parts, total, name)
        probe = self._image_read(0, 32)
        if probe.startswith(nzb.RAR4) or probe.startswith(nzb.RAR5) \
                or probe.startswith(nzb.SEVEN):
            return self._nested_plan()
        return self._finish_inner()

    def _plan_self_seven(self):
        """The current plan is a 7z archive: serve the stored film inside it."""
        head = self._image_read(0, 32)
        if not head.startswith(nzb.SEVEN):
            raise SessionError('not a 7z archive')
        try:
            next_offset, next_size = struct.unpack_from('<QQ', head, 12)
            if next_size <= 0:
                raise SessionError('the 7z header is missing from the archive')
            tail = self._image_read(32 + next_offset, next_size)
            if len(tail) < next_size:
                raise SessionError('the 7z header is incomplete')
            header = nzb.seven_read_header(
                tail, lambda offset, size: self._image_read(32 + offset, size))
            streams = nzb.seven_header_streams(header)
            names = nzb.seven_file_names(header)
            best, inner_name, ambiguous = nzb.seven_pick_stream(
                streams, names, self.options.get('season'), self.options.get('episode'),
                self.options.get('alt_season'), self.options.get('alt_episode'))
            if best is None and ambiguous:
                raise SessionError(
                    'the 7z archive holds several files and none is named S%02dE%02d'
                    % (int(self.options.get('season')), int(self.options.get('episode'))))
        except nzb.Unsupported as exc:
            raise SessionError(str(exc))
        except lzma.LZMAError:
            raise SessionError('the 7z header could not be decoded')
        except (struct.error, IndexError):
            raise SessionError('not a 7z archive')
        if not best:
            raise SessionError('this 7z archive is compressed - only stored 7z sets can be streamed')
        name = (inner_name or '').strip()
        self._episode_guard(name)
        start = 32 + best['offset']
        total = int(best['length'])
        probe = self._image_read(start, 32)
        if probe.startswith(nzb.RAR4) or probe.startswith(nzb.RAR5) \
                or probe.startswith(nzb.SEVEN):
            raise SessionError('this release holds an archive inside a 7z archive')
        return self._install_inner([(start, total)], total, name)

    def _set_plan(self, parts, total, name):
        with self.lock:
            self.cache.clear()
            self.cache_bytes = 0
        self._pinned = set()
        self.parts = parts
        self.length = total
        self.inner_name = name
        self.part_size = 0

    def _install_inner(self, extents, total, name):
        parts = self._slice_extents(extents)
        if not parts:
            raise SessionError('the film inside this archive lies outside the release')
        self._set_plan(parts, total, name)
        return self._finish_inner()

    def _finish_inner(self):
        probe = self._image_read(0, _ISO_SECTOR + 8)
        container = _sniff(probe)
        if not container:
            if _looks_image(probe):
                raise SessionError('the file inside this archive is an image, not the film')
            raise SessionError('the biggest file in this archive is not a video')
        self.container = container
        if self.container == 'iso' and self.options.get('disc'):
            return self._disc_plan()
        try:
            first = self._decode_first(self.parts[0]['segments'])['data']
            self._pinned.add((self.parts[0]['id'], 0))
            self._remember((self.parts[0]['id'], 0), first)
        except Exception:
            pass
        _log('nested: %s, %.2f GB inside the archive'
             % (self.inner_name, self.length / 1073741824.0))
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _rar_member(self, volumes, first, layout, wanted):
        """The wanted episode inside a RAR set that holds the whole season.

        The file starts are followed in storage order, then the episode is
        served like any stored RAR set.
        """
        fmt = layout.get('fmt')
        if fmt not in (4, 5) or len(volumes) < 2:
            raise SessionError('the wanted episode could not be located inside this RAR set')
        if fmt in (4, 5) and not layout.get('first', True):
            raise SessionError('the first RAR volume is missing from this NZB')
        heads = {0: first.get('data') or b''}
        crcs = {0: bool(first.get('crc_ok', True))}
        parsed = {}
        key = config.nzb_data_key(self.data)
        known = {}
        known_names = {}
        for name, value in (config.rar_index(key) if key else {}).items():
            if not isinstance(value, dict) or not value.get('parts'):
                continue
            known_names[name] = value
            for pair in nzb.episode_pairs(name):
                known.setdefault(pair, (name, value))
        queued = set()

        def end_of(kept):
            """Where a member we already know ends, so the walk can skip it."""
            spec = kept.get('parts') or []
            try:
                number, skip, size = int(spec[-1][0]), int(spec[-1][1]), int(spec[-1][2])
            except (TypeError, ValueError, IndexError):
                return None
            return (number, skip + size) if size > 0 else None

        def ahead(number):
            """Start the next volume heads now, so the walk waits for none."""
            workers = self._workers_for_reads()
            with self.lock:
                for index in range(number, min(number + 12, len(volumes))):
                    if index in parsed or index in queued or not volumes[index].segments:
                        continue
                    queued.add(index)
                    workers.submit(self._head_of, volumes[index])

        def fill(numbers):
            """Head and headers of these volumes, read in one parallel round."""
            missing = [number for number in numbers
                       if number < len(volumes) and number not in parsed]
            if not missing:
                return
            workers = self._workers_for_reads()
            futures = [workers.submit(self._head_of, volumes[number]) for number in missing]
            for number, future in zip(missing, futures):
                try:
                    head, crc = future.result()
                except Exception:
                    continue
                heads[number] = head
                crcs[number] = crc
            for number in missing:
                head = heads.get(number)
                if head is None:
                    continue
                try:
                    parsed[number] = nzb.rar_entries(head)
                except nzb.Unsupported as exc:
                    raise SessionError('RAR: %s' % exc)

        def entries(number):
            if number not in parsed:
                fill([number])
                if number not in parsed:
                    raise SessionError('RAR: the volume %d has no header' % (number + 1))
            return parsed[number]

        def at_offset(number, at):
            """A file header further inside a volume, after another file's data.

            Offsets in the parsed header are rebased to the volume itself.
            """
            if at <= 0:
                return None
            head = heads.get(number)
            if not head:
                try:
                    head, crc = self._head_of(volumes[number])
                except Exception:
                    return None
                heads[number] = head
                crcs.setdefault(number, crc)
            blob = self._volume_bytes(volumes[number], at, 16384, head)
            if not blob:
                return None
            item = nzb.rar_entry_at(blob, fmt)
            if item is None:
                return None
            item['offset'] = int(item.get('offset') or 0) + at
            item['next_offset'] = int(item.get('next_offset') or 0) + at
            return item

        def locate(target, low=0):
            """Follow the file starts in storage order.

            A season pack does not order its episodes and one episode can span
            several volumes, so the chain is walked from the first volume: a
            part that continues is repeated at the start of the next volume,
            and a part that ends is followed by the next header inside the
            same volume, right after its data. A member an earlier episode
            already mapped is skipped in one step, at its end.
            """
            number = low
            at = None
            steps = 0
            limit = len(volumes) * 64 + 256
            while number < len(volumes) and steps < limit:
                steps += 1
                ahead(number)
                if at is None:
                    batch = entries(number)
                else:
                    found = at_offset(number, at)
                    batch = [found] if found is not None else []
                at = None
                if not batch:
                    number += 1
                    continue
                jumped = False
                for item in batch:
                    if item.get('before'):
                        continue
                    name = item.get('name') or ''
                    if target in nzb.episode_pairs(name):
                        return number, item
                    kept = known_names.get(name)
                    end = end_of(kept) if kept else None
                    if end and end[0] >= number:
                        number, at = end
                        jumped = True
                        break
                if jumped:
                    continue
                last = batch[-1]
                if last.get('more'):
                    number += 1
                    continue
                following = int(last.get('offset') or 0) + int(last.get('length') or 0)
                if following <= 0:
                    number += 1
                    continue
                at = following
            return None, None

        start = entry = None
        # Un aspect invatat la o redare anterioara: o singura citire il confirma,
        # apoi episodul e servit fara sa mai fie cautat prin volume.
        for target in wanted:
            entry = known.get(target)
            if not entry:
                continue
            name, kept = entry[0], entry[1]
            probe = self._serve_known(volumes, name, kept, heads, crcs)
            if probe is not None:
                return self._member_done(probe)
        for target in wanted:
            start, entry = locate(target)
            if start is not None:
                break
        if start is None:
            raise SessionError('the wanted episode could not be located inside this RAR set')
        if not entry.get('store'):
            raise SessionError('this RAR is compressed - only stored RAR sets can be streamed')
        if not entry.get('unp_size'):
            raise SessionError('the RAR header does not say how big the episode is')
        if int(entry.get('unp_size') or 0) < nzb.MIN_INNER_VIDEO_BYTES:
            raise SessionError('the file inside the RAR is too small to be the episode')
        start_head = heads.get(start) or b''
        at = int(entry.get('offset') or 0)
        if at + 64 <= len(start_head):
            inner = start_head[at:at + 8]
            sniff = _sniff(start_head, at)
            image = _looks_image(start_head, at)
        else:
            probe = self._volume_bytes(volumes[start], at, 65536, start_head)
            inner = probe[:8]
            sniff = _sniff(probe)
            image = _looks_image(probe)
        if not sniff and image:
            raise SessionError('the file inside this RAR is an image, not the episode')
        self.inner_name = (entry.get('name') or '').strip()
        self.media_name = self.inner_name or self.media_name
        self.first_crc_ok = crcs.get(start, True)
        self.container = 'iso' if (self.inner_name.lower().endswith('.iso')
                                   or sniff == 'iso') else 'rar'
        self.length = int(entry.get('unp_size') or 0)
        self.part_size = 0
        remaining = self.length
        length = int(entry.get('length') or 0)
        self.parts.append({'id': 0, 'volume': start,
                           'segments': [item[2] for item in volumes[start].segments],
                           'skip': at, 'length': length, 'part_size': 0})
        remaining -= length
        number = start + 1
        index = 1
        target_name = entry.get('name') or ''
        while remaining > 0:
            if number >= len(volumes):
                raise SessionError('RAR: volumes do not add up')
            ahead(number)
            follow_entries = entries(number)
            follow = follow_entries[0] if follow_entries else None
            if follow is None or not follow.get('before') \
                    or (follow.get('name') or '') != target_name:
                raise SessionError('RAR: volumes do not add up')
            skip = int(follow.get('offset') or 0)
            size = min(int(follow.get('length') or 0), remaining)
            if size <= 0:
                raise SessionError('RAR: volumes do not add up')
            self.parts.append({'id': index, 'volume': number,
                               'segments': [item[2] for item in volumes[number].segments],
                               'skip': skip, 'length': size, 'part_size': 0})
            head = heads.get(number)
            if head:
                self._remember((index, 0), head)
            remaining -= size
            number += 1
            index += 1
        return self._member_done(start_head)

    def _serve_known(self, volumes, name, kept, heads, crcs):
        """Parts of an episode this release already gave us, from the index."""
        spec = kept.get('parts') or []
        name = kept.get('name') or name or ''
        self.inner_name = name
        self.media_name = name or self.media_name
        self.first_crc_ok = crcs.get(int(spec[0][0]), True)
        self.container = 'iso' if name.lower().endswith('.iso') else 'rar'
        self.length = int(kept.get('length') or 0)
        self.part_size = 0
        parts = []
        for index, item in enumerate(spec):
            number, skip, size = int(item[0]), int(item[1]), int(item[2])
            if number >= len(volumes) or size <= 0:
                return None
            parts.append({'id': index, 'volume': number,
                          'segments': [piece[2] for piece in volumes[number].segments],
                          'skip': skip, 'length': size, 'part_size': 0})
        if not parts or sum(part['length'] for part in parts) != self.length:
            return None
        self.parts = parts
        try:
            probe = self._image_read(0, 16)
        except Exception:
            probe = b''
        if not probe or probe.hex() != (kept.get('sig') or ''):
            self.parts = []
            return None
        _log('member: %s from the saved layout, %d part(s)' % (name, len(parts)))
        return probe

    def _mark_pack(self, name, size):
        """Remember a season pack the outer release name did not advertise.

        The episode was found by its inner file name, so the player can keep
        using this NZB for the next episodes even when the post itself has an
        obfuscated name without SxxExx.
        """
        if not isinstance(self.pack, dict):
            return
        pairs = nzb.episode_pairs(name or '')
        if not pairs:
            return
        per = self.pack.setdefault('per_episode', {})
        for season, episode in pairs:
            per.setdefault('S%02dE%02d' % (season, episode), int(size or 0))
        self.pack['pack'] = True
        self.pack['episodes'] = max(2, int(self.pack.get('episodes') or 0), len(per))
        self.pack['open_pack'] = True

    def _mark_possible_pack(self, volumes, needs_volumes):
        """A generic release name may still be a season pack.

        The inner file says SxxExx while the post itself does not, so the pack
        can only be opened again by trying it for the next episode.
        """
        wanted = set(self._wanted_pairs())
        if not wanted or (needs_volumes and len(volumes) < 2):
            return
        inner = set(nzb.episode_pairs(self.inner_name or ''))
        if not wanted & inner:
            return
        outside = set()
        for volume in volumes:
            outside |= set(nzb.episode_pairs(volume.name or ''))
        if wanted & outside:
            return
        self._mark_pack(self.inner_name, self.length)

    def _member_done(self, start_head):
        """Finish the episode once its parts are known."""
        name = self.inner_name or ''
        self._mark_pack(name, self.length)
        nested = bool(_INNER_RAR_NAME.search(name) or _INNER_SEVEN_NAME.search(name))
        if not nested and nzb.kind_of(name) != 'video':
            try:
                probe = self._image_read(0, 8)
            except Exception:
                probe = b''
            nested = bool(probe.startswith(nzb.RAR4) or probe.startswith(nzb.RAR5)
                          or probe.startswith(nzb.SEVEN))
        if nested:
            return self._nested_plan()
        if self.container == 'iso' and self.options.get('disc'):
            return self._disc_plan()
        self._save_member_index()
        self._pinned.add((0, 0))
        if len(start_head or b'') > 1024:
            self._remember((0, 0), start_head)
        self._warm_front(self.parts[0]['segments'])
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _save_member_index(self):
        """Keep where this episode sits, so the next play skips the walk."""
        if not self.inner_name or not self.parts:
            return
        try:
            sig = self._image_read(0, 16)
        except Exception:
            return
        if not sig:
            return
        spec = [[int(part.get('volume') or 0), int(part['skip']), int(part['length'])]
                for part in self.parts]
        try:
            config.remember_rar_index(config.nzb_data_key(self.data),
                                      {self.inner_name: {'name': self.inner_name,
                                                         'length': self.length,
                                                         'sig': sig.hex(),
                                                         'parts': spec}})
        except Exception:
            pass

    def prepare(self):
        _log('engine: %d worker(s) x %d pipelined on %d core(s), %s, prefetch %.0f MB, '
             'cache %.0f MB, timeout %ds, profile %s'
             % (self.worker_target, self.pipeline, _cores(),
                ', '.join('%s %d%s' % (pool.label, pool.limit,
                                       ' backup' if pool.provider.get('backup') else '')
                          for pool in self.pools),
                self.prefetch_bytes / 1048576.0, self.cache_limit / 1048576.0, self.timeout,
                PROFILE_NAMES[self.profile]))
        try:
            files = nzb.parse(self.data)
        except nzb.NzbError as exc:
            error = SessionError(str(exc))
            error.bad_nzb = True
            raise error
        try:
            media, kind = nzb.select_media(
                files, self.options.get('season'), self.options.get('episode'),
                self.options.get('alt_season'), self.options.get('alt_episode'))
        except nzb.NzbError as exc:
            raise SessionError(str(exc))
        self.pack = nzb.pack_info(files)
        if media is None:
            if kind == 'sample':
                raise SessionError('this NZB contains only a sample or trailer')
            raise SessionError('this NZB contains no video')
        self.media_name = media.name or 'video'
        if self.options.get('health'):
            self._check_health(files, media, kind)
        if kind == '7z':
            return self._prepare_seven(files, media)
        if kind == 'video':
            self._episode_guard(media.name or '')
            info = self._decode_first(media.segments)
            self.first_crc_ok = bool(info.get('crc_ok', True))
            self.inner_name = media.name or ''
            self.container = _sniff(info['data'])
            if not self.container:
                raise SessionError('the biggest file in this NZB is not a video')
            self.part_size = len(info['data'])
            self.length = info['size'] or media.bytes
            self.parts = [{
                'id': 0,
                'segments': [item[2] for item in media.segments],
                'skip': 0,
                'length': self.length,
                'part_size': self.part_size,
            }]
            if self.container == 'iso' and self.options.get('disc'):
                return self._disc_plan()
            self._pinned.add((0, 0))
            self._remember((0, 0), info['data'])
            self._warm_front(media.segments)
            self.prepared = True
            self._warm_tail()
            return self.info()

        volumes = nzb.rar_volumes(files, media)
        if not volumes:
            raise SessionError('this NZB contains no playable file')
        self.media_name = volumes[0].name or self.media_name
        first = self._decode_first(volumes[0].segments)
        self.first_crc_ok = bool(first.get('crc_ok', True))
        head = first['data']
        if not head.startswith(nzb.RAR4) and not head.startswith(nzb.RAR5):
            try:
                parts = nzb.numbered_parts(files, media)
            except nzb.Unsupported as exc:
                raise SessionError(str(exc))
            if parts:
                if parts[0] is not volumes[0] and parts[0].name != volumes[0].name:
                    first = self._decode_first(parts[0].segments)
                    self.first_crc_ok = bool(first.get('crc_ok', True))
                return self._prepare_split(parts, first)
        if head.startswith(nzb.RAR5) and len(volumes) > 1 and nzb.rar_names_unsorted(volumes):
            ordered = self._rar_header_order(volumes, first)
            if ordered is not None and ordered[0] is not volumes[0]:
                volumes = ordered
                self.media_name = volumes[0].name or self.media_name
                first = self._decode_first(volumes[0].segments)
                self.first_crc_ok = bool(first.get('crc_ok', True))
                head = first['data']
        try:
            outer_entries = nzb.rar_entries(head)
        except nzb.Unsupported:
            outer_entries = []
        if outer_entries and self._outer_nested(outer_entries, head):
            self._outer_plan(volumes)
            return self._nested_plan()
        try:
            layout = nzb.rar_layout(head)
        except nzb.Unsupported as exc:
            raise SessionError(str(exc))
        wanted = self._wanted_pairs()
        if wanted and len(volumes) > 1:
            pairs = nzb.episode_pairs(layout.get('name') or '')
            if pairs and not set(wanted) & pairs:
                return self._rar_member(volumes, first, layout, wanted)
        if not layout.get('store'):
            raise SessionError('this RAR is compressed - only stored RAR sets can be streamed')
        if not layout.get('unp_size'):
            raise SessionError('the RAR header does not say how big the film is')
        self.inner_name = (layout.get('name') or '').strip()
        self._episode_guard(self.inner_name)
        # Unele repack-uri pun un set RAR/7z in interiorul altui RAR. Primul
        # fisier din volumul exterior e atunci un volum intern (.r08 etc.),
        # nu filmul; fara garda, Kodi primeste 400 MB din mijlocul arhivei si
        # gaseste doar un flux audio. Respingem release-ul, playerul trece
        # la urmatoarea sursa.
        inner_head = head[layout['offset']:layout['offset'] + 8]
        nested = bool(inner_head.startswith(b'Rar!\x1a\x07')
                      or re.search(r'\.(?:rar|r\d{2,3})$', self.inner_name, re.I))
        if inner_head.startswith(b'7z\xbc\xaf\x27\x1c') or re.search(
                r'\.7z(?:\.\d+)?$', self.inner_name, re.I):
            self._outer_plan(volumes)
            return self._nested_plan()
        if int(layout.get('unp_size') or 0) < nzb.MIN_INNER_VIDEO_BYTES:
            raise SessionError('the file inside the RAR is too small to be the film')
        inner_sniff = _sniff(head, layout['offset'])
        if not inner_sniff and _looks_image(head, layout['offset']):
            raise SessionError('the file inside this RAR is an image, not the film')
        self.container = 'iso' if (self.inner_name.lower().endswith('.iso')
                                   or inner_sniff == 'iso') else 'rar'
        self.length = layout['unp_size']
        self.part_size = 0
        fmt = layout.get('fmt')
        if fmt == 5 and not layout.get('first', True):
            raise SessionError('the first RAR volume is missing from this NZB')
        base_volume = int(layout.get('volume') or 0)
        # Every volume after the first carries a volume-number vint, taken out of its data.
        sizes_key = config.nzb_data_key(self.data)
        first_size = int(first.get('size') or 0)
        sizes = {0: first_size} if first_size > 0 else {}
        try:
            for index, size in config.volume_sizes(sizes_key).items():
                if 0 <= index < len(volumes) and size > 0 and index not in sizes:
                    sizes[index] = size
        except Exception:
            pass

        def volume_size(index):
            return sizes.get(index) or nzb.file_size(volumes[index])

        # Some posters give no decoded size in the subject, so nzb.file_size
        # falls back to the encoded total (~3% larger) and every part boundary
        # drifts by a few KB. A real end-of-archive header is tiny, so the
        # measured decoded sizes are kept per volume and only measured once.
        tail = max(0, volume_size(0) - layout['offset'] - layout['length'])
        sample = volume_size(1) if len(volumes) > 1 else volume_size(0)
        estimate = sample if 1 in sizes else int(sample * 0.95)
        estimate = max(1, estimate)
        needed = min(len(volumes), int((self.length + estimate - 1) // estimate) + 4)
        # Encoded sizes (or no size at all in the subject) make every part
        # boundary drift; one =ybegin read per volume fixes that for good.
        trusted = bool(nzb.declared_size(volumes[needed - 1]))
        missing = [index for index in range(0, needed) if index not in sizes]
        if missing and (tail > 1048576 or not trusted):
            workers = self._workers_for_reads()
            futures = {workers.submit(self._split_size, volumes[index]): index
                       for index in missing}
            found = {}
            for future in as_completed(futures):
                index = futures.pop(future)
                try:
                    size = int(future.result() or 0)
                except Exception:
                    continue
                if size > 0:
                    found[index] = size
            sizes.update(found)
            if found:
                try:
                    config.remember_volume_sizes(sizes_key, len(volumes), found)
                except Exception:
                    pass
            tail = max(0, volume_size(0) - layout['offset'] - layout['length'])
        exact_sizes = tail <= 1048576
        remaining = self.length
        for index, volume in enumerate(volumes[:400]):
            last = index >= len(volumes) - 1
            # Volumul 0 are offsetul filmeului dupa poster; volumele urmatoare
            # incep direct cu headerul de volum + headerul filmului.
            skip = layout['offset'] if not index else (layout.get('next_offset') or layout['offset'])
            if fmt == 5 and index:
                skip += _vint_len(base_volume + index)
                if layout.get('volfield'):
                    skip -= _vint_len(base_volume)
            if last:
                size = remaining
            elif not index:
                size = min(layout['length'], remaining)
            elif exact_sizes and volume_size(index) - skip - tail > 0:
                size = min(volume_size(index) - skip - tail, remaining)
            else:
                size = min(self._rar_part_size(volume, index, layout), remaining)
            self.parts.append({
                'id': index,
                'segments': [item[2] for item in volume.segments],
                'skip': skip,
                'length': max(0, size),
                'part_size': 0,
            })
            remaining -= size
            if remaining <= 0:
                break
        if nested:
            return self._nested_plan()
        if self.container == 'iso' and self.options.get('disc'):
            return self._disc_plan()
        self._mark_possible_pack(volumes, True)
        self._pinned.add((0, 0))
        self._remember((0, 0), head)
        self._warm_front(volumes[0].segments)
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _prepare_split(self, parts, first=None):
        """A video split into numbered files: serve the files back to back."""
        if not parts:
            raise SessionError('this NZB contains no playable file')
        if first is None:
            first = self._decode_first(parts[0].segments)
        self.first_crc_ok = bool(first.get('crc_ok', True))
        self.media_name = parts[0].name or self.media_name
        self.inner_name = parts[0].name or ''
        self.container = _sniff(first['data'])
        if not self.container:
            raise SessionError('the first numbered video part is not a video')
        sizes = {}
        data = first.get('data') or b''
        sizes[0] = int(first.get('size') or 0) or nzb.file_size(parts[0])
        if len(parts) > 1:
            # Only the =ybegin line of each part is read, not the whole first
            # article: a 162-part remux no longer costs 100 MB before playback.
            sizes_key = config.nzb_data_key(self.data)
            try:
                for index, size in config.volume_sizes(sizes_key).items():
                    if 0 < index < len(parts) and size > 0:
                        sizes.setdefault(index, size)
            except Exception:
                pass
            missing = [index for index in range(1, len(parts)) if index not in sizes]
            workers = self._workers_for_reads()
            futures = {workers.submit(self._split_size, parts[index]): index
                       for index in missing}
            found = {}
            for future in as_completed(futures):
                index = futures.pop(future)
                try:
                    size = int(future.result() or 0)
                except Exception:
                    continue
                if size > 0:
                    found[index] = size
                    sizes[index] = size
            if found:
                try:
                    config.remember_volume_sizes(sizes_key, len(parts), found)
                except Exception:
                    pass
        for index, part in enumerate(parts):
            size = sizes.get(index, 0)
            if size <= 0:
                raise SessionError('a numbered video part could not be sized')
            self.parts.append({
                'id': index,
                'segments': [item[2] for item in part.segments],
                'skip': 0,
                'length': size,
                'part_size': len(data) if index == 0 else 0,
            })
            self.length += size
            if index == 0:
                self._remember((0, 0), data)
        self._pinned.add((0, 0))
        self._warm_front(parts[0].segments)
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _rar_header_order(self, volumes, first):
        """The volumes in archive order, from the RAR5 volume number in each header.

        Obfuscated repacks post randomly named volumes, so the file list says
        nothing about which one follows which; the archive header does. Read
        the headers in parallel: a 275-volume set no longer pays one round
        trip after another before playback can start.
        """
        numbers = {}
        number = nzb.rar5_volume(first['data'])
        if number is None or number in numbers:
            return None
        numbers[number] = volumes[0]
        if len(volumes) > 1:
            workers = self._workers_for_reads()
            futures = [workers.submit(self._decode_first, volume.segments)
                       for volume in volumes[1:]]
            waiting = dict(zip(futures, volumes[1:]))
            for future in as_completed(futures):
                volume = waiting.pop(future)
                number = nzb.rar5_volume(future.result()['data'])
                if number is None or number in numbers:
                    return None
                numbers[number] = volume
        if sorted(numbers) != list(range(len(numbers))):
            raise SessionError('a RAR volume is missing from this NZB')
        return [numbers[index] for index in range(len(numbers))]

    def _prepare_seven(self, files, head=None):
        volumes = nzb.seven_volumes(files, head)
        if not volumes:
            raise SessionError('this NZB contains no playable file')
        self.media_name = volumes[0].name or self.media_name
        if len(volumes) > 1:
            match = re.search(r'\.7z\.(\d+)$', volumes[0].name or '', re.I)
            if match and int(match.group(1)) != 1:
                raise SessionError('the first 7z volume is missing from this NZB')
        first_info = self._decode_first(volumes[0].segments)
        self.first_crc_ok = bool(first_info.get('crc_ok', True))
        head = first_info['data']
        if not head.startswith(nzb.SEVEN):
            raise SessionError('not a 7z archive')
        volume_map = []
        cache = {}
        position = 0
        sizes = {0: int(first_info.get('size') or 0) or nzb.file_size(volumes[0])}
        sizes_key = config.nzb_data_key(self.data)
        if len(volumes) > 1:
            # Only the =ybegin line of each volume is read. The article stride
            # is the same across a posted 7z set, so volume 0 gives it once.
            # Sizes never change, so a size measured at an earlier open is kept.
            measured = config.volume_sizes(sizes_key)
            sizes.update({index: size for index, size in measured.items()
                          if 1 <= index < len(volumes)})
            missing = [index for index in range(1, len(volumes))
                       if not sizes.get(index)]
            workers = self._workers_for_reads()
            futures = {workers.submit(self._split_size, volumes[index]): index
                       for index in missing}
            for future in as_completed(futures):
                index = futures.pop(future)
                sizes[index] = int(future.result() or 0)
            if missing:
                try:
                    config.remember_volume_sizes(sizes_key, len(volumes), sizes)
                except Exception:
                    pass
        stride = len(first_info.get('data') or b'')
        for index, volume in enumerate(volumes):
            size = sizes.get(index, 0)
            if size <= 0 or stride <= 0:
                raise SessionError('a 7z volume could not be sized')
            volume_map.append({'file': volume, 'start': position, 'size': size,
                               'part_size': stride})
            position += size
        cache[volumes[0].segments[0][2]] = first_info['data']
        secret = nzb.password(self.data)
        cached = config.seven_layout(sizes_key)
        if int(cached.get('count') or 0) != len(volumes) or not cached.get('length'):
            cached = {}
        best = None
        if cached:
            inner_name = cached.get('name') or ''
            start = int(cached.get('start') or 0)
            self.length = int(cached.get('length') or 0)
            extent = int(cached.get('extent') or 0) or self.length
            crypto = None
            if cached.get('crypto'):
                crypto = {'props': bytes.fromhex(cached['crypto'].get('props') or ''),
                          'rel': int(cached['crypto'].get('rel') or 0)}
            _log('7z header known from an earlier open, %d volume(s)' % len(volumes))
        else:
            try:
                next_offset, next_size = struct.unpack_from('<QQ', head, 12)
                if next_size <= 0:
                    raise SessionError('the 7z header is missing from the archive')
                tail = self._seven_read(volume_map, cache, 32 + next_offset, next_size)
                if len(tail) < next_size:
                    raise SessionError('the 7z header is incomplete - a volume is missing')
                header = nzb.seven_read_header(
                    tail, lambda offset, size: self._seven_read(volume_map, cache, 32 + offset, size),
                    secret)
                streams = nzb.seven_header_streams(header)
                names = nzb.seven_file_names(header)
                season = self.options.get('season')
                episode = self.options.get('episode')
                best, inner_name, ambiguous = nzb.seven_pick_stream(
                    streams, names, season, episode,
                    self.options.get('alt_season'), self.options.get('alt_episode'))
                if best is None and ambiguous:
                    raise SessionError(
                        'the 7z archive holds several files and none is named S%02dE%02d'
                        % (int(season), int(episode)))
            except nzb.Unsupported as exc:
                raise SessionError(str(exc))
            except lzma.LZMAError:
                raise SessionError('the 7z header could not be decoded')
            except (struct.error, IndexError):
                raise SessionError('not a 7z archive')
            if not best:
                raise SessionError('this 7z archive is compressed - only stored 7z sets can be streamed')
            start = 32 + best['offset']
            self.length = best['length']
            crypto = best.get('crypto')
        if inner_name:
            self.inner_name = inner_name
        span = 0
        if crypto:
            try:
                key, iv = nzb.seven_aes_setup(crypto.get('props') or b'', secret)
            except nzb.Unsupported as exc:
                raise SessionError(str(exc))
            shift = int(crypto.get('rel') or 0)
            # Plan offset 0 is the folder start, so the first film block always
            # has its CBC IV either stored or the folder IV.
            self.crypto = {'key': key, 'iv': iv, 'shift': shift}
            start -= shift
            span = shift + max(self.length, int((best or {}).get('packed') or 0) - shift)
        extent = span or self.length
        if not cached:
            record = {'count': len(volumes), 'name': self.inner_name or '',
                      'start': start, 'extent': extent, 'length': self.length}
            if crypto:
                record['crypto'] = {'props': (crypto.get('props') or b'').hex(),
                                    'rel': int(crypto.get('rel') or 0)}
            try:
                config.remember_seven_layout(sizes_key, record)
            except Exception:
                pass
        self.part_size = 0
        first_part_mid = ''
        for volume in volume_map:
            low = max(start, volume['start'])
            high = min(start + extent, volume['start'] + volume['size'])
            if high <= low:
                continue
            part = volume['part_size']
            local_start = low - volume['start']
            local_end = high - volume['start']
            first_index = local_start // part
            last_index = min((local_end - 1) // part, len(volume['file'].segments) - 1)
            if first_index > last_index:
                continue
            segments = [mid for _number, _size, mid in
                        volume['file'].segments[first_index:last_index + 1]]
            if not segments:
                continue
            if not first_part_mid:
                first_part_mid = segments[0]
            self.parts.append({
                'id': len(self.parts),
                'segments': segments,
                'skip': local_start - first_index * part,
                'length': high - low,
                'part_size': 0,
            })
            if high >= start + extent:
                break
        if not self.parts:
            raise SessionError('the 7z volumes are shorter than the archive header says')
        if crypto:
            self.plan_length = extent
            probe = self._crypto_bytes(0, _ISO_SECTOR + 8)
            if probe.startswith(nzb.RAR4) or probe.startswith(nzb.RAR5) \
                    or probe.startswith(nzb.SEVEN):
                raise SessionError('this encrypted 7z holds another archive')
            self.container = _sniff(probe)
            if not self.container:
                raise SessionError('the biggest file in this 7z archive is not a video')
            if self.container == 'iso' and self.options.get('disc'):
                raise SessionError('this encrypted 7z holds a disc image')
            _log('encrypted 7z: %s, %.2f GB under AES'
                 % (self.inner_name, self.length / 1073741824.0))
            self._mark_possible_pack(volumes, False)
            if first_part_mid in cache:
                self._pinned.add((0, 0))
                self._remember((0, 0), cache[first_part_mid])
            self._warm_front_later(self.parts[0]['segments'])
            self.prepared = True
            self._warm_tail_later()
            return self.info()
        probe = self._seven_read(volume_map, cache, start, _ISO_SECTOR + 8)
        nested = bool(probe.startswith(b'Rar!\x1a\x07') or probe.startswith(nzb.SEVEN)
                      or _INNER_RAR_NAME.search(inner_name or '')
                      or _INNER_SEVEN_NAME.search(inner_name or ''))
        self.container = 'rar' if nested else _sniff(probe)
        if not self.container:
            raise SessionError('the biggest file in this 7z archive is not a video')
        if nested:
            return self._nested_plan()
        if self.container == 'iso' and self.options.get('disc'):
            return self._disc_plan()
        self._mark_possible_pack(volumes, False)
        if first_part_mid in cache:
            self._pinned.add((0, 0))
            self._remember((0, 0), cache[first_part_mid])
        self._warm_front(self.parts[0]['segments'])
        self.prepared = True
        self._warm_tail()
        return self.info()

    def info(self):
        extension = {'mkv': '.mkv', 'mp4': '.mp4', 'avi': '.avi', 'ts': '.ts',
                     'm2ts': '.m2ts', 'iso': '.iso'}.get(self.container, '.mkv')
        base = re.split(r'[\\/]', self.inner_name or self.media_name or '')[-1]
        base = re.sub(r'\.(7z(?:\.\d+)?|part\d+\.rar|rar|r\d{2,3}|\d{3})$', '', base, flags=re.I)
        base = re.sub(r'\.(mkv|mp4|m4v|avi|ts|m2ts|vob|mov|wmv|webm|mpg|mpeg|iso)$', '', base, flags=re.I)
        return {'ok': True, 'container': self.container, 'length': self.length,
                'name': _safe_name(base or 'video') + extension, 'rar': self.container == 'rar'}

    def first_article(self):
        """The decoded first article kept by prepare(), for the VFS cache."""
        with self.lock:
            return self.cache.get((0, 0))

    # -- reading -----------------------------------------------------------

    def _part_size(self, part):
        if part.get('part_size'):
            return part['part_size']
        key = (part['id'], 0)
        with self.lock:
            kept = self.cache.get(key)
        if kept is not None:
            part['part_size'] = len(kept)
            return part['part_size']
        info = self._decode_first(part['segments'])
        part['part_size'] = len(info['data'])
        self._remember(key, info['data'])
        return part['part_size']

    def _locate(self, offset):
        walked = 0
        for index, part in enumerate(self.parts):
            if offset < walked + part['length']:
                return index, offset - walked
            walked += part['length']
        return len(self.parts), 0

    def _remember(self, key, data):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return
            self.cache[key] = data
            self.cache_bytes += len(data)
            while self.cache_bytes > self.cache_limit and len(self.cache) > 1:
                stale = next((item for item in self.cache if item not in self._pinned), None)
                if stale is None:
                    break
                dropped = self.cache.pop(stale)
                self.cache_bytes -= len(dropped)

    def _workers_for_reads(self):
        """One daemon worker per configured connection, capped by the box."""
        if self._workers is None:
            with self.lock:
                if self._workers is None:
                    self._workers = _Workers(self.worker_target)
        return self._workers

    def _lookahead(self, segments, part_size, remaining):
        """How many articles to keep in flight: enough to feed every worker."""
        if part_size <= 0:
            return 2
        needed = max(1, (remaining + part_size - 1) // part_size)
        if needed >= self.worker_target:
            wanted = max(int(self.prefetch_bytes / part_size) + 1,
                         self.worker_target * self.pipeline + WORKER_MARGIN)
            wanted = min(wanted, max(2, int(HARD_PREFETCH_BYTES / part_size)))
        else:
            wanted = needed + WORKER_MARGIN
        return max(2, min(len(segments), wanted))

    def _warm_tail(self):
        """Kodi reads the end of the file early (MKV index); start that article now."""
        try:
            if self.length <= 0:
                return
            end = self.length - 1
            if self.crypto:
                end += int(self.crypto.get('shift') or 0)
            part_index, local = self._locate(end)
            if part_index >= len(self.parts):
                return
            part = self.parts[part_index]
            part_size = self._part_size(part)
            if part_size <= 0:
                return
            position = part['skip'] + local
            index = min(position // part_size, len(part['segments']) - 1)
            key = (part['id'], index)
            workers = self._workers_for_reads()
            with self.lock:
                self._pinned.add(key)
                if key in self.cache:
                    self.cache.move_to_end(key)
                    return
                self._tail_keys.add(key)
                if key in self._pending:
                    return
                self._pending[key] = (workers.submit(self._fetch_batch, part, [index], [key], True),
                                      key)
        except Exception as exc:
            _log('tail prefetch skipped: %s' % str(exc)[:90], warning=True)

    def _submit_group(self, workers, part, indices):
        """One connection for a run of articles (the caller holds the lock)."""
        keys = [(part['id'], index) for index in indices]
        future = workers.submit(self._fetch_batch, part, list(indices), keys)
        for key in keys:
            self._pending[key] = (future, key)

    def _schedule(self, part, part_size, index, ahead):
        """Keep the segments that are about to be needed already downloading."""
        end = min(index + ahead, len(part['segments']))
        if end <= index:
            return
        workers = self._workers_for_reads()
        with self.lock:
            groups = {}
            for stale, entry in list(self._pending.items()):
                future = entry[0]
                if future.done():
                    self._pending.pop(stale, None)
                    continue
                groups.setdefault(id(future), (future, []))[1].append(stale)
            for future, stale_keys in groups.values():
                if any(key in self._tail_keys
                       or (key[0] == part['id'] and index <= key[1] < end)
                       for key in stale_keys):
                    continue
                if future.cancel():
                    for key in stale_keys:
                        if self._pending.get(key, (None,))[0] is future:
                            self._pending.pop(key, None)
            run = []
            for upcoming in range(index, end):
                key = (part['id'], upcoming)
                if key in self.cache or key in self._pending:
                    if run:
                        self._submit_group(workers, part, run)
                        run = []
                    continue
                run.append(upcoming)
                if len(run) >= self.pipeline:
                    self._submit_group(workers, part, run)
                    run = []
            if run:
                self._submit_group(workers, part, run)

    def _drop_pending(self):
        """Forget queued read-ahead: after a seek the old window is wasted work."""
        with self.lock:
            groups = {}
            for key, entry in list(self._pending.items()):
                future = entry[0]
                if key in self._tail_keys:
                    if future.done():
                        self._pending.pop(key, None)
                    continue
                groups.setdefault(id(future), (future, []))[1].append(key)
            for future, keys in groups.values():
                if future.cancel():
                    for key in keys:
                        if self._pending.get(key, (None,))[0] is future:
                            self._pending.pop(key, None)

    def _segment(self, part, index, generation):
        key = (part['id'], index)
        with self.lock:
            kept = self.cache.get(key)
            if kept is not None:
                self.cache.move_to_end(key)
                return kept
            entry = self._pending.get(key)
        if entry is not None:
            future, target = entry
            try:
                found = future.result()
                chunk = found.get(target) if isinstance(found, dict) else None
                if chunk is not None:
                    return chunk
            except CancelledError:
                with self.lock:
                    if generation != self._generation:
                        return b''
                if self._closing:
                    raise
            finally:
                with self.lock:
                    if self._pending.get(key, (None,))[0] is future:
                        self._pending.pop(key, None)
        return self._fetch(part, index, key, True)

    @staticmethod
    def _decode(article):
        if article is None:
            return None
        try:
            decoded = yenc.decode(article)
        except yenc.YencError:
            return None
        if not decoded.get('crc_ok', True):
            return None
        return decoded['data']

    def _fetch_batch(self, part, indices, keys, urgent=False):
        """Download and decode a group of segments, one connection for the group."""
        with self.lock:
            self.segments += len(indices)
        expected = part.get('part_size') or 0
        started = time.time()
        wanted = [part['segments'][index] for index in indices]
        try:
            articles = self._articles(wanted, urgent)
        except Exception as exc:
            with self.lock:
                self.read_errors += 1
            _log('articles %s failed: %s'
                 % (', '.join(str(index) for index in indices), str(exc)[:90]), warning=True)
            articles = [None] * len(indices)
        data = {}
        try:
            for position, (index, key, article) in enumerate(zip(indices, keys, articles)):
                chunk = self._decode(article)
                if chunk is None and article is not None:
                    _log('article %d failed its checksum, asking again' % index, warning=True)
                    try:
                        chunk = self._decode(self._article(wanted[position], True))
                    except Exception as exc:
                        with self.lock:
                            self.read_errors += 1
                        _log('article %d failed: %s' % (index, str(exc)[:90]), warning=True)
                if chunk is None:
                    chunk = self._pad(expected, index)
                else:
                    with self.lock:
                        self.missing_run = 0
                data[key] = chunk
                self._remember(key, chunk)
        finally:
            with self.lock:
                self.article_seconds += time.time() - started
        return data

    def _fetch(self, part, index, key, urgent=False):
        return self._fetch_batch(part, [index], [key], urgent)[key]

    def _pad(self, expected, index=None):
        """One missing article: zeros, unless this release is too damaged to play."""
        with self.lock:
            self.missing += 1
            self.missing_run += 1
            if self.missing_run > self.longest_run:
                self.longest_run = self.missing_run
            missing, run, seen = self.missing, self.missing_run, self.segments
        if missing <= 3 or missing % 25 == 0:
            _log('article %s is missing on every provider - zero-filled (%d so far)'
                 % ('%d' % index if index is not None else '?', missing), warning=True)
        if not self.hole_filling:
            raise SessionError('this release has missing articles and gap filling is off')
        if self.hole_consecutive and run > self.hole_consecutive:
            raise SessionError('%d articles in a row are missing - the film would freeze'
                               % run)
        if self.hole_percent and seen >= HOLE_WARMUP:
            ratio = 100.0 * missing / float(seen)
            if ratio > self.hole_percent:
                raise SessionError('%.1f%% of this release is missing (limit %g%%)'
                                   % (ratio, self.hole_percent))
        return b'\x00' * (expected or 1)

    def read(self, start, length, sink, stop=None):
        """Write bytes [start, start+length) to sink(bytes). Returns the count."""
        if not self.prepared:
            self.prepare()
        self.last_read = time.time()
        if start >= self.length:
            return 0
        if self.crypto:
            return self._read_crypto(start, length, sink, stop)
        return self._read_plan(start, length, sink, stop)

    def _read_crypto(self, start, length, sink, stop=None):
        """Plaintext from an AES folder: the plan starts at the folder start,
        so plaintext p sits at shift + p and the block before it is its CBC IV."""
        key, iv0 = self.crypto['key'], self.crypto['iv']
        shift = int(self.crypto.get('shift') or 0)
        length = min(length, self.length - start)
        written = 0
        position = shift + start
        while written < length:
            take = min(length - written, CRYPTO_CHUNK)
            block = position >> 4
            lead = position & 15
            need = lead + take
            padded = need + (-need % 16)
            if block:
                buffered = self._plan_bytes(16 * (block - 1), padded + 16)
                plain = nzb.seven_aes_bytes(buffered, key, None)[16 + lead:16 + lead + take]
            else:
                buffered = self._plan_bytes(0, padded)
                plain = nzb.seven_aes_bytes(buffered, key, iv0)[lead:lead + take]
            if not plain:
                break
            sink(plain)
            written += len(plain)
            position += len(plain)
            if stop and stop():
                break
        return written

    def _plan_bytes(self, start, count):
        out = []
        self._read_plan(start, count, out.append)
        return b''.join(out)

    def _crypto_bytes(self, start, count):
        out = []
        self._read_crypto(start, count, out.append)
        return b''.join(out)

    def _read_plan(self, start, length, sink, stop=None):
        with self.lock:
            previous = self._last_start
            limit = self.plan_length or self.length
            tail = start >= limit - INDEX_TAIL_BYTES
            if not tail:
                self._last_start = start
            seek = (not tail and previous is not None
                    and abs(start - previous) > SEEK_LOG_BYTES)
            if seek:
                self._generation += 1
            generation = self._generation
        if seek:
            _log('read jump to %.1f GB (%.0f MB from the previous read)'
                 % (start / 1073741824.0, (start - previous) / 1048576.0))
            self._drop_pending()
        length = min(length, limit - start)
        part_index, local = self._locate(start)
        written = 0
        while written < length and part_index < len(self.parts):
            part = self.parts[part_index]
            part_size = self._part_size(part)
            take = min(length - written, part['length'] - local)
            if take <= 0:
                part_index += 1
                local = 0
                continue
            self._pump(part, part_size, part['skip'] + local, take, sink, stop, generation)
            written += take
            part_index += 1
            local = 0
            if stop and stop():
                break
        return written

    def _pump(self, part, part_size, stream_offset, count, sink, stop, generation):
        position = stream_offset
        remaining = count
        segments = part['segments']
        ahead = self._lookahead(segments, part_size, remaining)
        cap = max(2, min(8, self.worker_target))
        while remaining > 0:
            if generation != self._generation:
                break
            index = position // part_size
            if index >= len(segments):
                break
            window = min(ahead, cap) if self.segments < 4 else ahead
            self._schedule(part, part_size, index + 1, window)
            chunk = self._segment(part, index, generation)
            inside = position - index * part_size
            if inside >= len(chunk):
                position = (index + 1) * part_size
                continue
            piece = chunk[inside:inside + remaining]
            if piece:
                sink(piece)
            position += len(piece)
            remaining -= len(piece)
            if stop and stop():
                break

    @property
    def missing_ratio(self):
        return self.missing / float(self.segments or 1)

    def stats(self):
        with self.lock:
            articles = self.segments or 1
            labels = []
            for label, count in sorted(self.served_counts.items(),
                                       key=lambda item: -item[1]):
                seconds = self.served_seconds.get(label) or 0
                if seconds > 0:
                    labels.append('%s %d (%.1f MB/s)' % (
                        label, count,
                        self.served_bytes.get(label, 0) / seconds / 1048576.0))
                else:
                    labels.append('%s %d' % (label, count))
            busy = ', '.join(labels)
            return {'articles': self.segments, 'read_errors': self.read_errors,
                    'avg_ms': self.article_seconds * 1000.0 / articles,
                    'provider': busy or (self._served.label if self._served else 'none')}

    def release_buffers(self):
        """Give the RAM back after a stop: the decoded articles are dropped, the
        plan and the measured sizes stay, so the next open is still instant."""
        with self.lock:
            released = self.cache_bytes
            self.cache.clear()
            self.cache_bytes = 0
            self.warm = []
        return released

    def close(self):
        self._closing = True
        workers, self._workers = self._workers, None
        if workers is not None:
            try:
                workers.close()
            except Exception:
                pass
        with self.lock:
            self._pending.clear()
        for pool in self.pools:
            pool.close()
        with self.lock:
            self.cache.clear()
            self.cache_bytes = 0


def _safe_name(name):
    import re
    name = re.sub(r'[^\w.\- ]+', '', str(name or 'video')).strip()
    name = re.sub(r'\s+', ' ', name)
    return name[:90] or 'video'
