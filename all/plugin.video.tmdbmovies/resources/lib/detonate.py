# -*- coding: utf-8 -*-

import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode, quote, unquote

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib import config as _config
from resources.lib.config import ADDON

API_FOLDER = "https://cloud.mail.ru/api/v2/folder"
API_DISPATCHER = "https://cloud.mail.ru/api/v2/dispatcher"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.wmv', '.mov', '.m4v', '.ts', '.webm',
              '.flv', '.3gp', '.mpg', '.mpeg', '.m2ts', '.divx', '.ogv')

# Linkuri hardcodate, grupate pe ani. Userul furnizeaza un link nou pt fiecare
# an (radacina e de obicei chiar folderul numit cu anul, ex. '2026').
HARDCODED_LINKS = {
    '2026':          ['PKz7/7ATNUQoQk'],
    '2025':          ['HksY/SUQQHTvgn'],
    '2024':          ['ctB7/jZPNZ2rRU'],
    '2023':          ['SkK1/YPuvBszyH'],
    '2022':          ['QVDD/b4ZQ7a1Q3'],
    '2021':          ['5EPY/foBXdJHhG'],
    '2020':          ['YGsM/ZJ2jBDwgV'],
    '2015-2019':     ['9w7m/Uoq8cdseQ'],
    '2010-2014':     ['gcg3/2xF4U63Lo'],
    '2000-2009':     ['YVWL/Foy2LoMux'],
}

# Cache RAM pentru listari (TTL 30 min) si dispatcher (TTL 30 min)
_folder_cache = {}
_dispatcher_cache = {'ts': 0, 'url': ''}
_CACHE_TTL = 1800

# JSON persistent in addon_data (incarcare instant la vizitele urmatoare)
try:
    from resources.lib.config import ADDON_DATA_DIR
except ImportError:
    ADDON_DATA_DIR = ''
_CACHE_FILE = os.path.join(ADDON_DATA_DIR, 'detonate_cache.json') if ADDON_DATA_DIR else ''
_JSON_TTL = 86400  # 24h - re-verifica in fundal

# Cache RAM pt rezultatele cautarilor TMDb: (titlu, an) -> tmdb_id
_search_cache = {}
_deadline_ts = [0.0]

# Lock pt scrieri concurente in JSON (enrich thread-uri + background refresh)
# RLock: reentrant - _enrich_movies tine lock-ul si cheama _save_cache care il
# re-acopera in acelasi thread.
_cache_lock = threading.RLock()

# Versiunea meta-cache-ului. v3 = titlul identic primul la scor; v4 = filtru
# de an server-side la cautare (fix Captain); v5 = prag de incredere la
# cautare (fix 'Don 1' -> Don hindi); v6 = titlul identic selectat intii +
# ponderi indian/an crescute (fix 'A R M' -> ARM en 2021 in loc de A.R.M
# malayalam 2024, si 'S I T' -> Sit en 2016).
# La schimbare, meta-urile vechi (cu potriviri gresite) sunt aruncate o data.
_META_VER = 6

# =============================================================================
# HTTP helpers
# =============================================================================

def _log(msg, level=xbmc.LOGINFO):
    try:
        xbmc.log("[DETONATE] " + str(msg), level)
    except Exception:
        pass


def _dbg(msg):
    _log(msg, xbmc.LOGDEBUG)


def _get_json(url, timeout=8):
    import requests
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        _log("GET " + url + " -> HTTP " + str(r.status_code))
    except Exception as e:
        _log("GET " + url + " error: " + repr(e))
    return None


# =============================================================================
# Links din setari
# =============================================================================

def _to_weblink(part):
    part = (part or '').strip()
    if not part:
        return ''
    m = re.search(r'cloud\.mail\.ru/public/([A-Za-z0-9_-]+/[A-Za-z0-9_-]+)', part, re.I)
    if m:
        return m.group(1)
    if re.match(r'^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$', part):
        return part
    return ''


def get_links():
    out = []
    for _year, links in HARDCODED_LINKS.items():
        for l in links:
            wl = _to_weblink(l)
            if wl and wl not in out:
                out.append(wl)
    return out


# =============================================================================
# JSON cache - persistent in addon_data, incarcare instant
# =============================================================================

def _load_cache():
    if not _CACHE_FILE:
        return {}
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and ('entries' in data or 'meta' in data):
                if data.get('meta_ver') != _META_VER:
                    if data.get('meta'):
                        _log("Meta cache version change ({} -> {}): meta reset".format(
                            data.get('meta_ver'), _META_VER))
                    data['meta'] = {}
                return data
    except Exception as e:
        _log("Cache load error: " + repr(e))
    return {}


