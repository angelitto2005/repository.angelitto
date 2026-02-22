# -*- coding: utf-8 -*-
#common.py

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import xbmc
import xbmcaddon
import xbmcvfs

# ==============================
# ADDON / PATHS
# ==============================
ADDON       = xbmcaddon.Addon()
ADDON_ID    = ADDON.getAddonInfo('id')
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

EPG_CACHE_FILE     = os.path.join(PROFILE_DIR, 'epg_cache.json')
CATALOG_CACHE_FILE = os.path.join(PROFILE_DIR, 'catalog.json')

# ==============================
# CONFIG
# ==============================
BASE_URL        = 'https://rotv123.com'
USER_AGENT      = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

CINEMAGIA_API   = 'https://api.cinemagia.ro/programTv/nowOnTv'
CINEMAGIA_KEY   = '45sHMMCSEc'

PREFETCH_WORKERS = 4

EPG_SOURCE_MAP = {
    '0': 'cinemagia',
    '1': None,
}

STREAM_PRIORITY_MAP = {
    '0': 0,
    '1': 1,
    '2': 2,
    '3': 3,
}

CATALOG_TTL_MAP = {
    '0': 86400,
    '1': 604800,
    '2': 2592000,
}

# ==============================
# SETTINGS
# ==============================
def get_settings():
    addon = xbmcaddon.Addon()
    epg_source_idx     = addon.getSetting('epg_source')
    stream_mode_auto   = addon.getSetting('stream_mode') == '0'
    stream_priority    = STREAM_PRIORITY_MAP.get(addon.getSetting('stream_priority'), 0)
    catalog_url        = addon.getSetting('catalog_url') or 'https://derzis.xyz/catalog.json'
    catalog_ttl        = CATALOG_TTL_MAP.get(addon.getSetting('catalog_ttl_days'), 604800)
    epg_source         = EPG_SOURCE_MAP.get(epg_source_idx, 'cinemagia')

    return {
        'epg_source':      epg_source,
        'stream_mode_auto': stream_mode_auto,
        'stream_priority': stream_priority,
        'catalog_url':     catalog_url,
        'catalog_ttl':     catalog_ttl,
    }


# ==============================
# UTILS
# ==============================
def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f'[{ADDON_ID}] {msg}', level)


def ensure_profile_dir():
    try:
        if not xbmcvfs.exists(PROFILE_DIR):
            xbmcvfs.mkdirs(PROFILE_DIR)
    except Exception as e:
        log(f'ensure_profile_dir: {e}', xbmc.LOGWARNING)


def _xbmcvfs_read(path):
    try:
        if not xbmcvfs.exists(path):
            return None
        f = xbmcvfs.File(path)
        raw = f.read()
        f.close()
        return raw if raw else None
    except Exception as e:
        log(f'_xbmcvfs_read({path}): {e}', xbmc.LOGWARNING)
        return None


def _xbmcvfs_write(path, content):
    try:
        ensure_profile_dir()
        f = xbmcvfs.File(path, 'w')
        f.write(content)
        f.close()
        return True
    except Exception as e:
        log(f'_xbmcvfs_write({path}): {e}', xbmc.LOGWARNING)
        return False


