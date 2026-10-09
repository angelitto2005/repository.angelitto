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
    entries = _playlist(playlist_id, limit, configure())
    if entries:
        _unmark_private_playlist(playlist_id)
        return entries
    entries = _authed_playlist_videos(playlist_id, limit)
    if entries:
        _mark_private_playlist(playlist_id)
    return entries


def _playlist_privacy():
    try:
        import store
        return store.get_state('playlist_privacy')
    except Exception:
        return {}


def _mark_private_playlist(playlist_id):
    try:
        import store
        privacy = store.get_state('playlist_privacy')
        if playlist_id and playlist_id not in privacy:
            privacy[str(playlist_id)] = 'private'
            store.set_state('playlist_privacy', privacy)
    except Exception:
        pass


def _unmark_private_playlist(playlist_id):
    try:
        import store
        privacy = store.get_state('playlist_privacy')
        if str(playlist_id) in privacy:
            del privacy[str(playlist_id)]
            store.set_state('playlist_privacy', privacy)
    except Exception:
        pass


def is_private_playlist(playlist_id):
    return bool(_playlist_privacy().get(str(playlist_id or '')))


def _authed_playlist_videos(playlist_id, limit=50):
    try:
        from account import youtube_sync
        if not youtube_sync.status().get('connected'):
            return []
        token = youtube_sync.access_token()
        entries = []
        seen = set()
        continuation = ''
        for _ in range(10):
            if continuation:
                response = youtube_sync._tv_request(
                    token, youtube_sync._TV_BROWSE_URL, '',
                    extra={'continuation': continuation})
            else:
                response = youtube_sync._browse(
                    token, 'VL' + str(playlist_id), '')
            for entry in youtube_sync._videos(response):
                vid = entry.get('video_id')
                if vid and vid not in seen:
                    seen.add(vid)
                    entries.append(entry)
                    if len(entries) >= limit:
                        return entries
            nxt = youtube_sync.playlist_continuation(response)
            if not nxt or nxt == continuation:
                break
            continuation = nxt
        return entries
    except Exception as exc:
        config.log('authed playlist failed: {}'.format(str(exc)[:120]))
        return []