def _save_cache(cache):
    """Salveaza cache-ul in JSON (thread-safe), cu versiunea curenta."""
    if not _CACHE_FILE:
        return
    try:
        with _cache_lock:
            cache['meta_ver'] = _META_VER
            cache_dir = os.path.dirname(_CACHE_FILE)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception as e:
        _log("Cache save error: " + repr(e))


def clear_detonate_cache():
    with _cache_lock:
        _folder_cache.clear()
        _dispatcher_cache.update({'ts': 0, 'url': ''})
        _search_cache.clear()
        if _CACHE_FILE and os.path.exists(_CACHE_FILE):
            try:
                os.remove(_CACHE_FILE)
                return True
            except Exception as e:
                _log("Cache delete error: " + repr(e))
    return False


def _ensure_cache(links):
    cache = _load_cache()
    entries = cache.get('entries', {})
    cache_age = time.time() - cache.get('last_update', 0)

    missing = [wl for wl in links if wl not in entries]

    if missing:
        from concurrent.futures import ThreadPoolExecutor
        try:
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(_fetch_folder, wl): wl for wl in missing}
                for fut, wl in futs.items():
                    try:
                        name, listing = fut.result()
                    except Exception as e:
                        name, listing = None, None
                        _log("Cache fetch error (" + wl + "): " + repr(e))
                    if listing is not None:
                        entries[wl] = {'root_name': name or '', 'listing': listing}
                    else:
                        _log("Cache fetch failed: " + wl)
        except Exception as e:
            _log("Cache parallel fetch error: " + repr(e))

    if missing or cache_age > _JSON_TTL:
        cache['entries'] = entries
        cache['last_update'] = time.time()
        _save_cache(cache)

    # Daca cache-ul era vechi (>24h) si nu erau linkuri lipsa, re-verifica
    # toate link-urile inline cu buget de timp (fara thread/RunPlugin).
    if cache_age > _JSON_TTL and not missing:
        _run_background_refresh_slice(links)

    return entries


def _run_background_refresh_slice(links, budget=10.0):
    """Re-verifica listarile folderelor (la 24h) INLINE, cu buget de timp."""
    try:
        old = _load_cache()
        deadline = time.time() + budget
        new_entries = {}
        for wl in links:
            if time.time() >= deadline:
                _log("Refresh slice incomplet - reia la urmatoarea deschidere")
                return
            name, listing = _fetch_folder(wl)
            if listing is not None:
                new_entries[wl] = {'root_name': name or '', 'listing': listing}
        if len(new_entries) < len(links):
            return
        old_names = set()
        for e in old.get('entries', {}).values():
            for f in e.get('listing', []):
                old_names.add(f.get('name', ''))
        new_names = set()
        for e in new_entries.values():
            for f in e.get('listing', []):
                new_names.add(f.get('name', ''))
        # Pastreaza meta-cache-ul TMDb (postere/plot) la rescriere
        cache = {'last_update': time.time(), 'entries': new_entries,
                 'meta': old.get('meta', {})}
        _save_cache(cache)
        added = new_names - old_names
        removed = old_names - new_names
        if added or removed:
            _log("Cache refresh: +{} -{} files".format(len(added), len(removed)))
    except Exception as e:
        _log("Background refresh error: " + repr(e))


def _prefetch_slice(links, budget=1.5):
    try:
        entries = _load_cache().get('entries', {})
        if not entries:
            return
        deadline = time.time() + budget
        for wl in links:
            entry = entries.get(wl)
            if not entry:
                continue
            listing = entry.get('listing', [])
            files = [it for it in listing
                     if it.get('kind') == 'file' and _is_video(it.get('name', ''))]
            if not files:
                continue
            try:
                cached = _load_cache().get('meta', {})
            except Exception:
                cached = {}
            missing = [f for f in files if f.get('name', '') not in cached]
            if not missing:
                continue  # folder complet sincronizat - instant
            if time.time() >= deadline:
                return  # buget epuizat - restul la urmatoarea vizita
            root_name = entry.get('root_name', '')
            try:
                _deadline_ts[0] = deadline  # lookup-urile se opresc la buget
                metas = _enrich_movies(files, deadline=deadline)
                _dbg("Prefetch slice {}: {}/{} metas".format(
                    root_name or wl, len(metas), len(files)))
            except Exception as e:
                _log("Prefetch slice error (" + str(root_name) + "): " + repr(e))
    except Exception as e:
        _log("Prefetch slice fatal: " + repr(e))


