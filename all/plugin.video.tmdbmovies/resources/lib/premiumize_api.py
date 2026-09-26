import time

import requests
import xbmc

from resources.lib.utils import DebridError, sleep_abortable

BASE = 'https://www.premiumize.me/api'
_REQUEST_TIMEOUT = 15
_MAX_RETRIES = 4
_BACKOFF = (1, 2, 4)
_RETRY_CODES = ('transient_error', 'link_generation_failed', 'unknown_error')
_READY_STATES = ('finished', 'seeding')


def _api_key():
    from resources.lib.config import ADDON
    try:
        return (ADDON.getSetting('pm_api_key') or '').strip()
    except Exception:
        return ''


def is_authenticated():
    return bool(_api_key())


def _headers():
    return {'Authorization': 'Bearer %s' % _api_key(),
            'Accept': 'application/json',
            'User-Agent': 'TMDbMovies/1.0 (Kodi addon)'}


def _norm_url(link):
    s = str(link or '').strip()
    if s.startswith('//'):
        return 'https:' + s
    if s.startswith('/'):
        return 'https://www.premiumize.me' + s
    return s


def needs_auth_header(url):
    return 'premiumize.me' in str(url or '').lower()


def auth_pipe(url):
    import urllib.parse
    hdr = {'Authorization': 'Bearer %s' % _api_key(),
           'User-Agent': 'TMDbMovies/1.0 (Kodi addon)'}
    return str(url or '') + '|' + urllib.parse.urlencode(hdr)


def _retry_after(r, default=2):
    try:
        return max(1, min(int(r.headers.get('Retry-After', default) or default), 60))
    except Exception:
        return default


def _sleep_backoff(attempt):
    try:
        idx = min(attempt - 1, len(_BACKOFF) - 1)
    except Exception:
        idx = 0
    return sleep_abortable(_BACKOFF[idx])


def _request(method, path, params=None, data=None):
    key = _api_key()
    if not key:
        raise DebridError('No Premiumize API key set')
    url = BASE + '/' + str(path or '').lstrip('/')
    attempt = 0
    while True:
        try:
            r = requests.request(method, url, headers=_headers(), params=params,
                                 data=data, timeout=_REQUEST_TIMEOUT)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            xbmc.log('[DEBRID][PM] %s %s network error' % (method, path), xbmc.LOGWARNING)
            raise DebridError('Premiumize connection failed')
        except Exception:
            xbmc.log('[DEBRID][PM] %s %s error' % (method, path), xbmc.LOGWARNING)
            raise DebridError('Premiumize request failed')
        if r.status_code == 429 and attempt < _MAX_RETRIES - 1:
            wait = _retry_after(r)
            xbmc.log('[DEBRID][PM] rate limited, waiting %ss (attempt %s/%s)' % (wait, attempt + 1, _MAX_RETRIES), xbmc.LOGINFO)
            attempt += 1
            if not sleep_abortable(wait):
                raise DebridError('Premiumize rate limited (Kodi closing)')
            continue
        if r.status_code >= 500 and attempt < _MAX_RETRIES - 1:
            attempt += 1
            if not _sleep_backoff(attempt):
                raise DebridError('Premiumize server busy (Kodi closing)')
            continue
        body = {}
        if r.content:
            try:
                body = r.json()
            except Exception:
                body = {}
        if not isinstance(body, dict):
            body = {}
        code = str(body.get('code') or '')
        message = str(body.get('message') or '')
        if r.status_code >= 400:
            if code == 'authentication_failed' or r.status_code in (401, 403):
                raise DebridError('Invalid Premiumize API key')
            if code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                attempt += 1
                if not _sleep_backoff(attempt):
                    raise DebridError('Premiumize error (Kodi closing)')
                continue
            xbmc.log('[DEBRID][PM] %s %s failed: HTTP %s code=%s %s'
                     % (method, path, r.status_code, code or '?', message[:120]), xbmc.LOGWARNING)
            raise DebridError(message or ('Premiumize HTTP %s' % r.status_code))
        if str(body.get('status') or '').lower() == 'error':
            if code == 'authentication_failed':
                raise DebridError('Invalid Premiumize API key')
            if code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                attempt += 1
                if not _sleep_backoff(attempt):
                    raise DebridError('Premiumize error (Kodi closing)')
                continue
            xbmc.log('[DEBRID][PM] %s %s error: code=%s %s' % (method, path, code or '?', message[:120]), xbmc.LOGWARNING)
            raise DebridError(message or 'Premiumize error')
        return body


