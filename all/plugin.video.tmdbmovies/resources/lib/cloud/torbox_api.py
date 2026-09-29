import requests
import xbmc

from resources.lib.utils import DebridError

BASE = 'https://api.torbox.app/v1/api/'

_REQUEST_TIMEOUT = 15

MEDIA_TYPES = ('torrents', 'usenet', 'webdl')

_CONTROL_PATHS = {
    'torrents': 'torrents/controltorrent',
    'usenet': 'usenet/controlusenetdownload',
    'webdl': 'webdl/controlwebdownload',
}

_CONTROL_ID_KEYS = {
    'torrents': 'torrent_id',
    'usenet': 'usenet_id',
    'webdl': 'webdl_id',
}

_EDIT_PATHS = {
    'torrents': 'torrents/edittorrent',
    'usenet': 'usenet/editusenetdownload',
    'webdl': 'webdl/editwebdownload',
}

_EDIT_ID_KEYS = {
    'torrents': 'torrent_id',
    'usenet': 'usenet_download_id',
    'webdl': 'webdl_id',
}

_MYLIST_PATHS = {
    'torrents': 'torrents/mylist',
    'usenet': 'usenet/mylist',
    'webdl': 'webdl/mylist',
}

_REQUESTDL_PATHS = {
    'torrents': 'torrents/requestdl',
    'usenet': 'usenet/requestdl',
    'webdl': 'webdl/requestdl',
}

_REQUESTDL_ID_KEYS = {
    'torrents': 'torrent_id',
    'usenet': 'usenet_id',
    'webdl': 'web_id',
}


def _api_key():
    from resources.lib.config import ADDON
    try:
        return (ADDON.getSetting('torbox_api_key') or '').strip()
    except Exception:
        return ''


def is_authenticated():
    return bool(_api_key())


def _headers():
    return {'Authorization': 'Bearer ' + _api_key()}


def _request(method, path, params=None, json_body=None):
    key = _api_key()
    if not key:
        raise DebridError('No TorBox API key set')
    url = BASE + path
    try:
        r = requests.request(method, url, headers=_headers(), params=params,
                             json=json_body, timeout=_REQUEST_TIMEOUT)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        xbmc.log(f"[DEBRID][TorBox] {method} {path} network error", xbmc.LOGWARNING)
        raise DebridError('TorBox connection failed')
    except Exception:
        xbmc.log(f"[DEBRID][TorBox] {method} {path} error", xbmc.LOGWARNING)
        raise DebridError('TorBox request failed')
    if r.status_code == 403:
        raise DebridError('Invalid TorBox API key')
    try:
        data = r.json()
    except Exception:
        raise DebridError(f'TorBox bad response (HTTP {r.status_code})')
    if r.status_code != 200 or not data.get('success'):
        detail = data.get('detail') or data.get('error') or f'HTTP {r.status_code}'
        xbmc.log(f"[DEBRID][TorBox] {method} {path} failed: {detail}", xbmc.LOGWARNING)
        raise DebridError(str(detail))
    return data.get('data')


def account_info():
    return _request('GET', 'user/me') or {}


def user_cloud(mediatype='torrents', bypass_cache=True):
    if mediatype not in MEDIA_TYPES:
        raise DebridError('Unknown media type')
    params = {}
    if bypass_cache:
        params['bypass_cache'] = 'true'
    data = _request('GET', _MYLIST_PATHS[mediatype], params=params)
    if isinstance(data, dict):
        return data.get('data') if isinstance(data.get('data'), list) else []
    if isinstance(data, list):
        return data
    return []


def user_folder(mediatype, item_id, fresh=False):
    if mediatype not in MEDIA_TYPES:
        raise DebridError('Unknown media type')
    try:
        target = int(item_id)
    except Exception:
        raise DebridError('Invalid item id')
    for item in user_cloud(mediatype, bypass_cache=fresh):
        if isinstance(item, dict) and item.get('id') == target:
            return item
    raise DebridError('Item not found on TorBox')


def delete_item(mediatype, item_id):
    if mediatype not in MEDIA_TYPES:
        raise DebridError('Unknown media type')
    body = {_CONTROL_ID_KEYS[mediatype]: int(item_id), 'operation': 'delete'}
    _request('POST', _CONTROL_PATHS[mediatype], json_body=body)
    clear_cloud_cache()
    return True


def toggle_airlock(mediatype, item_id):
    if mediatype not in MEDIA_TYPES:
        raise DebridError('Unknown media type')
    item_id = int(item_id)
    current = user_folder(mediatype, item_id, fresh=True)
    if not isinstance(current, dict):
        raise DebridError('Item not found on TorBox')
    if not isinstance(current.get('airlocked'), bool):
        raise DebridError('AirLock state unknown for this item')
    new_state = not current.get('airlocked')
    body = {_EDIT_ID_KEYS[mediatype]: item_id, 'airlocked': new_state}
    for echo_key in ('name', 'tags', 'alternative_hashes'):
        if current.get(echo_key) is not None:
            body[echo_key] = current.get(echo_key)
    try:
        _request('PUT', _EDIT_PATHS[mediatype], json_body=body)
    except DebridError as e:
        msg = str(e)
        if 'PLAN_RESTRICTED' in msg or 'restricted' in msg.lower():
            raise DebridError('AIRLock is not available on your TorBox plan')
        raise
    clear_cloud_cache()
    return new_state


def unrestrict_link(mediatype, item_id, file_id=None):
    if mediatype not in MEDIA_TYPES:
        raise DebridError('Unknown media type')
    params = {
        'token': _api_key(),
        _REQUESTDL_ID_KEYS[mediatype]: int(item_id),
        'file_id': int(file_id or 0),
    }
    data = _request('GET', _REQUESTDL_PATHS[mediatype], params=params)
    if isinstance(data, dict):
        link = data.get('link') or data.get('redirect') or data.get('url')
        if link:
            return link
    if isinstance(data, str):
        return data
    raise DebridError('No download link returned')


def clear_cloud_cache():
    try:
        from resources.lib.cache import MainCache
        MainCache().delete_prefix('tmdbmovies_tb_')
    except Exception:
        xbmc.log("[DEBRID][TorBox] clear cache error", xbmc.LOGWARNING)
