import os
import sys
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


def route(name):
    def decorator(func):
        _ROUTES[name] = func
        return func
    return decorator


def add_root(label, mode, image='', folder=True):
    _ROOT_ITEMS.append((label, mode, image, folder))


def build(handle, items, content='videos', cache=True):
    """Kodi may cache a listing on disk. That is fine as long as the
    localisation changes: the service clears it and refreshes when the country
    or the language setting changes, so the next build uses the new ones.
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
    try:
        handler(handle, params)
    except Exception as exc:
        import traceback
        config.log('Route {} failed: {}'.format(mode, exc), xbmc.LOGERROR)
        config.log(traceback.format_exc(), xbmc.LOGERROR)
        finish(handle)


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
    items = []
    for label, mode, image, folder in _ROOT_ITEMS:
        url, li, is_folder = lists.folder_item(label, mode, image,
                                               folder=folder)
        items.append((url, li, is_folder))
    build(handle, items, content=None, cache=False)


@route('open_settings')
def open_settings(handle, params):
    config.ADDON.openSettings()


# ------------------------------------------------------------------------ search
@route('search')
def search(handle, params):
    import lists
    import store
    prefill = str(params.get('q') or '').strip()
    items = []
    if prefill:
        items.append(lists.action_item(
            'Search Now', 'search_input', config.icon('search'),
            {'q': prefill},
            'Search YouTube for: {}'.format(prefill), folder=False))
        items.append(lists.action_item(
            'Empty Search', 'search_input', config.icon('search'), {},
            folder=False))
    else:
        items.append(lists.action_item(
            'Search YouTube', 'search_input', config.icon('search'), {},
            folder=False))
    for query in store.get_searches():
        items.append(lists.folder_item(
            query, 'search_results',
            config.icon('play') or config.addon_icon() or config.icon('search'),
            {'q': query, 'kind': 'video'},
            cm=[('[B][COLOR FFFF5555]Delete[/COLOR][/B]',
                 lists.run_plugin('forget_search', {'q': query}))][0:3]))
    if store.get_searches():
        items.append(lists.action_item(
            '[COLOR FFFF5555]Delete all search history[/COLOR]', 'clear_searches',
            config.icon('history')))
    build(handle, items, content=None)


@route('search_input')
def search_input(handle, params):
    import store
    default = str(params.get('q') or '')
    query = xbmcgui.Dialog().input('Search YouTube', default,
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
        lists.folder_item('Videos', 'search_results',
                          config.icon('search'), {'q': query, 'kind': 'video'}),
        lists.folder_item('Channels', 'search_results',
                          config.icon('subscriptions'),
                          {'q': query, 'kind': 'channel'}),
        lists.folder_item('Playlists', 'search_results',
                          config.icon('bookmarks'),
                          {'q': query, 'kind': 'playlist'}),
        lists.folder_item('Trailers', 'search_results',
                          config.icon('play'),
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
                                 entry['channel_id']},
                description=' '.join(x for x in (entry['subs'], entry['count']) if x)),
            'search_results', {'q': query, 'kind': 'channel'}, page=page)
    elif kind == 'playlist':
        def fetch(limit):
            return yt.search_playlists(query, limit=limit)
        items, content = lists.paged(
            fetch, lambda entry: lists.folder_item(
                entry['title'], 'playlist', entry['image'],
                {'url': entry['playlist_id']},
                description=' '.join(x for x in (entry['channel'], entry['count']) if x)),
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
@route('trending')
def trending(handle, params):
    import lists
    from browse import constants, localization, yt
    from music import detect, queue
    category_id = constants.trending_category()
    category = localization.category_query(category_id)
    music_folder = category_id == 'music'
    page = _page(params)
    entries = yt.trending_videos(category, limit=page * constants.results_per_page() + 1)
    if music_folder:
        queue.save_pool([entry for entry in entries if detect.looks_like_music(entry)])

    def builder(entry):
        mode = 'music_play' if (music_folder and detect.looks_like_music(entry)) else 'play'
        return lists.video_item(entry, mode)
    items, content = lists.paged(lambda limit: entries, builder, 'trending',
                                 {}, page=page)
    build(handle, items, content=content)


@route('live')
def live(handle, params):
    import lists
    from browse import constants, localization, yt
    category = localization.category_query(constants.live_category(), live=True)
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.live_videos(category, limit=limit),
        lambda entry: lists.video_item(entry, 'play'),
        'live', {}, page=page)
    build(handle, items, content=content)


@route('trailers')
def trailers(handle, params):
    import lists
    from browse import constants, localization, yt
    query = localization.trailer_query()
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.trailer_videos(query, limit=limit),
        lambda entry: lists.video_item(entry, 'play'),
        'trailers', {}, page=page)
    build(handle, items, content=content)


@route('random_music')
def random_music(handle, params):
    import lists
    from browse import constants, localization, yt
    from music import queue
    category = localization.category_query('music')
    page = _page(params)
    entries = yt.trending_videos(category,
                                limit=max(page * constants.results_per_page() + 1, 60))
    queue.save_pool(entries)
    items, content = lists.paged(
        lambda limit: entries,
        lambda entry: lists.video_item(entry, 'music_play'),
        'random_music', {}, page=page)
    build(handle, items, content=content)


@route('go_channel')
def go_channel(handle, params):
    import lists
    from browse import meta
    video_id = lists.video_id(params.get('video_id'))
    info = meta.video_meta(video_id) if video_id else {}
    channel_id = (info or {}).get('channel_id') or ''
    if not channel_id:
        _notify('Channel not found')
        return
    xbmc.executebuiltin('Container.Update({}?{},replace)'.format(
        BASE_URL, urlencode({'mode': 'channel',
                             'url': 'https://www.youtube.com/channel/' + channel_id,
                             'title': (info or {}).get('channel') or ''})))


@route('sub_channel')
def sub_channel(handle, params):
    import lists
    import store
    from browse import meta
    video_id = lists.video_id(params.get('video_id'))
    info = meta.video_meta(video_id) if video_id else {}
    channel_id = (info or {}).get('channel_id') or ''
    if not channel_id:
        _notify('Channel not found')
        return
    title = (info or {}).get('channel') or ''
    store.subscribe(title, 'https://www.youtube.com/channel/' + channel_id)
    _notify('Subscribed to {}'.format(title))


@route('channel')
def channel(handle, params):
    import lists
    import store
    url = params.get('url') or ''
    title = params.get('title') or ''
    known = next((item for item in store.get_subscriptions()
                  if item.get('url') == url), None)
    name = title or (known or {}).get('title') or url
    toggle = ('unsubscribe', '[B][COLOR FF00CED1]Unsubscribe[/COLOR][/B]') if known \
        else ('subscribe', '[B][COLOR FF00CED1]Subscribe[/COLOR][/B]')
    items = [
        lists.folder_item('Videos', 'channel_videos', config.icon('search'),
                          {'url': url, 'tab': 'videos'}),
        lists.folder_item('Shorts', 'channel_videos', config.icon('search'),
                          {'url': url, 'tab': 'shorts'}),
        lists.folder_item('Live', 'channel_videos', config.icon('live'),
                          {'url': url, 'tab': 'streams'}),
        lists.folder_item('Playlists', 'channel_playlists',
                          config.icon('bookmarks'), {'url': url}),
        lists.action_item(toggle[1], toggle[0], config.icon('subscriptions'),
                          {'url': url, 'title': name,
                           'image': (known or {}).get('image', '')}),
    ]
    build(handle, [item[0:3] for item in items], content=None)


@route('channel_videos')
def channel_videos(handle, params):
    import lists
    from browse import yt
    from music import detect
    url = params.get('url') or ''
    tab = params.get('tab') or 'videos'
    page = _page(params)

    def fetch(limit):
        return yt.channel_videos(url, tab=tab, limit=limit)

    def builder(entry):
        mode = 'music_play' if detect.looks_like_music(entry) else 'play'
        return lists.video_item(entry, mode)
    items, content = lists.paged(fetch, builder, 'channel_videos',
                                 {'url': url, 'tab': tab}, page=page)
    build(handle, items, content=content)


@route('channel_playlists')
def channel_playlists(handle, params):
    import lists
    from browse import yt
    url = params.get('url') or ''
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.channel_playlists(url, limit=limit),
        lambda entry: lists.folder_item(entry['title'], 'playlist',
                                        entry['image'],
                                        {'url': entry['playlist_id']},
                                        description=entry.get('count', '')),
        'channel_playlists', {'url': url}, page=page)
    build(handle, items, content=content)


@route('playlist')
def playlist(handle, params):
    import lists
    from browse import yt
    url = params.get('url') or ''
    page = _page(params)
    items, content = lists.paged(
        lambda limit: yt.playlist_videos(url, limit=limit),
        lambda entry: lists.video_item(entry, 'play'),
        'playlist', {'url': url}, page=page)
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
    playback.start_queue(handle, params)


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
    cancel(handle)


# ----------------------------------------------------------------------- library
@route('subscribe')
def subscribe(handle, params):
    import store
    store.subscribe(params.get('title') or '', params.get('url') or '',
                    params.get('image') or '')
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        'Subscribed to {}'.format(params.get('title') or ''),
        config.addon_icon(), time=2500)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('unsubscribe')
def unsubscribe(handle, params):
    import store
    store.unsubscribe(params.get('url') or '')
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        'Unsubscribed', config.addon_icon(), time=2500)
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('watch_later_add')
def watch_later_add(handle, params):
    import lists
    import store
    store.add_watch_later(lists.history_entry(params))
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        'Added to Watch Later', config.addon_icon(), time=2500)
    cancel(handle)


@route('watch_later')
def watch_later(handle, params):
    import lists
    import store
    from browse import constants
    entries = _merge_remote(store.get_watch_later(),
                            store.get_library('watch_later_remote'))
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
        items.append(lists.folder_item('[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
                                       'watch_later', config.icon('nextpage'),
                                       {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


@route('watch_later_remove')
def watch_later_remove(handle, params):
    import store
    store.remove_watch_later(params.get('video_id') or '')
    finish(handle)
    xbmc.executebuiltin('Container.Refresh')


@route('history')
def history(handle, params):
    import lists
    import store
    from browse import constants
    entries = _merge_remote(store.get_history(),
                            store.get_library('remote_history'))
    page = _page(params)
    per_page = constants.results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    lists.set_listing('history', {}, page)
    lists.set_context(entries)
    items = [lists.video_item(entry, 'play', cm=[
        ('[B][COLOR FFFF5555]Remove from history[/COLOR][/B]',
         lists.run_plugin('remove_history',
                          {'video_id': entry.get('video_id')}))])
        for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item('[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
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
def _notify(message, time_ms=4000):
    xbmcgui.Dialog().notification(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        message, config.addon_icon(), time=time_ms)


@route('my_youtube')
def my_youtube(handle, params):
    import lists
    from account import youtube_sync
    account = youtube_sync.status()
    items = []
    if account.get('connected'):
        items.append(lists.folder_item(
            'My subscriptions', 'subscription_feed', config.icon('feed')))
        items.append(lists.folder_item(
            'Subscribed channels', 'subscribed_channels',
            config.icon('subscriptions')))
        items.append(lists.folder_item(
            'Watch Later', 'watch_later', config.icon('bookmarks')))
        items.append(lists.folder_item(
            'Saved playlists', 'saved_playlists', config.icon('bookmarks')))
        items.append(lists.folder_item(
            'Watch history', 'history', config.icon('history')))
        items.append(lists.action_item(
            '[B][COLOR FF00CED1]Sync now[/COLOR][/B]', 'sync_now',
            config.icon('subscriptions'), folder=False))
        items.append(lists.action_item(
            '[B][COLOR FFFF5555]Disconnect[/COLOR][/B]', 'logout',
            config.icon('subscriptions'), folder=False))
    elif account.get('pending'):
        items.append(lists.folder_item(
            '[B][COLOR FFFF4500]Finish activation[/COLOR][/B]', 'login',
            config.icon('subscriptions')))
    else:
        items.append(lists.action_item(
            '[B][COLOR FF00CED1]Connect YouTube account (QR code)[/COLOR][/B]',
            'login', config.icon('subscriptions'),
            description='Link your YouTube account to browse subscriptions, '
                        'Watch Later, playlists and history.'))
    build(handle, [item[0:3] for item in items], content=None)


@route('subscription_feed')
def subscription_feed(handle, params):
    import lists
    import store
    from browse.constants import results_per_page
    entries = store.get_library('subscription_feed')
    page = _page(params)
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    lists.set_listing('subscription_feed', {}, page)
    lists.set_context(entries)
    items = [lists.video_item(entry, 'play') for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
            'subscription_feed', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content='videos', cache=False)


@route('subscribed_channels')
def subscribed_channels(handle, params):
    import lists
    from browse.constants import results_per_page
    import store
    entries = store.get_library('subscribed_channels')
    page = _page(params)
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    items = [lists.folder_item(entry['title'] or entry['url'], 'channel',
                               entry.get('image'), {'url': entry['url']})
             for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
            'subscribed_channels', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content=None)


@route('saved_playlists')
def saved_playlists(handle, params):
    import lists
    from browse.constants import results_per_page
    import store
    entries = store.get_library('saved_playlists')
    page = _page(params)
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    items = [lists.folder_item(entry['title'], 'playlist',
                               entry.get('image'),
                               {'url': entry.get('playlist_id')})
             for entry in entries[start:end]]
    if len(entries) > end:
        items.append(lists.folder_item(
            '[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
            'saved_playlists', config.icon('nextpage'), {'page': page + 1}))
    build(handle, items, content=None)


@route('login')
def login(handle, params):
    from account import youtube_sync
    account = youtube_sync.status()
    if account.get('connected'):
        _notify('YouTube account is already connected')
        finish(handle, update=True)
        return
    if not account.get('pending'):
        try:
            youtube_sync.start_device_link()
        except Exception as exc:
            xbmcgui.Dialog().ok('Connect YouTube account',
                                'Could not start the activation: {}'.format(exc))
            finish(handle)
            return
    login_menu(handle, params)


@route('login_menu')
def login_menu(handle, params):
    import lists
    from account import qr_login, youtube_sync
    pending = youtube_sync.pending_device_link()
    if not pending:
        login(handle, params)
        return
    qr_path = ''
    try:
        qr_path = qr_login.create(pending.get('qr_url', ''))
    except Exception as exc:
        config.log('QR render failed: {}'.format(exc))
    if not qr_path:
        xbmcgui.Dialog().ok(
            'Connect YouTube account',
            'Open this address: {}\n\nEnter this code:\n{}'.format(
                pending.get('verification_url', ''), pending.get('user_code', '')))
        finish(handle)
        return
    items = [
        lists.action_item(
            '[B][COLOR FF00CED1]Step 1 - Scan this QR code[/COLOR][/B]',
            'show_qr', qr_path, {'path': qr_path},
            description='Scan with the YouTube app on your phone (or open the '
                        'activation page and enter the code).',
            folder=False),
        lists.action_item(
            '[B][COLOR FF00CED1]Step 2 - Manual code: {}[/COLOR][/B]'.format(
                pending.get('user_code', '')),
            'show_code', config.icon('subscriptions'), {}, folder=False),
        lists.action_item(
            '[B][COLOR FFFF4500]Generate a new code[/COLOR][/B]', 'new_code',
            config.icon('history'), {}),
        lists.action_item(
            '[B][COLOR FF00CED1]Step 3 - Confirm connection[/COLOR][/B]',
            'sync_now', config.icon('subscriptions'), {}),
        lists.action_item(
            '[B][COLOR FFFF5555]Cancel[/COLOR][/B]', 'cancel_login',
            config.icon('history'), {}),
    ]
    build(handle, [item[0:3] for item in items], content=None, cache=False)


@route('show_qr')
def show_qr(handle, params):
    path = str(params.get('path') or '').replace('"', '')
    if path:
        xbmc.executebuiltin('ShowPicture({})'.format(path))


@route('show_code')
def show_code(handle, params):
    from account import youtube_sync
    pending = youtube_sync.pending_device_link()
    if not pending:
        _notify('The activation code expired, start again')
        return
    xbmcgui.Dialog().ok(
        'Sign in to YouTube',
        '1. Open: {}\n\n2. Enter the code:\n[COLOR FFFF4500]{}[/COLOR]\n\n'
        '3. Come back and choose "Step 3 - Confirm connection".'.format(
            pending.get('verification_url', ''), pending.get('user_code', '')))


@route('new_code')
def new_code(handle, params):
    from account import youtube_sync
    import store
    store.clear_oauth_pending()
    try:
        youtube_sync.start_device_link()
    except Exception as exc:
        _notify('Could not generate a new code: {}'.format(exc))
        finish(handle)
        return
    finish(handle)
    xbmc.executebuiltin('Container.Update({}?mode=login_menu,replace)'.format(
        BASE_URL))


@route('cancel_login')
def cancel_login(handle, params):
    import store
    store.clear_oauth_pending()
    finish(handle)
    _notify('Activation cancelled')
    xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
        BASE_URL))


@route('sync_now')
def sync_now(handle, params):
    from account import youtube_sync
    _notify('Syncing YouTube...')
    pending = youtube_sync.pending_device_link()
    result = youtube_sync.poll_pending_once() if pending else {'state': 'idle'}
    if result.get('state') == 'expired':
        _notify('The activation code expired, start again')
        xbmc.executebuiltin('Container.Update({}?mode=login,replace)'.format(
            BASE_URL))
        return
    if result.get('state') == 'failed':
        _notify('Sync failed: {}'.format(result.get('message', '')))
        xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
            BASE_URL))
        return
    if result.get('state') == 'waiting':
        _notify('Still waiting for approval on your phone')
        xbmc.executebuiltin('Container.Update({}?mode=login_menu,replace)'.format(
            BASE_URL))
        return
    try:
        summary = youtube_sync.sync_library()
    except Exception as exc:
        _notify('Sync failed: {}'.format(str(exc)[:120]))
        xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
            BASE_URL))
        return
    _notify('Synced: {0} channels, {1} videos'.format(
        summary.get('channels', 0), summary.get('videos', 0)), 6000)
    xbmc.executebuiltin('Container.Update({}?mode=my_youtube,replace)'.format(
        BASE_URL))


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
        store_clear_queue(queue)
    except Exception as exc:
        config.log('queue reset failed: {}'.format(exc))
    xbmcgui.Dialog().ok(
        '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B]',
        'Cache cleared' if ok else 'Could not clear the cache')
    xbmc.executebuiltin('Container.Refresh')


def store_clear_queue(queue):
    import store
    store.set_library('music_pool', [])
    store.set_library('subscription_feed', [])
    store.set_library('subscribed_channels', [])
    store.set_library('saved_playlists', [])
    store.set_library('remote_history', [])
    store.set_library('watch_later_remote', [])
    queue.clear()


@route('logout')
def logout(handle, params):
    from account import youtube_sync
    if xbmcgui.Dialog().yesno('Disconnect YouTube account?', nolabel='Cancel',
                              yeslabel='Disconnect'):
        youtube_sync.disconnect()
        _notify('YouTube account disconnected')
    xbmc.executebuiltin('Container.Refresh')


add_root('Search', 'search', config.icon('search'))
add_root('Trending', 'trending', config.icon('music'))
add_root('Random music', 'random_music', config.icon('music'))
add_root('Live', 'live', config.icon('live'))
add_root('Trailers', 'trailers', config.icon('play'))
add_root('My YouTube', 'my_youtube', config.icon('subscriptions'))
add_root('Watch Later', 'watch_later', config.icon('bookmarks'))
add_root('History', 'history', config.icon('history'))
add_root('Settings', 'open_settings', config.icon('settings'), folder=False)