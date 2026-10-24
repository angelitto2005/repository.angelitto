import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import xbmc
import xbmcgui
import xbmcplugin

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import config

ADDON_ID = config.ADDON_ID
BASE_URL = 'plugin://{}/'.format(ADDON_ID)

_ROUTES = {}
_ROOT_ITEMS = []
_SLOW_LISTING = 1.5      # seconds before a listing is worth a log line


def route(name):
    def decorator(func):
        _ROUTES[name] = func
        return func
    return decorator


def add_root(label, mode, image='', folder=True):
    _ROOT_ITEMS.append((label, mode, image, folder))


def build(handle, items, content='videos', cache=False):
    """Listings are not kept in Kodi's on-disk directory cache.

    A context menu is baked into the ListItem when the row is built, so a
    cached directory keeps showing "Subscribe" for a channel you just joined
    (or "Unblock" for a video you just unblocked) until Kodi drops the cache
    by itself. The data itself is already cached here - browse.yt keeps every
    listing in a pickle cache for 10-15 min - so re-running the plugin only
    costs the render, and every menu then matches the current state.
    """
    if handle <= 0:
        return
    if content:
        xbmcplugin.setContent(handle, content)
    if items:
        xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=cache)


def finish(handle, update=False):
    if handle <= 0:
        return
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=update)


def cancel(handle):
    if handle <= 0:
        return
    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())


def dispatch(handle, mode, params):
    handler = _ROUTES.get(mode)
    if not handler:
        config.log('Unknown route: {}'.format(mode), xbmc.LOGWARNING)
        finish(handle)
        return
    import time as _time
    _started = _time.time()
    try:
        handler(handle, params)
    except Exception as exc:
        import traceback
        config.log('Route {} failed: {}'.format(mode, exc), xbmc.LOGERROR)
        config.log(traceback.format_exc(), xbmc.LOGERROR)
        finish(handle)
    finally:
        # Only the slow ones, and always written: a listing that took seconds
        # was a cache miss or a slow answer from YouTube, and that is exactly
        # what is invisible with detailed logging off.
        _spent = _time.time() - _started
        if _spent >= _SLOW_LISTING:
            config.log('{} took {:.1f}s (cache expired or slow network)'.format(
                mode, _spent), always=True)


def _page(params):
    try:
        return max(1, int(params.get('page') or 1))
    except (TypeError, ValueError):
        return 1


def _merge_remote(local_entries, remote_entries):
    merged = []
    seen = set()
    for entry in list(local_entries or []) + list(remote_entries or []):
        vid = (entry or {}).get('video_id') or (entry or {}).get('url') or ''
        if vid and vid not in seen:
            seen.add(vid)
            merged.append(entry)
    return merged


# --------------------------------------------------------------------------- root
@route('root')
def root(handle, params):
    import lists
    _build_roots()
    items = []
    for label, mode, image, folder in _ROOT_ITEMS:
        url, li, is_folder = lists.folder_item(label, mode, image,
                                               folder=folder)
        items.append((url, li, is_folder))
    build(handle, items, content=None, cache=False)


@route('open_settings')
def open_settings(handle, params):
    config.ADDON.openSettings()


# ----------------------------------------------------------------- diagnostics
@route('netcheck')
def netcheck(handle, params):
    """Network/TLS identity report for this device (resources/lib/netcheck.py).

    Logs every line and shows the report in a text viewer, so the same report
    can be collected from a Windows PC and from an Android box and diffed - the
    "not a bot" gate is per egress IP, and two devices in one house rarely share
    one. Run it on a headless box from a PC (webserver enabled):

    Files.GetDirectory on
    plugin://plugin.video.tmdbm.trailers/?mode=netcheck  (add &video=<id>
    to also send one player API request and see the playabilityStatus).
    """
    import netcheck as _netcheck
    report = _netcheck.run(api_video=params.get('video') or params.get('api'))
    try:
        xbmcgui.Dialog().textviewer('TMDbM Trailers - netcheck', report)
    except Exception:
        pass
    finish(handle)


# ------------------------------------------------------------------------ search
@route('search')
def search(handle, params):
    import lists
    import store
    prefill = str(params.get('q') or '').strip()
    items = []
    if prefill:
        items.append(lists.action_item(
            config.T(32113), 'search_input', config.icon('search'),
            {'q': prefill},
            config.T(32181).format(prefill), folder=False))
        items.append(lists.action_item(
            config.T(32114), 'search_input', config.icon('search'), {},
            folder=False))
    else:
        items.append(lists.action_item(
            config.T(32112), 'search_input', config.icon('search'), {},
            folder=False))
    for query in store.get_searches():
        items.append(lists.folder_item(
            query, 'search_types',
            config.icon('trailers') or config.addon_icon() or config.icon('search'),
            {'q': query},
            cm=[('[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32115)),
                 lists.run_plugin('forget_search', {'q': query}))][0:3]))
    if store.get_searches():
        items.append(lists.action_item(
            '[COLOR FFFF5555]{}[/COLOR]'.format(config.T(32116)), 'clear_searches',
            config.icon('history')))
    build(handle, items, content=None)


