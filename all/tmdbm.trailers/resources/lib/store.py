import json
import os
import re
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
    collapsed = {}
    for item in _read(_SUBS, []):
        if not isinstance(item, dict) or not item.get('url'):
            continue
        key = _sub_key(item.get('url'))
        previous = collapsed.get(key)
        if previous is None or ('/channel/' in str(item.get('url'))
                                and '/channel/' not in str(previous.get('url'))):
            collapsed[key] = item
    return list(collapsed.values())


def _sub_key(url):
    text = str(url or '').strip().rstrip('/')
    match = re.search(r'/channel/([A-Za-z0-9_-]+)', text)
    if match:
        return 'channel:' + match.group(1)
    return 'url:' + text.lower()


def subscribe(title, url, image='', source='local'):
    key = _sub_key(url)
    if is_url_title(title, url):
        title = ''
    subs = [item for item in _read(_SUBS, [])
            if _sub_key(item.get('url')) != key]
    subs.append({'title': title, 'url': url, 'image': image,
                 'source': source, 'added': int(time.time())})
    _write(_SUBS, subs[:_SUBS_CAP])
    clear_feed_cache()


def unsubscribe(url):
    key = _sub_key(url)
    _write(_SUBS, [item for item in _read(_SUBS, [])
                   if _sub_key(item.get('url')) != key])
    clear_feed_cache()


def is_subscribed(url):
    key = _sub_key(url)
    return any(_sub_key(item.get('url')) == key
               for item in _read(_SUBS, []))


_BROKEN_THUMB_PREFIX = 'https://yt3.googleusercontent.com/UC'


def is_broken_thumb(image):
    return str(image or '').startswith(_BROKEN_THUMB_PREFIX)


def is_video_thumb(image):
    text = str(image or '')
    return 'i.ytimg.com' in text and '/vi/' in text


def is_url_title(title, url):
    text = str(title or '').strip()
    if not text:
        return True
    if text == str(url or '').strip():
        return True
    return text.startswith('http')


def needs_avatar(image):
    return not image or is_broken_thumb(image) or is_video_thumb(image)


def update_subscription_image(url, image):
    return update_subscription(url, image=image)


def update_subscription(url, image=None, title=None):
    key = _sub_key(url)
    changed = False
    subs = _read(_SUBS, [])
    for item in subs:
        if isinstance(item, dict) and _sub_key(item.get('url')) == key:
            if image and not is_broken_thumb(image):
                current = item.get('image') or ''
                if needs_avatar(current):
                    item['image'] = image
                    changed = True
            if title and is_url_title(item.get('title'), item.get('url')):
                item['title'] = title
                changed = True
    if changed:
        _write(_SUBS, subs[:_SUBS_CAP])
    return changed


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


_LOCAL_PLAYLISTS = 'local_playlists'
_LOCAL_PREFIX = 'local_playlist_'
_LOCAL_TRACK_CAP = 200
_LOCAL_FILE = 'local_playlists.json'
_FEED_CACHE = 'feed_local_cache'
_FEED_FULL_CACHE = 'feed_full_cache'
_FEED_CACHE_TTL = 1800
_YT_META = 'yt_meta_cache'
_YT_META_TTL = 7 * 24 * 3600
_YT_META_FAIL_TTL = 3600
_YT_META_CAP = 2000
_REMOTE_MIRROR_KEYS = ('subscription_feed', 'subscribed_channels',
                       'watch_later_remote', 'remote_history',
                       'saved_playlists', 'music_pool')


def _is_local_key(name):
    text = str(name or '')
    return text == _LOCAL_PLAYLISTS or text.startswith(_LOCAL_PREFIX)


def _migrate_local_playlists():
    try:
        if os.path.isfile(_path(_LOCAL_FILE)):
            return
        library = _read_obj(_LIBRARY)
        local = {key: value for key, value in library.items()
                 if key == _LOCAL_PLAYLISTS or key.startswith(_LOCAL_PREFIX)}
        if not local:
            return
        _write_obj(_LOCAL_FILE, local)
        for key in local:
            library.pop(key, None)
        _write_obj(_LIBRARY, library)
    except Exception as exc:
        config.log('local playlists migrate failed: {}'.format(exc),
                   xbmc.LOGWARNING)


