# -*- coding: utf-8 -*-

# NewPipe Addon
# Author Twilight0
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSES/GPL-3.0-only for more information.

# Privacy-first local storage: subscriptions, watch history and search
# history live in plain JSON files inside the addon profile. Nothing is
# uploaded anywhere; deleting the files (or uninstalling) wipes everything.
import json
import os
import time
import uuid

from tulip.kodi import dataPath

PROFILE = os.environ.get('NEWPIPE_PROFILE') or dataPath

_SUBS = 'subscriptions.json'
_HISTORY = 'watch_history.json'
_SEARCHES = 'search_history.json'
_YOUTUBE_OAUTH = 'youtube_oauth.json'
_WATCH_LATER = 'watch_later.json'
_YOUTUBE_LIBRARY = 'youtube_library.json'
_LOCAL_LIBRARY = 'local_library.json'
_LOCAL_STATE = 'local_state.json'

_SUBS_CAP = 2000
_HISTORY_CAP = 100
_SEARCHES_CAP = 25
_WATCH_LATER_CAP = 500


def _path(name):
    return os.path.join(PROFILE, name)


def _load(name, default):
    try:
        with open(_path(name), encoding='utf-8') as f:
            payload = json.load(f)
        return payload if isinstance(payload, list) else default
    except (OSError, ValueError):
        return default


