# -*- coding: utf-8 -*-
"""Persistent native Kodi playlist state for NewPipe MOD Random music.

The clicked plugin card must finish before Kodi receives a new playlist.  A
short service-owned launch delay prevents Android from treating that original
card as a second media item.  Once launched, Kodi itself advances the playlist
without reopening the search window between tracks.
"""
from __future__ import absolute_import

import random
import time
from urllib.parse import urlencode

from . import storage

_POOL_NAME = 'random_music_pool'
_QUEUE_STATE = 'random_music_queue'
_PLAYLIST_SIZE = 50
_PLAYLIST_START_DELAY = 0.75


def _video_id(entry):
    value = str((entry or {}).get('video_id') or (entry or {}).get('url') or '').strip()
    return value[-11:] if len(value) >= 11 else value


def _normalise(entry):
    entry = dict(entry or {})
    video_id = _video_id(entry)
    if not video_id:
        return None
    return {
        'video_id': video_id,
        'url': video_id,
        'title': str(entry.get('title') or video_id),
        'image': str(entry.get('image') or ''),
        'profile': 'default',
    }


def _tracks_from_state(state):
    tracks = []
    for entry in (state or {}).get('tracks') or []:
        item = _normalise(entry)
        if item:
            tracks.append(item)
    return tracks


def _position(state, tracks):
    try:
        position = int((state or {}).get('position', -1))
    except (TypeError, ValueError):
        position = -1
    return position if 0 <= position < len(tracks) else -1


def save_pool(entries):
    """Save the current Random music result page as a local source pool."""
    unique = {}
    for entry in entries or []:
        item = _normalise(entry)
        if item and item['video_id'] not in unique:
            unique[item['video_id']] = item
    storage.set_local_library(_POOL_NAME, list(unique.values()))
    return len(unique)


def clear_queue():
    """Forget the add-on state without touching unrelated Kodi playlists."""
    storage.set_local_state(_QUEUE_STATE, {})


def is_playlist_active():
    return storage.get_local_state(_QUEUE_STATE).get('mode') == 'playlist_active'


def is_launch_pending():
    return storage.get_local_state(_QUEUE_STATE).get('mode') == 'playlist_pending'


def cancel():
    """Cancel only an active Random music native playlist."""
    state = storage.get_local_state(_QUEUE_STATE)
    active = bool(_tracks_from_state(state))
    mode = state.get('mode')
    clear_queue()
    if mode == 'playlist_active':
        try:
            import xbmc
            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        except Exception:
            pass
    return active


def queue_tracks():
    """Return the shuffled order currently owned by Random music."""
    return _tracks_from_state(storage.get_local_state(_QUEUE_STATE))


def queue_position():
    """Return the current native playlist position, with stored fallback."""
    state = storage.get_local_state(_QUEUE_STATE)
    tracks = _tracks_from_state(state)
    if state.get('mode') == 'playlist_active':
        try:
            import xbmc
            position = int(xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition())
            if 0 <= position < len(tracks):
                return position
        except Exception:
            pass
    return _position(state, tracks)


def next_after(position=None):
    """Return the next queued track for a position, if there is one."""
    state = storage.get_local_state(_QUEUE_STATE)
    tracks = _tracks_from_state(state)
    if position is None:
        position = queue_position()
    try:
        next_index = int(position) + 1
    except (TypeError, ValueError):
        return None
    if 0 <= next_index < len(tracks):
        return tracks[next_index]
    return None


def _ordered_tracks(video_id, pool, size=_PLAYLIST_SIZE):
    """Put the selected track first, then create a no-immediate-repeat shuffle."""
    current = str(video_id or '').strip()
    normalised = []
    seen = set()
    for entry in pool or []:
        item = _normalise(entry)
        if item and item['video_id'] not in seen:
            normalised.append(item)
            seen.add(item['video_id'])
    if not normalised:
        return []

    selected = next((item for item in normalised if item['video_id'] == current), None)
    if selected is None:
        return []

    chooser = random.SystemRandom()
    tracks = [selected]
    previous = selected['video_id']
    remaining = [item for item in normalised if item['video_id'] != previous]
    while remaining and len(tracks) < size:
        chooser.shuffle(remaining)
        for item in remaining:
            if item['video_id'] != previous:
                tracks.append(item)
                previous = item['video_id']
                if len(tracks) >= size:
                    break
        remaining = [item for item in normalised if item['video_id'] != previous]
    return tracks


def _plugin_url(item):
    return 'plugin://plugin.video.newpipe/?' + urlencode({
        'action': 'random_music_queue_play',
        'url': item['video_id'],
        'title': item['title'],
        'image': item.get('image', ''),
        'profile': item.get('profile', 'default'),
    })


def plugin_url(item):
    """Return the direct Kodi plugin URL for one native queue item."""
    return _plugin_url(item)


def start(video_id):
    """Arm one native playlist; the service starts it after this route exits."""
    tracks = _ordered_tracks(video_id, storage.get_local_library(_POOL_NAME))
    if len(tracks) < 2:
        return 0
    # Replacing a prior music session must never leave its entries behind.
    cancel()
    storage.set_local_state(_QUEUE_STATE, {
        'tracks': tracks,
        'position': 0,
        'mode': 'playlist_pending',
        'launch_at': time.time() + _PLAYLIST_START_DELAY,
    })
    return len(tracks)


def consume_playlist_start(now=None):
    """Claim a prepared playlist once the clicked plugin card has exited."""
    state = storage.get_local_state(_QUEUE_STATE)
    if state.get('mode') != 'playlist_pending':
        return None
    try:
        due = float(state.get('launch_at', 0))
    except (TypeError, ValueError):
        due = 0
    now = time.time() if now is None else float(now)
    if now < due:
        return None
    tracks = _tracks_from_state(state)
    if len(tracks) < 2:
        clear_queue()
        return None
    storage.set_local_state(_QUEUE_STATE, {
        'tracks': tracks,
        'position': 0,
        'mode': 'playlist_active',
        'started_at': now,
    })
    return tracks
