import random
import time

import xbmc

import store

_POOL_KEY = 'music_pool'
_QUEUE_KEY = 'active_queue'
_BLOCKED_KEY = 'blocked'
_MUSIC_SIZE = 50
_RELATED_SIZE = 20


def _compact(entry):
    return {
        'video_id': str(entry.get('video_id') or ''),
        'title': entry.get('title') or '',
        'image': entry.get('image') or '',
        'duration': int(entry.get('duration') or 0),
        'is_live': bool(entry.get('is_live')),
        'channel': entry.get('channel') or '',
        'channel_id': entry.get('channel_id') or '',
        'views': entry.get('views') or '',
        'vdate': entry.get('vdate') or entry.get('published') or '',
        'snippet': entry.get('snippet') or '',
    }


def save_pool(entries):
    unique = {}
    for entry in entries or []:
        item = _compact(entry)
        if item['video_id'] and item['video_id'] not in unique:
            unique[item['video_id']] = item
    store.set_library(_POOL_KEY, list(unique.values()))
    return len(unique)


def pool():
    return store.get_library(_POOL_KEY)


def block(video_id):
    state = store.get_state(_BLOCKED_KEY)
    ids = state.get('ids') or []
    if video_id and video_id not in ids:
        ids.append(video_id)
        store.set_state(_BLOCKED_KEY, {'ids': ids, 'ts': time.time()})


def blocked():
    return set(store.get_state(_BLOCKED_KEY).get('ids') or [])


def top_up_pool(anchor, limit=40):
    """Grow a thin pool with fresh music from the same artist."""
    from browse import yt
    from music import detect

    anchor = anchor or {}
    raw = []
    channel_id = str(anchor.get('channel_id') or '')
    if channel_id:
        try:
            raw = yt.channel_videos(
                'https://www.youtube.com/channel/' + channel_id,
                'videos', limit=limit)
        except Exception as exc:
            xbmc.log('[tmdbm.trailers] channel top-up failed: {}'.format(
                str(exc)[:100]), xbmc.LOGWARNING)
            raw = []
    if not raw:
        seed = str(anchor.get('channel') or anchor.get('title') or '').strip()
        if not seed:
            return []
        try:
            raw = yt.search_videos('{} official video'.format(seed), limit=limit)
        except Exception as exc:
            xbmc.log('[tmdbm.trailers] search top-up failed: {}'.format(
                str(exc)[:100]), xbmc.LOGWARNING)
            return []
    skip = blocked()
    fresh = [item for item in raw
             if detect.looks_like_music(item, anchor.get('channel') or '')
             and item.get('video_id') and item['video_id'] not in skip]
    if not fresh:
        return []
    save_pool(pool() + fresh)
    xbmc.log('[tmdbm.trailers] music pool topped up with {} tracks'.format(
        len(fresh)))
    return fresh


def _available(video_id, entry=None, size=_MUSIC_SIZE):
    skip = blocked()

    def usable():
        return [item for item in pool()
                if item['video_id'] != video_id and item['video_id'] not in skip]

    source = usable()
    for _ in range(2):
        if len(source) >= size:
            break
        anchor = next((item for item in source
                       if item.get('channel_id') or item.get('channel')), None)
        if anchor is None and entry:
            anchor = _compact(entry)
        if not anchor or not top_up_pool(anchor):
            break
        source = usable()
    return source


def build_music_queue(video_id, size=_MUSIC_SIZE, entry=None):
    video_id = str(video_id or '')
    source = _available(video_id, entry, size)
    selected = next((item for item in pool() if item['video_id'] == video_id),
                    None)
    if selected is None:
        seed = _compact(entry or {})
        if not seed['video_id'] or seed['video_id'] != video_id:
            return []
        selected = seed
        top_up_pool(seed)
        source = _available(video_id, entry, size)
        if not any(item['video_id'] == video_id for item in source):
            source = [selected] + source
    chooser = random.SystemRandom()
    tracks = [selected]
    chosen = {selected['video_id']}
    remaining = [item for item in source if item['video_id'] not in chosen]
    while remaining and len(tracks) < size:
        chooser.shuffle(remaining)
        pick = next((item for item in remaining
                     if item['video_id'] not in chosen), None)
        if pick is None:
            break
        tracks.append(pick)
        chosen.add(pick['video_id'])
        remaining = [item for item in remaining if item['video_id'] not in chosen]
    return tracks


def build_context_queue(video_id):
    """The videos that follow the pressed one in the list the user browsed.

    Returns (tracks, found). When found is True the queue is exactly that
    list, in that order - nothing else is added.
    """
    import lists
    video_id = str(video_id or '')
    entries = lists.context_entries()
    if not video_id or not entries:
        return [], False
    ids = [item.get('video_id') for item in entries]
    if video_id not in ids:
        return [], False
    index = ids.index(video_id)
    rest = [_compact(item) for item in entries[index + 1:]]
    return [item for item in rest if item['video_id'] not in blocked()], True


def build_related_queue(video_id, size=_RELATED_SIZE):
    from browse import meta
    skip = blocked()
    entries = [item for item in meta.related(video_id, limit=size + 5)
               if item['video_id'] not in skip]
    return entries[:size]


def set_active(tracks, kind='music', pos=0, listing=None):
    store.set_state(_QUEUE_KEY, {
        'kind': kind,
        'tracks': [_compact(track) for track in tracks or []],
        'pos': int(pos),
        'started': time.time(),
        'mode': 'active',
        'listing': dict(listing or {}),
        'exhausted': False,
    })


def set_pending(tracks, kind='music', listing=None):
    store.set_state(_QUEUE_KEY, {
        'kind': kind,
        'tracks': [_compact(track) for track in tracks or []],
        'pos': 0,
        'started': time.time(),
        'mode': 'pending',
        'launch_at': time.time() + 0.4,
        'listing': dict(listing or {}),
        'exhausted': False,
    })