def run_meta_prefetch(links):
    entries = _load_cache().get('entries', {})
    t0 = time.time()
    total_new = 0
    for wl in links:
        if xbmc.Monitor().abortRequested():
            return
        entry = entries.get(wl)
        if not entry:
            continue
        root_name = entry.get('root_name', '')
        listing = entry.get('listing', [])
        files = [it for it in listing
                 if it.get('kind') == 'file' and _is_video(it.get('name', ''))]
        if not files:
            continue
        try:
            metas = _enrich_movies(files)
            total_new += len(metas)
            _log("Prefetch {}: {}/{} movies with metadata".format(
                root_name or wl, len(metas), len(files)))
        except Exception as e:
            _log("Prefetch error (" + str(root_name) + "): " + repr(e))
    _log("Prefetch done: {} metas total in {:.1f}s".format(
        total_new, time.time() - t0))


def run_background_refresh(links):
    old = _load_cache()
    old_names = set()
    for e in old.get('entries', {}).values():
        for f in e.get('listing', []):
            old_names.add(f.get('name', ''))

    new_entries = {}
    for wl in links:
        if xbmc.Monitor().abortRequested():
            return
        name, listing = _fetch_folder(wl)
        if listing is not None:
            new_entries[wl] = {'root_name': name or '', 'listing': listing}

    new_names = set()
    for e in new_entries.values():
        for f in e.get('listing', []):
            new_names.add(f.get('name', ''))

    added = new_names - old_names
    removed = old_names - new_names

    # Pastreaza meta-cache-ul TMDb (postere/plot) la rescriere
    cache = {'last_update': time.time(), 'entries': new_entries,
             'meta': old.get('meta', {})}
    _save_cache(cache)

    _log("Cache refresh: +{} -{} files".format(len(added), len(removed)))


# =============================================================================
# Folder API
# =============================================================================

def _fetch_folder(weblink):
    now = time.time()
    hit = _folder_cache.get(weblink)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1], hit[2]
    data = _get_json(API_FOLDER + "?weblink=" + quote(weblink, safe=''))
    if data and data.get('status') == 200 and data.get('body'):
        body = data['body']
        listing = body.get('list') or []
        name = body.get('name') or ''
        _folder_cache[weblink] = (now, name, listing)
        return name, listing
    return None, None


def _get_dispatcher_url():
    """Intoarce URL-ul de baza weblink_get (token de sesiune). Cache 300s."""
    now = time.time()
    if _dispatcher_cache['url'] and (now - _dispatcher_cache['ts']) < _CACHE_TTL:
        return _dispatcher_cache['url']
    data = _get_json(API_DISPATCHER)
    if data and data.get('body'):
        try:
            url = data['body'].get('weblink_get') or []
            if isinstance(url, list):
                url = url[0].get('url', '') if url else ''
            elif isinstance(url, dict):
                url = url.get('url', '')
        except Exception:
            url = ''
        if url:
            _dispatcher_cache['ts'] = now
            _dispatcher_cache['url'] = url
            return url
    return ''


# =============================================================================
# Curatare nume filme
# =============================================================================

_YEAR_RE = re.compile(r'(?:\(?)(19|20)\d{2}(?:\)?)')
_QUALITY_RE = re.compile(r'(2160p|1080p|720p|480p|360p)', re.I)
_TAG_RE = re.compile(
    r'\b(?:2160p|1080p|720p|480p|360p|4k|hdr10?|hdr|hdrip|web-?dl|webrip|web-?rip|'
    r'hdhub4u|hdhub|x264|x265|h\.?264|h\.?265|hevc|10bit|8bit|ds4k|esub|subs?|'
    r'dubbed|ddp\s?5\.?1|dd5\.?1|dolby\s?atmos|atmos|aac|5\.1|7\.1|2\.0|dual\s?audio|'
    r'dual|audio|uncut|unrated|hq|extended|remux|blu-?ray|dvdrip|hdtv|proper|repack|'
    r'screener|\d+(?:\.\d+)?\s?(?:gb|gib|mb|mib|kbps)|amzn|netflix|prime|disney\+?|'
    r'ott|mxplayer|jiocinema|hindi|tamil|telugu|kannada|malayalam|bengali|marathi|'
    r'punjabi|oriya|english)\b', re.IGNORECASE)


