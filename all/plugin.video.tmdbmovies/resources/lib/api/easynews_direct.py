# -*- coding: utf-8 -*-
"""Direct EasyNews search over the member web API.

The provider is deliberately separate from the EasyNews++ Stremio manifest and
from Usenet (NZB/NNTP).  Search results carry the clean download address only;
playback resolves the signed CDN address so Kodi never receives the login.
"""

import base64
import hashlib
import re
import threading
import time
import urllib.parse

import requests
import xbmc

from resources.lib.core.config import ADDON

EASYNEWS = "https://members.easynews.com"
SEARCH_URL = EASYNEWS + "/2.0/search/solr-search/advanced"
SEARCH_V3_URL = EASYNEWS + "/3.0/api/search"
USER_AGENT = "TMDbMovies"
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv", ".webm", ".m4v")
MIN_DURATION = 10 * 60
MIN_BYTES = 50 * 1024 * 1024
PREWARM_BYTES = 256 * 1024
PREWARM_TTL = 300

_PREWARMED = {}
_PREWARM_LOCK = threading.Lock()


def _log(message):
    try:
        xbmc.log("[TMDb Movies] [EASYNEWS-DIRECT] %s" % str(message), xbmc.LOGINFO)
    except Exception:
        pass


def _warm_log(message):
    try:
        xbmc.log("[TMDb Movies] [EASYNEWS-WARM] %s" % str(message), xbmc.LOGINFO)
    except Exception:
        pass


def _provider_credentials():
    """The EasyNews NNTP login, used when the Direct fields are empty."""
    try:
        from resources.lib.usenet import config as usenet_config
        for provider in usenet_config.providers():
            host = str(provider.get("host") or "").lower()
            if host == "easynews.com" or host.endswith(".easynews.com"):
                user = str(provider.get("user") or "").strip()
                password = str(provider.get("password") or "")
                if user and password:
                    return user, password
    except Exception:
        pass
    return "", ""


def credentials():
    try:
        user = (ADDON.getSetting("easynews_direct_user") or "").strip()
        password = ADDON.getSetting("easynews_direct_pass") or ""
        if user and password:
            return user, password
        return _provider_credentials()
    except Exception:
        return "", ""


def configured():
    user, password = credentials()
    return bool(user and password)


def enabled():
    try:
        value = str(ADDON.getSetting("use_easynews_direct") or "").strip().lower()
        return value in ("true", "1", "yes", "on")
    except Exception:
        return False


def available():
    return enabled() and configured()


def _max_results():
    try:
        value = int(ADDON.getSetting("easynews_direct_max") or "30")
    except (TypeError, ValueError):
        value = 30
    return max(1, min(100, value))


def _auth_header():
    user, password = credentials()
    raw = ("%s:%s" % (user, password)).encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def auth_headers():
    """Request headers for EasyNews calls; never put these in a URL."""
    if not configured():
        return {}
    return {"Authorization": _auth_header(), "User-Agent": USER_AGENT}


def _easynews_host(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == "easynews.com" or host.endswith(".easynews.com")


def resolve_playback(remote_url):
    """Resolve a download address to the signed CDN URL Kodi can play alone."""
    if not remote_url or not configured():
        return ""
    base = remote_url.split("|", 1)[0]
    if not base.startswith("https://"):
        return ""
    session = requests.Session()
    session.trust_env = False
    try:
        current = base
        for _hop in range(6):
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Range": "bytes=0-65535",
            }
            if _easynews_host(current):
                headers["Authorization"] = _auth_header()
            response = session.get(current, headers=headers, stream=True,
                                   allow_redirects=False, timeout=(10, 20),
                                   verify=True)
            try:
                status = response.status_code
                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location") or ""
                    if not location:
                        return ""
                    current = urllib.parse.urljoin(current, location)
                    if not _easynews_host(current):
                        _log("playback redirect outside EasyNews refused")
                        return ""
                    continue
                if status not in (200, 206):
                    _log("playback HTTP %d" % status)
                    return ""
                host = (urllib.parse.urlsplit(current).hostname or "").lower()
                if host == "members.easynews.com":
                    _log("playback did not reach the signed CDN")
                    return ""
                try:
                    chunk = next(response.iter_content(65536), b"")
                except Exception as error:
                    _log("playback read failed: %s" % type(error).__name__)
                    return ""
                if not chunk:
                    _log("playback empty body")
                    return ""
                return current
            finally:
                response.close()
    except Exception as error:
        _log("playback resolve failed: %s" % type(error).__name__)
        return ""
    finally:
        session.close()
    return ""


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace(",", ".")
    match = re.match(r"^\s*([\d.]+)\s*([KMGT]?)B?", text, re.IGNORECASE)
    if not match:
        return default
    try:
        number = float(match.group(1))
    except (TypeError, ValueError):
        return default
    unit = (match.group(2) or "").upper()
    if unit:
        number *= 1024 ** " KMGT".index(unit)
    return int(number)


