# -*- coding: utf-8 -*-
# Scrapetube wrapper for Kodi
# SPDX-License-Identifier: GPL-3.0
# See LICENSES/GPL-3.0 for more information.

from __future__ import absolute_import
from .scrapetube import get_videos, get_channel, get_playlist, get_search

YT_ADDON_ID = 'plugin.video.youtube'
YT_ADDON = 'plugin://{0}'.format(YT_ADDON_ID)
YT_ADDON = ''.join([YT_ADDON, '/play/?video_id={0}'])
YT_PREFIX = 'https://www.youtube.com/watch?v={0}'


def duration_converter(duration):

    """
    Converts duration in string (minutes:seconds) to integer in seconds.
    Tolerant: returns 0 for live streams, Shorts without duration,
    missing values or unparseable strings (previously raised).
    Handles H:MM:SS, M:SS and plain seconds.
    """

    if duration is None:
        return 0

    if not isinstance(duration, str):
        try:
            return int(duration)
        except (TypeError, ValueError):
            return 0

    text = duration.strip().upper()
    if not text or text in ('LIVE', 'SHORTS', 'UPCOMING', 'PREMIERE'):
        return 0

    # Strip trailing badges YouTube sometimes appends, e.g. "12:34 • LIVE"
    text = text.split('•')[0].strip()

    try:
        parts = [int(p) for p in text.split(':')]
    except ValueError:
        return 0

    if not parts:
        return 0

    total = 0
    for part in parts:
        total = total * 60 + part

    return total


def _get_title(item):

    """Best-effort title extraction across old and new YouTube shapes."""

    if not isinstance(item, dict):
        return ''

    # Added by the merged scrapetube core, always a plain string.
    title_text = item.get('title_text')
    if isinstance(title_text, str) and title_text:
        return title_text

    title = item.get('title')
    if isinstance(title, str) and title:
        return title

    if isinstance(title, dict):
        simple = title.get('simpleText')
        if isinstance(simple, str) and simple:
            return simple
        try:
            runs = title.get('runs') or []
            if runs and isinstance(runs[0], dict):
                text = runs[0].get('text')
                if isinstance(text, str):
                    return text
        except (AttributeError, IndexError, KeyError, TypeError):
            pass

    return ''


def _get_thumbnail(item, thumb_quality=-1):

    """Best-effort thumbnail extraction, '' when unavailable."""

    try:
        thumbs = item.get('thumbnail', {}).get('thumbnails') or []
        if thumbs:
            return thumbs[thumb_quality]['url']
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    try:
        thumbs = item.get('thumbnail', {}).get('thumbnails') or []
        if thumbs:
            return thumbs[-1]['url']
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    return ''


def _get_duration_text(item):

    """Best-effort duration label extraction across renderer shapes."""

    try:
        overlays = item.get('thumbnailOverlays') or []
        if overlays:
            return overlays[0]['thumbnailOverlayTimeStatusRenderer']['text']['simpleText']
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    length = item.get('lengthText')
    if isinstance(length, dict):
        simple = length.get('simpleText')
        if isinstance(simple, str):
            return simple

    return ''


def _build_video_dict(item, add_prefix=True, thumb_quality=-1, add_url=YT_PREFIX):

    video_id = item.get('videoId', '')

    return dict(
        title=_get_title(item),
        url=add_url.format(video_id) if add_prefix else video_id,
        image=_get_thumbnail(item, thumb_quality),
        duration=duration_converter(_get_duration_text(item)),
        is_live=bool(item.get('is_live', False)),
    )


def _build_playlist_dict(item):

    return dict(
        title=_get_title(item),
        url=item.get('playlistId', ''),
        image=_get_thumbnail(item, 0),
    )


def list_channel_videos(
    channel_id=None, channel_url=None, limit=None, sleep=1, sort_by="newest",
    content_type="videos", add_prefix=True, thumb_quality=-1, add_url=YT_PREFIX,
    proxies=None, cookies=None
):

    items_list = list(get_channel(
        channel_id=channel_id, channel_url=channel_url, limit=limit,
        sleep=sleep, sort_by=sort_by, content_type=content_type,
        proxies=proxies, cookies=cookies,
    ))

    items_list = [
        _build_video_dict(i, add_prefix, thumb_quality, add_url)
        for i in items_list
    ]

    return items_list


def list_playlists(
    url, api='https://www.youtube.com/youtubei/v1/browse', renderer='gridPlaylistRenderer', limit=None, sleep=1
):

    items_list = list(get_videos(url, api, "contents", renderer, limit, sleep))

    items_list = [
        _build_playlist_dict(i) for i in items_list
    ]

    return items_list


def list_playlist_videos(url, limit=None, sleep=1, add_prefix=True, thumb_quality=-1, add_url=YT_PREFIX, cookies=None):

    items_list = list(get_playlist(url, limit, sleep, cookies=cookies))

    items_list = [
        _build_video_dict(i, add_prefix, thumb_quality, add_url)
        for i in items_list
        ]

    return items_list


def list_search(
    query, limit=None, sleep=1, sort_by="relevance", results_type="video", add_prefix=True, thumb_quality=-1, add_url=YT_PREFIX, cookies=None
):

    items_list = list(get_search(query, limit, sleep, sort_by, results_type, cookies=cookies))

    if results_type == 'video':

        items_list = [
        _build_video_dict(i, add_prefix, thumb_quality, add_url)
        for i in items_list
        ]

        return items_list

    elif results_type == 'playlist':

        items_list = [
        _build_playlist_dict(i) for i in items_list
    ]

        return items_list

    else:

        return