def clean_title(name):
    base = os.path.splitext(str(name))[0]
    base = base.replace('+', ' ')
    year = ''
    head = base
    m = _YEAR_RE.search(base)
    if m:
        year = m.group(0).strip('()')
        head = base[:m.start()]
    parts = re.split(r'\s+-\s+', head, maxsplit=1)
    if len(parts) > 1:
        tail = parts[1]
        if _TAG_RE.search(tail) or len(parts[0]) < 3 or len(head) > 45:
            head = parts[0]
    title = _TAG_RE.sub(' ', head)
    title = re.sub(r'[._]+', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip(' ---_[]()')
    if not title:
        title = os.path.splitext(str(name))[0]
    return title, year


def _format_size(size):
    try:
        size = int(size or 0)
    except Exception:
        return ''
    if size <= 0:
        return ''
    if size >= 1073741824:
        return "{:.2f} GB".format(size / 1073741824)
    if size >= 1048576:
        return "{:.0f} MB".format(size / 1048576)
    return "{:.0f} KB".format(size / 1024)


def _quality_from_name(name):
    m = _QUALITY_RE.search(str(name))
    return m.group(1).lower() if m else ''


def _is_video(name):
    return os.path.splitext(str(name))[1].lower() in VIDEO_EXTS


# =============================================================================
# TMDb lookup (cautare + detalii) - paralel, cu deadline global
# =============================================================================

def _search_variants(title):
    variants = [title]
    # camelCase: litera mica urmata de majuscula -> spatiu (RaviKumar -> Ravi Kumar)
    camel = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', title)
    if camel not in variants:
        variants.append(camel)
    # fara tokenuri scurte de 1-2 caractere (SO, HD, X etc.)
    tokens = [t for t in title.split() if len(t) > 2]
    dropped = ' '.join(tokens)
    if dropped and dropped not in variants:
        variants.append(dropped)
    # compact: fara spatii deloc
    compact = re.sub(r'\s+', '', title)
    if compact and compact not in variants:
        variants.append(compact)
    return variants


def _short_fallback_queries(title):
    out = []
    if ' - ' in title:
        head = title.split(' - ', 1)[0].strip()
        if head and head not in out:
            out.append(head)
    words = title.split()
    if len(words) >= 2:
        two = ' '.join(words[:2])
        if two not in out:
            out.append(two)
    if words:
        one = words[0]
        if one not in out:
            out.append(one)
    return out


def _search_tmdb(title, year):
    try:
        from resources.lib.tmdb_api import get_tmdb_search_results

        def _fetch(query, use_year):
            try:
                res = get_tmdb_search_results(query, 'movie', 1,
                                              year=str(year) if use_year else None)
                if res is None or res.status_code != 200:
                    return []
                return (res.json() or {}).get('results') or []
            except Exception:
                return []

        best_overall_score, best_overall_id = -1, None
        for query in _search_variants(title):
            seen_ids = set()
            combined = []
            for r in _fetch(query, True) + _fetch(query, False):
                rid = r.get('id')
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    combined.append(r)
            if not combined:
                continue
            best = _pick_best_result(combined, year, query)
            tid = best.get('id') if best else None
            if tid is None:
                continue
            score = _score_item(best, year, query)
            if score > best_overall_score:
                best_overall_score, best_overall_id = score, tid
        if best_overall_id is None:
            for q in _short_fallback_queries(title):
                seen_ids = set()
                combined = []
                for r in _fetch(q, True) + _fetch(q, False):
                    rid = r.get('id')
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        combined.append(r)
                if not combined:
                    continue
                best = _pick_best_result(combined, year, q)
                tid = best.get('id') if best else None
                if tid is None:
                    continue
                score = _score_item(best, year, q)
                if score >= 4 and score > best_overall_score:
                    best_overall_score, best_overall_id = score, tid
        return best_overall_id
    except Exception as e:
        _log("Search failed (" + str(title) + "): " + repr(e))
        return None


def _lookup(title, year):
    key = (str(title).lower().strip(), str(year))
    tid = _search_cache.get(key)
    if tid is None:
        if time.time() > _deadline_ts[0]:
            return {}
        tid = _search_tmdb(title, year)
        if tid:
            _search_cache[key] = tid
    if not tid:
        return {}
    if time.time() > _deadline_ts[0]:
        return {}
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        data = get_tmdb_item_details(tid, 'movie', lightweight=True)
        return data or {}
    except Exception as e:
        _log("Details failed (" + str(title) + "): " + repr(e))
        return {}


_META_KEYS = ('id', 'tmdb_id', 'title', 'original_title', 'name', 'overview',
              'poster_path', 'backdrop_path', 'vote_average', 'vote_count',
              'release_date', 'runtime', 'genres', 'tagline',
              'production_companies', 'original_language')

_INDIAN_LANGS = ('hi', 'ta', 'te', 'kn', 'ml', 'bn', 'mr', 'pa', 'gu')


def _norm_title(s):
    return re.sub(r'[^a-z0-9]', '', str(s or '').lower())


def _score_item(it, year, query=''):
    q = _norm_title(query)
    score = 0
    titles = (it.get('title'), it.get('original_title'), it.get('name'))
    if q and any(_norm_title(t) == q for t in titles if t):
        score += 4
    if str(it.get('original_language') or '') in _INDIAN_LANGS:
        score += 3
    if year and str(it.get('release_date') or '')[:4] == str(year):
        score += 2
    return score


def _pick_best_result(results, year, query=''):
    if not results:
        return None
    best, best_score = None, -1
    for it in results:
        s = _score_item(it, year, query)
        if s > best_score:
            best, best_score = it, s
    return best


def _slim_meta(meta):
    return {k: meta[k] for k in _META_KEYS if k in meta}


def _enrich_movies(files, deadline=None):
    out = {}
    jobs = []
    try:
        meta_cache = _load_cache().get('meta', {})
    except Exception:
        meta_cache = {}
    for f in files:
        name = f.get('name', '')
        cached = meta_cache.get(name)
        if cached:
            out[name] = cached
            continue
        title, year = clean_title(name)
        if title:
            jobs.append((name, title, year))
    if not jobs:
        return out
    if deadline is None:
        deadline = time.time() + 30.0
    _deadline_ts[0] = deadline
    from concurrent.futures import ThreadPoolExecutor, as_completed
    new_metas = {}
    ex = ThreadPoolExecutor(max_workers=8)
    try:
        futs = {ex.submit(_lookup, t, y): n for n, t, y in jobs}
        try:
            remaining = max(0.1, _deadline_ts[0] - time.time())
            for fut in as_completed(futs, timeout=remaining):
                name = futs[fut]
                try:
                    meta = fut.result()
                except Exception:
                    meta = {}
                if meta:
                    out[name] = meta
                    new_metas[name] = _slim_meta(meta)
        except Exception:
            pass
    except Exception as e:
        _log("Enrich error: " + repr(e))
    finally:
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass
    if new_metas:
        try:
            with _cache_lock:
                cache = _load_cache()
                mc = cache.get('meta', {})
                mc.update(new_metas)
                cache['meta'] = mc
                _save_cache(cache)
        except Exception as e:
            _log("Meta cache save error: " + repr(e))
    return out


# =============================================================================
# Rendering
# =============================================================================

def _base_url():
    return sys.argv[0]


def _media_icon(name):
    try:
        return os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', name)
    except Exception:
        return name


_CLEAR_CM = [('[B][COLOR FFFF5555]Clear Detonate Cache[/COLOR][/B]',
              'RunPlugin({})'.format(_base_url() + '?' + urlencode({'mode': 'detonate_clear_cache'})))]


def _add_folder(handle, label, params, icon='DefaultFolder.png', title=None,
                year=None, plot='', clear_cache=False):
    url = _base_url() + '?' + urlencode(params)
    li = xbmcgui.ListItem(label=label)
    icon_path = icon if ('/' in icon or '\\' in icon or icon.startswith('Default')) else _media_icon(icon)
    li.setArt({'icon': icon_path, 'thumb': icon_path, 'poster': icon_path})
    info = {'title': title or label}
    if year:
        try:
            info['year'] = int(year)
        except Exception:
            pass
    if plot:
        info['plot'] = plot
    try:
        from resources.lib.tmdb_api import set_metadata
        set_metadata(li, info)
    except Exception:
        li.setInfo('video', info)
    if clear_cache:
        li.addContextMenuItems(_CLEAR_CM)
    xbmcplugin.addDirectoryItem(handle, url, li, isFolder=True)


def _add_movie(handle, entry, meta=None):
    name = entry.get('name', '')
    weblink = entry.get('weblink', '')
    title, year = clean_title(name)
    size = _format_size(entry.get('size'))
    quality = _quality_from_name(name)

    tmdb_id = ''
    if meta:
        tmdb_id = str(meta.get('id') or meta.get('tmdb_id') or '')

    watched = False
    progress = 0
    if tmdb_id:
        try:
            from resources.lib import watched_provider
            watched = bool(watched_provider.is_movie_watched(tmdb_id))
        except Exception:
            pass
        try:
            from resources.lib import trakt_sync
            progress = float(trakt_sync.get_local_playback_progress(tmdb_id, 'movie') or 0)
        except Exception:
            pass

    label = title
    if year:
        label += " (" + year + ")"
    if watched:
        label = '[B][COLOR FF6AFB92]' + label + '[/COLOR][/B]'
    if size:
        label += " [B][COLOR gray][" + size + "][/COLOR][/B]"
    if quality:
        label += " [B][COLOR FF6AFB92][" + quality + "][/COLOR][/B]"

    params = {'mode': 'detonate_play', 'link': weblink}
    if tmdb_id:
        params['tmdb_id'] = tmdb_id
    url = _base_url() + '?' + urlencode(params)

    li = xbmcgui.ListItem(label=label)
    li.setProperty('IsPlayable', 'true')

    info = {'mediatype': 'movie', 'title': title}
    if year:
        info['year'] = int(year)
    if size:
        info['size'] = entry.get('size', 0)

    if meta:
        from resources.lib.config import IMG_BASE, BACKDROP_BASE
        poster_path = meta.get('poster_path', '')
        backdrop_path = meta.get('backdrop_path', '')
        poster = (IMG_BASE + poster_path) if poster_path else 'DefaultVideo.png'
        backdrop = (BACKDROP_BASE + backdrop_path) if backdrop_path else ''
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop})

        plot = meta.get('overview', '') or ''
        tagline = str(meta.get('tagline') or '').strip()
        try:
            genres = ", ".join([g['name'] for g in meta.get('genres', [])])
        except Exception:
            genres = ''
        plot_header = ''
        if tagline and genres:
            plot_header = "[B][COLOR yellow]" + tagline + "[/COLOR][/B] | [B][COLOR FF00CED1]" + genres + "[/COLOR][/B]\n"
        elif tagline:
            plot_header = "[B][COLOR yellow]" + tagline + "[/COLOR][/B]\n"
        elif genres:
            plot_header = "[B][COLOR FF00CED1]" + genres + "[/COLOR][/B]\n"
        info['plot'] = plot_header + plot
        info['rating'] = meta.get('vote_average', 0)
        info['votes'] = meta.get('vote_count', 0)
        info['premiered'] = meta.get('release_date', '')
        try:
            studio = meta['production_companies'][0].get('name', '')
        except Exception:
            studio = ''
        if studio:
            info['studio'] = studio
        try:
            duration = int(meta.get('runtime') or 0) * 60
        except Exception:
            duration = 0
        if duration <= 0:
            duration = 7200
        info['duration'] = duration

        resume_percent = 0
        if progress >= 1000000:
            resume_time = int(progress - 1000000)
            resume_percent = (resume_time / duration) * 100
        elif 0 < progress < 90:
            resume_percent = progress
        info['resume_percent'] = resume_percent
    else:
        icon = 'DefaultVideo.png'
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})

    try:
        from resources.lib.tmdb_api import set_metadata
        unique_ids = {'tmdb': tmdb_id} if tmdb_id else None
        set_metadata(li, info, unique_ids=unique_ids, watched_info=watched)
    except Exception:
        li.setInfo('video', {'title': title, 'mediatype': 'movie'})
        if year:
            li.setInfo('video', {'year': int(year)})

    cm = []
    if tmdb_id:
        try:
            from resources.lib.tmdb_api import _get_full_context_menu
            _imdb = ''
            try:
                _imdb = (meta or {}).get('external_ids', {}).get('imdb_id', '')
            except Exception:
                pass
            cm = _get_full_context_menu(tmdb_id, 'movie', title, year=year, imdb_id=_imdb) or []
        except Exception as e:
            _log("Context menu error: " + repr(e))
    cm.extend(_CLEAR_CM)
    li.addContextMenuItems(cm)

    xbmcplugin.addDirectoryItem(handle, url, li, isFolder=False)


