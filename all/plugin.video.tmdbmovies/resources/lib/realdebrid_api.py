import time
import math
import requests
import xbmc

from resources.lib.utils import DebridError

BASE = 'https://api.real-debrid.com/rest/1.0/'

_RETRY_STATUS = (500, 502, 503, 504)
_MAX_RETRIES = 5
_REQUEST_TIMEOUT = 15


def _api_key():
    from resources.lib.config import ADDON
    try:
        return (ADDON.getSetting('rd_api_key') or '').strip()
    except Exception:
        return ''


def is_authenticated():
    return bool(_api_key())


def _headers():
    return {'Authorization': 'Bearer ' + _api_key()}


def _request(method, path, params=None, data=None, raw=False):
    key = _api_key()
    if not key:
        raise DebridError('No Real-Debrid API key set')
    url = BASE + path
    attempt = 0
    rate_retried = False
    while True:
        try:
            r = requests.request(method, url, headers=_headers(), params=params,
                                 data=data, timeout=_REQUEST_TIMEOUT)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            xbmc.log(f"[DEBRID][RD] {method} {path} network error", xbmc.LOGWARNING)
            raise DebridError('Real-Debrid connection failed')
        except Exception:
            xbmc.log(f"[DEBRID][RD] {method} {path} error", xbmc.LOGWARNING)
            raise DebridError('Real-Debrid request failed')
        if r.status_code == 429 and not rate_retried:
            rate_retried = True
            time.sleep(2)
            continue
        if r.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES - 1:
            attempt += 1
            time.sleep(1)
            continue
        break
    if raw:
        if r.status_code in (401, 403):
            raise DebridError('Invalid Real-Debrid API key')
        if r.status_code != 200:
            try:
                err = r.json()
                detail = err.get('error_description') or err.get('error') or f'HTTP {r.status_code}'
            except Exception:
                detail = f'HTTP {r.status_code}'
            raise DebridError(str(detail))
        return r
    if r.status_code == 401:
        raise DebridError('Invalid Real-Debrid API key')
    if r.status_code == 204:
        return None
    if r.status_code != 200:
        try:
            err = r.json()
            detail = err.get('error_description') or err.get('error') or f'HTTP {r.status_code}'
        except Exception:
            detail = f'HTTP {r.status_code}'
        xbmc.log(f"[DEBRID][RD] {method} {path} failed: {detail}", xbmc.LOGWARNING)
        raise DebridError(str(detail))
    if not r.content:
        return None
    try:
        return r.json()
    except Exception:
        raise DebridError('Real-Debrid bad response')


def account_info():
    return _request('GET', 'user') or {}


def user_cloud(page=1, limit=1000):
    params = {'page': int(page or 1), 'limit': int(limit or 1000)}
    return _request('GET', 'torrents', params=params) or []


def torrent_info(torrent_id):
    tid = str(torrent_id or '').strip()
    if not tid:
        raise DebridError('Invalid torrent id')
    return _request('GET', f'torrents/info/{tid}') or {}


def downloads(page=1, limit=50):
    try:
        r = _request('GET', 'downloads', params={'page': int(page or 1), 'limit': int(limit or 50)}, raw=True)
    except DebridError as e:
        if 'HTTP 204' in str(e):
            return {'items': [], 'total_pages': 1}
        raise
    try:
        items = r.json()
    except Exception:
        items = []
    if not isinstance(items, list):
        items = []
    total = 0
    try:
        total = int(r.headers.get('X-Total-Count', '0'))
    except Exception:
        total = 0
    total_pages = 1
    if total > 0:
        total_pages = max(1, int(math.ceil(total / float(limit))))
    elif len(items) >= limit:
        total_pages = (int(page or 1)) + 1
    return {'items': items, 'total_pages': total_pages}


def delete_torrent(torrent_id):
    tid = str(torrent_id or '').strip()
    if not tid:
        raise DebridError('Invalid torrent id')
    _request('DELETE', f'torrents/delete/{tid}')
    clear_cloud_cache()
    return True


def delete_download(download_id):
    did = str(download_id or '').strip()
    if not did:
        raise DebridError('Invalid download id')
    _request('DELETE', f'downloads/delete/{did}')
    clear_cloud_cache()
    return True


def unrestrict_link(link):
    link = str(link or '').strip()
    if not link:
        raise DebridError('Empty link')
    if link.lower().endswith(('.rar', '.zip', '.r00', '.7z')):
        raise DebridError('Archive files are not playable')
    result = _request('POST', 'unrestrict/link', data={'link': link}) or {}
    dl = result.get('download')
    if not dl:
        raise DebridError('No download link returned')
    return dl


def clear_cloud_cache():
    try:
        from resources.lib.cache import MainCache
        MainCache().delete_prefix('tmdbmovies_rd_')
    except Exception:
        xbmc.log("[DEBRID][RD] clear cache error", xbmc.LOGWARNING)
