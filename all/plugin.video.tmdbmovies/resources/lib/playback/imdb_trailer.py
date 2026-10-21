# -*- coding: utf-8 -*-
"""Trailers from IMDb's public GraphQL endpoint.

IMDb serves signed progressive MP4 files for a title's videos. They are
complete files with the moov atom up front, so Kodi's own demuxer plays
them directly: no DASH manifest, no proxy, no adaptive stream. That makes
the start almost instant, which is the whole point of the IMDb mode.

The endpoint is the one imdb.com itself calls, it needs no account and no
token. It only answers when the request carries the imdb-web-next client
name, otherwise it replies 403.
"""
import json
import re
import threading
import time
import urllib.request

import xbmc

from resources.lib.core.config import ADDON, BASE_URL, API_KEY
from resources.lib.core.utils import log, read_json, write_json

ENDPOINT = 'https://caching.graphql.imdb.com/'
HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'x-imdb-client-name': 'imdb-web-next',
}
QUERY = ('query($id: ID!) { title(id: $id) { primaryVideos(first: 8) { edges { node { id '
         'contentType { id } playbackURLs { url videoMimeType videoDefinition } } } } } }')
# Highest first: a 1080p trailer is worth the few extra MB, 480p is the
# safety net that practically every title has.
QUALITY_ORDER = ('DEF_1080p', 'DEF_720p', 'DEF_480p', 'DEF_SD')
URL_TTL_MAX = 6 * 3600
URL_TTL_MARGIN = 300
NEG_TTL = 600
ID_TTL = 30 * 86400
TIMEOUT = 6

_lock = threading.Lock()
_url_cache = {}
_neg_cache = {}
_id_cache = {}


def _ids_file():
    try:
        import os
        return os.path.join(ADDON.getAddonInfo('profile'), 'imdb_ids.json')
    except Exception:
        return ''


def _load_id_cache():
    with _lock:
        if _id_cache:
            return
    data = read_json(_ids_file()) or {}
    if isinstance(data, dict):
        now = int(time.time())
        with _lock:
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                stamp = int(value.get('ts') or 0)
                if now - stamp < ID_TTL and value.get('id'):
                    _id_cache[key] = value['id']
    log(f"[IMDB-TRAILER] IMDb ID cache loaded ({len(_id_cache)})")


def _save_id_cache():
    data = {}
    now = int(time.time())
    with _lock:
        for key, value in _id_cache.items():
            data[key] = {'id': value, 'ts': now}
    if data:
        write_json(_ids_file(), data)


def _external_ids(tmdb_id, media_type):
    url = f'{BASE_URL}/{media_type}/{tmdb_id}/external_ids?api_key={API_KEY}'
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read(512 * 1024).decode('utf-8'))
        return (data or {}).get('imdb_id') or ''
    except Exception as exc:
        log(f"[IMDB-TRAILER] external_ids error for {media_type}/{tmdb_id}: {exc}", xbmc.LOGWARNING)
        return ''


def imdb_id_for(tmdb_id, media_type='movie'):
    """IMDb title ID (tt...) for a TMDb ID, '' when there is none."""
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id:
        return ''
    media_type = 'tv' if str(media_type or '').lower() in ('tv', 'tvshow', 'show', 'series') else 'movie'
    key = f'{media_type}:{tmdb_id}'
    with _lock:
        cached = _id_cache.get(key)
    if cached:
        return cached
    _load_id_cache()
    with _lock:
        cached = _id_cache.get(key)
    if cached:
        return cached
    found = _external_ids(tmdb_id, media_type)
    if found:
        with _lock:
            _id_cache[key] = found
        _save_id_cache()
        log(f"[IMDB-TRAILER] IMDb ID for {media_type}/{tmdb_id}: {found}")
    return found


def _signed_ttl(url):
    """Seconds the signed URL stays valid (from its Expires parameter)."""
    match = re.search(r'[?&]Expires=(\d+)', url or '')
    if not match:
        return URL_TTL_MAX
    try:
        expires = int(match.group(1))
    except ValueError:
        return URL_TTL_MAX
    ttl = expires - int(time.time()) - URL_TTL_MARGIN
    return max(60, min(ttl, URL_TTL_MAX))


def _pick(nodes):
    """Best signed MP4 of the first trailer node that has one."""
    nodes = [n for n in (nodes or []) if isinstance(n, dict)]
    trailers = [n for n in nodes
                if str((n.get('contentType') or {}).get('id') or '').endswith('.trailer')]
    for node in (trailers or nodes):
        files = {}
        for item in node.get('playbackURLs') or []:
            url = str((item or {}).get('url') or '')
            if (item or {}).get('videoMimeType') == 'MP4' and url.startswith('https://'):
                files.setdefault(item.get('videoDefinition'), url)
        if not files:
            continue
        for definition in QUALITY_ORDER:
            if definition in files:
                return files[definition], definition
        return next(iter(files.values())), ''
    return '', ''


def resolve(imdb_id, timeout=TIMEOUT):
    """Signed MP4 URL of the title's trailer, '' when there is none."""
    imdb_id = str(imdb_id or '').strip()
    if not re.fullmatch(r'tt\d{5,10}', imdb_id):
        return '', ''
    now = time.time()
    with _lock:
        hit = _url_cache.get(imdb_id)
        if hit and hit[0] > now:
            return hit[1], hit[2]
        if _neg_cache.get(imdb_id, 0) > now:
            return '', ''
    url = ''
    definition = ''
    try:
        body = json.dumps({'query': QUERY, 'variables': {'id': imdb_id}}).encode('utf-8')
        request = urllib.request.Request(ENDPOINT, data=body, headers=HEADERS, method='POST')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
        title = ((data or {}).get('data') or {}).get('title') or {}
        edges = (title.get('primaryVideos') or {}).get('edges') or []
        url, definition = _pick([edge.get('node') for edge in edges if isinstance(edge, dict)])
    except Exception as exc:
        log(f"[IMDB-TRAILER] GraphQL error for {imdb_id}: {exc}", xbmc.LOGWARNING)
        url = ''
    with _lock:
        if url:
            _url_cache[imdb_id] = (time.time() + _signed_ttl(url), url, definition)
            _neg_cache.pop(imdb_id, None)
            log(f"[IMDB-TRAILER] {imdb_id} -> {definition or 'MP4'}")
        else:
            _neg_cache[imdb_id] = time.time() + NEG_TTL
    return url, definition


def url_for(tmdb_id=None, media_type='movie', imdb_id=''):
    """Trailer URL of a title, addressed by TMDb ID or by IMDb ID."""
    if not imdb_id:
        imdb_id = imdb_id_for(tmdb_id, media_type)
    if not imdb_id:
        return '', ''
    return resolve(imdb_id)
