"""Newznab: search the user's own indexers and download the NZB.

Every indexer counts API hits (searches) and grabs (NZB downloads) per day and
suspends accounts that keep asking after the limit, so requests go through a
small bookkeeping file: it reads the limits an indexer reports
(newznab:apilimits), stops at 90% of them, rests an indexer that answered 429
for an hour and one that answered "limit reached" until the next day. Answers
are cached for a few hours, so opening the same film twice costs nothing.
"""

import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import config, nzb

TIMEOUT = 15
MAX_BYTES = 4 * 1024 * 1024
CHUNK = 256 * 1024
MAX_NZB_BYTES = 128 * 1024 * 1024
CATEGORY = {'movie': '2000', 'series': '5000'}
CACHE_TTL = 6 * 3600
CACHE_KEEP = 60
DAY_SHARE = 0.9
DEFAULT_API_MAX = 200
RETRY_AFTER = 3600
USER_AGENT = 'plugin.video.tmdbmovies usenet'


def _agent():
    return config.indexer_agent() or USER_AGENT

_LOCK = threading.Lock()
_LIMITS = re.compile(rb'<[^>]*apilimits\b([^>]*)>', re.I)
_SAMPLE = re.compile(r'\b(sampl(?:e)?|trailer|teaser|featurette|extras?)\b', re.I)
_SECRET = re.compile(r'((?:apikey|api_key|key|token)=)[^&\s]+', re.I)
_CREDENTIALS = re.compile(r'(https?://)[^/\s:@]+:[^/\s@]+@')


def redact(text):
    """An API key or a password must never reach a log line through an error."""
    clean = _SECRET.sub(r'\1***', str(text or ''))
    return _CREDENTIALS.sub(r'\1***@', clean)


class LimitReached(Exception):
    """This indexer must not be asked again today."""


class KeyRejected(Exception):
    """The API key was not accepted."""


def _now():
    return time.time()


def _today(now=None):
    return time.strftime('%Y-%m-%d', time.gmtime(_now() if now is None else now))