# ==============================
# HTTP
# ==============================
def http_get(url, timeout=10, extra_headers=None):
    if not url.startswith('http'):
        url = urllib.parse.urljoin(BASE_URL + '/', url)
    headers = {'User-Agent': USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        log(f'http_get({url}): {e}', xbmc.LOGWARNING)
        return None

SITE_HEADERS = {
    'Referer': BASE_URL + '/',
    'Origin':  BASE_URL,
}


# ==============================
# CATALOG
# ==============================
_CATALOG_CACHE = None


def load_catalog(force_refresh=False):
    global _CATALOG_CACHE

    if _CATALOG_CACHE is not None and not force_refresh:
        return _CATALOG_CACHE

    settings = get_settings()
    ttl      = settings['catalog_ttl']
    url      = settings['catalog_url']

    if not force_refresh:
        raw = _xbmcvfs_read(CATALOG_CACHE_FILE)
        if raw:
            try:
                data = json.loads(raw)
                age  = time.time() - data.get('fetched_at', 0)
                if age < ttl:
                    _CATALOG_CACHE = data.get('channels', [])
                    log(f'Catalog din disc ({len(_CATALOG_CACHE)} canale, vârstă {int(age)}s)')
                    return _CATALOG_CACHE
                else:
                    log('Catalog disc expirat, fetch remote...')
            except Exception as e:
                log(f'Catalog disc corupt: {e}', xbmc.LOGWARNING)

    log(f'Fetch catalog: {url}')
    raw_bytes = http_get(url, timeout=15)
    if raw_bytes:
        try:
            data = json.loads(raw_bytes.decode('utf-8'))
            data['fetched_at'] = time.time()
            _xbmcvfs_write(CATALOG_CACHE_FILE, json.dumps(data, ensure_ascii=False))
            _CATALOG_CACHE = data.get('channels', [])
            log(f'Catalog fetch OK ({len(_CATALOG_CACHE)} canale)')
            return _CATALOG_CACHE
        except Exception as e:
            log(f'Catalog parse error: {e}', xbmc.LOGERROR)

    raw = _xbmcvfs_read(CATALOG_CACHE_FILE)
    if raw:
        try:
            data = json.loads(raw)
            _CATALOG_CACHE = data.get('channels', [])
            log(f'Catalog fallback disc vechi ({len(_CATALOG_CACHE)} canale)', xbmc.LOGWARNING)
            return _CATALOG_CACHE
        except Exception:
            pass

    log('Catalog indisponibil!', xbmc.LOGERROR)
    _CATALOG_CACHE = []
    return _CATALOG_CACHE


def get_active_channels():
    return [
        ch for ch in load_catalog()
        if ch.get('active', True) and ch.get('web_url')
    ]


def get_categories():
    seen = {}
    for ch in get_active_channels():
        for cat in ch.get('categories', []):
            if cat not in seen:
                seen[cat] = True
    return list(seen.keys())


def get_channels_by_category(category):
    return [
        ch for ch in get_active_channels()
        if category in ch.get('categories', [])
    ]


def get_epg_id(channel, source):
    if not source:
        return None
    return channel.get('epg_ids', {}).get(source)


# ==============================
# EPG CACHE (disc)
# ==============================
def _read_epg_disk_cache():
    raw = _xbmcvfs_read(EPG_CACHE_FILE)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _write_epg_disk_cache(cache_dict):
    _xbmcvfs_write(EPG_CACHE_FILE, json.dumps(cache_dict, ensure_ascii=False))

_EPG_RAM = {}
_EPG_DISK = None


def _get_epg_disk(station_id):
    global _EPG_DISK
    if _EPG_DISK is None:
        _EPG_DISK = _read_epg_disk_cache()
    entry = _EPG_DISK.get(str(station_id))
    if not entry:
        return None
    if float(entry.get('expire', 0)) <= time.time():
        return None
    return entry.get('data')


def _set_epg_disk(station_id, expire_epoch, info):
    global _EPG_DISK
    if _EPG_DISK is None:
        _EPG_DISK = _read_epg_disk_cache()
    _EPG_DISK[str(station_id)] = {'expire': float(expire_epoch), 'data': info}
    _write_epg_disk_cache(_EPG_DISK)


# ==============================
# EPG FETCH
# ==============================
def _fmt_time_range(start_iso, stop_iso):
    try:
        s = datetime.fromisoformat(start_iso).strftime('%H:%M')
        e = datetime.fromisoformat(stop_iso).strftime('%H:%M')
        return f'{s}–{e}'
    except Exception:
        return ''


def _pick_now_next(shows):
    active = future = None
    for sh in shows or []:
        if sh.get('tense') == 'active' and not active:
            active = sh
        elif sh.get('tense') == 'future' and not future:
            future = sh
        if active and future:
            break
    return active, future


def _compute_expire(stop_iso, fallback_ttl=120):
    now = time.time()
    min_ttl, max_ttl = 30, 7200
    if stop_iso:
        try:
            stop_ts = datetime.fromisoformat(stop_iso).timestamp()
            ttl = int(stop_ts - now - 30)
            return now + max(min_ttl, min(ttl, max_ttl))
        except Exception:
            pass
    return now + max(min_ttl, min(fallback_ttl, max_ttl))


def load_epg(station_id):
    if not station_id:
        return None

    sid = str(station_id)
    now = time.time()

    entry = _EPG_RAM.get(sid)
    if entry and float(entry.get('expire', 0)) > now:
        return entry.get('data')

    disk = _get_epg_disk(sid)
    if disk:
        expire = (_EPG_DISK or {}).get(sid, {}).get('expire', now + 60)
        _EPG_RAM[sid] = {'expire': expire, 'data': disk}
        return disk

    url = f'{CINEMAGIA_API}?acckey={CINEMAGIA_KEY}&station_id={sid}'
    raw = http_get(url)
    if not raw:
        return None

    try:
        payload = json.loads(raw.decode('utf-8', errors='ignore'))
    except Exception:
        return None

    if not payload:
        return None

    item   = payload[0] if isinstance(payload, list) else payload
    shows  = item.get('shows') or []
    active, future = _pick_now_next(shows)

    if not active:
        return None

    info = {
        'now_title':   (active.get('title') or '').strip(),
        'now_time':    _fmt_time_range(active.get('start'), active.get('stop')),
        'now_percent': active.get('percentToComplete', 0),
        'next_title':  (future.get('title') or '').strip() if future else '',
        'next_time':   _fmt_time_range(future.get('start'), future.get('stop')) if future else '',
    }

    expire = _compute_expire(active.get('stop'), fallback_ttl=120)
    _EPG_RAM[sid] = {'expire': expire, 'data': info}
    _set_epg_disk(sid, expire, info)

    return info


def prefetch_epg(station_ids, max_workers=PREFETCH_WORKERS):
    uniq = list(dict.fromkeys(str(s) for s in station_ids if s))
    if not uniq:
        return

    now = time.time()
    to_fetch = []
    for sid in uniq:
        entry = _EPG_RAM.get(sid)
        if entry and float(entry.get('expire', 0)) > now:
            continue
        if _get_epg_disk(sid):
            continue
        to_fetch.append(sid)

    if not to_fetch:
        return

    log(f'EPG prefetch: {len(to_fetch)} stații')
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(load_epg, sid) for sid in to_fetch]
        for _ in as_completed(futures):
            pass