# =============================================================================
# Liste
# =============================================================================

def _safe_end(func):
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        handle = _config.HANDLE
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _log("LIST ERROR (" + func.__name__ + "): " + repr(e))
            try:
                import traceback
                _log(traceback.format_exc())
            except Exception:
                pass
            try:
                xbmcgui.Dialog().notification('Detonate', 'Error loading list - see log', xbmcgui.NOTIFICATION_ERROR, 4000)
            except Exception:
                pass
            try:
                xbmcplugin.endOfDirectory(handle, False)
            except Exception:
                pass
            return None
    return wrapper


@_safe_end
def list_years():
    handle = _config.HANDLE
    _t0 = time.time()
    _dbg("Opening Detonate root...")
    links = get_links()
    if not links:
        xbmcgui.Dialog().notification('Detonate', 'No cloud.mail.ru links configured - add them in Settings > Detonate', xbmcgui.NOTIFICATION_WARNING, 6000)
        xbmcplugin.endOfDirectory(handle)
        return

    entries = _ensure_cache(links)

    years = {}        # an -> weblink-ul de deschis
    folders = {}
    files = []
    for link in links:
        entry = entries.get(link)
        if not entry:
            _log("Cache miss: " + link)
            continue
        root_name = entry.get('root_name', '')
        listing = entry.get('listing', [])
        if root_name and re.fullmatch(r'\d{4}', root_name):
            # Radacina insasi e un an (ex: folderul '2026' cu 33 filme direct)
            years.setdefault(root_name, link)
            continue
        for it in listing:
            kind = it.get('kind', 'file')
            if kind == 'folder':
                fname = it.get('name', '')
                if re.fullmatch(r'\d{4}', fname):
                    years.setdefault(fname, it.get('weblink', ''))
                else:
                    folders.setdefault(fname, it)
            elif _is_video(it.get('name', '')):
                files.append(it)
    # Filmele din radacini care nu sunt an: anul din numele fisierului
    for f in files:
        _t, _y = clean_title(f.get('name', ''))
        if _y:
            years.setdefault(_y, '')

    xbmcplugin.setContent(handle, 'files')
    _add_folder(handle, '[B][COLOR cyan]ALL MOVIES[/COLOR][/B]',
                {'mode': 'detonate_all'}, icon='DefaultMovies.png',
                title='All Bollywood Movies',
                plot='All movies from all years combined into a single list.',
                clear_cache=True)
    for y in sorted(years, reverse=True):
        _add_folder(handle, '[B][COLOR FFCCCCFF]' + y + '[/COLOR][/B]',
                    {'mode': 'detonate_year', 'year': y}, icon='calender.png',
                    title='Bollywood ' + y, year=y,
                    plot='Bollywood movies from ' + y,
                    clear_cache=True)
    for fname in sorted(folders):
        f = folders[fname]
        _add_folder(handle, fname,
                    {'mode': 'detonate_folder', 'link': f.get('weblink', '')},
                    clear_cache=True)
    if not years:
        metas = _enrich_movies(files)
        for f in files:
            try:
                _add_movie(handle, f, metas.get(f.get('name', '')))
            except Exception as e:
                _log("Render error (" + f.get('name', '') + "): " + repr(e))
    xbmcplugin.endOfDirectory(handle)
    _dbg("Root: endOfDirectory OK")

    _prefetch_slice(links)
    _dbg("Root rendered in {:.2f}s".format(time.time() - _t0))


