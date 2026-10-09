import json
import os
import time
import uuid

import xbmc

import config

PROFILE = config.ensure_dir(config.ADDON_PROFILE)

_SEARCHES = 'search_history.json'
_HISTORY = 'watch_history.json'
_SUBS = 'subscriptions.json'
_BOOKMARKS = 'bookmarks.json'
_WATCH_LATER = 'watch_later.json'
_LIBRARY = 'library.json'
_STATE = 'state.json'
_OAUTH = 'youtube_oauth.json'

_SEARCHES_CAP = 25
_HISTORY_CAP = 100
_SUBS_CAP = 2000
_BOOKMARKS_CAP = 200
_WATCH_LATER_CAP = 500


def _path(name):
    return os.path.join(PROFILE, name)


def _read(name, default):
    try:
        with open(_path(name), encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return default
    return payload if isinstance(payload, type(default)) else default


def _write(name, payload):
    try:
        with open(_path(name), 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
    except OSError as exc:
        config.log('write {} failed: {}'.format(name, exc), xbmc.LOGWARNING)


def _read_obj(name):
    return _read(name, {})


def _write_obj(name, payload):
    _write(name, payload)
    try:
        os.chmod(_path(name), 0o600)
    except OSError:
        pass


def get_searches():
    return _read(_SEARCHES, [])


def add_search(query):
    query = str(query or '').strip()
    if not query:
        return
    searches = [item for item in get_searches() if item != query]
    searches.insert(0, query)
    _write(_SEARCHES, searches[:_SEARCHES_CAP])


def remove_search(query):
    _write(_SEARCHES, [item for item in get_searches() if item != query])


def clear_searches():
    _write(_SEARCHES, [])


def get_history():
    return _read(_HISTORY, [])


def add_history(entry):
    entry = dict(entry or {})
    video_id = entry.get('video_id') or ''
    if not video_id:
        return
    entry['video_id'] = video_id
    entry['watched'] = int(time.time())
    history = [item for item in get_history() if item.get('video_id') != video_id]
    history.insert(0, entry)
    _write(_HISTORY, history[:_HISTORY_CAP])


def remove_history(video_id):
    _write(_HISTORY, [item for item in get_history()
                      if item.get('video_id') != video_id])


def clear_history():
    _write(_HISTORY, [])


def get_subscriptions():
    return _read(_SUBS, [])


def subscribe(title, url, image='', source='local'):
    subs = [item for item in get_subscriptions() if item.get('url') != url]
    subs.append({'title': title, 'url': url, 'image': image,
                 'source': source, 'added': int(time.time())})
    _write(_SUBS, subs[:_SUBS_CAP])


def unsubscribe(url):
    _write(_SUBS, [item for item in get_subscriptions() if item.get('url') != url])


def is_subscribed(url):
    return any(item.get('url') == url for item in get_subscriptions())


def get_bookmarks():
    return _read(_BOOKMARKS, [])


def bookmark(title, url, image=''):
    marks = [item for item in get_bookmarks() if item.get('url') != url]
    marks.append({'title': title, 'url': url, 'image': image,
                  'added': int(time.time())})
    _write(_BOOKMARKS, marks[:_BOOKMARKS_CAP])


def unbookmark(url):
    _write(_BOOKMARKS, [item for item in get_bookmarks() if item.get('url') != url])


def get_watch_later():
    return _read(_WATCH_LATER, [])


def add_watch_later(entry):
    entry = dict(entry or {})
    video_id = entry.get('video_id') or ''
    if not video_id:
        return
    entry['video_id'] = video_id
    items = [item for item in get_watch_later()
             if item.get('video_id') != video_id]
    items.insert(0, entry)
    _write(_WATCH_LATER, items[:_WATCH_LATER_CAP])


def remove_watch_later(video_id):
    _write(_WATCH_LATER, [item for item in get_watch_later()
                          if item.get('video_id') != video_id])


def get_library(name):
    value = _read_obj(_LIBRARY).get(str(name or ''))
    return value if isinstance(value, list) else []


def set_library(name, entries):
    library = _read_obj(_LIBRARY)
    library[str(name or '')] = list(entries or [])
    library['updated_at'] = int(time.time())
    _write_obj(_LIBRARY, library)


def clear_library():
    try:
        os.remove(_path(_LIBRARY))
    except OSError:
        pass


def merge_youtube_subscriptions(remote):
    existing = {item.get('url'): dict(item)
                for item in get_subscriptions() if item.get('url')}
    remote_map = {item.get('url'): dict(item) for item in remote or []
                  if item.get('url')}
    merged = []
    for url, entry in remote_map.items():
        previous = existing.pop(url, {})
        item = dict(previous)
        item.update(entry)
        item['source'] = 'both' if previous.get('source') in ('local', 'both') else 'youtube'
        item['synced'] = int(time.time())
        merged.append(item)
    for entry in existing.values():
        if entry.get('source') == 'youtube':
            continue
        if entry.get('source') == 'both':
            entry.pop('youtube_subscription_id', None)
            entry.pop('synced', None)
            entry['source'] = 'local'
        merged.append(entry)
    _write(_SUBS, merged[:_SUBS_CAP])
    return len(remote_map)


def get_state(name):
    value = _read_obj(_STATE).get(str(name or ''))
    return value if isinstance(value, dict) else {}


def set_state(name, value):
    state = _read_obj(_STATE)
    state[str(name or '')] = dict(value or {})
    _write_obj(_STATE, state)


def get_oauth_token():
    return _read_obj(_OAUTH).get('token') or {}


def set_oauth_token(token):
    data = _read_obj(_OAUTH)
    data['token'] = dict(token or {})
    _write_obj(_OAUTH, data)


def clear_oauth_token():
    data = _read_obj(_OAUTH)
    data.pop('token', None)
    _write_obj(_OAUTH, data)


def get_oauth_pending():
    return _read_obj(_OAUTH).get('pending') or {}


def set_oauth_pending(pending):
    data = _read_obj(_OAUTH)
    data['pending'] = dict(pending or {})
    _write_obj(_OAUTH, data)


def clear_oauth_pending():
    data = _read_obj(_OAUTH)
    data.pop('pending', None)
    _write_obj(_OAUTH, data)


def get_auth_provider():
    return _read_obj(_OAUTH).get('provider') or {}


def set_auth_provider(provider):
    data = _read_obj(_OAUTH)
    data['provider'] = dict(provider or {})
    _write_obj(_OAUTH, data)


def clear_auth_provider():
    data = _read_obj(_OAUTH)
    data.pop('provider', None)
    _write_obj(_OAUTH, data)


def get_device_id():
    return _read_obj(_OAUTH).get('device_id') or ''


def set_device_id(device_id=None):
    data = _read_obj(_OAUTH)
    data['device_id'] = device_id or str(uuid.uuid4())
    _write_obj(_OAUTH, data)
    return data['device_id']