@route('search_input')
def search_input(handle, params):
    import store
    default = str(params.get('q') or '')
    query = xbmcgui.Dialog().input(config.T(32112), default,
                                    type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
    store.add_search(query)
    target = BASE_URL + '?' + urlencode({'mode': 'search_types', 'q': query})
    xbmc.executebuiltin('Container.Update({})'.format(target))


@route('forget_search')
def forget_search(handle, params):
    import store
    store.remove_search(params.get('q'))
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('clear_searches')
def clear_searches(handle, params):
    import store
    store.clear_searches()
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('search_types')
def search_types(handle, params):
    import lists
    query = params.get('q') or ''
    items = [
        lists.folder_item(config.T(32117), 'search_results',
                          config.icon('videos'), {'q': query, 'kind': 'video'}),
        lists.folder_item(config.T(32118), 'search_results',
                          config.icon('subscribedch'),
                          {'q': query, 'kind': 'channel'}),
        lists.folder_item(config.T(32119), 'search_results',
                          config.icon('playlists'),
                          {'q': query, 'kind': 'playlist'}),
        lists.folder_item(config.T(32104), 'search_results',
                          config.icon('trailers'),
                          {'q': query, 'kind': 'trailer'}),
    ]
    build(handle, [item[0:3] for item in items], content=None)


@route('search_results')
def search_results(handle, params):
    import lists
    from browse import constants, localization, yt
    from music import detect
    query = str(params.get('q') or '').strip()
    kind = params.get('kind') or 'video'
    page = _page(params)
    per_page = constants.results_per_page()

    if kind == 'channel':
        def fetch(limit):
            return yt.search_channels(query, limit=limit)
        items, content = lists.paged(
            fetch, lambda entry: lists.folder_item(
                entry['title'] or entry['channel_id'], 'channel',
                entry['image'], {'url': 'https://www.youtube.com/channel/' +
                                 entry['channel_id'],
                                 'title': entry.get('title') or '',
                                 'image': entry.get('image') or ''},
                description=' '.join(x for x in (entry['subs'], entry['count']) if x)),
            'search_results', {'q': query, 'kind': 'channel'}, page=page)
    elif kind == 'playlist':
        def fetch(limit):
            return yt.search_playlists(query, limit=limit)

        def _pl_builder(entry):
            entry = entry or {}
            if not entry.get('playlist_id'):
                return None
            _title = (lists.clean_title(entry.get('title') or '')
                      or entry.get('title') or '')
            return lists.folder_item(
                _title, 'playlist', entry['image'],
                {'url': entry['playlist_id']},
                description=' '.join(x for x in (entry['channel'], entry['count']) if x),
                cm=[('[B][COLOR FF00CED1]Import playlist[/COLOR][/B]',
                     lists.run_plugin('local_playlist_import',
                                      {'pid': entry['playlist_id'],
                                       'title': _title}))])

        items, content = lists.paged(
            fetch, _pl_builder,
            'search_results', {'q': query, 'kind': 'playlist'}, page=page)
    elif kind == 'trailer':
        search_query = '{} {}'.format(query, localization.trailer_query()).strip()
        def fetch(limit):
            return yt.trailer_videos(search_query, limit=limit)
        items, content = lists.paged(
            fetch, lambda entry: lists.video_item(entry, 'play'),
            'search_results', {'q': query, 'kind': 'trailer'}, page=page)
    else:
        requested = page * per_page + 1
        try:
            entries = yt.search_videos(query, limit=requested)
        except Exception as exc:
            config.log('search_results page {} failed: {}'.format(page, exc))
            entries = []
        _save_music_pool(entries, query)

        def fetch(limit):
            return entries
        def builder(entry):
            mode = 'music_play' if detect.looks_like_music(entry, query) else 'play'
            return lists.video_item(entry, mode)
        items, content = lists.paged(fetch, builder, 'search_results',
                                     {'q': query, 'kind': 'video'}, page=page)
    build(handle, items, content=content)


def _save_music_pool(entries, hint=''):
    from music import detect, queue
    from browse import constants, yt
    if not constants.autoplay_next():
        return
    candidates = [entry for entry in entries if detect.looks_like_music(entry, hint)]
    if len(candidates) < 10 and hint:
        try:
            extra = yt.search_videos('{} official video'.format(hint), limit=40)
        except Exception as exc:
            config.log('music top-up search failed: {}'.format(str(exc)[:100]),
                       xbmc.LOGWARNING)
            extra = []
        candidates.extend(entry for entry in extra
                          if detect.looks_like_music(entry, 'official video'))
    if len(candidates) >= 2:
        queue.save_pool(queue.pool() + candidates)


# ----------------------------------------------------------------------- browsing
def _trending_query():
    from browse import constants, localization
    return localization.trending_query(constants.trending_category())


def _live_query():
    from browse import constants, localization
    return localization.category_query(constants.live_category(), live=True)


def _trailer_query():
    from browse import localization
    return localization.trailer_query()


def _music_query():
    from browse import localization
    return localization.category_query('music')


# Random music always asks for a deep page (the route shuffles whatever comes
# back), so its cache key never matches the plain Trending one.
_RANDOM_MUSIC_FLOOR = 60


def warm_first_pages():
    """Fetch the first page of the heavy listings up front.

    The arguments are the ones the routes build for page 1 (see lists.paged:
    limit = per_page + 1), so opening those lists later is a cache hit instead
    of a request. Random music is included because it only shuffles what the
    cache returns, so warming changes nothing about what it shows. Opt-in
    through the prefetch setting, because a request the user never needed is
    exactly what we do not want to spend.
    """
    from browse import constants, yt
    import lists
    import time
    per_page = constants.results_per_page()
    # The amounts come from the very helpers the routes use, so warming a
    # listing and opening it can never ask for different numbers. With block
    # rules active that difference is real: Trending asks for forty nine rows
    # while warming thirty one, and the cache keys on the amount, so the warmed
    # copy was never the one the route asked for.
    trending_one = lists.rows_to_fetch(per_page)
    random_one = max(lists.rows_to_fetch(per_page), _RANDOM_MUSIC_FLOOR)
    blocked_one = lists.page_fetch_amount(1, blocked=True)
    targets = (
        ('trending', _trending_query(), yt.trending_videos, trending_one),
        ('live', _live_query(), yt.live_videos, blocked_one),
        ('trailers', _trailer_query(), yt.trailer_videos, blocked_one),
        ('random music', _music_query(), yt.trending_videos, random_one),
    )
    # Side by side, not one after another: Live alone takes about ten seconds
    # on a cold cache, and doing them in turn left Trailers and Random Music
    # unwarmed for ten seconds after start. Four threads, four requests, one
    # burst instead of a queue - the same shape the feed warming already uses.
    started = time.time()

    def _warm(target):
        name, query, fetch, limit = target
        mark = time.time()
        try:
            fetch(query, limit=limit)
            config.log('prefetch: {} warmed ({} items) in {:.1f}s'.format(
                name, limit, time.time() - mark), always=True)
        except Exception as exc:
            config.log('prefetch {} failed: {}'.format(name, str(exc)[:120]),
                       xbmc.LOGWARNING, always=True)

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        list(pool.submit(_warm, target) for target in targets)
    config.log('prefetch: all warm after {:.1f}s'.format(time.time() - started),
               always=True)


@route('trending')
def trending(handle, params):
    import lists
    from browse import constants, yt
    from music import detect, queue
    category_id = constants.trending_category()
    music_folder = category_id == 'music'
    page = _page(params)
    entries = yt.trending_videos(_trending_query(),
                             limit=lists.rows_to_fetch(
                                 page * constants.results_per_page()))
    if music_folder:
        queue.save_pool([entry for entry in entries if detect.looks_like_music(entry)])

    def builder(entry):
        mode = 'music_play' if (music_folder and detect.looks_like_music(entry)) else 'play'
        return lists.video_item(entry, mode)
    items, content = lists.paged(lambda limit: entries, builder, 'trending',
                                 {}, page=page, blocked=True)
    build(handle, items, content=content)


@route('live')
def live(handle, params):
    import lists
    from browse import yt
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.live_videos(_live_query(), limit=limit),
        lambda entry: lists.video_item(entry, 'play'),
        'live', {}, page=page, blocked=True)
    build(handle, items, content=content)


@route('trailers')
def trailers(handle, params):
    import lists
    from browse import yt
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.trailer_videos(_trailer_query(), limit=limit),
        lambda entry: lists.video_item(entry, 'play'),
        'trailers', {}, page=page, blocked=True)
    build(handle, items, content=content)


@route('charts')
def charts(handle, params):
    import lists
    from browse import yt
    sections = yt.chart_sections()
    items = [lists.folder_item(
        config.T(32120), 'chart_artists', config.icon('topartists'), {})]
    for entry in sections:
        if not entry.get('playlist_id'):
            continue
        _title = (lists.clean_title(entry.get('title') or '')
                  or entry.get('title') or '')
        items.append(lists.folder_item(
            _title, 'chart_videos',
            entry.get('image') or config.icon('charts'),
            {'url': entry.get('playlist_id'), 'title': _title},
            cm=[('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32142)),
                 lists.run_plugin('local_playlist_import',
                                  {'pid': entry.get('playlist_id'),
                                   'title': _title}))]))
    build(handle, [item[0:3] for item in items], content=None)


_FILL_DATES = {'busy': False}


def _fill_dates_bg(entries, refresh=False):
    """Finish the metadata fill the directory timeout had to cut off.

    Music charts carry no date at all, so the first visit only fills what fits
    in the listing deadline. This runs the rest in the background and the next
    visit shows them.

    The lists that are read from local files (History, Watch Later, a local
    playlist) paint straight away and pass refresh=True, because their rows
    only miss the channel, views, date and plot - so there is something to show
    immediately.

    The automatic repaint was removed: a `Container.Refresh` from this thread
    landed ~1s after a Stop, right on top of the media window re-initialising
    and a Back navigation - and Kodi crashed (Android log 03:02:45.4 stop ->
    03:02:46.4 refresh, the last line before the crash). The data is already in
    the store, so the next render shows it; the price is a list without the
    dates until then.
    """
    import threading as _threading
    entries = [dict(entry or {}) for entry in entries or []]
    if not entries or _FILL_DATES['busy']:
        return

    def _run():
        try:
            import lists
            done, healed = lists.fill_missing_meta(entries, timeout=60.0,
                                                   return_healed=True)
            dated = sum(1 for entry in done if lists.entry_date(entry))
            config.log('background meta fill: {}/{} with a date'.format(
                dated, len(done)), always=True)
            # No Container.Refresh from here (see docstring): a background
            # refresh over a Stop / Back navigation crashed Kodi.
            if refresh and healed:
                config.log('background meta fill: dates will show on the next '
                           'open of the list')
        except Exception as exc:
            config.log('background meta fill failed: {}'.format(exc))
        finally:
            _FILL_DATES['busy'] = False

    _FILL_DATES['busy'] = True
    _threading.Thread(target=_run, daemon=True).start()


def _video_playing():
    try:
        return bool(xbmc.Player().isPlayingVideo())
    except Exception:
        return False


def _modal_open():
    try:
        return bool(xbmc.getCondVisibility('System.HasModalDialog'))
    except Exception:
        return False


def _bg_refresh_ok(folder_hint=''):
    """May a background thread repaint the list right now?

    A `Container.Refresh` from a worker is queued on the UI thread, so it can
    land on whatever is in front: a Stop that just closed the media window, a
    Back that is already navigating, or a modal dialog. That is the pattern
    that crashed Kodi (Android log: Stop 03:02:45.4, background refresh
    03:02:46.4, no shutdown lines after). Only repaint while the list the
    worker filled is still on screen, nothing is playing and no dialog is up;
    otherwise the data waits in the store for the next open of the list.
    """
    try:
        if _modal_open() or _video_playing():
            return False
        if folder_hint:
            folder = xbmc.getInfoLabel('Container.FolderPath') or ''
            if folder_hint not in folder:
                config.log('background refresh skipped (other list)')
                return False
        return True
    except Exception:
        return False


_CHART_FULL_FETCH = 250   # the longest YouTube Music chart is 100
# YouTube's own pseudo playlists: they are not real ids and cannot be read
_PLAYLIST_PSEUDO_IDS = ('LL', 'WL')


def _playlist_counter(declared, page, per_page):
    """The running count that rides on the Next page row, e.g. 60/240.

    It says where the reader is and how long the playlist is without spending a
    row of its own on the sentence.
    """
    if not declared:
        return ''
    shown = min(page * per_page, declared)
    return '  [B][COLOR FFFFA500]{}/{}[/COLOR][/B]'.format(shown, declared)


def _declared_playlist_count(playlist_id):
    """How many tracks YouTube says this playlist holds.

    Two sources: the length seen while the playlist was last read, and the
    saved playlists list. The first one also covers a playlist that was only
    ever opened from a link, which never sits in the library at all.
    """
    key = str(playlist_id or '')
    try:
        import store
        seen = store.get_state('playlist_counts')
        if isinstance(seen, dict) and int(seen.get(key) or 0) > 0:
            return int(seen.get(key) or 0)
    except Exception:
        pass
    try:
        import store
        block = store.get_library('saved_playlists')
        entries = (block.get('items') or block.get('entries') or []) \
            if isinstance(block, dict) else (block or [])
        for entry in entries:
            if str(entry.get('playlist_id') or '') == str(playlist_id or ''):
                try:
                    return int(entry.get('count') or 0)
                except (TypeError, ValueError):
                    return 0
    except Exception:
        pass
    return 0