@_safe_end
def list_year(year):
    handle = _config.HANDLE
    _t0 = time.time()
    links = get_links()
    if not links:
        xbmcplugin.endOfDirectory(handle)
        return

    entries = _ensure_cache(links)
    _dbg("Year {}: entries loaded in {:.2f}s".format(year, time.time() - _t0))

    seen = {}
    for link in links:
        entry = entries.get(link)
        if not entry:
            continue
        root_name = entry.get('root_name', '')
        listing = entry.get('listing', [])
        target = None
        if root_name == str(year):
            target = listing
        else:
            for it in listing:
                if it.get('kind') == 'folder' and it.get('name') == str(year):
                    _rn, sub = _fetch_folder(it.get('weblink', ''))
                    target = sub
                    break
            if target is None:
                # radacina ne-an: filme direct cu anul in nume
                for f in listing:
                    if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                        _t, _y = clean_title(f.get('name', ''))
                        if _y == str(year):
                            seen.setdefault(f.get('name', ''), f)
                continue
        for f in (target or []):
            if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                seen.setdefault(f.get('name', ''), f)

    metas = _enrich_movies(list(seen.values()), deadline=time.time() + 30.0)
    _dbg("Year {}: {} movies, {}/{} with metadata, enrich+fetch {:.2f}s".format(
        year, len(seen), len(metas), len(seen), time.time() - _t0))
    xbmcplugin.setContent(handle, 'movies')
    for fname in sorted(seen):
        try:
            _add_movie(handle, seen[fname], metas.get(fname))
        except Exception as e:
            _log("Render error (" + fname + "): " + repr(e))
    xbmcplugin.endOfDirectory(handle)
    _dbg("Year {}: endOfDirectory OK".format(year))
    _dbg("Year {}: rendered in {:.2f}s".format(year, time.time() - _t0))