def _seconds(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^\d+$", text):
        return int(text)
    parts = re.findall(r"(\d+)\s*([hms])", text, re.IGNORECASE)
    if parts:
        return sum(int(number) * {"h": 3600, "m": 60, "s": 1}[unit.lower()]
                   for number, unit in parts)
    return None


def _words(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower().replace("&", " and ")).split()


def _prewarm_target(url):
    base, separator, tail = str(url or "").partition("|")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    if separator:
        for key, value in urllib.parse.parse_qsl(tail, keep_blank_values=True):
            if key.lower() == "user-agent":
                headers["User-Agent"] = value
            elif key.lower() == "referer":
                headers["Referer"] = value
    return base, headers


def _prewarm_total(response):
    match = re.match(r"bytes\s+\d+-\d+/(\d+)", response.headers.get("Content-Range") or "")
    if match:
        return int(match.group(1))
    length = response.headers.get("Content-Length") or ""
    if response.status_code == 200 and length.isdigit():
        return int(length)
    return None


def _prewarm_range(session, base, headers, start, end, timeout):
    request_headers = dict(headers)
    request_headers["Range"] = "bytes=%d-%s" % (start, "" if end is None else end)
    try:
        response = session.get(base, headers=request_headers, stream=True,
                               allow_redirects=True, timeout=(5, timeout),
                               verify=True)
        try:
            if response.status_code not in (200, 206):
                _warm_log("prewarm HTTP %d" % response.status_code)
                return None, 0
            total = _prewarm_total(response)
            received = 0
            for piece in response.iter_content(64 * 1024):
                if not piece:
                    continue
                received += len(piece)
                if received >= PREWARM_BYTES:
                    break
            return total, received
        finally:
            response.close()
    except Exception as error:
        _warm_log("prewarm failed: %s" % type(error).__name__)
        return None, 0


def prewarm(url, timeout=8):
    """Fetch small head and tail ranges so the CDN is warm before Kodi opens it."""
    base, headers = _prewarm_target(url)
    if not base.startswith(("http://", "https://")):
        return False
    key = hashlib.sha1(base.encode("utf-8")).hexdigest()
    now = time.time()
    with _PREWARM_LOCK:
        stamp = _PREWARMED.get(key)
        if stamp and now - stamp < PREWARM_TTL:
            return True
    started = time.time()
    session = requests.Session()
    session.trust_env = False
    try:
        total, received = _prewarm_range(
            session, base, headers, 0, PREWARM_BYTES - 1, timeout)
        if not received:
            return False
        if total and total > PREWARM_BYTES * 2:
            _prewarm_range(session, base, headers,
                           total - PREWARM_BYTES, None, timeout)
        with _PREWARM_LOCK:
            _PREWARMED[key] = time.time()
            if len(_PREWARMED) > 16:
                oldest = sorted(_PREWARMED, key=_PREWARMED.get)[
                    :len(_PREWARMED) - 16]
                for stale in oldest:
                    _PREWARMED.pop(stale, None)
        _warm_log("prewarm ready in %.1fs" % (time.time() - started))
        return True
    finally:
        session.close()


def _one_word_movie_ok(name, title):
    """A one-word film name must not be just the prefix of another title."""
    try:
        from resources.lib.usenet.indexer import _name_words, _title_tokens
    except Exception:
        return True
    tokens = _title_tokens(title)
    if len(set(tokens)) != 1:
        return True
    words = _name_words(name)
    return not words or set(words) <= set(tokens)


def _title_matches(name, titles, content_type, year, season, episode):
    words = _words(name)
    for title in titles:
        wanted = _words(title)
        if not wanted or words[:len(wanted)] != wanted:
            continue
        rest = " ".join(words[len(wanted):])
        if content_type == "tv":
            if season is None or episode is None:
                return False
            if re.search(r"\bs0*%d[ ._-]?e0*%d\b" % (season, episode), rest):
                return True
            if re.search(r"\b0*%d[ ._-]?x0*%d\b" % (season, episode), rest):
                return True
            continue
        if re.search(r"\bs\d{1,2}[ ._-]?e\d{1,3}\b", rest):
            continue
        if not _one_word_movie_ok(name, title):
            continue
        if not year:
            return True
        if re.search(r"\b(?:%d|%d|%d)\b" % (year - 1, year, year + 1), rest):
            return True
        if not re.search(r"\b(?:19|20)\d{2}\b", rest):
            return True
    return False


def _explicit_language_codes(name):
    """Language words in an EasyNews filename, e.g. POLISH or italian."""
    text = str(name or '')
    text = re.sub(r'\.(?:mkv|mp4|avi|ts|m2ts|mov|wmv|webm|m4v)$', '', text, flags=re.I)
    text = re.sub(r'-[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*$', '', text)
    marker = re.search(r'\b(?:s\d{1,2}[ ._-]?e\d{1,3}|(?:19|20)\d{2})\b', text, re.I)
    if not marker:
        return set()
    try:
        from resources.lib.usenet.indexer import _LANGUAGE_CODES
    except Exception:
        return set()
    codes = set()
    for word in re.findall(r'[A-Za-z]{2,}', text[marker.end():]):
        code = _LANGUAGE_CODES.get(word.lower())
        if code and (len(word) >= 4 or word.isupper()):
            codes.add(code)
    return codes


def _identity_filter_rows(rows, original_language, episode_title, season, episode):
    """Same conflict-only identity rules as the Usenet indexers.

    EasyNews has no IMDb/language fields in its answer, so only the filename
    can prove a conflict: a foreign language word or a wrong episode title.
    Rows without that evidence are kept.
    """
    if not rows or not (original_language or episode_title):
        return rows
    try:
        from resources.lib.usenet import indexer as usenet_indexer
        language = str(original_language or '').strip().lower()
        wanted_languages = usenet_indexer._language_codes(language)
        if not wanted_languages and len(language) in (2, 3):
            wanted_languages = {language}
        why = {}
        candidates = []
        for row in rows:
            row['title'] = row.get('name') or ''
            row['indexer'] = 'EasyNews Direct'
            row['language'] = ''
            row['imdb'] = ''
            codes = _explicit_language_codes(row['title'])
            if codes and wanted_languages and not (codes & wanted_languages):
                why['wrong language'] = why.get('wrong language', 0) + 1
                continue
            if codes:
                row['language'] = ','.join(sorted(codes))
            candidates.append(row)
        kept = usenet_indexer._identity_filter(
            candidates, '', original_language or '', episode_title or '', why,
            season=season, episode=episode)
        if why:
            _log("identity filter: " + ", ".join(
                "%s=%d" % (reason, count) for reason, count in sorted(why.items())))
        return kept
    except Exception as error:
        _log("identity filter unavailable: %s" % type(error).__name__)
        return rows


def _field(raw, names):
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return ""


def _item(raw):
    if isinstance(raw, (list, tuple)):
        if len(raw) < 12:
            return None
        return {
            "key": str(raw[0] or ""),
            "id": "",
            "name": str(raw[10] or ""),
            "extension": str(raw[11] or ""),
            "size": _number(raw[4] if len(raw) > 4 else 0),
            "seconds": _seconds(raw[14]) if len(raw) > 14 else None,
            "bad": False,
            "type": "",
        }
    if not isinstance(raw, dict):
        return None
    if str(raw.get("type") or "").upper() not in ("", "VIDEO"):
        return None
    return {
        "key": str(_field(raw, ("hash", "0")) or ""),
        "id": str(_field(raw, ("id",)) or ""),
        "name": str(_field(raw, ("prettyFn", "fn", "10")) or ""),
        "extension": str(_field(raw, ("extension", "ext", "11")) or ""),
        "size": _number(_field(raw, ("rawSize", "size", "4"))),
        "seconds": _seconds(_field(raw, ("runtime", "14"))),
        "bad": bool(raw.get("passwd") or raw.get("password") or raw.get("virus")),
        "type": str(raw.get("type") or ""),
    }


def _download_base(answer):
    base = str(answer.get("downURL") or (EASYNEWS + "/dl")).rstrip("/")
    farm = str(answer.get("dlFarm") or "auto")
    port = str(answer.get("dlPort") or "auto")
    return base, farm, port


def _parse_answer(answer, titles, content_type, year, season, episode, limit, custom=False):
    if not isinstance(answer, dict):
        return []
    rows = answer.get("data") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return []
    base, farm, port = _download_base(answer)
    v3 = bool(answer.get("_v3"))
    out = []
    seen = set()
    for raw in rows:
        item = _item(raw)
        if not item or not item["key"] or item["bad"]:
            continue
        name = item["name"].replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name:
            continue
        extension = item["extension"].strip()
        if extension and not extension.startswith("."):
            extension = "." + extension
        if not extension:
            found = re.search(r"(\.[a-z0-9]{2,5})$", name, re.IGNORECASE)
            extension = found.group(1) if found else ""
        extension = extension.lower()
        if extension not in VIDEO_EXTENSIONS:
            continue
        stem = name[:-len(extension)] if name.lower().endswith(extension) else name
        stem = stem.strip().strip(".")
        if not stem:
            continue
        low = stem.lower()
        if "sample" in _words(low):
            continue
        seconds = item["seconds"]
        if seconds is not None and 0 < seconds < MIN_DURATION:
            continue
        size = item["size"]
        if size and size < MIN_BYTES:
            continue
        if not custom and not _title_matches(stem, titles, content_type, year, season, episode):
            continue
        filename = stem + extension
        token = item["key"] + ((item["id"] or "") if v3 else "") + extension
        path = "%s/%s" % (token, urllib.parse.quote(filename, safe=""))
        url = "%s/%s/%s/%s" % (base, urllib.parse.quote(farm, safe=""),
                               urllib.parse.quote(port, safe=""), path)
        if url in seen:
            continue
        seen.add(url)
        out.append({
            "name": filename,
            "url": url,
            "size": size,
            "seconds": seconds,
        })
        if len(out) >= limit:
            break
    return out


def _search_params(query):
    return {
        "st": "adv",
        "sb": 1,
        "fex": ",".join(item.lstrip(".") for item in VIDEO_EXTENSIONS),
        "fty[]": "VIDEO",
        "spamf": 1,
        "u": 1,
        "gx": 1,
        "pno": 1,
        "sS": 3,
        "s1": "relevance",
        "s1d": "-",
        "s2": "dsize",
        "s2d": "-",
        "s3": "dtime",
        "s3d": "-",
        "gps": query,
        "pby": 100,
        "safeO": 1,
    }


def _search_v3(query):
    headers = auth_headers()
    headers["Accept"] = "application/json"
    try:
        response = requests.get(
            SEARCH_V3_URL,
            params=_search_params(query),
            headers=headers,
            timeout=20,
        )
        status = response.status_code
        if status != 200:
            _log("v3 search HTTP %d" % status)
            return None
        answer = response.json()
        if not isinstance(answer, dict):
            _log("v3 search returned no answer")
            return None
        answer["_v3"] = True
        return answer
    except Exception as error:
        _log("v3 search failed: %s" % type(error).__name__)
        return None


def _search_v2(query):
    try:
        response = requests.get(
            SEARCH_URL,
            params=_search_params(query),
            headers=auth_headers(),
            timeout=20,
        )
        status = response.status_code
        if status != 200:
            _log("v2 search HTTP %d" % status)
            return None
        return response.json()
    except Exception as error:
        _log("v2 search failed: %s" % type(error).__name__)
        return None


def _search_answer(query):
    answer = _search_v3(query)
    if answer is not None:
        return answer
    return _search_v2(query)


def search(title, alt_title, year, content_type, season=None, episode=None,
           original_language=None, episode_title=None, show_all=False):
    if not available():
        return []
    titles = []
    for value in (title, alt_title):
        value = str(value or "").strip()
        if value and value.lower() not in [item.lower() for item in titles]:
            titles.append(value)
    if not titles:
        return []
    try:
        year = int(year) if year else 0
    except (TypeError, ValueError):
        year = 0
    try:
        if content_type == "tv":
            season = int(season)
            episode = int(episode)
    except (TypeError, ValueError):
        if content_type == "tv":
            return []
    query = titles[0]
    if year and content_type != "tv":
        query = "%s %d" % (query, year)
    if content_type == "tv" and season is not None and episode is not None:
        query = "%s S%02dE%02d" % (query, season, episode)
    answer = _search_answer(query)
    if answer is None:
        return []
    rows = _parse_answer(answer, titles, content_type, year, season, episode, _max_results())
    if show_all:
        return rows
    return _identity_filter_rows(rows, original_language, episode_title, season, episode)


def search_custom(query, limit=None):
    """Free-text search for the Usenet custom search; no film-title filter."""
    if not available():
        return []
    query = str(query or "").strip()
    if not query:
        return []
    try:
        limit = int(limit) if limit else _max_results()
    except (TypeError, ValueError):
        limit = _max_results()
    limit = max(1, min(100, limit))
    answer = _search_answer(query)
    if answer is None:
        return []
    return _parse_answer(answer, [query], "movie", 0, None, None, limit, custom=True)
