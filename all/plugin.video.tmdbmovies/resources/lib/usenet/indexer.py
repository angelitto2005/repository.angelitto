"""Newznab: search the user's own indexers and download the NZB.

Every indexer counts API hits (searches) and grabs (NZB downloads) per day and
suspends accounts that keep asking after the limit, so requests go through a
small bookkeeping file: it reads the limits an indexer reports
(newznab:apilimits), stops at 90% of them, rests an indexer that answered 429
for an hour and one that answered "limit reached" until the next day. Answers
are cached for a few hours, so opening the same film twice costs nothing.
"""

import html
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
NZBINDEX_PAUSE = 900
BINSEARCH_PAUSE = 900
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


_SEASON_WORD_EPISODE = re.compile(
    r'\b(?:season|seizoen)\s*(\d{1,2})\s*[._ -]*(?:episode|aflevering|ep)\s*[._ -]*(\d{1,3})\b', re.I)
_SINGLE_EPISODE = re.compile(r'\bs(\d{1,2})\s*[._ -]?\s*e(\d{1,3})\b', re.I)
_EPISODE_RANGE = re.compile(r'\bs(\d{1,2})\s*e(\d{1,3})\s*[-\u2013]\s*e?(\d{1,3})\b', re.I)


_SEASON_RANGE = re.compile(
    r'\bs(\d{1,2})\s*[-\u2013]\s*s?(\d{1,2})\b'
    r'|\b(?:seasons?|seizoen(?:en)?)\s*(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\b', re.I)
_SEASON_MARK = re.compile(
    r'\bs(\d{1,2})\b(?!\s*[._ -]?\s*e)'
    r'|\b(?:season|seizoen)\s*(\d{1,2})\b', re.I)


def _pack_season_ok(title, season):
    """A pack for another season must not sit in this episode's list."""
    text = str(title or '')
    wanted = int(season)
    for mark in _SEASON_RANGE.finditer(text):
        low, high = [int(group) for group in mark.groups() if group][:2]
        return low <= wanted <= high
    found = set()
    for mark in _SEASON_MARK.finditer(text):
        for group in mark.groups():
            if group:
                found.add(int(group))
    if not found:
        return True
    return wanted in found


def _pack_title(title, season=None):
    """No single episode in the name, or a range of episodes: a pack we can use."""
    text = str(title or '')
    if _SEASON_WORD_EPISODE.search(text):
        return False
    if re.search(r'\.part\d+$', text, re.I):
        return False
    if season is not None:
        for mark in _EPISODE_RANGE.finditer(text):
            if int(mark.group(1)) == int(season):
                return False
    mark = _SINGLE_EPISODE.search(text)
    if not mark:
        return True
    return bool(re.match(r'\s*[-\u2013]\s*e?\d{1,3}\b', text[mark.end():], re.I))


def _episode_query(indexer, common, digits, season, episode, title):
    params = dict(common, t='tvsearch', season=int(season), ep=int(episode or 0))
    if digits:
        params['imdbid'] = digits
    else:
        params['q'] = _query_title(title)
    rows = results(_get(indexer, params), indexer['name'])
    if rows or not title:
        return rows
    # Some indexers ignore the IMDb id for series: ask by name instead.
    return results(_get(indexer, dict(common, t='tvsearch', season=int(season),
                                      ep=int(episode or 0), q=_query_title(title))), indexer['name'])


def _pack_tier(title):
    low = (title or '').lower()
    if re.search(r'2160p|\b4k\b|\buhd\b', low):
        return '4k'
    if '1080p' in low:
        return '1080p'
    if '720p' in low:
        return '720p'
    return ''