# ==============================
# EPG PLOT
# ==============================
def _safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default


def _progress_bar(percent, length=12):
    p = max(0, min(100, _safe_int(percent, 0)))
    color  = 'lime' if p < 70 else ('orange' if p < 90 else 'red')
    filled = max(0, min(length, int(round(p / 100.0 * length))))
    bar    = '█' * filled + '░' * (length - filled)
    return f'[COLOR {color}]{bar}[/COLOR] [COLOR white]{p}%[/COLOR]'


def build_epg_plot(info):
    if not info:
        return 'EPG indisponibil', ''

    now_title   = (info.get('now_title') or '').strip()
    now_time    = (info.get('now_time') or '').strip()
    now_percent = info.get('now_percent', 0)
    next_title  = (info.get('next_title') or '').strip()
    next_time   = (info.get('next_time') or '').strip()

    if not now_title:
        return 'EPG indisponibil', ''

    C_GOLD   = 'FFFFD700'
    C_SILVER = 'FFCCCCCC'
    C_TIME   = 'FF7EC8FF'

    lines = []
    l1 = f'[B][COLOR {C_GOLD}]ACUM[/COLOR][/B]'
    if now_time:
        l1 += f'  [COLOR {C_TIME}]{now_time}[/COLOR]'
    lines.append(l1)
    lines.append(_progress_bar(now_percent))
    lines.append(f'[B]{now_title}[/B]')

    if next_title:
        lines.append('')
        l2 = f'[B][COLOR {C_GOLD}]URMEAZĂ[/COLOR][/B]'
        if next_time:
            l2 += f'  [COLOR {C_TIME}]{next_time}[/COLOR]'
        lines.append(l2)
        lines.append(next_title)

    plot    = '[CR]'.join(lines)
    tagline = f'ACUM: {now_title}'
    if next_title:
        tagline += f' → URMEAZĂ: {next_title}'

    return plot, tagline