@_safe_end
def list_all():
    handle = _config.HANDLE
    _t0 = time.time()
    _dbg("Opening Detonate All...")
    links = get_links()
    if not links:
        xbmcplugin.endOfDirectory(handle)
        return

    entries = _ensure_cache(links)
    _dbg("All: entries loaded in {:.2f}s".format(time.time() - _t0))

    seen = {}
    for link in links:
        entry = entries.get(link)
        if not entry:
            continue
        root_name = entry.get('root_name', '')
        listing = entry.get('listing', [])
        if root_name and re.fullmatch(r'\d{4}', root_name):
            for f in listing:
                if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                    seen.setdefault(f.get('name', ''), f)
            continue
        for it in listing:
            kind = it.get('kind', 'file')
            name = it.get('name', '')
            if kind == 'file' and _is_video(name):
                seen.setdefault(name, it)
            elif kind == 'folder':
                _rn, sub = _fetch_folder(it.get('weblink', ''))
                if sub:
                    for f in sub:
                        if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                            seen.setdefault(f.get('name', ''), f)

    all_movies = list(seen.values())
    metas = _enrich_movies(all_movies, deadline=time.time() + 60.0)
    _dbg("All: {} movies total, enrich+fetch {:.2f}s".format(
        len(all_movies), time.time() - _t0))

    xbmcplugin.setContent(handle, 'movies')

    def _sort_key(item):
        name = item.get('name', '')
        title, year = clean_title(name)
        return title.lower()

    for f in sorted(all_movies, key=_sort_key):
        fname = f.get('name', '')
        try:
            _add_movie(handle, f, metas.get(fname))
        except Exception as e:
            _log("Render error (" + fname + "): " + repr(e))

    xbmcplugin.endOfDirectory(handle)
    _dbg("All: rendered in {:.2f}s".format(time.time() - _t0))