_CHART_RANK_RE = re.compile(r'^\s*(\d{1,3})\s*[.)]\s*')


def _split_chart_rank(text):
    """Split YouTube's own chart position off a chart title.

    The number is the real place in the chart, so it is worth keeping, but it
    comes with gaps once rows are blocked and the list then reads 3, 4, 5 with
    nothing before them."""
    value = str(text or '')
    match = _CHART_RANK_RE.match(value)
    if not match:
        return '', value
    return match.group(1), value[match.end():]


@route('chart_artists')
def chart_artists(handle, params):
    import lists
    from browse import yt
    page = _page(params)
    entries = [entry for entry in yt.chart_artists() if entry.get('url')]
    total = len(entries)
    entries = lists.filter_blocked(entries, name_key='title')

    def fetch(limit):
        return entries

    def builder(entry):
        return lists.folder_item(
            entry['title'], 'channel',
            entry.get('image') or config.icon('topartists'),
            {'url': entry.get('url'), 'title': entry.get('title')},
            description=entry.get('subs', ''))

    items, content = lists.paged(fetch, builder, 'chart_artists', {}, page=page,
                                 total=total)
    build(handle, items, content=content)


@route('chart_videos')
def chart_videos(handle, params):
    import lists
    from browse import constants, yt
    from music import detect
    url = params.get('url') or ''
    title = params.get('title') or ''
    page = _page(params)
    per_page = constants.results_per_page()
    # Charts are short and fixed, so the whole one is fetched once and every
    # page is cut out of it. The fetch is cached, so page 2 costs no request,
    # and the page length comes from the chart itself rather than from what
    # survived the block filter.
    try:
        source = yt.chart_tracks(url, limit=_CHART_FULL_FETCH)
    except Exception as exc:
        config.log('chart_videos page {} failed: {}'.format(page, exc))
        source = []
    total = len(source)
    _start = (page - 1) * per_page
    _kept = lists.filter_blocked(source)
    undated = [entry for entry in source[_start:_start + per_page]
               if not lists.entry_date(entry)]
    # the visible position, counted across pages and skipping hidden rows, so
    # the list reads 1, 2, 3 even when a blocked artist took the first two
    _number = [len(_kept[:_start])]

    def fetch(limit):
        return source

    def builder(entry):
        _number[0] += 1
        real_rank, plain = _split_chart_rank(entry.get('title'))
        row = dict(entry)
        row['title'] = '%d. %s' % (_number[0], plain)
        if real_rank and real_rank != str(_number[0]):
            row['snippet'] = config.T(32520).format(real_rank,
                                                    title or '')
        mode = 'music_play' if detect.looks_like_music(row) else 'play'
        return lists.video_item(row, mode)
    items, content = lists.paged(fetch, builder, 'chart_videos',
                                 {'url': url, 'title': title}, page=page,
                                 blocked=True, total=total)
    build(handle, items, content=content)
    if undated:
        _fill_dates_bg(undated)


@route('random_music')
def random_music(handle, params):
    import lists
    from browse import constants, yt
    from music import queue
    page = _page(params)
    entries = yt.trending_videos(_music_query(),
                                 limit=max(lists.rows_to_fetch(
                                     page * constants.results_per_page()),
                                     _RANDOM_MUSIC_FLOOR))
    import random as _random
    _random.SystemRandom().shuffle(entries)
    queue.save_pool(entries)
    items, content = lists.paged(
        lambda limit: entries,
        lambda entry: lists.video_item(entry, 'music_play'),
        'random_music', {}, page=page, blocked=True)
    build(handle, items, content=content, cache=False)


@route('go_channel')
def go_channel(handle, params):
    import lists
    from browse import meta
    video_id = lists.video_id(params.get('video_id'))
    info = meta.video_meta(video_id) if video_id else {}
    channel_id = (info or {}).get('channel_id') or ''
    if not channel_id:
        _notify(config.T(32184))
        return
    xbmc.executebuiltin('Container.Update({}?{},replace)'.format(
        BASE_URL, urlencode({'mode': 'channel',
                             'url': 'https://www.youtube.com/channel/' + channel_id,
                             'title': (info or {}).get('channel') or ''})))


@route('sub_channel')
def sub_channel(handle, params):
    """Subscribe or unsubscribe from a video whose channel is not known yet.

    The context menu cannot know the channel at build time (see
    lists._menu_channel_id), so this decides here: pressing it again on a
    channel you already joined unsubscribes instead of silently re-joining.
    """
    import lists
    import store
    from browse import meta
    video_id = lists.video_id(params.get('video_id'))
    info = meta.video_meta(video_id) if video_id else {}
    channel_id = (info or {}).get('channel_id') or ''
    if not channel_id:
        _notify(config.T(32184))
        return
    title = (info or {}).get('channel') or ''
    _curl = 'https://www.youtube.com/channel/' + channel_id
    if store.is_subscribed(_curl):
        marked = _unsubscribe_label(_curl, title)
        named = _unsubscribe_label(_curl, title, allow_id=False)
        if not xbmcgui.Dialog().yesno(config.T(32154),
                                      config.T(32311).format(marked)):
            return
        store.unsubscribe(_curl)
        lists.clear_menu_memo()
        named = _unsubscribe_label(_curl, title, allow_id=False)
        _notify(config.T(32310).format(named) if named else config.T(32185))
    else:
        store.subscribe(title, _curl)
        import threading as _threading
        _threading.Thread(target=_backfill_sub_thumbs, args=([_curl],),
                          daemon=True).start()
        lists.clear_menu_memo()
        _marked = _channel_markup(title)
        _notify(config.T(32164).format(_marked) if _marked else config.T(32308))
    xbmc.executebuiltin('Container.Refresh')


@route('channel')
def channel(handle, params):
    import lists
    import store
    url = params.get('url') or ''
    title = params.get('title') or ''
    known = next((item for item in store.get_subscriptions()
                  if item.get('url') == url), None)
    # Only a real name travels down: with an unnamed channel the url used to
    # become the channel name in the notification, in the subscriptions file
    # and on every video row of the page.
    real_name = title if not store.is_url_title(title, url) \
        else ((known or {}).get('title') or '')
    toggle = ('unsubscribe', '[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32154))) if known \
        else ('subscribe', '[B][COLOR FF00FF7F]{}[/COLOR][/B]'.format(config.T(32153)))
    items = [
        lists.folder_item(config.T(32117), 'channel_videos', config.icon('videos'),
                          {'url': url, 'tab': 'videos', 'title': real_name}),
        lists.folder_item(config.T(32180), 'channel_videos', config.icon('shorts'),
                          {'url': url, 'tab': 'shorts', 'title': real_name}),
        lists.folder_item(config.T(32103), 'channel_videos', config.icon('live'),
                          {'url': url, 'tab': 'streams', 'title': real_name}),
        lists.folder_item(config.T(32119), 'channel_playlists',
                          config.icon('playlists'),
                          {'url': url, 'title': real_name}),
        lists.action_item(toggle[1], toggle[0],
                          config.icon('unsubscribe' if known else 'subscribe'),
                          {'url': url, 'title': real_name,
                           'image': params.get('image') or (known or {}).get('image', '')},
                          folder=False),
    ]
    build(handle, [item[0:3] for item in items], content=None)


@route('channel_videos')
def channel_videos(handle, params):
    import lists
    from browse import constants, yt
    from music import detect
    url = params.get('url') or ''
    tab = params.get('tab') or 'videos'
    page = _page(params)
    requested = page * constants.results_per_page() + 1
    try:
        source = yt.channel_videos(url, tab=tab, limit=requested)
    except Exception as exc:
        config.log('channel_videos page {} failed: {}'.format(page, exc))
        source = []
    if not source and tab == 'videos':
        try:
            from browse import rich
            albums = rich.channel_albums(url, limit=requested)
        except Exception as exc:
            config.log('channel_albums failed: {}'.format(str(exc)[:100]))
            albums = []
        if albums:
            start = (page - 1) * constants.results_per_page()
            items = [lists.folder_item(
                entry['title'], 'chart_videos', config.icon('albums'),
                {'url': entry['playlist_id'], 'title': entry['title']})
                for entry in albums[start:start + constants.results_per_page()]
                if entry.get('playlist_id')]
            build(handle, [item[0:3] for item in items], content=None)
            return
    source = lists.fill_missing_meta(source)

    def fetch(limit):
        return source

    def builder(entry):
        entry = dict(entry or {})
        if not entry.get('channel'):
            entry['channel'] = params.get('title') or ''
        mode = 'music_play' if detect.looks_like_music(entry) else 'play'
        return lists.video_item(entry, mode)
    items, content = lists.paged(fetch, builder, 'channel_videos',
                                 {'url': url, 'tab': tab}, page=page)
    build(handle, items, content=content)


def _playlist_id(value):
    """Accept a bare playlist id or any URL carrying ?list=; else ''."""
    value = (value or '').strip()
    if not value:
        return ''
    if value.startswith(('PL', 'OL', 'RD', 'UU', 'FL', 'LL')) and '://' not in value:
        return value
    try:
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(value).query)
        listed = (query.get('list') or [''])[0].strip()
        if listed:
            return listed
    except Exception:
        pass
    return ''