def remove_library(name):
    if _is_local_key(name):
        _migrate_local_playlists()
        data = _read_obj(_LOCAL_FILE)
        data.pop(str(name or ''), None)
        _write_obj(_LOCAL_FILE, data)
        return
    library = _read_obj(_LIBRARY)
    library.pop(str(name or ''), None)
    _write_obj(_LIBRARY, library)


def get_local_playlists():
    return [item for item in get_library(_LOCAL_PLAYLISTS)
            if isinstance(item, dict) and item.get('id')]


def create_local_playlist(name):
    pid = uuid.uuid4().hex[:12]
    items = get_local_playlists()
    items.append({'id': pid, 'name': name,
                  'created': int(time.time())})
    set_library(_LOCAL_PLAYLISTS, items)
    return pid


def rename_local_playlist(pid, name):
    items = get_local_playlists()
    for item in items:
        if item.get('id') == pid:
            item['name'] = name
    set_library(_LOCAL_PLAYLISTS, items)


def delete_local_playlist(pid):
    set_library(_LOCAL_PLAYLISTS,
                [item for item in get_local_playlists()
                 if item.get('id') != pid])
    remove_library(_LOCAL_PREFIX + str(pid or ''))


def get_local_playlist_tracks(pid):
    return get_library(_LOCAL_PREFIX + str(pid or ''))


def add_to_local_playlist(pid, entry):
    entry = dict(entry or {})
    video_id = entry.get('video_id') or ''
    if not video_id:
        return None
    entry['video_id'] = video_id
    tracks = get_local_playlist_tracks(pid)
    if any(track.get('video_id') == video_id for track in tracks):
        return 'duplicate'
    if len(tracks) >= _LOCAL_TRACK_CAP:
        return 'full'
    tracks.append(entry)
    set_library(_LOCAL_PREFIX + str(pid or ''), tracks)
    return 'added'


def remove_from_local_playlist(pid, video_id):
    set_library(_LOCAL_PREFIX + str(pid or ''),
                [track for track in get_local_playlist_tracks(pid)
                 if track.get('video_id') != video_id])


def get_library(name):
    if _is_local_key(name):
        _migrate_local_playlists()
        value = _read_obj(_LOCAL_FILE).get(str(name or ''))
        return value if isinstance(value, list) else []
    value = _read_obj(_LIBRARY).get(str(name or ''))
    return value if isinstance(value, list) else []


def set_library(name, entries):
    if _is_local_key(name):
        _migrate_local_playlists()
        data = _read_obj(_LOCAL_FILE)
        data[str(name or '')] = list(entries or [])
        _write_obj(_LOCAL_FILE, data)
        return
    library = _read_obj(_LIBRARY)
    library[str(name or '')] = list(entries or [])
    library['updated_at'] = int(time.time())
    _write_obj(_LIBRARY, library)


def prune_youtube_subscriptions():
    merged = {}
    for item in _read(_SUBS, []):
        if not isinstance(item, dict) or not item.get('url'):
            continue
        if item.get('source') == 'youtube':
            continue
        item = dict(item)
        if item.get('source') == 'both':
            item.pop('youtube_subscription_id', None)
            item.pop('synced', None)
            item['source'] = 'local'
        key = _sub_key(item.get('url'))
        previous = merged.get(key)
        if previous is None or ('/channel/' in str(item.get('url'))
                                and '/channel/' not in str(previous.get('url'))):
            merged[key] = item
    _write(_SUBS, list(merged.values())[:_SUBS_CAP])
    clear_feed_cache()


def clear_remote_mirrors():
    library = _read_obj(_LIBRARY)
    for key in _REMOTE_MIRROR_KEYS:
        library.pop(key, None)
    _write_obj(_LIBRARY, library)