@_safe_end
def list_folder(weblink):
    """Listare generica de folder (foldere non-an din radacina)."""
    handle = _config.HANDLE
    _name, listing = _fetch_folder(weblink)
    files = []
    if listing:
        for it in listing:
            if it.get('kind') == 'folder':
                _add_folder(handle, it.get('name', ''),
                            {'mode': 'detonate_folder', 'link': it.get('weblink', '')})
            elif _is_video(it.get('name', '')):
                files.append(it)
    metas = _enrich_movies(files, deadline=time.time() + 30.0)
    xbmcplugin.setContent(handle, 'files')
    for f in files:
        try:
            _add_movie(handle, f, metas.get(f.get('name', '')))
        except Exception as e:
            _log("Render error (" + f.get('name', '') + "): " + repr(e))
    xbmcplugin.endOfDirectory(handle)


# =============================================================================
# Playback
# =============================================================================

def play_movie(weblink, tmdb_id=''):
    handle = _config.HANDLE
    base = _get_dispatcher_url()
    if not base:
        xbmcgui.Dialog().notification('Detonate', 'Could not resolve file URL', xbmcgui.NOTIFICATION_ERROR, 6000)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return
    url = base.rstrip('/') + '/' + quote(weblink, safe='/')

    name = os.path.basename(unquote(weblink))
    title, year = clean_title(name)

    li = xbmcgui.ListItem(path=url)
    info = {'mediatype': 'movie', 'title': title}
    if year:
        info['year'] = int(year)
    if tmdb_id:
        try:
            from resources.lib.tmdb_api import get_tmdb_item_details
            from resources.lib.config import IMG_BASE, BACKDROP_BASE
            meta = get_tmdb_item_details(tmdb_id, 'movie', lightweight=True) or {}
            poster_path = meta.get('poster_path', '')
            backdrop_path = meta.get('backdrop_path', '')
            if poster_path:
                li.setArt({'icon': IMG_BASE + poster_path, 'thumb': IMG_BASE + poster_path,
                           'poster': IMG_BASE + poster_path})
            if backdrop_path:
                li.setArt({'fanart': BACKDROP_BASE + backdrop_path})
            if meta.get('overview'):
                info['plot'] = meta['overview']
        except Exception:
            pass

    try:
        from resources.lib.tmdb_api import set_metadata
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id} if tmdb_id else None, watched_info=False)
    except Exception:
        li.setInfo('video', {'title': title, 'mediatype': 'movie'})
        if year:
            li.setInfo('video', {'year': int(year)})

    _log("Playing: " + title + " -> " + url)
    xbmcplugin.setResolvedUrl(handle, True, li)
    try:
        xbmc.Player().play(url, li)
    except Exception as e:
        _log("player.play error: " + repr(e))
