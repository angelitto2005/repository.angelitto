import json
import os
import re
import time
import unicodedata
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
# Parsed copy of library.json, kept between reads and dropped when the file
# changes. It is the one file here that grows with the account and is read once
# per video while a listing is being completed.
_LIBRARY_CACHE = {'stamp': None, 'data': None}

_SEARCHES_CAP = 25
_HISTORY_CAP = 100
_SUBS_CAP = 2000
_BOOKMARKS_CAP = 200
_WATCH_LATER_CAP = 500


def _path(name):
    return os.path.join(PROFILE, name)


def _library_stamp():
    """Fingerprint of library.json, fine grained enough that a write a moment
    ago is always seen as a change."""
    try:
        info = os.stat(_path(_LIBRARY))
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _read(name, default):
    if name == _LIBRARY:
        # library.json is read once per video while a listing fills its
        # metadata, and it is close to a megabyte once the account has played
        # with it, so parsing it per call was costing seconds on every listing.
        # The parsed copy is kept and only thrown away when the file itself
        # changes, which also covers another addon process writing it.
        stamp = _library_stamp()
        if stamp is not None and _LIBRARY_CACHE['stamp'] == stamp \
                and _LIBRARY_CACHE['data'] is not None:
            return _LIBRARY_CACHE['data']
        payload = _read_uncached(name, default)
        _LIBRARY_CACHE['stamp'] = stamp
        _LIBRARY_CACHE['data'] = payload
        return payload
    return _read_uncached(name, default)


def _read_uncached(name, default):
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
    if name == _LIBRARY:
        # the copy on disk is now this payload, so keep the parsed one and let
        # the next read go through the cache instead of parsing again
        _LIBRARY_CACHE['data'] = payload
        _LIBRARY_CACHE['stamp'] = _library_stamp()


def _unlink(name):
    if name == _LIBRARY:
        _LIBRARY_CACHE['stamp'] = None
        _LIBRARY_CACHE['data'] = None
    try:
        os.remove(_path(name))
    except OSError:
        pass


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


def subscription(url):
    """The stored record for a channel url, matched on the same key as
    is_subscribed, so a different url form for the same channel still finds it.
    """
    key = _sub_key(url)
    for item in _read(_SUBS, []):
        if isinstance(item, dict) and _sub_key(item.get('url')) == key:
            return item
    return {}


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


def get_feed_full_cache(allow_stale=False):
    if _debug_no_cache():
        return {}
    data = _read_obj(_LIBRARY).get(_FEED_FULL_CACHE)
    if not allow_stale and not _feed_cache_valid(data):
        return {}
    entries = data.get('entries') if isinstance(data, dict) else None
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


# --------------------------------------------------------------- blocked names
# Two kinds of rule, because YouTube has no artist field at all: browse only
# says who uploaded a video. A "channel" rule hides every row of that channel,
# while an "artist" rule hides just the rows whose title names that artist, so a
# channel posting several artists keeps the rest. Both can be held for the same
# name - an artist who owns their channel should disappear from it and from
# everywhere else at the same time.
_BLOCKED = 'blocked_artists.json'
_BLOCKED_NAMES = 'blocked_names'   # only read once, to move old entries over
KIND_CHANNEL = 'channel'
KIND_ARTIST = 'artist'


def _name_key(value):
    """Comparison key for an artist or channel name.

    Has to survive the three ways the same name reaches us: the user types
    "tzanca uraganu" without accents, the listing row spells it with the
    comma-below letters, and a row may arrive with a legacy cedilla instead.
    So the text is decomposed, the combining marks dropped, then casefolded and
    squeezed - NFKC alone keeps them, because the comma-below capital has no
    canonical decomposition and casefold only turns it into the lowercase one.
    """
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text.casefold()).strip()


def _entry_kind(value):
    kind = str(value or '').strip().lower()
    return kind if kind in (KIND_CHANNEL, KIND_ARTIST) else KIND_CHANNEL


def _migrate_blocked():
    """Move a block list written into state.json into its own file."""
    raw = _read_obj(_STATE).get(_BLOCKED_NAMES)
    if raw is None:
        return False
    names = raw.get('names') if isinstance(raw, dict) else None
    if not names:
        state = _read_obj(_STATE)
        state.pop(_BLOCKED_NAMES, None)
        _write_obj(_STATE, state)
        return False
    _write_obj(_BLOCKED, raw)
    state = _read_obj(_STATE)
    state.pop(_BLOCKED_NAMES, None)
    _write_obj(_STATE, state)
    return True