def _tomorrow(now=None):
    stamp = _now() if now is None else now
    return (int(stamp) // 86400 + 1) * 86400


# -- bookkeeping ---------------------------------------------------------------

def _load(name):
    path = config.data_file(name)
    if not path:
        return {}
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(name, data):
    path = config.data_file(name)
    if not path:
        return
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except Exception:
        pass


def _usage_entry(data, url, now=None):
    host = re.sub(r'^https?://', '', url).split('/', 1)[0]
    entry = data.setdefault(host, {})
    if entry.get('day') != _today(now):
        entry.update(day=_today(now), api=0, grab=0)
    return entry


def _allowed(url, kind='api', now=None):
    with _LOCK:
        entry = _usage_entry(_load('usenet_usage.json'), url, now)
    stamp = _now() if now is None else now
    if entry.get('paused_until', 0) > stamp and kind in entry.get('paused', ('api', 'grab')):
        return False
    limit = entry.get(kind + '_max') or (DEFAULT_API_MAX if kind == 'api' else 0)
    return not limit or entry.get(kind, 0) < limit * DAY_SHARE


def _note(url, kind='api', body=b''):
    with _LOCK:
        data = _load('usenet_usage.json')
        entry = _usage_entry(data, url)
        entry[kind] = entry.get(kind, 0) + 1
        found = _LIMITS.search(body[:4096]) if body else None
        if found:
            attributes = dict((k.decode().lower(), v.decode())
                              for k, v in re.findall(rb'(\w+)="(\d+)"', found.group(1)))
            for name, field in (('apimax', 'api_max'), ('grabmax', 'grab_max')):
                if attributes.get(name, '').isdigit() and int(attributes[name]):
                    entry[field] = int(attributes[name])
        _save('usenet_usage.json', data)


def _pause(url, until, kinds=('api', 'grab')):
    with _LOCK:
        data = _load('usenet_usage.json')
        entry = _usage_entry(data, url)
        entry.update(paused_until=until, paused=list(kinds))
        _save('usenet_usage.json', data)


def usage_line(url):
    """'12 searches today of 100' - shown by the indexer test."""
    entry = _usage_entry(_load('usenet_usage.json'), url)
    limit = entry.get('api_max')
    return '%d searches today%s' % (entry.get('api', 0), (' of %d' % limit) if limit else '')


# -- the API -------------------------------------------------------------------

def _get(indexer, params, timeout=None):
    url, key = indexer['url'], indexer['key']
    if not _allowed(url, 'api'):
        raise LimitReached('the daily searches on %s are used up' % indexer['name'])
    query = urlencode(dict(params, apikey=key))
    request = Request(url + '?' + query, headers={'User-Agent': _agent(),
                                                  'Accept': 'application/rss+xml, application/xml'})
    try:
        with urlopen(request, timeout=timeout or TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code in (401, 403):
            raise KeyRejected('%s: the API key was not accepted' % indexer['name'])
        if code == 429:
            _pause(url, _now() + RETRY_AFTER, ('api',))
            raise LimitReached('%s asked to wait - it is asked again in an hour' % indexer['name'])
        raise LimitReached('%s did not answer (%s)' % (indexer['name'], code or type(exc).__name__))
    _note(url, 'api', body)
    if len(body) > MAX_BYTES:
        raise LimitReached('%s sent an answer that is too large' % indexer['name'])
    head = body[:800]
    if re.search(rb'<error[^>]*code="500"', head):
        _pause(url, _tomorrow())
        raise LimitReached('%s reached its daily limit' % indexer['name'])
    if re.search(rb'<error[^>]*code="501"', head):
        _pause(url, _tomorrow(), ('grab',))
        raise LimitReached('%s used up its NZB downloads' % indexer['name'])
    return body


def _localname(tag):
    return tag.split('}')[-1] if '}' in tag else tag


def _posted(rfc2822):
    if not rfc2822:
        return 0
    try:
        import email.utils
        parsed = email.utils.parsedate_tz(rfc2822.strip())
        return int(email.utils.mktime_tz(parsed)) if parsed else 0
    except Exception:
        return 0


def results(body, indexer_name):
    """Newznab RSS -> [{'indexer','title','nzb_url','size','grabs','posted','password'}]."""
    head = body[:2048].lower()
    if b'<!doctype' in head:
        raise LimitReached('%s answered with a web page, not the API' % indexer_name)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise LimitReached('%s gave an answer we cannot read' % indexer_name)
    if root.tag == 'error':
        code = str(root.get('code') or '')
        if code in ('100', '101', '102'):
            raise KeyRejected('%s: the API key was not accepted' % indexer_name)
        raise LimitReached('%s: %s' % (indexer_name, redact((root.get('description') or 'error')[:80])))
    rows = []
    for item in root.iter('item'):
        title = ''
        link = ''
        size = 0
        grabs = 0
        posted = 0
        password = False
        for child in item:
            tag = _localname(child.tag)
            if tag == 'title':
                title = (child.text or '').strip()
            elif tag == 'link' and not link:
                text = (child.text or '').strip()
                if text.startswith('http'):
                    link = text
            elif tag == 'enclosure':
                url = child.get('url') or ''
                if url.startswith('http'):
                    link = url
                try:
                    size = int(child.get('length') or 0)
                except ValueError:
                    pass
            elif tag == 'pubDate' and not posted:
                posted = _posted(child.text)
            elif tag == 'attr':
                name = (child.get('name') or '').lower()
                value = child.get('value') or ''
                if name == 'size' and value:
                    try:
                        size = int(value)
                    except ValueError:
                        pass
                elif name == 'grabs' and value:
                    try:
                        grabs = int(value)
                    except ValueError:
                        pass
                elif name in ('usenetdate', 'postdate') and value:
                    posted = _posted(value) or posted
                elif name == 'password':
                    password = value.strip() not in ('', '0')
        if not title or not link:
            continue
        rows.append({'indexer': indexer_name, 'title': title, 'nzb_url': link, 'size': size,
                     'grabs': grabs, 'posted': posted, 'password': password})
    return rows


def _query(indexer, kind, imdb, season, episode, title):
    digits = re.sub(r'\D', '', str(imdb or ''))
    common = {'extended': 1, 'limit': 100, 'cat': CATEGORY['series' if season is not None else 'movie']}
    if season is None:
        params = dict(common, t='movie')
        if digits:
            params['imdbid'] = digits
        else:
            params['q'] = (title or '').strip()
        rows = results(_get(indexer, params), indexer['name'])
        if rows or not title:
            return rows
        # Some indexers have nothing under the IMDb id: ask by name instead.
        return results(_get(indexer, dict(common, t='movie', q=title.strip())), indexer['name'])
    params = dict(common, t='tvsearch', season=int(season), ep=int(episode or 0))
    if digits:
        params['imdbid'] = digits
    else:
        params['q'] = title or ''
    rows = results(_get(indexer, params), indexer['name'])
    if rows or not title:
        return rows
    # Some indexers ignore the IMDb id for series: ask by name instead.
    return results(_get(indexer, dict(common, t='tvsearch', season=int(season),
                                      ep=int(episode or 0), q=title.strip())), indexer['name'])


def episode_pairs(title):
    """Every (season, episode) a release name declares: S01E01E02, S01E01-E02, 1x01-02."""
    low = re.sub(r'[\._-]+', ' ', str(title or '').lower())
    pairs = set()
    for match in re.finditer(r's(\d{1,2})\s*e(\d{1,3})((?:\s*[-]?\s*e?\d{1,3})*)', low):
        season = int(match.group(1))
        pairs.add((season, int(match.group(2))))
        for extra in re.findall(r'(\d{1,3})', match.group(3) or ''):
            pairs.add((season, int(extra)))
    for match in re.finditer(r'(\d{1,2})x(\d{1,3})((?:\s*[-]?\s*\d{1,3})*)', low):
        season = int(match.group(1))
        pairs.add((season, int(match.group(2))))
        for extra in re.findall(r'(\d{1,3})', match.group(3) or ''):
            pairs.add((season, int(extra)))
    return pairs


def is_single_episode(title, season, episode):
    """With 'single episodes only' a season pack is refused: this engine streams,
    and a pack means tens of GB downloaded before the first frame. A file that carries
    several episodes (S01E01E02, S01E01-E02, 1x01-02) is accepted for each of them."""
    if season is None:
        return True
    text = str(title or '')
    low = re.sub(r'[\._-]+', ' ', text.lower())
    if (int(season), int(episode or 0)) in episode_pairs(text):
        return True
    looks_like_pack = (re.search(r'\bs\d{1,2}\s*e\d{1,3}\s*[-]\s*e?\d{1,3}\b', low)
                       or re.search(r'\bs\d{2}\b(?![\s]*e\d)', low)
                       or re.search(r'\b(complete|boxset|season|seasons)\b', low))
    return not looks_like_pack


def _why(why, reason):
    why[reason] = why.get(reason, 0) + 1


_TITLE_STOP = {
    'the', 'a', 'an', 'and', 'of', 'for', 'with', 'from', 'part', 'complete',
    'extended', 'remastered', 'proper', 'repack', 'internal', 'limited',
    'bluray', 'blu', 'ray', 'webrip', 'webdl', 'web', 'hdtv', 'remux',
    'hevc', 'h264', 'h265', 'x264', 'x265', 'avc', 'dts', 'ddp', 'dd', 'atmos',
    'truehd', 'hdr', 'sdr', 'dv', 'uhd', '2160p', '1080p', '720p', '480p',
    'german', 'dl', 'ita', 'eng', 'french', 'multi', 'sub', 'subs', 'ro',
}


def _title_tokens(text):
    text = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', str(text or ''))
    words = re.findall(r'[0-9a-z]+', text.lower())
    return [word for word in words if len(word) >= 4 and word not in _TITLE_STOP
            and not re.fullmatch(r'(?:19|20)\d{2}', word)]


_EPISODE_MARK = re.compile(
    r'(?<![0-9a-z])s\d{1,2}[\s._-]*e\d{1,3}|(?<![0-9a-z])\d{1,2}x\d{1,3}', re.I)


def _title_matches(candidate, query, year, is_movie, alt_query=''):
    """Reject an indexer answer that is plainly another film.

    Only distinctive words from the requested title are required to appear, so
    release tags and different editions still pass; a non-Latin title has no
    usable tokens and is never filtered.
    """
    tokens = _title_tokens(query) + _title_tokens(alt_query)
    if not tokens:
        return True
    folded = re.sub(r'[^0-9a-z]+', ' ', str(candidate or '').lower())
    if not any(token in folded for token in tokens):
        return False
    # For a series the show name must sit before SxxExx: a show title that only
    # shows up after it is that episode's name ("Secrets and Lies" is also the
    # title of 30 Rock S02E08, so a text search returns the wrong series).
    if not is_movie:
        mark = _EPISODE_MARK.search(str(candidate or ''))
        if mark:
            head = re.sub(r'[^0-9a-z]+', ' ', str(candidate or '')[:mark.start()].lower())
            if re.search(r'[a-z]{2,}', head) and not any(token in head for token in tokens):
                return False
    if is_movie and year:
        try:
            wanted = int(year)
        except (TypeError, ValueError):
            wanted = 0
        if wanted:
            found = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', str(candidate or ''))
            if found and wanted not in [int(item) for item in found]:
                return False
    return True


def _filter_rows(rows, season, episode, min_size, episodes_only, per_indexer_limit,
                 seen_links, seen_titles, per_indexer, why,
                 query_title='', query_year=None, query_alt=''):
    """The releases that would reach the source list, in the order they arrived."""
    kept = []
    for row in rows:
        link = row.get('nzb_url') or ''
        if link:
            if link in seen_links:
                _why(why, 'same NZB twice')
                continue
            seen_links.add(link)
        title = (row.get('title') or '').strip()
        if not title or row.get('password'):
            _why(why, 'broken row')
            continue
        if _SAMPLE.search(title):
            continue
        if not _title_matches(title, query_title, query_year, season is None, query_alt):
            _why(why, 'wrong title')
            continue
        try:
            size = int(row.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        row['size'] = size
        if size and size < min_size:
            _why(why, 'too small')
            continue
        if episodes_only and not is_single_episode(title, season, episode):
            _why(why, 'pack, not a single episode')
            continue
        folded = nzb.release_key(title)
        size_key = size // (100 * 1024 * 1024) if size else 0
        title_key = (folded, size_key)
        if title_key in seen_titles:
            _why(why, 'same title twice')
            continue
        seen_titles.add(title_key)
        indexer_name = row.get('indexer') or 'Indexer'
        if per_indexer_limit and per_indexer.get(indexer_name, 0) >= per_indexer_limit:
            _why(why, 'over the per-indexer limit')
            continue
        per_indexer[indexer_name] = per_indexer.get(indexer_name, 0) + 1
        kept.append(row)
    return kept


def _cache_key(kind, imdb, season, episode, indexer):
    """One answer per indexer: a partial sequential answer must never hide the others."""
    return '%s|%s|%s|%s|%s|%s' % (kind, imdb, season, episode,
                                   indexer.get('url', ''), indexer.get('name', ''))


def _cache_get(key):
    """(hit, rows) for a fresh answer, including a cached empty answer."""
    with _LOCK:
        kept = _load('usenet_cache.json').get(key)
    if kept is not None and _now() - kept.get('at', 0) < CACHE_TTL:
        return True, kept.get('rows') or []
    return False, []


def _cache_put(key, rows):
    with _LOCK:
        data = _load('usenet_cache.json')
        data[key] = {'at': _now(), 'rows': rows}
        fresh = sorted(((name, value) for name, value in data.items()
                        if _now() - value.get('at', 0) < CACHE_TTL),
                       key=lambda pair: pair[1].get('at', 0), reverse=True)[:CACHE_KEEP]
        _save('usenet_cache.json', dict(fresh))


def clear_cache():
    """Forget every cached answer - used by Clear cache in the settings."""
    with _LOCK:
        _save('usenet_cache.json', {})
    return True


def _ask(indexer, kind, imdb, season, episode, title, use_cache, logger):
    """(cache_key, rows, from_cache, note) for one indexer."""
    key = _cache_key(kind, imdb, season, episode, indexer)
    if use_cache:
        hit, rows = _cache_get(key)
        if hit:
            if logger:
                logger('[USENET] %s: %d result(s) from cache' % (indexer['name'], len(rows)))
            return key, rows, True, None
    try:
        rows = _query(indexer, kind, imdb, season, episode, title)
        if logger:
            logger('[USENET] %s: %d result(s)' % (indexer['name'], len(rows)))
        return key, rows, False, None
    except (LimitReached, KeyRejected) as exc:
        return key, [], False, redact(exc)
    except Exception as exc:
        return key, [], False, '%s: %s' % (indexer['name'], redact(str(exc)[:90]))


def find(kind, imdb, season=None, episode=None, title='', year=None, alt_title='',
         logger=None, use_cache=True, mode=None, min_usable=None, min_size=0,
         episodes_only=False, per_indexer_limit=0):
    """Search the configured indexers. Returns (rows, notes).

    Sequential asks the next indexer only while fewer than 'min_usable' releases
    passed the filters; parallel asks every selected indexer at once. Answers are
    cached per indexer, so one partial answer never hides the others.
    """
    if not config.indexers_enabled():
        return [], ['indexers are off in the settings']
    entries = config.indexers()
    if not entries:
        return [], ['no indexer is configured']
    if min_usable is None:
        min_usable = config.stop_after()
    min_usable = max(1, int(min_usable))
    mode = str(mode or config.fetch_mode()).strip().lower()
    if mode != 'parallel':
        mode = 'sequential'
    min_size = max(0, int(min_size or 0))
    per_indexer_limit = max(0, int(per_indexer_limit or 0))
    episodes_only = bool(episodes_only) and season is not None

    notes = []
    rows = []
    seen_links, seen_titles, per_indexer, why = set(), set(), {}, {}
    raw_count = 0

    def collect(found):
        nonlocal raw_count
        raw_count += len(found)
        kept = _filter_rows(found, season, episode, min_size, episodes_only,
                            per_indexer_limit, seen_links, seen_titles,
                            per_indexer, why, query_title=title, query_year=year,
                            query_alt=alt_title)
        rows.extend(kept)
        return len(kept)

    if mode == 'parallel':
        if logger:
            logger('[USENET] parallel: asking %d indexer(s)' % len(entries))
        from concurrent.futures import ThreadPoolExecutor

        def one(entry):
            return _ask(entry, kind, imdb, season, episode, title, use_cache, logger)

        workers = max(1, min(4, len(entries)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='UsenetIndexer') as pool:
            answers = list(pool.map(one, entries))
        for key, found, cached, note in answers:
            if note:
                notes.append(note)
            elif not cached and use_cache:
                _cache_put(key, found)
            collect(found)
    else:
        if logger:
            logger('[USENET] sequential: asking up to %d indexer(s), stop at %d usable'
                   % (len(entries), min_usable))
        for position, entry in enumerate(entries, 1):
            key, found, cached, note = _ask(entry, kind, imdb, season, episode, title,
                                            use_cache, logger)
            if note:
                notes.append(note)
            elif not cached and use_cache:
                _cache_put(key, found)
            here = collect(found)
            if logger:
                logger('[USENET] sequential: %s -> %d usable (total %d of %d)'
                       % (entry['name'], here, len(rows), min_usable))
            if len(rows) >= min_usable:
                if logger:
                    logger('[USENET] sequential: enough after %s, %d indexer(s) not asked'
                           % (entry['name'], len(entries) - position))
                break

    if logger:
        for note in notes:
            logger('[USENET] %s' % note)
        dropped = ', '.join('%s: %d' % (reason, count) for reason, count in sorted(why.items()))
        logger('[USENET] %d of %d release(s) kept from %d indexer(s)%s'
               % (len(rows), raw_count, len(set(row.get('indexer') or 'Indexer' for row in rows)),
                  (' | dropped -> ' + dropped) if dropped else ''))
    return rows, notes


# -- NZB download --------------------------------------------------------------

def _remove_file(path):
    try:
        os.remove(path)
    except Exception:
        pass


def _complete_nzb(path):
    """A real NZB closes with </nzb>: a truncated download must never be kept."""
    try:
        size = os.path.getsize(path)
        if size < 64:
            return False
        with open(path, 'rb') as handle:
            if b'<nzb' not in handle.read(4096).lower():
                return False
            handle.seek(max(0, size - 8192))
            return b'</nzb>' in handle.read().lower()
    except Exception:
        return False


def _body_chunks(response):
    """The response body, gunzipped on the fly (we ask for gzip ourselves)."""
    first = response.read(2)
    if not first:
        return
    if first == b'\x1f\x8b':
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(first)
        if data:
            yield data
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            data = decoder.decompress(chunk)
            if data:
                yield data
        data = decoder.flush()
        if data:
            yield data
        return
    yield first
    while True:
        chunk = response.read(CHUNK)
        if not chunk:
            return
        yield chunk


def _save_nzb(url, timeout, temp):
    """Stream the download straight to disk: no 4 MB cap and no full copy in RAM."""
    request = Request(url, headers={'User-Agent': _agent(),
                                    'Accept-Encoding': 'gzip'})
    total = 0
    try:
        with urlopen(request, timeout=timeout) as response:
            with open(temp, 'wb') as handle:
                for chunk in _body_chunks(response):
                    total += len(chunk)
                    if total > MAX_NZB_BYTES:
                        raise ValueError('the NZB is larger than %d MB'
                                         % (MAX_NZB_BYTES // (1024 * 1024)))
                    handle.write(chunk)
    except Exception:
        _remove_file(temp)
        raise
    if total <= 0 or not _complete_nzb(temp):
        _remove_file(temp)
        return False
    return True


def fetch_nzb(url, key=None, timeout=25):
    """Download the .nzb once and keep it in the profile (without the API key)."""
    key = key or config.nzb_key(url)
    path = config.nzb_path(key)
    if not path:
        return None
    if os.path.exists(path):
        if _complete_nzb(path):
            return path
        _remove_file(path)
    if not str(url or '').lower().startswith(('http://', 'https://')):
        return None
    temp = path + '.part'
    for _attempt in range(2):
        try:
            if _save_nzb(url, timeout, temp):
                os.replace(temp, path)
                return path
        except Exception as exc:
            _remove_file(temp)
            code = getattr(exc, 'code', None)
            if code and 400 <= code < 500:
                return None
    return None


# -- the test button -----------------------------------------------------------

def test(indexer):
    """(ok, message) for one indexer: caps, then a real search if needed."""
    url = indexer['url']
    try:
        body = _get(indexer, {'t': 'caps'}, timeout=12)
        if b'<caps' in body[:4096].lower() or b'<server' in body[:4096].lower():
            return True, '%s: API key accepted (%s)' % (indexer['name'], usage_line(url))
    except KeyRejected as exc:
        return False, str(exc)
    except LimitReached as exc:
        return False, str(exc)
    try:
        body = _get(indexer, {'t': 'search', 'q': 'the', 'limit': 1}, timeout=12)
        if b'<rss' in body[:4096].lower() or b'<channel' in body[:4096].lower():
            return True, '%s: API key accepted (%s)' % (indexer['name'], usage_line(url))
        return False, '%s answered something unexpected - check the address ends in /api' % indexer['name']
    except (KeyRejected, LimitReached) as exc:
        return False, redact(exc)
    except Exception as exc:
        return False, '%s: %s' % (indexer['name'], redact(str(exc)[:90]))