@route('channel_playlists')
def channel_playlists(handle, params):
    import lists
    from browse import yt
    url = params.get('url') or ''
    page = _page(params)

    def builder(entry):
        entry = entry or {}
        if not entry.get('playlist_id'):
            return None
        title = (lists.clean_title(entry.get('title') or '')
                 or entry.get('title') or entry['playlist_id'])
        return lists.folder_item(title, 'playlist', entry.get('image'),
                                 {'url': entry['playlist_id']},
                                 description=entry.get('count', ''),
                                 cm=[('[B][COLOR FF00CED1]Import playlist[/COLOR][/B]',
                                      lists.run_plugin('local_playlist_import',
                                                       {'pid': entry['playlist_id'],
                                                        'title': title}))])

    items, content = lists.paged(
        lambda limit: yt.channel_playlists(url, limit=limit),
        builder, 'channel_playlists', {'url': url}, page=page)
    build(handle, items, content=content, cache=False)


@route('playlist')
def playlist(handle, params):
    import lists
    from browse.constants import results_per_page
    from browse import yt
    url = params.get('url') or ''
    pid = _playlist_id(url)
    page = _page(params)
    if not pid or pid in _PLAYLIST_PSEUDO_IDS:
        build(handle, [lists.folder_item(
            config.T(32522), 'playlist', config.icon('playlists'), {'url': url},
            folder=False)[0:3]], content='videos')
        return
    # One page at a time, like every other listing here. Asking for a whole
    # long playlist in one go meant page one walked every continuation YouTube
    # had, which measured at 30 to 42 seconds on real playlists. This asks for
    # the page plus one row, the one extra row being what says there is more.
    declared = _declared_playlist_count(pid)

    def fetch(limit):
        rows = list(yt.playlist_videos(pid, limit=limit) or [])
        # the playlist parser gives title, channel, views and date, but no
        # description and no duration, so the rows are completed here or the
        # listing shows an empty plot and no length
        return lists.fill_missing_meta(rows)

    def builder(entry):
        return lists.video_item(entry, 'play')

    items, content = lists.paged(
        fetch, builder, 'playlist', {'url': url}, page=page, content='videos',
        total=lambda: _declared_playlist_count(pid),
        next_extra=lambda: _playlist_counter(
            _declared_playlist_count(pid), page, results_per_page()))
    build(handle, items, content=content)


# ----------------------------------------------------------------------- playback
@route('play')
def play(handle, params):
    import playback
    from browse import constants
    from music import queue
    video_id = params.get('video_id') or ''
    if video_id and constants.autoplay_next() and video_id not in queue.blocked():
        playback.start_queue(handle, params)
        return
    playback.resolve_play(handle, params)


@route('music_play')
def music_play(handle, params):
    import playback
    from browse import constants
    from music import queue
    video_id = params.get('video_id') or ''
    if video_id and constants.autoplay_next() and video_id not in queue.blocked():
        playback.start_queue(handle, params)
        return
    playback.resolve_play(handle, params)


@route('related_play')
def related_play(handle, params):
    import playback
    playback.start_queue(handle, params)


@route('queue_play')
def queue_play(handle, params):
    import playback
    playback.resolve_play(handle, params, arm=False)


@route('no_autoplay')
def no_autoplay(handle, params):
    from music import queue
    video_id = params.get('video_id') or ''
    if video_id:
        queue.block(video_id)
    import lists
    lists.clear_menu_memo()
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32162), config.addon_icon(), time=2500, sound=False)
    cancel(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('unblock')
def unblock(handle, params):
    from music import queue
    queue.unblock(params.get('video_id') or '')
    import lists
    lists.clear_menu_memo()
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32163), config.addon_icon(), time=2500, sound=False)
    cancel(handle)
    xbmc.executebuiltin('Container.Refresh')


# ----------------------------------------------------------------------- library
def _resolve_sub_info(url):
    thumb = ''
    owner = ''
    try:
        from browse import yt as _ytav
        avatar, title = _ytav.channel_header(url) or ('', '')
        if avatar.startswith('http'):
            thumb = avatar
        owner = title or ''
    except Exception as exc:
        config.log('sub avatar {} failed: {}'.format(url, str(exc)[:90]))
    if not thumb or not owner:
        try:
            from browse import yt
            videos = yt.channel_videos(url, limit=1) or []
            if videos:
                if not thumb and videos[0].get('image'):
                    thumb = videos[0]['image']
                if not owner:
                    owner = videos[0].get('channel') or ''
        except Exception as exc:
            config.log('sub thumb {} failed: {}'.format(url, str(exc)[:90]))
    return thumb, owner


def _channel_handle(url):
    """Last path segment of a channel url: the UC id or the @handle.

    Used as a placeholder label while the real name is still being resolved,
    which reads far better in a list than the whole youtube link.
    """
    tail = str(url or '').rstrip('/').rsplit('/', 1)[-1]
    return tail or str(url or '')


def _resolve_sub_image(url, image=''):
    import store
    image = str(image or '')
    if image and not store.needs_avatar(image):
        return image
    thumb, _owner = _resolve_sub_info(url)
    return thumb or image


def _backfill_sub_thumbs(urls):
    changed = False
    try:
        import store as _store
        for url in urls or []:
            try:
                thumb, owner = _resolve_sub_info(url or '')
            except Exception:
                continue
            if (thumb or owner) and _store.update_subscription(
                    url or '', image=thumb or None, title=owner or None):
                changed = True
    except Exception as exc:
        config.log('sub thumb backfill failed: {}'.format(str(exc)[:90]))
        return
    if changed:
        # No Container.Refresh from a thread (same reason as _fill_dates_bg): it
        # can land on a window transition and crash Kodi. The avatar is stored,
        # so the list shows it on its next open.
        config.log('subscription avatars refreshed; the list shows them on '
                   'its next open')


@route('subscribe')
def subscribe(handle, params):
    import store
    import threading
    title = params.get('title') or ''
    url = params.get('url') or ''
    image = params.get('image') or ''
    # A channel reached without its name (search > Channels) arrives with the
    # url in the title; the store already drops that, and the notification must
    # not show a link either.
    if store.is_url_title(title, url):
        title = ''
    store.subscribe(title, url, image)
    if store.needs_avatar(image) or not title:
        threading.Thread(target=_backfill_sub_thumbs, args=([url],),
                         daemon=True).start()
    import lists
    lists.clear_menu_memo()
    _marked = _channel_markup(title)
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32164).format(_marked) if _marked else config.T(32308),
        config.addon_icon(), time=2500, sound=False)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('unsubscribe')
def unsubscribe(handle, params):
    import store
    url = params.get('url') or ''
    title = params.get('title') or ''
    # Both names are resolved before the record is dropped, otherwise the
    # stored fallback is already gone by the time the notification needs it.
    marked = _unsubscribe_label(url, title)
    named = _unsubscribe_label(url, title, allow_id=False)
    if not xbmcgui.Dialog().yesno(config.T(32154),
                                  config.T(32311).format(marked)):
        finish(handle)
        return
    store.unsubscribe(url)
    import lists
    lists.clear_menu_memo()
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32310).format(named) if named else config.T(32185),
        config.addon_icon(), time=2500, sound=False)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('watch_later_add')
def watch_later_add(handle, params):
    import lists
    import store
    store.add_watch_later(lists.history_entry(params))
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32183), config.addon_icon(), time=2500, sound=False)
    cancel(handle)


