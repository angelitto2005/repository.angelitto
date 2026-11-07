"""One NZB as a byte stream.

The session is what turns "byte 1 234 567 of the film" into "articles 42, 43
and 44 of this release, here decoded": it knows the decoded size of a segment,
which segment covers an offset, and it keeps the last few MB in RAM so a seek
back a few seconds does not hit the network again.

Three shapes are supported:
  * a plain video file (mkv / mp4 / avi / ts) posted as segments;
  * a stored (uncompressed) RAR set, which is what scene TV releases use;
  * a stored 7z set, whose file data starts after the 32-byte start header.
Compressed or encrypted archives cannot be read sequentially, so they are
refused with a clear reason instead of serving broken bytes.
"""

import queue
import threading
import time
import re
import os
from collections import OrderedDict
from concurrent.futures import CancelledError, Future

from . import config, nntp, nzb, yenc

HOLE_WARMUP = 20                # articles read before the percentage is trusted
DEFAULT_HOLE_PERCENT = 2.0      # of the articles read may be missing
DEFAULT_HOLE_CONSECUTIVE = 4    # missing articles in a row that already break a film
FAILURES_BEFORE_DOWN = 3        # connection errors in a row before the backup takes over
TRANSIENT_TRIES = 2             # a stalled connection gets one fresh retry
READ_CHUNK = 1024 * 1024
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
    return ''


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
        self.last_read = time.time()
        self.prepared = False
        self.first_crc_ok = True
        self.warm = []

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
                try:
                    replies = connection.body_many([wanted[slot] for slot in left])
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
                    with self.lock:
                        seen = self.served_counts.get(pool.label, 0)
                        self.served_counts[pool.label] = seen + len(delivered)
                        self.served_bytes[pool.label] = (
                            self.served_bytes.get(pool.label, 0)
                            + sum(len(payload) for _slot, payload in delivered))
                        self.served_seconds[pool.label] = (
                            self.served_seconds.get(pool.label, 0.0) + elapsed)
                        clear = (not pool.provider.get('backup')
                                 and not self._primary_cleared)
                        if clear:
                            self._primary_cleared = True
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

    def _warm_front(self, segments):
        """Keep the next few articles beside the first one.

        The reader is sequential: while the connection pool is still being
        dialed, one late article at the very start holds up the whole open
        even when everything after it has already arrived.
        """
        self.warm = []
        wanted = [(index, item[2]) for index, item in enumerate(segments[1:WARM_ARTICLES], start=1)]
        if not wanted:
            return
        replies = self._articles([message_id for _index, message_id in wanted])
        for (index, message_id), article in zip(wanted, replies):
            if article is None:
                continue
            try:
                info = yenc.decode(article)
            except yenc.YencError:
                continue
            self.warm.append((index, message_id, info['data']))
            self._remember((0, index), info['data'])

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
        media, kind = nzb.pick_media(files)
        if media is None:
            if kind == 'sample':
                raise SessionError('this NZB contains only a sample or trailer')
            raise SessionError('this NZB contains no video')
        self.media_name = media.name or 'video'
        if kind == '7z':
            return self._prepare_seven(files)
        if kind == 'video':
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
            self._pinned.add((0, 0))
            self._remember((0, 0), info['data'])
            self._warm_front(media.segments)
            self.prepared = True
            self._warm_tail()
            return self.info()

        volumes = nzb.rar_volumes(files)
        if not volumes:
            raise SessionError('this NZB contains no playable file')
        self.media_name = volumes[0].name or self.media_name
        first = self._decode_first(volumes[0].segments)
        self.first_crc_ok = bool(first.get('crc_ok', True))
        head = first['data']
        try:
            layout = nzb.rar_layout(head)
        except nzb.Unsupported as exc:
            raise SessionError(str(exc))
        if not layout.get('store'):
            raise SessionError('this RAR is compressed - only stored RAR sets can be streamed')
        if not layout.get('unp_size'):
            raise SessionError('the RAR header does not say how big the film is')
        self.inner_name = (layout.get('name') or '').strip()
        # Unele repack-uri pun un set RAR/7z in interiorul altui RAR. Primul
        # fisier din volumul exterior e atunci un volum intern (.r08 etc.),
        # nu filmul; fara garda, Kodi primeste 400 MB din mijlocul arhivei si
        # gaseste doar un flux audio. Respingem release-ul, playerul trece
        # la urmatoarea sursa.
        inner_head = head[layout['offset']:layout['offset'] + 8]
        if (inner_head.startswith(b'Rar!\x1a\x07')
                or inner_head.startswith(b'7z\xbc\xaf\x27\x1c')
                or re.search(r'\.(?:rar|r\d{2,3}|7z(?:\.\d+)?)$', self.inner_name, re.I)):
            raise SessionError('this release is a RAR inside a RAR - not supported')
        self.container = 'iso' if (self.inner_name.lower().endswith('.iso') or
                                   (not self.inner_name and
                                    _sniff(head, layout['offset']) == 'iso')) else 'rar'
        self.length = layout['unp_size']
        self.part_size = 0
        fmt = layout.get('fmt')
        if fmt == 5 and not layout.get('first', True):
            raise SessionError('the first RAR volume is missing from this NZB')
        base_volume = int(layout.get('volume') or 0)
        # Every volume after the first carries a volume-number vint, taken out of its data.
        tail = nzb.file_size(volumes[0]) - layout['offset'] - layout['length']
        remaining = self.length
        for index, volume in enumerate(volumes[:400]):
            last = index >= len(volumes) - 1
            skip = layout['offset']
            if fmt == 5 and index:
                skip += _vint_len(base_volume + index)
                if layout.get('volfield'):
                    skip -= _vint_len(base_volume)
            if last:
                size = remaining
            elif fmt == 5 and index and tail > 0:
                size = nzb.file_size(volume) - skip - tail
            else:
                size = min(layout['length'], remaining)
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
        self._pinned.add((0, 0))
        self._remember((0, 0), head)
        self._warm_front(volumes[0].segments)
        self.prepared = True
        self._warm_tail()
        return self.info()

    def _prepare_seven(self, files):
        volumes = nzb.seven_volumes(files)
        if not volumes:
            raise SessionError('this NZB contains no playable file')
        self.media_name = volumes[0].name or self.media_name
        first = self._decode_first(volumes[0].segments)
        self.first_crc_ok = bool(first.get('crc_ok', True))
        head = first['data']
        try:
            layout = nzb.seven_layout(head)
        except nzb.Unsupported as exc:
            raise SessionError(str(exc))
        start = layout['offset']
        self.container = _sniff(head, start)
        if not self.container:
            raise SessionError('this 7z archive is compressed - only stored 7z sets can be streamed')
        self.length = layout['length']
        self.part_size = 0
        remaining = self.length
        for index, volume in enumerate(volumes[:400]):
            skip = start if index == 0 else 0
            size = min(remaining, max(0, nzb.file_size(volume) - skip))
            self.parts.append({
                'id': index,
                'segments': [item[2] for item in volume.segments],
                'skip': skip,
                'length': size,
                'part_size': len(head) if index == 0 else 0,
            })
            remaining -= size
            if remaining <= 0:
                break
        if remaining > 0:
            raise SessionError('the 7z volumes are shorter than the archive header says')
        self._pinned.add((0, 0))
        self._remember((0, 0), head)
        self._warm_front(volumes[0].segments)
        self.prepared = True
        self._warm_tail()
        return self.info()

    def info(self):
        extension = {'mkv': '.mkv', 'mp4': '.mp4', 'avi': '.avi', 'ts': '.ts',
                     'iso': '.iso'}.get(self.container, '.mkv')
        base = re.split(r'[\\/]', self.inner_name or self.media_name or '')[-1]
        base = re.sub(r'\.(7z(?:\.\d+)?|part\d+\.rar|rar|r\d{2,3}|\d{3})$', '', base, flags=re.I)
        base = re.sub(r'\.(mkv|mp4|m4v|avi|ts|m2ts|mov|wmv|webm|mpg|mpeg|iso)$', '', base, flags=re.I)
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
            part_index, local = self._locate(self.length - 1)
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
        with self.lock:
            previous = self._last_start
            tail = start >= self.length - INDEX_TAIL_BYTES
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
        length = min(length, self.length - start)
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