def _feed_cache_valid(data):
    if not isinstance(data, dict):
        return False
    try:
        age = int(time.time()) - int(data.get('ts') or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= _FEED_CACHE_TTL


def _debug_no_cache():
    try:
        return bool(config.get_bool('debug', False))
    except Exception:
        return False


def get_feed_cache():
    if _debug_no_cache():
        return []
    data = _read_obj(_LIBRARY).get(_FEED_CACHE)
    if not _feed_cache_valid(data):
        return []
    entries = data.get('entries')
    return entries if isinstance(entries, list) else []


def set_feed_cache(entries):
    library = _read_obj(_LIBRARY)
    library[_FEED_CACHE] = {'ts': int(time.time()),
                            'entries': list(entries or [])}
    _write_obj(_LIBRARY, library)


def get_feed_full_cache():
    if _debug_no_cache():
        return {}
    data = _read_obj(_LIBRARY).get(_FEED_FULL_CACHE)
    if not _feed_cache_valid(data):
        return {}
    entries = data.get('entries')
    if not isinstance(entries, list):
        return {}
    return {'entries': entries, 'need': int(data.get('need') or 0),
            'exhausted': bool(data.get('exhausted', True))}


def set_feed_full_cache(entries, need, exhausted):
    library = _read_obj(_LIBRARY)
    library[_FEED_FULL_CACHE] = {'ts': int(time.time()),
                                 'entries': list(entries or []),
                                 'need': int(need or 0),
                                 'exhausted': bool(exhausted)}
    _write_obj(_LIBRARY, library)


def clear_feed_cache():
    remove_library(_FEED_CACHE)
    remove_library(_FEED_FULL_CACHE)


def set_yt_meta_failed(video_id):
    try:
        if not video_id:
            return
        library = _read_obj(_LIBRARY)
        data = library.get(_YT_META)
        if not isinstance(data, dict):
            data = {}
        data[str(video_id)] = {'ts': int(time.time()), 'fail': True}
        if len(data) > _YT_META_CAP:
            ordered = sorted(data.items(),
                             key=lambda kv: int((kv[1] or {}).get('ts') or 0))
            data = dict(ordered[-(_YT_META_CAP - 500):])
        library[_YT_META] = data
        _write_obj(_LIBRARY, library)
    except Exception as exc:
        config.log('yt meta fail mark failed: {}'.format(exc),
                   xbmc.LOGWARNING)


def is_yt_meta_failed(video_id):
    try:
        data = _read_obj(_LIBRARY).get(_YT_META) or {}
        item = data.get(str(video_id or ''))
        if not isinstance(item, dict) or not item.get('fail'):
            return False
        return int(time.time()) - int(item.get('ts') or 0) <= _YT_META_FAIL_TTL
    except Exception:
        return False


def clear_yt_meta_cache():
    remove_library(_YT_META)


def get_yt_meta(video_id):
    try:
        data = _read_obj(_LIBRARY).get(_YT_META) or {}
        item = data.get(str(video_id or ''))
        if not isinstance(item, dict):
            return {}
        if int(time.time()) - int(item.get('ts') or 0) > _YT_META_TTL:
            return {}
        meta = item.get('meta')
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def set_yt_meta(video_id, meta):
    try:
        if not video_id or not isinstance(meta, dict):
            return
        library = _read_obj(_LIBRARY)
        data = library.get(_YT_META)
        if not isinstance(data, dict):
            data = {}
        data[str(video_id)] = {'ts': int(time.time()), 'meta': dict(meta)}
        if len(data) > _YT_META_CAP:
            ordered = sorted(data.items(),
                             key=lambda kv: int((kv[1] or {}).get('ts') or 0))
            data = dict(ordered[-(_YT_META_CAP - 500):])
        library[_YT_META] = data
        _write_obj(_LIBRARY, library)
    except Exception as exc:
        config.log('yt meta cache failed: {}'.format(exc), xbmc.LOGWARNING)


def merge_youtube_subscriptions(remote):
    existing = {}
    for item in get_subscriptions():
        if not isinstance(item, dict) or not item.get('url'):
            continue
        existing[_sub_key(item.get('url'))] = dict(item)
    remote_map = {}
    for item in remote or []:
        if not isinstance(item, dict) or not item.get('url'):
            continue
        remote_map[_sub_key(item.get('url'))] = dict(item)
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