@route('watch_later')
def watch_later(handle, params):
    import lists
    import store
    from browse import constants
    entries = _merge_remote(store.get_watch_later(),
                            store.get_library('watch_later_remote'))
    _fill_dates_bg(entries, refresh=True)
    page = _page(params)
    per_page = constants.results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    lists.set_listing('watch_later', {}, page)
    lists.set_context(entries)
    items = [lists.video_item(entry, 'play', in_watch_later=True, cm=[
        ('[B][COLOR FFFF5555]Remove from Watch Later[/COLOR][/B]',
         lists.run_plugin('watch_later_remove',
                          {'video_id': entry.get('video_id')}))]
        ) for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item('[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(config.T(32160).format(page + 1)),
                                       'watch_later', config.icon('nextpage'),
                                       {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


@route('watch_later_remove')
def watch_later_remove(handle, params):
    import store
    store.remove_watch_later(params.get('video_id') or '')
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


# ----------------------------------------------------------------------- local playlists
@route('local_playlists')
def local_playlists(handle, params):
    import lists
    import store
    items = []
    for entry in store.get_local_playlists():
        count = len(store.get_local_playlist_tracks(entry.get('id')))
        items.append(lists.folder_item(
            '{} [B][COLOR FFFFA500]({})[/COLOR][/B]'.format(
                entry.get('name') or config.T(32194), count),
            'local_playlist', config.icon('playlists'),
            {'pid': entry.get('id'), 'title': entry.get('name') or ''},
            cm=[('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32159)),
                 lists.run_plugin('local_playlist_play',
                                  {'pid': entry.get('id')})),
                ('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32138)),
                 lists.run_plugin('local_playlist_rename',
                                  {'pid': entry.get('id'),
                                   'title': entry.get('name') or ''})),
                ('[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32139)),
                 lists.run_plugin('local_playlist_delete',
                                  {'pid': entry.get('id'),
                                   'title': entry.get('name') or ''}))]))
    items.append(lists.action_item(
        '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32134)), 'local_playlist_create',
        config.icon('playlists'), {}, folder=False))
    build(handle, [item[0:3] for item in items], content=None)


@route('local_playlist')
def local_playlist(handle, params):
    import lists
    import store
    pid = params.get('pid') or ''
    entries = store.get_local_playlist_tracks(pid)
    _fill_dates_bg(entries, refresh=True)
    lists.set_listing('local_playlist', {'pid': pid}, 1)
    lists.set_context(entries)

    def builder(entry):
        return lists.video_item(entry, 'music_play', cm=[
            ('[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32141)),
             lists.run_plugin('local_playlist_remove',
                              {'pid': pid,
                               'video_id': entry.get('video_id')}))])

    items = []
    for entry in entries:
        built = builder(entry)
        if built:
            items.append(built)
    build(handle, [item[0:3] if len(item) > 3 else item for item in items],
          content='videos')


@route('local_playlist_play')
def local_playlist_play(handle, params):
    import lists
    import playback
    import store
    pid = params.get('pid') or ''
    entries = store.get_local_playlist_tracks(pid)
    if not entries:
        cancel(handle)
        return
    lists.set_listing('local_playlist', {'pid': pid}, 1)
    lists.set_context(entries)
    playback.start_queue(handle, lists.entry_params(entries[0]))


@route('local_playlist_create')
def local_playlist_create(handle, params):
    import store
    name = xbmcgui.Dialog().input(config.T(32135)) or ''
    name = name.strip()
    if name:
        store.create_local_playlist(name)
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
            config.T(32148).format(
                '[B][COLOR FFFFA500]{}[/COLOR][/B]'.format(name)),
            config.addon_icon(), time=2500, sound=False)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('local_playlist_add')
def local_playlist_add(handle, params):
    import lists
    import store
    track = lists.history_entry(params)
    if not track.get('video_id'):
        cancel(handle)
        return
    video_id = track.get('video_id')
    all_playlists = store.get_local_playlists()
    options = []
    member_of = []
    for entry in all_playlists:
        name = entry.get('name') or config.T(32194)
        tracks = store.get_local_playlist_tracks(entry.get('id'))
        member = any(track.get('video_id') == video_id for track in tracks)
        member_of.append(member)
        count = '[B][COLOR FFFFA500]({})[/COLOR][/B]'.format(len(tracks))
        if member:
            options.append('[B][COLOR FFFF5555]- {}[/COLOR][/B] {}'.format(name, count))
        else:
            options.append('[B][COLOR FF00FF7F]+ {}[/COLOR][/B] {}'.format(name, count))
    choice = xbmcgui.Dialog().select(
        config.T(32136), options + [config.T(32137)])
    if choice is None or choice < 0:
        cancel(handle)
        return
    if choice == len(options):
        name = xbmcgui.Dialog().input(config.T(32135)) or ''
        name = name.strip()
        if not name:
            cancel(handle)
            return
        pid = store.create_local_playlist(name)
        picked = name
        result = store.add_to_local_playlist(pid, track)
    else:
        pid = all_playlists[choice].get('id')
        picked = all_playlists[choice].get('name') or config.T(32194)
        if member_of[choice]:
            store.remove_from_local_playlist(pid, video_id)
            result = 'removed'
        else:
            result = store.add_to_local_playlist(pid, track)
    shown = '[B][COLOR FFFFA500]{}[/COLOR][/B]'.format(picked)
    if result == 'added':
        message = config.T(32143).format(shown)
    elif result == 'removed':
        message = config.T(32147).format(shown)
    elif result == 'duplicate':
        message = config.T(32144).format(shown)
    elif result == 'full':
        message = config.T(32145).format(shown)
    else:
        message = config.T(32146)
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        message, config.addon_icon(), time=2500, sound=False)
    cancel(handle)


@route('local_playlist_remove')
def local_playlist_remove(handle, params):
    import store
    store.remove_from_local_playlist(params.get('pid') or '',
                                     params.get('video_id') or '')
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('local_playlist_rename')
def local_playlist_rename(handle, params):
    import store
    pid = params.get('pid') or ''
    name = xbmcgui.Dialog().input(
        config.T(32135), params.get('title') or '') or ''
    name = name.strip()
    if name:
        store.rename_local_playlist(pid, name)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('local_playlist_delete')
def local_playlist_delete(handle, params):
    import store
    name = params.get('title') or 'playlist'
    if xbmcgui.Dialog().yesno(
            config.T(32139), config.T(32140).format(
                '[B][COLOR FFFFA500]{}[/COLOR][/B]'.format(name))):
        store.delete_local_playlist(params.get('pid') or '')
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
            config.T(32149).format(
                '[B][COLOR FFFFA500]{}[/COLOR][/B]'.format(name)),
            config.addon_icon(), time=2500, sound=False)
    finish(handle)
    xbmc.executebuiltin('Container.Update({}?mode=local_playlists,replace)'.format(
        BASE_URL))


@route('local_playlist_import')
def local_playlist_import(handle, params):
    import lists
    import store
    from browse import yt
    pid = _playlist_id(params.get('pid') or params.get('url') or '')
    title = params.get('title') or config.T(32194)
    if not pid:
        cancel(handle)
        return
    try:
        videos = yt.playlist_videos(pid, limit=200)
    except Exception as exc:
        config.log('playlist import failed: {}'.format(exc), xbmc.LOGERROR)
        videos = []
    videos = [entry for entry in (videos or []) if (entry or {}).get('video_id')]
    if not videos:
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
            config.T(32151), config.addon_icon(), time=2500, sound=False)
        cancel(handle)
        return
    new_id = store.create_local_playlist(title)
    added = 0
    for entry in videos:
        if store.add_to_local_playlist(new_id, dict(entry)) == 'added':
            added += 1
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32150).format(
            added, '[B][COLOR FFFFA500]{}[/COLOR][/B]'.format(title)),
        config.addon_icon(), time=2500, sound=False)
    cancel(handle)