def _season_packs(indexer, digits, season, title, use_cache, logger):
    """Season packs, cached per season: the whole TV tree is asked once, and a
    100-row page is mostly episodes, so another page is read only while the usual
    1080p/720p pack tiers are still missing."""
    pages = config.pack_pages()
    key = 'series|%s|%s|packs5p%d|%s|%s' % (digits, season, pages,
                                          indexer.get('url', ''), indexer.get('name', ''))
    if use_cache:
        hit, rows = _cache_get(key)
        if hit:
            if logger:
                logger('[USENET] %s: %d season pack(s) from cache' % (indexer['name'], len(rows)))
            return rows
    packs, known, tiers, answered = [], set(), set(), False

    def ask(offset, by_title=False):
        params = {'extended': 1, 'limit': 100, 'cat': CATEGORY['series'],
                  't': 'tvsearch', 'season': int(season)}
        if offset:
            params['offset'] = offset
        if digits and not by_title:
            params['imdbid'] = digits
        else:
            params['q'] = _query_title(title)
        return results(_get(indexer, params), indexer['name'])

    def take(found):
        for row in found:
            link = row.get('nzb_url') or ''
            name = row.get('title')
            if (link and link not in known and _pack_title(name, season)
                    and _pack_season_ok(name, season)):
                known.add(link)
                packs.append(row)
                tier = _pack_tier(name)
                if tier:
                    tiers.add(tier)

    offset = 0
    by_title = not digits
    previous_first = ''
    for _page in range(pages):
        try:
            found = ask(offset, by_title=by_title)
            if not found and offset == 0 and not by_title and title:
                # Some indexers ignore the IMDb id for a season ask.
                by_title = True
                found = ask(0, by_title=True)
        except Exception:
            break
        answered = True
        first_link = (found[0].get('nzb_url') or '') if found else ''
        if first_link and first_link == previous_first:
            # The indexer ignored offset and repeated the same page.
            break
        previous_first = first_link
        take(found)
        if '1080p' in tiers and '720p' in tiers:
            break
        if len(found) < 100:
            break
        offset += 100
    if answered and use_cache:
        _cache_put(key, packs)
    return packs


def _series_query(indexer, common, digits, season, episode, title, use_cache, logger):
    """Episode sources plus the season packs, the packs cached for the whole season."""
    rows = _episode_query(indexer, common, digits, season, episode, title)
    try:
        packs = _season_packs(indexer, digits, season, title, use_cache, logger)
    except Exception:
        packs = []
    known = set(row.get('nzb_url') for row in rows)
    return [row for row in packs if row.get('nzb_url') not in known] + rows


def _query(indexer, kind, imdb, season, episode, title, packs=True, use_cache=True, logger=None,
           year=None, all_categories=False):
    if indexer.get('builtin') == 'nzbindex':
        return _nzbindex_rows(indexer, title, year, season, episode)
    if indexer.get('builtin') == 'binsearch':
        return _binsearch_rows(indexer, title, year, season, episode)
    digits = re.sub(r'\D', '', str(imdb or ''))
    if all_categories and season is None:
        # A user's own words are not a film title: search every category
        # (sports live under TV > Sport, not under Movies).
        params = {'extended': 1, 'limit': 100, 't': 'search',
                  'q': _query_title(title)}
        return results(_get(indexer, params), indexer['name'])
    common = {'extended': 1, 'limit': 100, 'cat': CATEGORY['series' if season is not None else 'movie']}
    if season is None:
        params = dict(common, t='movie')
        if digits:
            params['imdbid'] = digits
        else:
            params['q'] = _query_title(title)
        rows = results(_get(indexer, params), indexer['name'])
        if rows or not title:
            return rows
        # Some indexers have nothing under the IMDb id: ask by name instead.
        return results(_get(indexer, dict(common, t='movie', q=_query_title(title))), indexer['name'])
    if packs:
        return _series_query(indexer, common, digits, season, episode, title, use_cache, logger)
    return _episode_query(indexer, common, digits, season, episode, title)


def is_single_episode(title, season, episode):
    """With 'single episodes only' a season pack is refused: this engine streams,
    and a pack means tens of GB downloaded before the first frame. A file that carries
    several episodes (S01E01E02, S01E01-E02, 1x01-02) is accepted for each of them."""
    if season is None:
        return True
    text = str(title or '')
    low = re.sub(r'[\._-]+', ' ', text.lower())
    if (int(season), int(episode or 0)) in nzb.episode_pairs(text):
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
    'series', 'season', 'collection', 'boxset', 'episode',
    'bluray', 'blu', 'ray', 'webrip', 'webdl', 'web', 'hdtv', 'remux',
    'hevc', 'h264', 'h265', 'x264', 'x265', 'avc', 'dts', 'ddp', 'dd', 'atmos',
    'truehd', 'hdr', 'sdr', 'dv', 'uhd', '2160p', '1080p', '720p', '480p',
    'german', 'dl', 'ita', 'eng', 'french', 'multi', 'sub', 'subs', 'ro',
    'dual', 'audio', 'dubbed', 'subbed',
}
_TITLE_GLUE = {'the', 'a', 'an', 'and', 'of', 'for', 'with', 'from', 'part'}