def _pct(progress, status):
    if str(status or '').lower() in _READY_STATES:
        return 100
    try:
        v = float(progress)
    except Exception:
        v = 0.0
    if v > 0:
        v = v * 100.0 if v <= 1.0 else v
        try:
            return max(0, min(100, int(round(v))))
        except Exception:
            return 0
    return 0


def account_info():
    return _request('GET', 'account/info') or {}


def user_cloud():
    body = _request('GET', 'transfer/list') or {}
    raw = body.get('transfers')
    if not isinstance(raw, list):
        raw = []
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        status = str(it.get('status') or '').lower()
        file_id = it.get('file_id')
        file_id = '' if file_id in (None, 'None', 'null') else str(file_id)
        folder_id = it.get('folder_id')
        folder_id = '' if folder_id in (None, 'None', 'null') else str(folder_id)
        items.append({
            'id': str(it.get('id') or ''),
            'name': str(it.get('name') or 'Unnamed'),
            'status': status,
            'progress_pct': _pct(it.get('progress'), status),
            'message': str(it.get('message') or ''),
            'file_id': file_id,
            'folder_id': folder_id,
            'is_folder': not file_id,
        })
    return {'items': items, 'total': len(items), 'total_pages': 1}


def folder_list(folder_id):
    body = _request('GET', 'folder/list', params={'id': str(folder_id or '')}) or {}
    raw = body.get('content')
    if not isinstance(raw, list):
        raw = []
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        ftype = str(it.get('type') or '').lower()
        items.append({
            'id': str(it.get('id') or ''),
            'name': str(it.get('name') or 'Unnamed'),
            'type': ftype,
            'is_folder': ftype == 'folder',
            'size': int(it.get('size') or 0),
            'link': _norm_url(it.get('link')),
            'created': str(it.get('created_at') or ''),
        })
    return {'items': items, 'total': len(items), 'total_pages': 1}


def item_details(item_id):
    tid = str(item_id or '').strip()
    if not tid:
        raise DebridError('Invalid item id')
    return _request('GET', 'item/details', params={'id': tid}) or {}


def unrestrict_src(src):
    body = _request('POST', 'transfer/directdl', data={'src': str(src or '')}) or {}
    raw = body.get('content')
    out = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        link = _norm_url(it.get('link'))
        if not link:
            continue
        path = str(it.get('path') or '')
        out.append({'name': path.split('/')[-1] or 'file', 'link': link,
                    'size': int(it.get('size') or 0)})
    return out


def delete_transfer(transfer_id):
    tid = str(transfer_id or '').strip()
    if not tid:
        raise DebridError('Invalid transfer id')
    _request('POST', 'transfer/delete', data={'id': tid})
    clear_cloud_cache()
    return True


def retry_transfer(transfer_id):
    tid = str(transfer_id or '').strip()
    if not tid:
        raise DebridError('Invalid transfer id')
    _request('POST', 'transfer/retry', data={'id': tid})
    clear_cloud_cache()
    return True


def clear_cloud_cache():
    try:
        from resources.lib.cache import MainCache
        MainCache().delete_prefix('tmdbmovies_pm_')
    except Exception:
        xbmc.log('[DEBRID][PM] clear cache error', xbmc.LOGWARNING)