@route('history')
def history(handle, params):
    import lists
    import store
    from browse import constants
    entries = _merge_remote(store.get_history(),
                            store.get_library('remote_history'))
    _fill_dates_bg(entries, refresh=True)
    page = _page(params)
    per_page = constants.results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    lists.set_listing('history', {}, page)
    lists.set_context(entries)
    items = [lists.video_item(entry, 'play', cm=[
        ('[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32186)),
         lists.run_plugin('remove_history',
                          {'video_id': entry.get('video_id')}))])
        for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item('[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(config.T(32160).format(page + 1)),
                                       'history', config.icon('nextpage'),
                                       {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


@route('remove_history')
def remove_history(handle, params):
    import store
    store.remove_history(params.get('video_id') or '')
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('clear_history')
def clear_history(handle, params):
    import store
    store.clear_history()
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


# --------------------------------------------------------------------- account
def _unsubscribe_label(url, title='', allow_id=True):
    """Channel name for the confirmation and the notification.

    Read before the record is dropped, and the menu sometimes carries only the
    url - the stored title is the fallback. The confirmation falls back to the
    channel id as well, so the dialog never asks about an unnamed blank; the
    notification keeps the plain wording instead of naming an id.
    """
    import store
    name = title if title and not store.is_url_title(title, url) else ''
    if not name:
        name = (store.subscription(url) or {}).get('title') or ''
    if not name and allow_id:
        return _channel_markup(_channel_handle(url))
    return _channel_markup(name)


def _channel_markup(name):
    """Channel name for a notification: always bold and in the addon colour.

    The name reaches us straight from YouTube, so any markup it carries is
    dropped first, otherwise the wrapping tags could end up unbalanced.
    """
    import re as _re
    try:
        import lists as _lists
        text = _lists.clean_title(str(name or ''), single_line=True)
    except Exception:
        text = str(name or '').strip()
    text = _re.sub(r'\[/?(?:B|I)\]|\[COLOR[^\]]*\]|\[/COLOR\]', '',
                   text).strip()
    if not text:
        return ''
    return '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(text)


def _notify(message, time_ms=4000):
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        message, config.addon_icon(), time=time_ms, sound=False)


def _blocked_markup(name, kind=None):
    """A blocked name in a notification: bold, and in the colour its kind
    wears in the blocked list."""
    import store
    colours = {store.KIND_CHANNEL: 'FF00CED1', store.KIND_ARTIST: 'FFCCCCFF'}
    return '[B][COLOR %s]%s[/COLOR][/B]' % (
        colours.get(kind, 'FFCCCCFF'), name)


def _row_block_entry(params):
    """The row the menu was opened on, as the filter sees it."""
    import lists
    import store
    vid = params.get('video_id') or ''
    channel = str(params.get('channel') or '').strip()
    if not channel:
        try:
            channel = str((store.get_yt_meta(vid) or {}).get('channel')
                          or '').strip()
        except Exception:
            channel = ''
    return {'video_id': vid, 'channel': channel,
            'title': params.get('title') or '',
            'artist': lists.artist_from_title(params.get('title'))}


def _add_block_rule(handle, params, kind):
    import lists
    import store
    entry = _row_block_entry(params)
    name = entry.get('artist') if kind == store.KIND_ARTIST else entry.get('channel')
    if not name:
        _notify(config.T(32508))
        cancel(handle)
        return
    store.add_blocked_name(name, kind)
    lists.clear_menu_memo()
    _notify(config.T(32510).format(_blocked_markup(name, kind)))
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('block_channel')
def block_channel(handle, params):
    """Hide every row of this row's channel."""
    import store
    _add_block_rule(handle, params, store.KIND_CHANNEL)


@route('block_artist')
def block_artist(handle, params):
    """Hide only the rows that name this artist, so a channel that posts
    several of them keeps the rest."""
    import store
    _add_block_rule(handle, params, store.KIND_ARTIST)


@route('unblock_artist')
def unblock_artist(handle, params):
    """Take back whichever rule hides this row: the channel one, the artist one,
    or both when the row is hidden by both."""
    import lists
    import store
    entry = _row_block_entry(params)
    hits = store.blocked_matches(entry, entry.get('artist'))
    for kind, label in hits:
        store.remove_blocked_name(label, kind)
    if hits:
        lists.clear_menu_memo()
        _notify(config.T(32511).format(
            ', '.join('%s (%s)' % (_blocked_markup(label, kind), kind)
                      for kind, label in hits)))
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('remove_rule')
def remove_rule(handle, params):
    """Drop one rule from the blocked list page."""
    import lists
    import store
    label = params.get('name') or ''
    kind = params.get('kind') or ''
    if label and store.remove_blocked_name(label, kind):
        lists.clear_menu_memo()
        _notify(config.T(32512).format(_blocked_markup(label, kind)))
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('blocked_artists')
def blocked_artists(handle, params):
    """A plain listing, one row per rule, unblocked from its own context menu.

    The two kinds carry different colours so they can be told apart at a
    glance: turquoise for a channel rule, soft white for an artist one.
    """
    import lists
    import store
    colours = {store.KIND_CHANNEL: 'FF00CED1', store.KIND_ARTIST: 'FFCCCCFF'}
    entries = store.get_blocked_names()
    items = []
    for entry in entries.values():
        kind = entry.get('kind') or store.KIND_CHANNEL
        label = entry.get('label') or ''
        marker = config.T(32518 if kind == store.KIND_ARTIST else 32519)
        remove = 'RunPlugin({}?mode=remove_rule&{})'.format(
            BASE_URL, urlencode({'name': label, 'kind': kind}))
        items.append(lists.folder_item(
            '[B][COLOR %s]%s[/COLOR][/B]  [COLOR FF888888]%s[/COLOR]'
            % (colours.get(kind, 'FFCCCCFF'), label, marker),
            'blocked_artists', config.icon('unsubscribe'),
            description=marker,
            cm=[('[B][COLOR FF00FF7F]{}[/COLOR][/B]'.format(config.T(32515)),
                 remove)]))
    if not items:
        items.append(lists.folder_item(config.T(32506), 'blocked_artists',
                                      config.icon('unsubscribe'), folder=False))
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    finish(handle)


@route('my_youtube')
def my_youtube(handle, params):
    import lists
    from account import youtube_sync
    account = youtube_sync.status()
    items = []
    if account.get('connected'):
        items.append(lists.folder_item(
            config.T(32121), 'subscription_feed', config.icon('mysubscriptions')))
        items.append(lists.folder_item(
            config.T(32122), 'subscribed_channels',
            config.icon('subscribedch')))
        items.append(lists.folder_item(
            config.T(32108), 'watch_later', config.icon('watchlater')))
        items.append(lists.folder_item(
            config.T(32123), 'saved_playlists', config.icon('playlists')))
        items.append(lists.folder_item(
            config.T(32124), 'history', config.icon('history')))
        items.append(lists.action_item(
            '[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32513)),
            'blocked_artists', config.icon('unsubscribe')))
        items.append(lists.action_item(
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32125)), 'sync_now',
            config.icon('sync'), folder=False))
        items.append(lists.action_item(
            '[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32126)), 'logout',
            config.icon('disconnect'), folder=False))
    elif account.get('pending'):
        items.append(lists.folder_item(
            '[B][COLOR FFFF4500]{}[/COLOR][/B]'.format(config.T(32127)), 'login',
            config.icon('subscribe')))
    else:
        items.append(lists.folder_item(
            config.T(32121), 'subscription_feed', config.icon('mysubscriptions')))
        items.append(lists.folder_item(
            config.T(32122), 'subscribed_channels',
            config.icon('subscribedch')))
        items.append(lists.action_item(
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32128)),
            'login', config.icon('subscribe'),
            description=config.T(32195)))
    build(handle, [item[0:3] for item in items], content=None)