_APOSTROPHE_RE = re.compile(r"['\u2018\u2019`]")


def _query_title(title):
    """The title as the indexers index it: apostrophes are dropped."""
    return _APOSTROPHE_RE.sub('', str(title or '')).strip()


def _title_tokens(text):
    text = _APOSTROPHE_RE.sub('', str(text or ''))
    text = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', text)
    words = re.findall(r'[0-9a-z]+', text.lower())
    return [word for word in words if len(word) >= 4 and word not in _TITLE_STOP
            and not re.fullmatch(r'(?:19|20)\d{2}', word)]


def _name_words(text):
    """The name words only: stop at the first release tag or year, keep glue."""
    clean = _APOSTROPHE_RE.sub('', str(text or ''))
    clean = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', clean)
    words = []
    for word in re.findall(r'[0-9a-z]+', clean.lower()):
        if re.fullmatch(r'(?:19|20)\d{2}', word):
            break
        if word in _TITLE_GLUE:
            continue
        if word in _TITLE_STOP:
            break
        if len(word) >= 4:
            words.append(word)
    return words


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
    folded = _APOSTROPHE_RE.sub('', str(candidate or '')).lower()
    folded = re.sub(r'[^0-9a-z]+', ' ', folded)
    if not any(token in folded for token in tokens):
        return False
    wanted = 0
    if year:
        try:
            wanted = int(year)
        except (TypeError, ValueError):
            wanted = 0
    # For a series the name part must be the show itself: "Millennium Love"
    # and "Der Millennium Raub" share a word with "Millennium" but are other
    # series, and a show title that only shows up after SxxExx is the episode
    # name ("Secrets and Lies" is also the title of 30 Rock S02E08).
    if not is_movie:
        name_part = _series_name_part(candidate)
        words = _name_words(name_part or candidate)
        if words and not set(words) <= set(tokens):
            return False
        # A row with no season or episode marker in a series search is often a
        # film that shares the word ("Millennium Actress 2002"): the year has
        # to be the show's year.
        if not name_part and wanted:
            found = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', str(candidate or ''))
            if found and wanted not in [int(item) for item in found]:
                return False
    if is_movie and wanted:
        found = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', str(candidate or ''))
        if found and wanted not in [int(item) for item in found]:
            return False
    return True


def _series_name_part(candidate):
    """The text before the first season/episode marker ('' when there is none)."""
    text = str(candidate or '')
    starts = [match.start() for match in
              (_EPISODE_MARK.search(text), _SEASON_MARK.search(text)) if match]
    return text[:min(starts)] if starts else ''


# -- the built-in free search --------------------------------------------------