def consume_pending(now=None):
    state = active()
    if state.get('mode') != 'pending':
        return None
    try:
        due = float(state.get('launch_at', 0))
    except (TypeError, ValueError):
        due = 0
    now = time.time() if now is None else float(now)
    if now < due:
        return None
    tracks = [track for track in state.get('tracks') or []
              if isinstance(track, dict) and track.get('video_id')]
    if len(tracks) < 2:
        clear()
        return None
    state['mode'] = 'active'
    store.set_state(_QUEUE_KEY, state)
    return tracks


def _tail_split(started):
    state = active()
    if not state.get('tracks') or state.get('mode') != 'active':
        return None, None, None
    if state.get('started') != started:
        return None, None, None
    try:
        pos = int(state.get('pos') or 0)
    except (TypeError, ValueError):
        return None, None, None
    tracks = state.get('tracks') or []
    if pos < 0 or pos + 1 >= len(tracks):
        return None, None, None
    return state, pos, tracks[pos + 1:]


def reshuffle_tail(started):
    split = _tail_split(started)
    state, pos, tail = split
    if not tail or len(tail) < 2:
        return None
    random.SystemRandom().shuffle(tail)
    state['tracks'] = state['tracks'][:pos + 1] + tail
    store.set_state(_QUEUE_KEY, state)
    return tail


def reorder_tail(started, order_ids):
    split = _tail_split(started)
    state, pos, tail = split
    if not tail:
        return None
    by_id = {}
    for track in tail:
        by_id.setdefault(track.get('video_id'), track)
    new_tail = [by_id[vid] for vid in (order_ids or []) if vid in by_id]
    have = {track.get('video_id') for track in new_tail}
    new_tail += [track for track in tail if track.get('video_id') not in have]
    if [track.get('video_id') for track in new_tail] == [track.get('video_id') for track in tail]:
        return None
    state['tracks'] = state['tracks'][:pos + 1] + new_tail
    store.set_state(_QUEUE_KEY, state)
    return new_tail


def set_position(pos):
    state = active()
    if not state.get('tracks'):
        return
    try:
        pos = int(pos)
    except (TypeError, ValueError):
        return
    if pos != state.get('pos'):
        state['pos'] = pos
        store.set_state(_QUEUE_KEY, state)


def extend_tracks(entries, started):
    state = active()
    if not state.get('tracks') or state.get('mode') != 'active':
        return []
    if state.get('started') != started or state.get('exhausted'):
        return []
    seen = {track.get('video_id') for track in state['tracks']}
    seen |= blocked()
    fresh = []
    for entry in entries or []:
        item = _compact(entry)
        if item['video_id'] and item['video_id'] not in seen:
            seen.add(item['video_id'])
            fresh.append(item)
    if not fresh:
        state['exhausted'] = True
    else:
        state['tracks'] = state['tracks'] + fresh
        listing = state.get('listing') or {}
        try:
            listing['page'] = int(listing.get('page') or 1) + 1
        except (TypeError, ValueError):
            listing['page'] = 2
        state['listing'] = listing
    store.set_state(_QUEUE_KEY, state)
    return fresh


def active():
    return store.get_state(_QUEUE_KEY)


def active_tracks():
    return active().get('tracks') or []


def is_active():
    return bool(active_tracks())


def clear_state():
    store.set_state(_QUEUE_KEY, {})


def clear():
    had = bool(active_tracks())
    clear_state()
    if had:
        try:
            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        except Exception:
            pass


def cancel():
    had = bool(active_tracks())
    mode = active().get('mode')
    clear_state()
    if had and mode == 'active':
        try:
            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        except Exception:
            pass
    return had


def position():
    """Index of the track that is playing, tracked by us, not guessed."""
    state = active()
    tracks = state.get('tracks') or []
    if not tracks:
        return -1
    try:
        pos = int(state.get('pos') or 0)
    except (TypeError, ValueError):
        pos = 0
    return pos if 0 <= pos < len(tracks) else 0


def advance():
    """Move to the next track and return it, refilling from the same pool."""
    state = active()
    kind = state.get('kind') or 'music'
    tracks = state.get('tracks') or []
    if not tracks:
        return None
    index = position() + 1
    if index >= len(tracks):
        extra = refetch_remaining(kind)
        if extra:
            tracks = tracks + extra
            state['tracks'] = [_compact(track) for track in tracks]
        else:
            clear()
            return None
    state['pos'] = index
    store.set_state(_QUEUE_KEY, state)
    return tracks[index]


def next_after(index=None):
    tracks = active_tracks()
    if not tracks:
        return None
    current = position() if index is None else index
    try:
        current = int(current)
    except (TypeError, ValueError):
        return None
    if 0 <= current + 1 < len(tracks):
        return tracks[current + 1]
    return None


def refetch_remaining(kind='music', size=None):
    """Rebuild the tail of a music queue once the previous one is exhausted."""
    if kind != 'music':
        return []
    tracks = active_tracks()
    size = size or _MUSIC_SIZE
    played = {track.get('video_id') for track in tracks}
    source = [item for item in pool()
              if item['video_id'] not in played and item['video_id'] not in blocked()]
    if len(source) < 10:
        anchor = None
        index = position()
        if 0 <= index < len(tracks):
            anchor = tracks[index]
        elif tracks:
            anchor = tracks[-1]
        if anchor:
            top_up_pool(anchor)
            source = [item for item in pool()
                      if item['video_id'] not in played
                      and item['video_id'] not in blocked()]
    if not source:
        return []
    chooser = random.SystemRandom()
    chooser.shuffle(source)
    return source[:size]