@route('subscription_feed')
def subscription_feed(handle, params):
    import lists
    import store
    from browse.constants import results_per_page
    entries = store.get_library('subscription_feed')
    if not entries:
        return feed(handle, params)
    try:
        _local_only = [sub for sub in store.get_subscriptions()
                       if isinstance(sub, dict)
                       and sub.get('source') == 'local' and sub.get('url')]
    except Exception:
        _local_only = []
    if _local_only:
        from browse import constants as _constants, yt as _yt
        try:
            _per_channel = int(_constants.feed_per_channel())
        except Exception:
            _per_channel = 3
        _urls = {sub.get('url') for sub in _local_only if sub.get('url')}
        _seen = {entry.get('video_id') for entry in entries}
        _fresh = [entry for entry in store.get_feed_cache()
                  if isinstance(entry, dict)
                  and entry.get('_feed_sub') in _urls
                  and entry.get('video_id') not in _seen]
        for entry in _fresh:
            _seen.add(entry.get('video_id'))
        if not _fresh:
            _fresh = []
            _added = 0
            for sub in _local_only:
                if _added >= 30:
                    break
                url = sub.get('url') or ''
                name = sub.get('title') or url
                if url not in _urls:
                    continue
                try:
                    videos = _yt.channel_videos(url, limit=_per_channel)[:_per_channel]
                except Exception as exc:
                    config.log('mixed feed {} failed: {}'.format(url, str(exc)[:90]))
                    continue
                for entry in videos:
                    item = dict(entry or {})
                    if not item.get('video_id') or item.get('video_id') in _seen:
                        continue
                    _seen.add(item.get('video_id'))
                    item['title'] = '{} - {}'.format(name, item.get('title') or item['video_id'])
                    item['channel'] = item.get('channel') or name
                    item['_local_only'] = True
                    item['_feed_sub'] = url
                    _fresh.append(item)
                    _added += 1
            store.set_feed_cache(_fresh)
        _mirror_ids = {entry.get('video_id') for entry in entries}
        entries = entries + [entry for entry in _fresh
                             if entry.get('video_id') not in _mirror_ids]
    original = list(entries)
    entries = lists.fill_missing_meta(entries)
    lists.persist_filled('subscription_feed', original, entries)
    try:
        _hide_shorts = bool(config.get_bool('hide_shorts', False))
    except Exception:
        _hide_shorts = False
    if _hide_shorts:
        entries = [entry for entry in entries if not entry.get('is_shorts')]
    entries = sorted(entries,
                     key=lambda entry: (not (entry.get('channel') or ''),
                                        (entry.get('channel') or '').lower()))
    page = _page(params)
    per_page = results_per_page()
    entries = lists.filter_blocked(entries)
    start = (page - 1) * per_page
    end = start + per_page
    lists.set_listing('subscription_feed', {}, page)
    lists.set_context(entries)
    items = [lists.video_item(entry, 'play') for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(
                config.T(32160).format(page + 1)),
            'subscription_feed', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


# The feed is the only listing that fans out over the subscribed channels, so
# it is the only one whose entry time grows with the account size. Requests run
# in small waves instead of one after another: the same calls to YouTube, but a
# wave costs the slowest channel instead of the sum of all of them. Results are
# still consumed in subscription order, so the listing stays stable.
_FEED_WORKERS = 6
_feed_refresh_lock = threading.Lock()


def _feed_channel_videos(url, per_channel):
    from browse import yt
    try:
        return yt.channel_videos(url, limit=per_channel)[:per_channel]
    except Exception as exc:
        config.log('feed {} failed: {}'.format(url, str(exc)[:100]))
        return []


def _iter_feed_channels(subs, per_channel, need):
    pool = ThreadPoolExecutor(max_workers=_FEED_WORKERS)
    fetched = 0
    try:
        for start in range(0, len(subs), _FEED_WORKERS):
            wave = [sub for sub in subs[start:start + _FEED_WORKERS]
                    if (sub or {}).get('url')]
            if not wave:
                continue
            futures = [(sub, pool.submit(_feed_channel_videos,
                                         sub.get('url') or '', per_channel))
                       for sub in wave]
            for sub, future in futures:
                videos = future.result()
                fetched += len(videos)
                yield sub, videos
                if fetched >= need:
                    return
    finally:
        pool.shutdown(wait=False)


def _collect_feed(need, per_channel):
    import store
    subs = sorted(store.get_subscriptions(),
                  key=lambda sub: -((sub or {}).get('added') or 0))
    collected = []
    for sub, videos in _iter_feed_channels(subs, per_channel, need):
        name = sub.get('title') or sub.get('url') or ''
        for entry in videos:
            item = dict(entry or {})
            if not item.get('video_id'):
                continue
            item['title'] = '{} - {}'.format(name, item.get('title') or item['video_id'])
            item['channel'] = item.get('channel') or name
            if sub.get('source') == 'local':
                item['_local_only'] = True
            collected.append(item)
    exhausted = len(collected) < need
    store.set_feed_full_cache(collected, need, exhausted)
    return collected, exhausted


def _refresh_feed_in_background(need, per_channel):
    if not _feed_refresh_lock.acquire(False):
        return

    def _run():
        try:
            if xbmc.Monitor().abortRequested():
                return
            collected, _exhausted = _collect_feed(need, per_channel)
            if collected and _bg_refresh_ok('subscription_feed'):
                xbmc.executeBuiltin('Container.Refresh')
        except Exception as exc:
            config.log('feed background refresh failed: {}'.format(str(exc)[:120]))
        finally:
            _feed_refresh_lock.release()

    thread = threading.Thread(target=_run, name='feed-refresh')
    thread.daemon = True
    thread.start()


@route('feed')
def feed(handle, params):
    import lists
    import store
    from browse import constants
    from music import detect
    page = _page(params)
    per_page = constants.results_per_page()
    per_channel = constants.feed_per_channel()
    need = (page + 1) * per_page + 1
    collected = []
    exhausted = True
    _full = store.get_feed_full_cache()
    if _full and len(_full.get('entries') or []) >= need:
        collected = _full.get('entries') or []
        exhausted = _full.get('exhausted', True)
    else:
        _stale = store.get_feed_full_cache(allow_stale=True)
        if _stale and (_stale.get('entries') or []):
            # Show the expired copy straight away and refill it behind the
            # listing. The wait is what people notice, not the staleness, and
            # this costs no extra request: the refresh is the one the user
            # would have triggered anyway by opening the feed.
            collected = _stale.get('entries') or []
            exhausted = _stale.get('exhausted', True)
            _refresh_feed_in_background(need, per_channel)
        else:
            collected, exhausted = _collect_feed(need, per_channel)
    collected = lists.fill_missing_meta(collected)
    try:
        _hide_all = bool(config.get_bool('hide_shorts', False))
    except Exception:
        _hide_all = False
    if _hide_all:
        collected = [item for item in collected if not item.get('is_shorts')]
    collected = lists.filter_blocked(collected)
    lists.set_context(collected)
    start = (page - 1) * per_page
    end = start + per_page
    items = [lists.video_item(
        entry, 'music_play' if detect.looks_like_music(entry) else 'play')
        for entry in collected[start:end]]
    if not exhausted or len(collected) > end:
        items.append(lists.folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(config.T(32160).format(page + 1)),
            'feed', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


@route('subscribed_channels')
def subscribed_channels(handle, params):
    import lists
    from browse.constants import results_per_page
    import store
    entries = [entry for entry in store.get_subscriptions()
               if isinstance(entry, dict) and entry.get('url')]
    entries.sort(key=lambda entry: -(entry.get('added') or 0))
    # Names first: an unnamed channel used to be listed as its whole url until
    # the resolver caught up, which is the first thing you see after a quick
    # Subscribe. Avatars are cosmetic, so they only get the leftover budget.
    _unnamed = [entry.get('url') for entry in entries
                if store.is_url_title(entry.get('title'), entry.get('url'))][:10]
    _missing = list(_unnamed)
    for entry in entries:
        if len(_missing) >= 13:
            break
        if store.needs_avatar(entry.get('image')) and entry.get('url') \
                not in _missing:
            _missing.append(entry['url'])
    if _missing:
        import threading as _threading
        _threading.Thread(target=_backfill_sub_thumbs, args=(_missing,),
                          daemon=True).start()
    page = _page(params)
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    items = []
    for entry in entries[start:end]:
        _title = entry.get('title') or ''
        _label = _title if not store.is_url_title(_title, entry.get('url')) \
            else _channel_handle(entry.get('url'))
        if entry.get('source') == 'local':
            _label = '{} [COLOR FF00FF7F][LOCAL][/COLOR]'.format(_label)
        items.append(lists.folder_item(_label, 'channel',
                                       entry.get('image'),
                                       {'url': entry.get('url'),
                                        'title': _title}))
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(config.T(32160).format(page + 1)),
            'subscribed_channels', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content=None)


@route('saved_playlists')
def saved_playlists(handle, params):
    import lists
    import store
    from browse import yt
    from browse.constants import results_per_page
    entries = store.get_library('saved_playlists')
    page = _page(params)
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page

    def _label(entry):
        # the skin fonts have no glyph for emoji, and a name made of nothing
        # but emoji would come out as a row of empty boxes
        title = lists.clean_title(entry.get('title') or '') or config.T(32194)
        try:
            count = int(entry.get('count') or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            title += ' [B][COLOR FFFFA500]({})[/COLOR][/B]'.format(count)
        if yt.is_private_playlist(entry.get('playlist_id')):
            title += ' [B][COLOR FFFF5555](Privat)[/COLOR][/B]'
        return title

    items = [lists.folder_item(_label(entry), 'playlist',
                               entry.get('image'),
                               {'url': entry.get('playlist_id')})
             for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(
                config.T(32160).format(page + 1)),
            'saved_playlists', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content=None)

def _label(entry):
    # the skin fonts have no glyph for emoji, and a playlist name that is
    # nothing but emoji is left empty rather than shown as empty boxes
    title = lists.clean_title(entry.get('title') or '') or config.T(32194)
    try:
        count = int(entry.get('count') or 0)
    except (TypeError, ValueError):
        count = 0
        if count > 0:
            title += ' [B][COLOR FFFFA500]({})[/COLOR][/B]'.format(count)
        if yt.is_private_playlist(entry.get('playlist_id')):
            title += ' [B][COLOR FFFF5555](Privat)[/COLOR][/B]'
        return title

    items = [lists.folder_item(_label(entry), 'playlist',
                               entry.get('image'),
                               {'url': entry.get('playlist_id')})
             for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(config.T(32160).format(page + 1)),
            'saved_playlists', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content=None)


@route('login')
def login(handle, params):
    import threading
    import time
    import xbmc
    from account import qr_login, youtube_sync
    from auth_dialog import QRProgressDialog, run_modal_main_thread
    account = youtube_sync.status()
    if account.get('connected'):
        import store
        try:
            n_subs = len(store.get_subscriptions())
        except Exception:
            n_subs = 0
        try:
            n_feed = len(store.get_library('subscription_feed'))
        except Exception:
            n_feed = 0
        xbmcgui.Dialog().ok(
            config.T(32093),
            '{}\n{}'.format(config.T(32094),
                            config.T(32095).format(n_subs, n_feed)))
        _back_to_account(handle)
        return
    pending = youtube_sync.pending_device_link()
    if not pending:
        try:
            pending = youtube_sync.start_device_link()
        except Exception as exc:
            xbmcgui.Dialog().ok(config.T(32167),
                                config.T(32187).format(exc))
            finish(handle)
            return
    try:
        qr_path = qr_login.create(pending.get('qr_url', ''))
    except Exception as exc:
        config.log('QR render failed: {}'.format(exc))
        qr_path = ''
    content = config.T(32188).format(
        pending.get('verification_url', ''),
        '[B][COLOR FF00FF7F]{}[/COLOR][/B]'.format(pending.get('user_code', '')))
    dialog = QRProgressDialog(
        'auth_qr.xml', config.ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(
            config.T(32167)),
        qr_image=qr_path or '',
        icon=config.icon('myyoutube'),
        addon_icon=config.addon_icon(),
        content=content)
    try:
        xbmcgui.Window(10000).setProperty('tmdbm.auth_modal_open', '1')
    except Exception:
        pass
    _result = {}
    _mon = xbmc.Monitor()
    _span = max(1, int(pending.get('expires_at', 0) or 0) - int(time.time()))

    def _poll():
        while not dialog.iscanceled() and not _mon.abortRequested():
            try:
                cur = youtube_sync.pending_device_link()
            except Exception:
                cur = {}
            if not cur:
                dialog.close()
                return
            try:
                res = youtube_sync.poll_pending_once()
            except Exception as exc:
                config.log('login poll failed: {}'.format(exc))
                res = {'state': 'waiting'}
            state = res.get('state')
            if state == 'authorized':
                _result['ok'] = True
                dialog.close()
                return
            if state == 'expired':
                _result['expired'] = True
                dialog.close()
                return
            if state == 'failed':
                _result['message'] = res.get('message', '')
                dialog.close()
                return
            if state == 'idle':
                dialog.close()
                return
            try:
                left = int(cur.get('expires_at', 0) or 0) - int(time.time())
            except Exception:
                left = 0
            dialog.update(max(0, int(left * 100 / _span)), content)
            time.sleep(2)

    threading.Thread(target=_poll, daemon=True).start()
    run_modal_main_thread(dialog)
    dialog.close()
    try:
        xbmcgui.Window(10000).clearProperty('tmdbm.auth_modal_open')
    except Exception:
        pass
    if _result.get('ok'):
        _notify(config.T(32179))
        _back_to_account(handle)
        threading.Thread(target=_sync_after_login, daemon=True).start()
        return
    if _result.get('expired'):
        _notify(config.T(32169))
    elif 'message' in _result:
        _notify(config.T(32174).format(_result.get('message', '')))
    else:
        import store
        store.clear_oauth_pending()
    _back_to_account(handle)


def _safe_bg_refresh(folder_hint=''):
    """Repaint from a worker thread only when it cannot land on a transition.

    Same guard as `_bg_refresh_ok`, plus a small pause: the login flow ends
    with `Container.Update(...my_youtube)`, and a refresh queued right behind
    that navigation is what makes Kodi crash on a 32 bit box.
    """
    try:
        xbmc.sleep(800)
    except Exception:
        pass
    if not _bg_refresh_ok(folder_hint):
        return False
    try:
        xbmc.executebuiltin('Container.Refresh')
        return True
    except Exception:
        return False


def _back_to_account(handle):
    finish(handle)
    xbmc.sleep(500)
    xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
        BASE_URL))