def _save(name, payload):
    os.makedirs(PROFILE, exist_ok=True)
    with open(_path(name), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def _load_object(name):
    try:
        with open(_path(name), encoding='utf-8') as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_object(name, payload):
    _save(name, payload)
    try:
        os.chmod(_path(name), 0o600)
    except OSError:
        pass


def get_subscriptions():
    return _load(_SUBS, [])


def subscribe(title, url):
    current = next((s for s in get_subscriptions() if s.get('url') == url), {})
    subs = [s for s in get_subscriptions() if s.get('url') != url]
    source = 'both' if current.get('source') == 'youtube' else 'local'
    item = dict(current)
    item.update({'title': title, 'url': url, 'added': int(time.time()), 'source': source})
    subs.append(item)
    _save(_SUBS, subs[:_SUBS_CAP])


def unsubscribe(url):
    _save(_SUBS, [s for s in get_subscriptions() if s.get('url') != url])


def sync_youtube_subscriptions(remote_subscriptions):
    """Merge an account snapshot without removing manually saved channels."""
    existing = {entry.get('url'): dict(entry) for entry in get_subscriptions() if entry.get('url')}
    remote = {entry.get('url'): dict(entry) for entry in remote_subscriptions if entry.get('url')}
    merged = []

    for url, entry in remote.items():
        previous = existing.pop(url, {})
        item = dict(previous)
        item.update(entry)
        item['source'] = 'both' if previous.get('source') in ('local', 'both') else 'youtube'
        item['synced'] = int(time.time())
        merged.append(item)

    for entry in existing.values():
        source = entry.get('source', 'local')
        if source == 'youtube':
            continue
        if source == 'both':
            entry.pop('youtube_subscription_id', None)
            entry.pop('synced', None)
            entry['source'] = 'local'
        merged.append(entry)

    _save(_SUBS, merged[:_SUBS_CAP])
    return len(remote)


def clear_youtube_subscriptions():
    """Remove account-imported channels while preserving manual subscriptions.

    A channel with ``source == 'youtube'`` came only from the linked YouTube
    account and must disappear with that account.  A ``both`` channel was also
    added manually by the person using Kodi, so retain it as a local channel
    after dropping YouTube-only metadata.
    """
    kept = []
    removed = 0
    for entry in get_subscriptions():
        item = dict(entry)
        source = item.get('source', 'local')
        if source == 'youtube':
            removed += 1
            continue
        if source == 'both':
            item.pop('youtube_subscription_id', None)
            item.pop('synced', None)
            item['source'] = 'local'
        kept.append(item)
    _save(_SUBS, kept[:_SUBS_CAP])
    return removed


def get_youtube_oauth_token():
    return _load_object(_YOUTUBE_OAUTH).get('token') or {}


def set_youtube_oauth_token(token):
    data = _load_object(_YOUTUBE_OAUTH)
    data['token'] = dict(token or {})
    _save_object(_YOUTUBE_OAUTH, data)


def clear_youtube_oauth_token():
    data = _load_object(_YOUTUBE_OAUTH)
    data.pop('token', None)
    _save_object(_YOUTUBE_OAUTH, data)


def get_youtube_oauth_pending():
    return _load_object(_YOUTUBE_OAUTH).get('pending') or {}


def set_youtube_oauth_pending(pending):
    data = _load_object(_YOUTUBE_OAUTH)
    data['pending'] = dict(pending or {})
    _save_object(_YOUTUBE_OAUTH, data)


def clear_youtube_oauth_pending():
    data = _load_object(_YOUTUBE_OAUTH)
    data.pop('pending', None)
    _save_object(_YOUTUBE_OAUTH, data)


def get_youtube_auth_provider():
    return _load_object(_YOUTUBE_OAUTH).get('provider') or {}


def set_youtube_auth_provider(provider):
    data = _load_object(_YOUTUBE_OAUTH)
    data['provider'] = dict(provider or {})
    _save_object(_YOUTUBE_OAUTH, data)


def clear_youtube_auth_provider():
    """Remove the cached public YouTube TV client data."""
    data = _load_object(_YOUTUBE_OAUTH)
    data.pop('provider', None)
    _save_object(_YOUTUBE_OAUTH, data)


def get_youtube_library(name):
    """Return an account-library snapshot saved after an explicit sync.

    The TV response is cached locally so opening a Kodi folder never blocks or
    performs an automatic authenticated request in the UI thread.
    """
    library = _load_object(_YOUTUBE_LIBRARY)
    value = library.get(str(name or ''))
    return value if isinstance(value, list) else []


def set_youtube_library(name, entries):
    library = _load_object(_YOUTUBE_LIBRARY)
    library[str(name or '')] = list(entries or [])
    library['updated_at'] = int(time.time())
    _save_object(_YOUTUBE_LIBRARY, library)


def clear_youtube_library():
    try:
        os.remove(_path(_YOUTUBE_LIBRARY))
    except OSError:
        pass


def get_local_library(name):
    """Read an add-on-only local collection such as the Random music pool."""
    value = _load_object(_LOCAL_LIBRARY).get(str(name or ''))
    return value if isinstance(value, list) else []


def set_local_library(name, entries):
    library = _load_object(_LOCAL_LIBRARY)
    library[str(name or '')] = list(entries or [])
    _save_object(_LOCAL_LIBRARY, library)


def get_local_state(name):
    """Read small private playback state without exposing it to account sync."""
    value = _load_object(_LOCAL_STATE).get(str(name or ''))
    return value if isinstance(value, dict) else {}


def set_local_state(name, value):
    state = _load_object(_LOCAL_STATE)
    state[str(name or '')] = dict(value or {})
    _save_object(_LOCAL_STATE, state)


def get_youtube_device_id():
    return _load_object(_YOUTUBE_OAUTH).get('device_id') or ''


def set_youtube_device_id(device_id=None):
    data = _load_object(_YOUTUBE_OAUTH)
    data['device_id'] = device_id or str(uuid.uuid4())
    _save_object(_YOUTUBE_OAUTH, data)
    return data['device_id']


_BOOKMARKS = 'bookmarks.json'
_BOOKMARKS_CAP = 200


def get_bookmarks():
    return _load(_BOOKMARKS, [])


def bookmark(title, url, image=''):
    marks = [m for m in get_bookmarks() if m.get('url') != url]
    marks.append({'title': title, 'url': url, 'image': image or '', 'added': int(time.time())})
    _save(_BOOKMARKS, marks[:_BOOKMARKS_CAP])


def unbookmark(url):
    _save(_BOOKMARKS, [m for m in get_bookmarks() if m.get('url') != url])


def get_watch_later():
    return _load(_WATCH_LATER, [])


def add_watch_later(entry):
    """Save a full video card in the local Watch Later list."""
    entry = dict(entry or {})
    video_id = entry.get('video_id') or entry.get('url') or ''
    if not video_id:
        return
    entry['video_id'] = video_id
    entry['added'] = int(time.time())
    items = [item for item in get_watch_later()
             if (item.get('video_id') or item.get('url')) != video_id]
    items.insert(0, entry)
    _save(_WATCH_LATER, items[:_WATCH_LATER_CAP])


def remove_watch_later(video_id):
    _save(_WATCH_LATER, [item for item in get_watch_later()
                          if (item.get('video_id') or item.get('url')) != video_id])


def clear_watch_later():
    _save(_WATCH_LATER, [])


def get_history():
    return _load(_HISTORY, [])


def add_history(entry):
    history = [h for h in get_history() if h.get('video_id') != entry.get('video_id')]
    entry['watched'] = int(time.time())
    history.insert(0, entry)
    _save(_HISTORY, history[:_HISTORY_CAP])


def clear_history():
    _save(_HISTORY, [])


def remove_history(video_id):
    _save(_HISTORY, [h for h in get_history() if h.get('video_id') != video_id])


def get_searches():
    return _load(_SEARCHES, [])


def add_search(query):
    query = (query or '').strip()
    if not query:
        return
    searches = [q for q in get_searches() if q != query]
    searches.insert(0, query)
    _save(_SEARCHES, searches[:_SEARCHES_CAP])


def remove_search(query):
    _save(_SEARCHES, [q for q in get_searches() if q != query])


def clear_searches():
    _save(_SEARCHES, [])
