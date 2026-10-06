# -*- coding: utf-8 -*-
# NewPipe Addon
# Author Twilight0
# SPDX-License-Identifier: GPL-3.0-only
#
# Browsing uses Scrapetube page scraping, with no API key or account. Results
# are cache-keyed by language/country. Video listings deliberately perform one
# YouTube request chain only: prior builds fetched each page twice merely to add
# a channel context-menu link, which made page changes unnecessarily slow.
from scrapetube.wrapper import (
    list_search,
    list_channel_videos,
    list_playlist_videos,
    list_playlists,
)

from .constants import cache_function, cache_duration
from . import localization


def configure():
    """Set the NewPipe-style YouTube content locale for the current request."""
    return localization.configure()


@cache_function(cache_duration(15))
def _search(query, limit=25, sort='relevance', locale='pt:BR'):
    localization.configure()
    return list_search(query, limit=limit, sleep=0, sort_by=sort) or []


def search(query, limit=25, sort='relevance'):
    return _search(query, limit=limit, sort=sort, locale=configure())


def _video_results(query, limit, sort, locale):
    """Return Kodi video tuples after one scraping pass, without duplicate cards."""
    seen_video_ids = set()
    results = []
    for item in _search(query, limit=limit, sort=sort, locale=locale):
        video_id = (item.get('url') or '')[-11:]
        if not video_id or video_id in seen_video_ids:
            continue
        seen_video_ids.add(video_id)
        # The channel URL used only for a context-menu shortcut. Avoiding a
        # second raw YouTube query has a far larger benefit for page latency.
        results.append((item, '', ''))
        if len(results) >= limit:
            break
    return results


@cache_function(cache_duration(15))
def _search_videos(query, limit=25, sort='relevance', locale='pt:BR'):
    return _video_results(query, limit, sort, locale)


def search_videos(query, limit=25, sort='relevance'):
    return _search_videos(query, limit=limit, sort=sort, locale=configure())


@cache_function(cache_duration(15))
def _search_playlists(query, limit=25, locale='pt:BR'):
    localization.configure()
    return list_search(query, limit=limit, sleep=0, results_type='playlist') or []


def search_playlists(query, limit=25):
    return _search_playlists(query, limit=limit, locale=configure())


@cache_function(cache_duration(15))
def _trending_videos(query, limit=25, locale='pt:BR'):
    # YouTube's legacy combined trending feed is no longer reliable. Do not
    # emulate it with global view-count sorting: that turns "Music" into a
    # list dominated by the largest unrelated markets. Use the localized
    # category query with relevance under the configured hl/gl locale.
    return _video_results(
        localization.regional_category_query(query), limit, 'relevance', locale)


def trending_videos(query, limit=25):
    return _trending_videos(query, limit=limit, locale=configure())


@cache_function(cache_duration(10))
def _live_videos(query, limit=25, locale='pt:BR'):
    return _video_results(
        localization.regional_category_query(query), limit, 'relevance', locale)


def live_videos(query, limit=25):
    return _live_videos(query, limit=limit, locale=configure())


@cache_function(cache_duration(15))
def _trailer_videos(query, limit=25, locale='pt:BR'):
    # Trailer language is expressed in the query itself. Do not append the
    # configured country suffix used for broad Trending categories.
    return _video_results(query, limit, 'relevance', locale)


def trailer_videos(query, limit=25):
    return _trailer_videos(query, limit=limit, locale=configure())


@cache_function(cache_duration(30))
def _channel_videos(url, tab='videos', limit=25, locale='pt:BR'):
    localization.configure()
    return list_channel_videos(channel_url=url, limit=limit, sleep=0, content_type=tab)


def channel_videos(url, tab='videos', limit=25):
    return _channel_videos(url, tab=tab, limit=limit, locale=configure())


@cache_function(cache_duration(60))
def _channel_playlists(url, limit=25, locale='pt:BR'):
    localization.configure()
    return list_playlists(url.rstrip('/') + '/playlists', limit=limit, sleep=0)


def channel_playlists(url, limit=25):
    return _channel_playlists(url, limit=limit, locale=configure())


@cache_function(cache_duration(30))
def _playlist_videos(playlist_id, limit=50, locale='pt:BR'):
    localization.configure()
    return list_playlist_videos(playlist_id, limit=limit, sleep=0)


def playlist_videos(playlist_id, limit=50):
    return _playlist_videos(playlist_id, limit=limit, locale=configure())
