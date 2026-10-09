import config

from . import localization, rich
from .constants import cache_duration, cache_function


def configure():
    return localization.configure()


def _dedupe(limit):
    def build(items):
        seen = set()
        out = []
        for raw in items:
            entry = rich.video(raw)
            vid = entry['video_id']
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append(entry)
            if len(out) >= limit:
                break
        return out
    return build


@cache_function(cache_duration(15))
def _search(query, limit, sort, results_type, locale):
    localization.configure()
    raw = rich.search(query, limit=limit, sort=sort, results_type=results_type)
    config.debug('search query="{}" sort={} type={} locale={} got={}'.format(
        query, sort, results_type, locale, len(raw)))
    if results_type == 'channel':
        return [rich.channel(item) for item in raw]
    if results_type == 'playlist':
        return [rich.playlist(item) for item in raw]
    return _dedupe(limit)(raw)


def search_videos(query, limit=25, sort='relevance'):
    return _search(query, limit, sort, 'video', configure())


def search_channels(query, limit=25):
    return _search(query, limit, 'relevance', 'channel', configure())


def search_playlists(query, limit=25):
    return _search(query, limit, 'relevance', 'playlist', configure())


@cache_function(cache_duration(15))
def _trending(query, limit, locale):
    localization.configure()
    raw = rich.search(localization.regional_category_query(query), limit=limit,
                      sort='relevance', results_type='video')
    return _dedupe(limit)(raw)


def trending_videos(query, limit=25):
    return _trending(query, limit, configure())


@cache_function(cache_duration(10))
def _live(query, limit, locale):
    localization.configure()
    query = localization.regional_category_query(query)
    raw = rich.search(query, limit=limit * 3, sort='relevance',
                      results_type='video')
    entries = _dedupe(limit * 3)(raw)
    live = [entry for entry in entries if entry['is_live']]
    if live:
        return live[:limit]
    return _dedupe(limit)(rich.search(query + ' live', limit=limit,
                                      sort='relevance', results_type='video'))


def live_videos(query, limit=25):
    return _live(query, limit, configure())


@cache_function(cache_duration(15))
def _trailers(query, limit, locale):
    localization.configure()
    return _dedupe(limit)(rich.search(query, limit=limit, sort='upload_date',
                                      results_type='video'))


def trailer_videos(query, limit=25):
    return _trailers(query, limit, configure())


@cache_function(cache_duration(30))
def _channel(url, tab, limit, locale):
    localization.configure()
    return _dedupe(limit)(rich.channel_videos(url, tab=tab, limit=limit))


def channel_videos(url, tab='videos', limit=25):
    return _channel(url, tab, limit, configure())


@cache_function(cache_duration(60))
def _channel_pl(url, limit, locale):
    localization.configure()
    return [rich.playlist(item)
            for item in rich.channel_playlists(url, limit=limit)]


def channel_playlists(url, limit=25):
    return _channel_pl(url, limit, configure())


@cache_function(cache_duration(30))
def _playlist(playlist_id, limit, locale):
    localization.configure()
    return _dedupe(limit)(rich.playlist_videos(playlist_id, limit=limit))


def playlist_videos(playlist_id, limit=50):
    return _playlist(playlist_id, limit, configure())