def _nzbindex_get(indexer, params, timeout=None):
    """The site's own RSS feed: no account and no key, but it throttles bursts."""
    url = indexer['url'].rstrip('/') + '/rss?' + urlencode(params)
    if not _allowed(indexer['url'], 'api'):
        raise LimitReached('the searches on %s are paused for a while' % indexer['name'])
    request = Request(url, headers={'User-Agent': _agent(),
                                    'Accept': 'application/rss+xml, application/xml'})
    try:
        with urlopen(request, timeout=timeout or TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == 429:
            _pause(indexer['url'], _now() + NZBINDEX_PAUSE, ('api',))
            raise LimitReached('%s asked to wait - it is asked again in a few minutes'
                               % indexer['name'])
        raise LimitReached('%s did not answer (%s)'
                           % (indexer['name'], code or type(exc).__name__))
    _note(indexer['url'], 'api', body)
    if len(body) > MAX_BYTES:
        raise LimitReached('%s sent an answer that is too large' % indexer['name'])
    return body


def _free_query_title(title):
    """A query of name words only: the site tokenises on punctuation."""
    text = _APOSTROPHE_RE.sub('', str(title or '').replace('&', ' and '))
    text = re.sub(r'[^0-9A-Za-z]+', ' ', text)
    return ' '.join(text.split())


def _free_queries(title, year, season, episode):
    """Title + year wins; the shorter forms only run when nothing matched."""
    base = _free_query_title(title)
    if not base:
        return []
    year = str(year or '').strip()
    if not re.fullmatch(r'(?:19|20)\d{2}', year):
        year = ''
    if season is None:
        return [' '.join(piece for piece in (base, year) if piece)]
    try:
        season = int(season)
        episode = int(episode or 0)
    except (TypeError, ValueError):
        return []
    queries = []
    for pieces in ((base, year, 'S%02dE%02d' % (season, episode)),
                   (base, 'S%02dE%02d' % (season, episode)),
                   (base, year, 'S%dE%d' % (season, episode))):
        query = ' '.join(piece for piece in pieces if piece)
        if query not in queries:
            queries.append(query)
    return queries


def _free_clean(title):
    """A release name from the first file of the collection."""
    text = re.sub(r'^\[\d+/\d+\]\s*[-:]?\s*', '', str(title or '')).strip()
    quoted = re.search(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', text)
    if quoted:
        text = quoted.group(1)
    text = re.sub(r'\s+yEnc(\s+\d+)?\s*$', '', text, flags=re.I).strip()
    text = re.sub(r'\.(?:par2|nfo|nzb)$', '', text, flags=re.I)
    return text.strip()


def _nzbindex_rows(indexer, title, year, season, episode):
    for query in _free_queries(title, year, season, episode):
        found = results(_nzbindex_get(indexer, {'q': query, 'max': 100, 'complete': 1,
                                               'sort': 'agedesc', 'page': 0}),
                        indexer['name'])
        page_rows, seen = [], set()
        useful = False
        for row in found:
            link = str(row.get('nzb_url') or '')
            if link.startswith('http://www.nzbindex.com/'):
                link = 'https://' + link[7:]
                row['nzb_url'] = link
            if not link or link in seen:
                continue
            try:
                size = int(row.get('size') or 0)
            except (TypeError, ValueError):
                size = 0
            if size <= 0:
                continue
            row['size'] = size
            row['title'] = _free_clean(row.get('title'))
            if not row['title'] or row['title'] in seen:
                continue
            seen.add(link)
            seen.add(row['title'])
            page_rows.append(row)
            if not useful:
                useful = _title_matches(row['title'], title, year,
                                        season is None)
        if page_rows and useful:
            return page_rows
    return []


_SIZE_UNITS = {'tb': 1024 ** 4, 'gb': 1024 ** 3, 'mb': 1024 ** 2, 'kb': 1024, 'b': 1}
_AGE_SECONDS = {'minute': 60, 'hour': 3600, 'day': 86400,
                'week': 7 * 86400, 'month': 30 * 86400, 'year': 365 * 86400}


def _binsearch_size(text):
    match = re.search(r'([\d.]+)\s*(tb|gb|mb|kb|b)\b', str(text or ''), re.I)
    if not match:
        return 0
    try:
        return int(float(match.group(1)) * _SIZE_UNITS[match.group(2).lower()])
    except ValueError:
        return 0


def _binsearch_posted(text, now=None):
    match = re.search(r'(\d+)\s*(minute|hour|day|week|month|year)s?',
                      str(text or ''), re.I)
    if not match:
        return 0
    return int((now or _now()) - int(match.group(1)) * _AGE_SECONDS[match.group(2).lower()])


def _binsearch_get(indexer, params, timeout=None):
    """The site's search page: no account, plain HTML, 25 rows a page."""
    url = indexer['url'].rstrip('/') + '/search?' + urlencode(params)
    if not _allowed(indexer['url'], 'api'):
        raise LimitReached('the searches on %s are paused for a while' % indexer['name'])
    request = Request(url, headers={'User-Agent': _agent(), 'Accept': 'text/html'})
    try:
        with urlopen(request, timeout=timeout or TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == 429:
            _pause(indexer['url'], _now() + BINSEARCH_PAUSE, ('api',))
            raise LimitReached('%s asked to wait - it is asked again in a few minutes'
                               % indexer['name'])
        if code == 403:
            raise LimitReached('%s asked for a browser check - try again later'
                               % indexer['name'])
        raise LimitReached('%s did not answer (%s)'
                           % (indexer['name'], code or type(exc).__name__))
    _note(indexer['url'], 'api', body)
    if len(body) > MAX_BYTES:
        raise LimitReached('%s sent an answer that is too large' % indexer['name'])
    head = body[:4096].lower()
    if b'just a moment' in head or b'cf-chl' in head:
        raise LimitReached('%s asked for a browser check - try again later' % indexer['name'])
    return body


def _binsearch_rows(indexer, title, year, season, episode):
    for query in _free_queries(title, year, season, episode):
        body = _binsearch_get(indexer, {'q': query}).decode('utf-8', 'replace')
        page_rows, seen = [], set()
        useful = False
        for raw in re.findall(r'<tr\b[^>]*>.*?</tr>', body, re.S):
            token = re.search(r'<input type="checkbox"[^>]*name="([A-Za-z0-9+/=_-]+)"', raw)
            subject = re.search(r'<a[^>]*href="/details/[^"]+">([^<]+)</a>', raw)
            if not token or not subject:
                continue
            flat = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', raw)).split())
            if 'incomplete' in flat.lower() or not re.search(r'\bcomplete\s+files?\b',
                                                             flat, re.I):
                continue
            name = _free_clean(html.unescape(subject.group(1)))
            if not name:
                continue
            size_match = re.search(r'bg-white">([^<]+)</span>', raw)
            size = _binsearch_size(size_match.group(1) if size_match else '')
            if size <= 0:
                continue
            link = '%s/nzb?%s' % (indexer['url'].rstrip('/'),
                                  urlencode({'q': query, token.group(1): 'on'}))
            if link in seen:
                continue
            seen.add(link)
            age_match = re.search(r'<td class="min-w-20">([^<]+)</td>', raw)
            page_rows.append({
                'indexer': indexer['name'], 'title': name, 'nzb_url': link,
                'size': size, 'grabs': 0, 'password': False,
                'posted': _binsearch_posted(age_match.group(1) if age_match else ''),
            })
            if not useful:
                useful = _title_matches(name, title, year, season is None)
        if page_rows and useful:
            return page_rows
    return []


def _filter_rows(rows, season, episode, min_size, episodes_only,
                 seen_links, seen_titles, why,
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
        title_key = (folded, size_key, str(row.get('indexer') or '').strip().lower())
        if title_key in seen_titles:
            _why(why, 'same title twice')
            continue
        seen_titles[title_key] = row
        kept.append(row)
    return kept


_ROW_4K = re.compile(r'2160p|\b4k\b|\buhd\b', re.I)
_ROW_BLURAY = re.compile(r'\b(bluray|blu-ray|bdrip|bd25|bd50|remux)\b', re.I)
_ROW_WEB = re.compile(r'\b(web-dl|webdl)\b', re.I)
_ROW_LOW = re.compile(r'\b(webrip|hdtv|cam|ts|telesync|hdcam)\b', re.I)
_ROW_HEVC = re.compile(r'\b(hevc|h\.?265|x265|av1)\b', re.I)
_ROW_AUDIO = re.compile(r'\b(atmos|truehd|dts[- ]?hd|dts[- ]?x)\b', re.I)


def _row_score(row, season, episode):
    """How good a release is, best first: resolution, exact episode, source, codec/audio, grabs, age.

    Used only to choose which N rows survive the per-indexer cap. The source
    list is sorted again for the UI, so this order never reaches the user.
    """
    title = str(row.get('title') or '')
    low = title.lower()
    if _ROW_4K.search(low):
        resolution = 4
    elif '1080p' in low:
        resolution = 3
    elif '720p' in low:
        resolution = 2
    else:
        resolution = 1
    if 'remux' in low:
        source = 5
    elif _ROW_BLURAY.search(low):
        source = 4
    elif _ROW_WEB.search(low):
        source = 3
    elif _ROW_LOW.search(low):
        source = 2
    else:
        source = 1
    bonus = (1 if _ROW_HEVC.search(low) else 0) + (1 if _ROW_AUDIO.search(low) else 0)
    exact = 1
    if season is not None:
        try:
            exact = 1 if (int(season), int(episode or 0)) in nzb.episode_pairs(title) else 0
        except Exception:
            exact = 0
    try:
        grabs = int(row.get('grabs') or 0)
    except (TypeError, ValueError):
        grabs = 0
    try:
        posted = int(row.get('posted') or 0)
    except (TypeError, ValueError):
        posted = 0
    return (resolution, exact, source, bonus, grabs, posted)


def _cap_per_indexer(rows, limit, season, episode, why):
    """Keep the best N rows of each indexer, in the order they still had."""
    if not limit or len(rows) <= limit:
        return rows
    groups = {}
    for row in rows:
        groups.setdefault(row.get('indexer') or 'Indexer', []).append(row)
    keep = set()
    for group in groups.values():
        group.sort(key=lambda row: _row_score(row, season, episode), reverse=True)
        for row in group[:limit]:
            keep.add(id(row))
        for _row in group[limit:]:
            _why(why, 'over the per-indexer limit')
    return [row for row in rows if id(row) in keep]


def _cache_key(kind, imdb, season, episode, indexer, year=''):
    """One answer per indexer: a partial sequential answer must never hide the others."""
    return '%s|%s|%s|%s|%s|%s|%s' % (kind, imdb, season, episode, year or '',
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


def _stat(name, **values):
    try:
        from . import stats
        stats.indexer(name, **values)
    except Exception:
        pass


def _ask(indexer, kind, imdb, season, episode, title, use_cache, logger, packs=True, year=None,
         all_categories=False):
    """(cache_key, rows, from_cache, note) for one indexer."""
    key = _cache_key(kind, imdb, season, episode, indexer, year)
    if season is not None:
        key += ('|packs5p%d' % config.pack_pages()) if packs else '|ep2'
    if use_cache:
        hit, rows = _cache_get(key)
        if hit:
            if logger:
                logger('[USENET] %s: %d result(s) from cache' % (indexer['name'], len(rows)))
            return key, rows, True, None
    started = time.time()
    try:
        rows = _query(indexer, kind, imdb, season, episode, title, packs, use_cache, logger,
                      year=year, all_categories=all_categories)
        _stat(indexer['name'], s=1, ss=time.time() - started, r=len(rows))
        if logger:
            logger('[USENET] %s: %d result(s)' % (indexer['name'], len(rows)))
        return key, rows, False, None
    except (LimitReached, KeyRejected) as exc:
        _stat(indexer['name'], s=1, ss=time.time() - started, se=1)
        return key, [], False, redact(exc)
    except Exception as exc:
        _stat(indexer['name'], s=1, ss=time.time() - started, se=1)
        return key, [], False, '%s: %s' % (indexer['name'], redact(str(exc)[:90]))


def find(kind, imdb, season=None, episode=None, title='', year=None, alt_title='',
         logger=None, use_cache=True, mode=None, min_usable=None, min_size=0,
         episodes_only=False, per_indexer_limit=0, scope='', all_categories=False):
    """Search the configured indexers. Returns (rows, notes).

    Sequential asks the enabled free built-ins and the Full keyed indexers
    together, because neither has a search-quota worry, then the Free/Trial
    indexers one at a time while the keyed usable answers (Full + Free/Trial)
    stay below 'min_usable': free built-in results never silence a keyed
    indexer. Parallel asks every selected indexer at once. Answers are cached
    per indexer, so one partial answer never hides the others.

    scope 'all', 'free' or 'paid' narrows which indexers are asked; the custom
    text search uses it so a free query never spends a keyed indexer's quota.
    all_categories makes that custom search ask Newznab with t=search and no
    category, so sports and other non-movie sections are included.
    """
    selection = str(scope or 'all').strip().lower()
    if selection not in ('all', 'free', 'paid'):
        selection = 'all'
    entries = config.indexers()
    if selection == 'free':
        entries = [entry for entry in entries if entry.get('builtin')]
    elif selection == 'paid':
        entries = [entry for entry in entries if not entry.get('builtin')]
    if not entries:
        return [], [{'free': 'no free indexer is enabled',
                     'paid': 'no paid indexer is enabled'}.get(selection,
                                                               'no indexer is configured')]
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
    seen_links, seen_titles, why = set(), {}, {}
    raw_count = 0

    def collect(found):
        nonlocal raw_count
        raw_count += len(found)
        kept = _filter_rows(found, season, episode, min_size, episodes_only,
                            seen_links, seen_titles, why,
                            query_title=title, query_year=year,
                            query_alt=alt_title)
        rows.extend(kept)
        return len(kept)

    if mode == 'parallel':
        if logger:
            logger('[USENET] parallel: asking %d indexer(s)' % len(entries))
        from concurrent.futures import ThreadPoolExecutor

        def one(entry):
            return _ask(entry, kind, imdb, season, episode, title, use_cache, logger,
                        packs=not episodes_only, year=year, all_categories=all_categories)

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
        free = [entry for entry in entries if entry.get('builtin')]
        full = [entry for entry in entries
                if not entry.get('builtin') and entry.get('full')]
        limited = [entry for entry in entries
                   if not entry.get('builtin') and not entry.get('full')]
        if logger:
            logger('[USENET] sequential: %d free, %d Full together, %d Free/Trial one by one until a key gives %d usable'
                   % (len(free), len(full), len(limited), min_usable))
        keyed_kept = 0
        first = free + full
        if first:
            from concurrent.futures import ThreadPoolExecutor

            if logger:
                logger('[USENET] free + Full together: %s'
                       % ', '.join(entry.get('name') or '?' for entry in first))

            def first_one(entry):
                return _ask(entry, kind, imdb, season, episode, title, use_cache, logger,
                            packs=not episodes_only, year=year, all_categories=all_categories)

            workers = max(1, min(6, len(first)))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='UsenetFree') as pool:
                answers = list(pool.map(first_one, first))
            free_kept = 0
            for entry, (key, found, cached, note) in zip(first, answers):
                if note:
                    notes.append(note)
                elif not cached and use_cache:
                    _cache_put(key, found)
                here = collect(found)
                if entry.get('builtin'):
                    free_kept += here
                else:
                    keyed_kept += here
            if logger:
                logger('[USENET] free + Full: %d free usable, %d keyed usable (%d of %d)'
                       % (free_kept, keyed_kept, keyed_kept, min_usable))
        if keyed_kept >= min_usable:
            if logger and limited:
                logger('[USENET] sequential: enough with Full, %d Free/Trial not asked'
                       % len(limited))
        else:
            for position, entry in enumerate(limited, 1):
                key, found, cached, note = _ask(entry, kind, imdb, season, episode, title,
                                                use_cache, logger, packs=not episodes_only,
                                                year=year, all_categories=all_categories)
                if note:
                    notes.append(note)
                elif not cached and use_cache:
                    _cache_put(key, found)
                here = collect(found)
                keyed_kept += here
                if logger:
                    logger('[USENET] sequential: %s -> %d usable with a key (%d of %d)'
                           % (entry['name'], here, keyed_kept, min_usable))
                if keyed_kept >= min_usable:
                    if logger and position < len(limited):
                        logger('[USENET] sequential: enough with a key after %s, %d not asked'
                               % (entry['name'], len(limited) - position))
                    break
            if logger and limited and keyed_kept < min_usable:
                logger('[USENET] sequential: only %d usable with a key after all %d'
                       % (keyed_kept, len(limited)))

    rows = _cap_per_indexer(rows, per_indexer_limit, season, episode, why)

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


def fetch_nzb(url, key=None, timeout=25, indexer_name=''):
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
                _stat(indexer_name, g=1)
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
    if indexer.get('builtin') == 'nzbindex':
        try:
            body = _nzbindex_get(indexer, {'q': 'the matrix 1999', 'max': 5, 'complete': 1},
                                 timeout=12)
            if b'<rss' in body[:4096].lower() or b'<channel' in body[:4096].lower():
                return True, '%s: free search works (%s)' % (indexer['name'], usage_line(url))
            return False, '%s answered something unexpected' % indexer['name']
        except (KeyRejected, LimitReached) as exc:
            return False, redact(exc)
        except Exception as exc:
            return False, '%s: %s' % (indexer['name'], redact(str(exc)[:90]))
    if indexer.get('builtin') == 'binsearch':
        try:
            body = _binsearch_get(indexer, {'q': 'the matrix 1999'}, timeout=12)
            if b'type="checkbox"' in body:
                return True, '%s: free search works (%s)' % (indexer['name'], usage_line(url))
            return False, '%s answered something unexpected' % indexer['name']
        except (KeyRejected, LimitReached) as exc:
            return False, redact(exc)
        except Exception as exc:
            return False, '%s: %s' % (indexer['name'], redact(str(exc)[:90]))
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
