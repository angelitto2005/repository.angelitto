import time

import requests
import xbmc
from requests.utils import requote_uri

from resources.lib.utils import DebridError, sleep_abortable

BASE = 'https://offcloud.com/api'
_REQUEST_TIMEOUT = 15
_MAX_RETRIES = 3
_BACKOFF = (1, 2)


def _api_key():
    from resources.lib.config import ADDON
    try:
        return (ADDON.getSetting('oc_api_key') or '').strip()
    except Exception:
        return ''


def is_authenticated():
    return bool(_api_key())


def _headers():
    return {'Authorization': 'Bearer %s' % _api_key(),
            'Accept': 'application/json',
            'User-Agent': 'TMDbMovies/1.0 (Kodi addon)'}


def _key_params(extra=None):
    p = {'key': _api_key()}
    if extra:
        p.update(extra)
    return p


def _display_name(raw):
    import urllib.parse
    s = str(raw or '').strip()
    if not s:
        return 'file'
    try:
        s = urllib.parse.unquote(s)
    except Exception:
        pass
    return s or 'file'


def _norm_url(link):
    s = str(link or '').strip()
    if not s:
        return ''
    if s.startswith('//'):
        return 'https:' + s
    try:
        return requote_uri(s)
    except Exception:
        return s


def _backoff(attempt):
    try:
        idx = min(attempt - 1, len(_BACKOFF) - 1)
    except Exception:
        idx = 0
    return sleep_abortable(_BACKOFF[idx])


def _request(method, path, params=None, data=None, json_body=None):
    key = _api_key()
    if not key:
        raise DebridError('No Offcloud API key set')
    url = BASE + '/' + str(path or '').lstrip('/')
    attempt = 0
    while True:
        try:
            r = requests.request(method, url, headers=_headers(),
                                 params=_key_params(params), data=data,
                                 json=json_body, timeout=_REQUEST_TIMEOUT)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            xbmc.log('[DEBRID][OC] %s %s network error' % (method, path), xbmc.LOGWARNING)
            raise DebridError('Offcloud connection failed')
        except Exception:
            xbmc.log('[DEBRID][OC] %s %s error' % (method, path), xbmc.LOGWARNING)
            raise DebridError('Offcloud request failed')
        if r.status_code in (429, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
            attempt += 1
            if not _backoff(attempt):
                raise DebridError('Offcloud unavailable (Kodi closing)')
            continue
        body = {}
        if r.content:
            try:
                body = r.json()
            except Exception:
                body = {}
        if isinstance(body, dict) and str(body.get('error') or ''):
            xbmc.log('[DEBRID][OC] %s %s error: %s' % (method, path, str(body.get('error'))[:120]), xbmc.LOGWARNING)
            raise DebridError(str(body.get('error')))
        if r.status_code >= 400:
            if r.status_code in (401, 403):
                raise DebridError('Invalid Offcloud API key')
            xbmc.log('[DEBRID][OC] %s %s failed: HTTP %s' % (method, path, r.status_code), xbmc.LOGWARNING)
            raise DebridError('Offcloud HTTP %s' % r.status_code)
        return body


def validate_key():
    _request('GET', 'account/info')
    return True


def account_info():
    return _request('GET', 'account/info') or {}


def user_cloud():
    raw = _request('GET', 'cloud/history')
    if isinstance(raw, dict):
        raw = raw.get('history') or raw.get('requests') or []
    items = []
    for it in (raw if isinstance(raw, list) else []):
        if not isinstance(it, dict):
            continue
        items.append({
            'id': str(it.get('requestId') or ''),
            'name': str(it.get('fileName') or 'Unnamed'),
            'status': str(it.get('status') or '').lower(),
            'is_folder': bool(it.get('isDirectory')),
            'server': str(it.get('server') or ''),
            'url': _norm_url(it.get('url')),
            'original_link': str(it.get('originalLink') or ''),
            'message': str(it.get('message') or it.get('detail') or ''),
            'created': str(it.get('createdOn') or ''),
            'size': int(it.get('size') or 0),
        })
    return {'items': items, 'total': len(items), 'total_pages': 1}


def explore(request_id):
    rid = str(request_id or '').strip()
    if not rid:
        raise DebridError('Invalid Offcloud request id')
    raw = _request('GET', 'cloud/explore/%s' % rid)
    out = []
    for it in (raw if isinstance(raw, list) else []):
        if isinstance(it, str):
            link = _norm_url(it)
            if not link:
                continue
            base = link.split('?')[0].split('#')[0].split('/')[-1]
            out.append({'name': _display_name(base), 'link': link, 'size': 0})
        elif isinstance(it, dict):
            link = _norm_url(it.get('url') or it.get('link'))
            if not link:
                continue
            path = str(it.get('path') or it.get('name') or '')
            name = _display_name(path.split('/')[-1] if path else link.split('/')[-1])
            out.append({'name': name, 'link': link, 'size': int(it.get('size') or 0)})
    return out


def play_url(item):
    if not isinstance(item, dict):
        return ''
    direct = _norm_url(item.get('url'))
    if direct:
        return direct
    server = str(item.get('server') or '').strip()
    rid = str(item.get('id') or '').strip()
    name = str(item.get('name') or '').strip()
    if server and rid and name:
        return 'https://%s.offcloud.com/cloud/download/%s/%s' % (server, rid, name)
    return ''


def delete_request(request_id):
    rid = str(request_id or '').strip()
    if not rid:
        raise DebridError('Invalid Offcloud request id')
    _request('GET', 'cloud/remove/%s' % rid)
    clear_cloud_cache()
    return True


def clear_cloud_cache():
    try:
        from resources.lib.cache import MainCache
        MainCache().delete_prefix('tmdbmovies_oc_')
    except Exception:
        xbmc.log('[DEBRID][OC] clear cache error', xbmc.LOGWARNING)