def _blocked_by_kind():
    """{'channel': {key: label}, 'artist': {key: label}}.

    Reads both the nested layout it writes and the flat one from before the
    kinds existed ({key: label}), where every entry was a channel rule.
    """
    if not os.path.isfile(_path(_BLOCKED)):
        _migrate_blocked()
    raw = _read_obj(_BLOCKED)
    names = raw.get('names') if isinstance(raw, dict) else None
    out = {KIND_CHANNEL: {}, KIND_ARTIST: {}}
    if not isinstance(names, dict):
        return out
    nested = bool(names) and all(
        key in (KIND_CHANNEL, KIND_ARTIST) and isinstance(value, dict)
        for key, value in names.items())
    if nested:
        for kind in (KIND_CHANNEL, KIND_ARTIST):
            for key, label in (names.get(kind) or {}).items():
                clean = str(key or '').strip()
                if clean:
                    out[kind][clean] = str(label or clean).strip() or clean
        return out
    for key, value in names.items():
        clean = str(key or '').strip()
        if not clean:
            continue
        if isinstance(value, dict):
            kind = _entry_kind(value.get('kind'))
            label = str(value.get('label') or clean).strip() or clean
        elif isinstance(value, str):
            # written before the types existed: it was the channel rule
            kind = KIND_CHANNEL
            label = value.strip() or clean
        else:
            kind = _entry_kind(value)
            label = str(value).strip() or clean
        out[kind][clean] = label
    return out


def get_blocked_names():
    """{key: {'label', 'kind'}}, sorted by label for display."""
    flat = {}
    for kind, entries in _blocked_by_kind().items():
        for key, label in entries.items():
            flat['%s:%s' % (kind, key)] = {'label': label, 'kind': kind}
    return dict(sorted(flat.items(),
                       key=lambda pair: pair[1]['label'].casefold()))


def get_blocked_keys(kind=None):
    by_kind = _blocked_by_kind()
    if kind is None:
        return set(by_kind[KIND_CHANNEL]) | set(by_kind[KIND_ARTIST])
    return set(by_kind[_entry_kind(kind)])


def is_name_blocked(name, keys=None):
    key = _name_key(name)
    if not key:
        return False
    return key in (keys if keys is not None else get_blocked_keys())


def add_blocked_name(name, kind=KIND_CHANNEL):
    label = str(name or '').strip()
    key = _name_key(label)
    if not key:
        return False
    kind = _entry_kind(kind)
    by_kind = _blocked_by_kind()
    if key in by_kind[kind]:
        return False
    by_kind[kind][key] = label
    data = _read_obj(_BLOCKED)
    data['names'] = by_kind
    data['ts'] = int(time.time())
    _write_obj(_BLOCKED, data)
    return True


def remove_blocked_name(name, kind=None):
    """Drop a rule. With no kind the name is dropped for both."""
    key = _name_key(name)
    by_kind = _blocked_by_kind()
    if key not in by_kind[KIND_CHANNEL] and key not in by_kind[KIND_ARTIST]:
        return False
    if kind is not None:
        wanted = _entry_kind(kind)
        if key not in by_kind[wanted]:
            return False
        by_kind[wanted].pop(key, None)
    else:
        by_kind[KIND_CHANNEL].pop(key, None)
        by_kind[KIND_ARTIST].pop(key, None)
    data = _read_obj(_BLOCKED)
    if by_kind[KIND_CHANNEL] or by_kind[KIND_ARTIST]:
        data['names'] = by_kind
        data['ts'] = int(time.time())
    else:
        data.pop('names', None)
        if not data:
            _unlink(_BLOCKED)
            return True
    _write_obj(_BLOCKED, data)
    return True


def blocked_matches(entry, artist=None):
    """Which rules hide this row, as (kind, label) pairs.

    ``artist`` is the artist read off the title; the caller passes it because
    only it has the title, and passing it in keeps this free of parsing rules.
    """
    entry = entry or {}
    by_kind = _blocked_by_kind()
    if not (by_kind[KIND_CHANNEL] or by_kind[KIND_ARTIST]):
        return []
    hits = []
    channel_key = _name_key(entry.get('channel') or '')
    if channel_key and channel_key in by_kind[KIND_CHANNEL]:
        hits.append((KIND_CHANNEL, by_kind[KIND_CHANNEL][channel_key]))
    artist_key = _name_key(artist or '')
    if artist_key and artist_key in by_kind[KIND_ARTIST]:
        hits.append((KIND_ARTIST, by_kind[KIND_ARTIST][artist_key]))
    return hits


def clear_blocked_names():
    _unlink(_BLOCKED)
