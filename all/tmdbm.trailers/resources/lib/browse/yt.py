import config

from . import charts, localization, rich
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


@cache_function(cache_duration(15), stale=True)
def _trending(query, limit, locale):
    localization.configure()
    raw = rich.search(localization.regional_category_query(query), limit=limit,
                      sort='relevance', results_type='video')
    return _dedupe(limit)(raw)


def trending_videos(query, limit=25):
    return _trending(query, limit, configure())


@cache_function(cache_duration(10), stale=True)
def _live(query, limit, locale):
    localization.configure()
    query = localization.regional_category_query(query)
    raw = rich.search(query, limit=limit * 3, sort='relevance',
                      results_type='video')
    entries = _dedupe(limit * 3)(raw)
    live = [entry for entry in entries if entry['is_live']]
    seen = {entry.get('video_id') for entry in live}
    fill = [entry for entry in entries
            if not entry.get('is_live')
            and 'live' in _title_text(entry).casefold()
            and entry.get('video_id') not in seen]
    combined = live + fill
    if len(combined) < limit:
        top_up = query if 'live' in query.casefold() else query + ' live'
        raw = rich.search(top_up, limit=limit * 3,
                          sort='relevance', results_type='video')
        for entry in _dedupe(limit * 3)(raw):
            if len(combined) >= limit:
                break
            vid = entry.get('video_id')
            if not vid or vid in seen:
                continue
            if entry.get('is_live') or 'live' in _title_text(entry).casefold():
                seen.add(vid)
                combined.append(entry)
    return combined[:limit]


def _title_text(entry):
    title = (entry or {}).get('title') or ''
    if isinstance(title, dict):
        runs = title.get('runs') or []
        title = ''.join(str(run.get('text') or '') for run in runs
                        if isinstance(run, dict)) or title.get('simpleText') or ''
    return str(title)


def live_videos(query, limit=25):
    return _live(query, limit, configure())


@cache_function(cache_duration(15), stale=True)
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


@cache_function(cache_duration(720))
def _channel_av(url, locale):
    localization.configure()
    from . import rich as _rich
    return _rich.channel_avatar(url) or ''


def channel_avatar(url):
    try:
        return _channel_av(url, configure())
    except Exception:
        return ''


@cache_function(cache_duration(720))
def _channel_hd(url, locale):
    localization.configure()
    from . import rich as _rich
    avatar, title = _rich.channel_header(url)
    return (avatar or '', title or '')


def channel_header(url):
    try:
        return _channel_hd(url, configure())
    except Exception:
        return '', ''


@cache_function(cache_duration(30))
@cache_function(cache_duration(15), stale=True)
def _playlist(playlist_id, limit, locale):
    localization.configure()
    entries = _dedupe(limit)(rich.playlist_videos(playlist_id, limit=limit))
    _remember_playlist_count(playlist_id)
    return entries


def _remember_playlist_count(playlist_id):
    """Keep the length YouTube states next to the playlist.

    Duplicate songs and rows the parser skips make the rows that arrive
    fewer than that number, so the Next page button follows the number
    instead of the rows: otherwise a long playlist ends without a way
    forward, which is how a 130 track playlist stopped at 50.
    """
    try:
        from browse.scrapetube import scrapetube as _scrapetube
        count = int(_scrapetube.PLAYLIST_VIDEO_COUNT.get(str(playlist_id)) or 0)
        if not count:
            return
        import store
        known = store.get_state('playlist_counts')
        if not isinstance(known, dict):
            known = {}
        key = str(playlist_id)
        if int(known.get(key) or 0) == count:
            return
        known[key] = count
        store.set_state('playlist_counts', known)
    except Exception:
        pass


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


def chart_sections():
    return charts.chart_sections(localization.content_country())


def chart_tracks(playlist_id, limit=100):
    return charts.chart_tracks(playlist_id, limit=limit)


def chart_artists():
    return charts.chart_artists(localization.content_country())


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