def _sync_after_login():
    try:
        from account import youtube_sync as _ys
        summary = _ys.sync_library()
    except Exception as exc:
        _notify(config.T(32174).format(str(exc)[:120]))
        return
    _notify(config.T(32191).format(
        summary.get('channels', 0), summary.get('videos', 0)), 6000)
    # From a thread: repaint only if the user is still on the account list.
    _safe_bg_refresh('my_youtube')


@route('sync_now')
def sync_now(handle, params):
    from account import youtube_sync
    _notify(config.T(32173))
    pending = youtube_sync.pending_device_link()
    result = youtube_sync.poll_pending_once() if pending else {'state': 'idle'}
    if result.get('state') == 'expired':
        _notify(config.T(32169))
        xbmc.executebuiltin('Container.Update({}?mode=login,replace)'.format(
            BASE_URL))
        return
    if result.get('state') == 'failed':
        _notify(config.T(32174).format(result.get('message', '')))
        xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
            BASE_URL))
        return
    if result.get('state') == 'waiting':
        _notify(config.T(32172))
        xbmc.executebuiltin('Container.Update({}?mode=login,replace)'.format(
            BASE_URL))
        return
    try:
        summary = youtube_sync.sync_library()
    except Exception as exc:
        _notify(config.T(32174).format(str(exc)[:120]))
        xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
            BASE_URL))
        return
    _notify(config.T(32191).format(
        summary.get('channels', 0), summary.get('videos', 0)), 6000)
    xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
        BASE_URL))


@route('donate')
def donate(handle, params):
    from auth_dialog import QRProgressDialog, run_modal_main_thread
    from account import qr_login
    import os
    url = qr_login.DONATE_URL
    qr_path = os.path.join(config.MEDIA_DIR, 'donate_qr.png')
    if not os.path.isfile(qr_path):
        try:
            qr_path = qr_login.create(url)
        except Exception as exc:
            config.log('donate QR failed: {}'.format(exc))
            qr_path = ''
    msg = ('Enjoying the addon?\nSupport its development\n'
           'and buy me a coffee!\n'
           'Link: [B][COLOR FF6AFB92]' + url + '[/COLOR][/B]\n'
           'Thank you for your support!')
    dialog = QRProgressDialog(
        'auth_qr.xml', config.ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR FF6AFB92]Support the Project[/COLOR][/B]',
        qr_image=qr_path or '',
        icon=config.icon('trailers'),
        addon_icon=config.addon_icon(),
        content=msg)
    run_modal_main_thread(dialog)
    dialog.close()
    finish(handle)


@route('upload_log')
def upload_log(handle, params):
    import requests
    import xbmcvfs
    dialog = xbmcgui.Dialog()
    choice = dialog.select(
        'Select log file',
        ['[B][COLOR FF6AFB92]kodi.log[/COLOR][/B] - active log',
         '[B][COLOR FFFF4444]kodi.old.log[/COLOR][/B] - old log'])
    if choice is None or choice < 0:
        cancel(handle)
        return
    filename = 'kodi.log' if choice == 0 else 'kodi.old.log'
    path = xbmcvfs.translatePath('special://logpath/{}'.format(filename))
    if not xbmcvfs.exists(path):
        dialog.ok('Error', 'File {} not found.'.format(filename))
        cancel(handle)
        return
    if not dialog.yesno(
            'Upload Kodi Log',
            'Do you want to upload {} to paste.kodi.tv?\n'
            'Useful for error reporting.'.format(filename)):
        cancel(handle)
        return
    url = 'https://paste.kodi.tv/'
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        log_file = xbmcvfs.File(path, 'r')
        text = log_file.read()
        log_file.close()
        if isinstance(text, str):
            text = text.encode('utf-8', errors='ignore')
        trimmed = False
        if len(text) > 350000:
            cut = text[-350000:].find(b'\n')
            text = text[-350000 + cut + 1:] if cut > 0 else text[-350000:]
            trimmed = True
        response = requests.post('{}documents'.format(url), data=text,
                                 timeout=20.0)
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        if response.status_code != 200:
            body = (response.text or '')[:200]
            dialog.ok('Error',
                      'Upload failed: server returned HTTP {}.\n{}'.format(
                          response.status_code, body))
            cancel(handle)
            return
        try:
            data = response.json()
        except Exception:
            body = (response.text or '')[:200]
            dialog.ok('Error',
                      'Upload failed: server response was not '
                      'JSON.\n{}'.format(body))
            cancel(handle)
            return
        if 'key' in data:
            link = '{}{}'.format(url, data['key'])
            extra = '\n(Log trimmed to last ~350KB, paste limit.)' \
                if trimmed else ''
            dialog.ok('Upload Successful',
                      'The log was uploaded successfully!{}'
                      '\n\nLink: [B][COLOR FF6AFB92]{}[/COLOR][/B]'.format(
                          extra, link))
        else:
            dialog.ok('Error', 'Upload failed. Check the Kodi log.')
    except Exception as exc:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        config.log('upload log failed: {}'.format(exc), xbmc.LOGERROR)
        dialog.ok('Error', 'Load error: {}'.format(exc))
    cancel(handle)


@route('clear_cache')
def clear_cache(handle, params):
    from browse import constants
    from music import queue
    try:
        ok = bool(constants.reset_cache())
    except Exception as exc:
        config.log('cache reset failed: {}'.format(exc))
        ok = False
    try:
        from player import _clear_extract_cache
        if not _clear_extract_cache():
            ok = False
    except Exception as exc:
        config.log('extract cache reset failed: {}'.format(exc))
        ok = False
    try:
        store_clear_queue(queue)
    except Exception as exc:
        config.log('queue reset failed: {}'.format(exc))
    xbmcgui.Dialog().ok(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        config.T(32192) if ok else config.T(32193))
    xbmc.executebuiltin('Container.Refresh')


def store_clear_queue(queue):
    import store
    store.set_library('music_pool', [])
    store.set_library('subscription_feed', [])
    store.set_library('subscribed_channels', [])
    store.set_library('saved_playlists', [])
    store.set_library('remote_history', [])
    store.set_library('watch_later_remote', [])
    store.clear_feed_cache()
    store.clear_yt_meta_cache()
    queue.clear()


@route('logout')
def logout(handle, params):
    from account import youtube_sync
    account = youtube_sync.status()
    if not account.get('connected') and not account.get('pending'):
        _notify(config.T(32177))
        return
    if xbmcgui.Dialog().yesno(config.T(32168),
                               config.T(32182),
                               nolabel=config.T(32133), yeslabel=config.T(32126)):
        youtube_sync.disconnect()
        _notify(config.T(32178))
    xbmc.executebuiltin('Container.Refresh')


def _build_roots():
    del _ROOT_ITEMS[:]
    add_root(config.T(32100), 'search', config.icon('search'))
    add_root(config.T(32101), 'trending', config.icon('trending'))
    add_root(config.T(32102), 'random_music', config.icon('random'))
    add_root(config.T(32103), 'live', config.icon('live'))
    add_root(config.T(32104), 'trailers', config.icon('trailers'))
    add_root(config.T(32105), 'charts', config.icon('charts'))
    add_root(config.T(32106), 'my_youtube', config.icon('myyoutube'))
    add_root(config.T(32107), 'feed', config.icon('feed'))
    add_root(config.T(32108), 'watch_later', config.icon('watchlater'))
    add_root(config.T(32109), 'history', config.icon('history'))
    add_root(config.T(32110), 'local_playlists', config.icon('playlists'))
    add_root(config.T(32111), 'open_settings', config.icon('settings'),
             folder=False)


_build_roots()