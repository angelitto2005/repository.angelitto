# -*- coding: utf-8 -*-
# NewPipe Addon
# Author Twilight0
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSES/GPL-3.0-only for more information.
# All routes registered on urldispatcher; main.py only dispatches.
from urllib.parse import parse_qs, urlencode, urlparse

import xbmc
import xbmcgui

from scrapetube import get_search
from tulip import directory, kodi
from tulip.log import log
from urldispatcher import urldispatcher

from . import player as playback
from . import qr_login
from . import storage
from . import yt
from . import youtube_sync
from . import localization
from . import ui


_STATE_PREFIX = 'np:'
# YouTube hqdefault is 480x360 (4:3), which leaves vertical black bars in
# landscape cards. mqdefault is 320x180 (16:9) and exists reliably for videos.
_THUMBNAIL_URL = 'https://i.ytimg.com/vi/{0}/mqdefault.jpg'
# The visible labels are translated by ui.py; the query term itself is converted
# at request time by localization.py according to the content language.
TRENDING_CATEGORIES = [
    ('music', 30160, 'music'),
    ('gaming', 30161, 'gaming'),
    ('news', 30162, 'news'),
    ('movies', 30163, 'movies'),
    ('live', 30164, 'live'),
]
LIVE_CATEGORIES = [
    ('news', 30162, 'news'),
    ('music', 30160, 'music'),
    ('games', 30161, 'gaming'),
    ('sports', 30165, 'sports'),
    ('podcasts', 30166, 'podcasts'),
]
_LEGACY_TRENDING_QUERIES = {
    'Music': 'Música', 'Gaming': 'Jogos', 'News': 'Notícias',
    'Movies': 'Filmes', 'Live': 'Ao vivo',
}
_LEGACY_LIVE_QUERIES = {
    'News': 'Notícias ao vivo', 'Music': 'Música ao vivo',
    'Gaming': 'Jogos ao vivo', 'Sports': 'Esportes ao vivo',
    'Podcasts': 'Podcasts ao vivo',
}
_TRAILER_QUERIES = {
    'pt_dubbed': 'trailer oficial filme dublado em português',
    'pt_subtitled': 'trailer oficial filme legendado em português',
    'en_original': 'official movie trailer',
    'es': 'tráiler oficial película español',
    'ro': 'trailer oficial film română',
}
_TRAILER_SEARCH_SUFFIXES = {
    'pt_dubbed': 'trailer oficial dublado em português',
    'pt_subtitled': 'trailer oficial legendado em português',
    'en_original': 'official movie trailer',
    'es': 'tráiler oficial película español',
    'ro': 'trailer oficial film română',
}


def _text(value, fallback=''):
    """Resolve numeric labels through the selected NewPipe MOD UI language."""
    if isinstance(value, int):
        return ui.text(value, fallback)
    return value or fallback


def _item(entry):
    entry = dict(entry)
    if 'title' in entry:
        entry['title'] = _text(entry['title'], _text(30186, 'Unknown'))
    if isinstance(entry.get('cm'), list):
        fixed = []
        for cm in entry['cm']:
            cm = dict(cm)
            cm['title'] = _text(cm.get('title'), '')
            fixed.append(cm)
        entry['cm'] = fixed
    # A string query is the compact route state handled by main.py. Tulip
    # serializes it as one parameter, then main.py restores its key/value data.
    if 'query' in entry and not isinstance(entry['query'], str):
        entry.pop('query')
    return entry


def _build(items, **kwargs):
    # Mark video rows explicitly. Arctic Fuse uses ``ListItem.DBType=video``
    # to choose the landscape-card layout.
    if kwargs.get('content') == 'videos' and 'mediatype' not in kwargs:
        kwargs['mediatype'] = 'video'
    directory.builder([_item(i) for i in items if i], **kwargs)


def _setting(key, default=''):
    try:
        value = kodi.setting(key)
        return value if value not in (None, '') else default
    except Exception:
        return default


def _limit(default_key='results_per_page', fallback=25):
    try:
        return max(1, int(_setting(default_key, fallback)))
    except (TypeError, ValueError):
        return fallback


def _configured_category(setting_id, categories, fallback):
    """Return the category selected in settings, without showing a dialog."""
    selected = str(_setting(setting_id, '')).strip()
    for identifier, _label, query in categories:
        if selected == identifier:
            return query
    return fallback


def _trailer_query():
    """Return the language-specific trailer query selected in settings."""
    return _TRAILER_QUERIES.get(
        str(_setting('trailer_language', 'pt_dubbed')).strip(),
        _TRAILER_QUERIES['pt_dubbed'])


def _trailer_search_query(query):
    """Add the configured trailer language/version to a user search."""
    suffix = _TRAILER_SEARCH_SUFFIXES.get(
        str(_setting('trailer_language', 'pt_dubbed')).strip(),
        _TRAILER_SEARCH_SUFFIXES['pt_dubbed'])
    return '{0} {1}'.format((query or '').strip(), suffix).strip()


def _page_number(page):
    try:
        return max(1, int(page))
    except (TypeError, ValueError):
        return 1


def _state(**params):
    """Encode route parameters through Tulip's supported ``query`` field."""
    values = [(key, str(value)) for key, value in params.items() if value is not None]
    return _STATE_PREFIX + urlencode(values)


def _icon(name):
    try:
        return kodi.addonmedia(name + '.png')
    except Exception:
        return ''


def _artwork(image):
    """Make list cards use item artwork and deliberately clear fanart."""
    if not image:
        return {'fanart': ''}
    return {
        'icon': image,
        'thumb': image,
        'poster': image,
        'landscape': image,
        'banner': image,
        'fanart': '',
    }


def _video_artwork(image):
    """Expose a YouTube frame as landscape art, never as a poster.

    Arctic Fuse selects landscape video art only when thumb differs from (or
    has no) poster. Do not set icon either: matching icon and fanart would
    cause the skin to reject the landscape candidate.
    """
    if not image:
        return {'fanart': ''}
    return {
        'thumb': image,
        'landscape': image,
        'banner': image,
        'fanart': image,
    }


def _video_id(url):
    if not url:
        return ''
    if url.startswith('http'):
        query = parse_qs(urlparse(url).query)
        if 'v' in query:
            return query['v'][0]
        tail = url.rstrip('/').rsplit('/', 1)[-1]
        return tail[:11] if len(tail) >= 11 else tail
    return url


def _video_thumbnail(item):
    """Always prefer YouTube's stable per-video thumbnail endpoint."""
    video_id = _video_id(item.get('url', ''))
    if video_id:
        return _THUMBNAIL_URL.format(video_id)
    return item.get('image', '')


def _route_folder(title, action, image='', **params):
    return {
        'title': title,
        'action': action,
        'query': _state(**params),
        'image': image or _icon('search'),
        'artwork': _artwork(image or _icon('search')),
        'fanart': '',
        'isFolder': 'True',
        'isPlayable': 'False',
    }


def _next_page(action, current_page, **params):
    next_params = dict(params)
    next_params['page'] = _page_number(current_page) + 1
    return _route_folder(
        '{0} {1}'.format(_text(30034, 'Next page'), next_params['page']),
        action,
        _icon('next'),
        **next_params
    )


def _build_paged(fetch, item_builder, action, route_params=None, page=1, content='videos'):
    """Build one page of results, loading one extra item to detect a next page."""
    page = _page_number(page)
    per_page = _limit()
    requested = page * per_page + 1
    try:
        source = list(fetch(requested) or [])
    except Exception as exc:
        log('NewPipe page {0} failed: {1}'.format(page, exc))
        source = []

    start = (page - 1) * per_page
    end = start + per_page
    items = [item_builder(entry) for entry in source[start:end]]
    if len(source) > end:
        items.append(_next_page(action, page, **(route_params or {})))
    _build(items, content=content)


def _channel_cm(channel_url, channel_title=''):
    if not channel_url:
        return []
    return [{
        'title': 30026,
        'query': {'action': 'channel', 'url': channel_url, 'title': channel_title or ''},
    }]


def _video_item(item, channel_url='', channel_title='', profile='default'):
    video_id = _video_id(item.get('url', ''))
    title = item.get('title') or _text(30186, 'Unknown')
    if item.get('is_live'):
        title = '[LIVE] ' + title
    cm = _channel_cm(channel_url, channel_title)
    if video_id:
        cm.append({
            'title': 30088,
            'query': {
                'action': 'watch_later_add',
                'url': video_id,
                'title': title,
                'image': _video_thumbnail(item),
                'channel_url': channel_url or '',
                'channel_title': channel_title or '',
            },
        })
    if channel_url:
        known = any(s.get('url') == channel_url for s in storage.get_subscriptions())
        cm.append({
            'title': 30015 if known else 30013,
            'query': {'action': 'unsubscribe' if known else 'subscribe',
                      'url': channel_url, 'title': channel_title or ''},
        })
    image = _video_thumbnail(item)
    entry = {
        'title': title,
        'action': 'play',
        'url': video_id,
        'image': image,
        # Video cards are landscape artwork. No poster is sent: forcing a
        # 16:9 YouTube image into poster is what creates black side bars in
        # Arctic Fuse's wide-card view.
        'artwork': _video_artwork(image),
        'fanart': image,
        'duration': item.get('duration') or 0,
        'isFolder': 'False',
        'isPlayable': 'True',
        'cm': cm,
    }
    if profile == 'trailer':
        # Tulip preserves the compact query on playable items; main.py expands
        # it before dispatching the play route.
        entry['query'] = _state(profile='trailer')
    return entry


def _channel_thumb(item):
    try:
        thumbs = item.get('thumbnail', {}).get('thumbnails') or []
        return thumbs[-1].get('url', '') if thumbs else ''
    except (AttributeError, IndexError):
        return ''


def _channel_title(item):
    title = item.get('title', '')
    if isinstance(title, dict):
        return title.get('simpleText') or ''
    return title if isinstance(title, str) else ''


def _channel_id(item):
    return item.get('channelId') or item.get('browseId') or ''


@urldispatcher.register('root')
def root():
    _build([
        {'title': 30001, 'action': 'search', 'icon': _icon('search'), 'image': _icon('search'),
         'isFolder': 'True', 'isPlayable': 'False'},
        {'title': 30025, 'action': 'trending', 'icon': _icon('trending'), 'image': _icon('trending'),
         'isFolder': 'True', 'isPlayable': 'False'},
        {'title': 30018, 'action': 'live', 'icon': _icon('live'), 'image': _icon('live'),
         'isFolder': 'True', 'isPlayable': 'False'},
        {'title': 30051, 'action': 'trailers', 'icon': _icon('trending'), 'image': _icon('trending'),
         'isFolder': 'True', 'isPlayable': 'False'},
        {'title': 30084, 'action': 'subscriptions', 'icon': _icon('subscriptions'),
         'image': _icon('subscriptions'), 'isFolder': 'True', 'isPlayable': 'False'},
        {'title': 30005, 'action': 'open_settings', 'icon': _icon('settings'), 'image': _icon('settings'),
         'isFolder': 'False', 'isPlayable': 'False'},
    ])


@urldispatcher.register('open_settings')
def open_settings():
    kodi.openSettings()


@urldispatcher.register('search', kwargs=['query'])
def search(query=None):
    if not query:
        history = [{
            'title': 30006, 'action': 'search_input', 'icon': _icon('search'), 'image': _icon('search'),
            'isFolder': 'True', 'isPlayable': 'False',
        }]
        history += [
            {'title': q, 'action': 'search_results', 'url': q, 'isFolder': 'True', 'isPlayable': 'False',
             'cm': [{'title': 30008, 'query': {'action': 'forget_search', 'url': q}}]}
            for q in storage.get_searches()
        ]
        _build(history)
        return
    search_results(query)


@urldispatcher.register('search_input')
def search_input():
    query = kodi.dialog.input(heading=_text(30001, 'Search'))
    if query:
        storage.add_search(query)
        search_results(query)
    else:
        kodi.close_all()


@urldispatcher.register('clear_searches')
def clear_searches():
    storage.clear_searches()
    kodi.refresh()


@urldispatcher.register('clear_cache')
def clear_cache():
    from .constants import reset_cache
    ok = bool(reset_cache())
    kodi.infoDialog(_text(30032 if ok else 30033))
    kodi.refresh()


@urldispatcher.register('trending', kwargs=['query', 'page'])
def trending(query=None, page=1):
    if not query:
        query = _configured_category(
            'trending_category', TRENDING_CATEGORIES, 'music')
    else:
        # Links made with version 1.0.2 must not preserve the old global
        # English query after this localized-category update.
        query = _LEGACY_TRENDING_QUERIES.get(query, query)
    query = localization.category_query(query)
    _build_paged(
        lambda limit: yt.trending_videos(query, limit=limit),
        lambda entry: _video_item(*entry),
        'trending',
        {'query': query},
        page=page,
    )


def _live_results(query, limit):
    items = [entry for entry in yt.live_videos(query, limit=limit * 3) if entry[0].get('is_live')]
    if not items:
        return yt.live_videos(query + ' live', limit=limit)
    return items


@urldispatcher.register('live', kwargs=['query', 'page'])
def live(query=None, page=1):
    if not query:
        query = _configured_category(
            'live_category', LIVE_CATEGORIES, 'news')
    else:
        query = _LEGACY_LIVE_QUERIES.get(query, query)
    query = localization.category_query(query, live=True)
    _build_paged(
        lambda limit: _live_results(query, limit),
        lambda entry: _video_item(*entry),
        'live',
        {'query': query},
        page=page,
    )


@urldispatcher.register('trailers', kwargs=['page'])
def trailers(page=1):
    """List trailers in the configured language without a selection dialog."""
    query = _trailer_query()
    _build_paged(
        lambda limit: yt.trailer_videos(query, limit=limit),
        lambda entry: _video_item(*entry, profile='trailer'),
        'trailers',
        page=page,
    )


@urldispatcher.register('forget_search', kwargs=['url'])
def forget_search(url):
    storage.remove_search(url)
    kodi.refresh()


def _list_channels(query, page=1):
    # This route calls Scrapetube directly, so initialize the same explicit
    # NewPipe-style ``hl``/``gl`` content locale used by the yt adapter.
    yt.configure()

    def make_item(raw):
        channel_id = _channel_id(raw)
        if not channel_id:
            return None
        url = 'https://www.youtube.com/channel/' + channel_id
        title = _channel_title(raw) or channel_id
        image = _channel_thumb(raw)
        return {
            'title': title,
            'action': 'channel',
            'query': _state(url=url, title=title),
            'image': image,
            'artwork': _artwork(image),
            'fanart': '',
            'isFolder': 'True',
            'isPlayable': 'False',
            'cm': [{'title': 30013, 'query': {'action': 'subscribe', 'url': url, 'title': title}}],
        }

    _build_paged(
        lambda limit: get_search(query, limit=limit, sleep=0, results_type='channel'),
        make_item,
        'search_results',
        {'url': query, 'kind': 'channel'},
        page=page,
    )


def _list_playlist_results(query, page=1):
    _build_paged(
        lambda limit: yt.search_playlists(query, limit=limit),
        _playlist_item,
        'search_results',
        {'url': query, 'kind': 'playlist'},
        page=page,
    )


@urldispatcher.register('search_results', kwargs=['url', 'kind', 'page'])
def search_results(url, kind=None, page=1):
    if kind not in ('video', 'channel', 'playlist', 'trailer'):
        kinds = [_text(30010), _text(30011), _text(30012), _text(30051)]
        choice = kodi.selectDialog(kinds, heading=_text(30001, 'Search'))
        if choice < 0:
            kodi.close_all()
            return
        kind = ('video', 'channel', 'playlist', 'trailer')[choice]

    storage.add_search(url)
    if kind == 'channel':
        _list_channels(url, page=page)
    elif kind == 'playlist':
        _list_playlist_results(url, page=page)
    elif kind == 'trailer':
        trailer_query = _trailer_search_query(url)
        _build_paged(
            lambda limit: yt.trailer_videos(trailer_query, limit=limit),
            lambda entry: _video_item(*entry, profile='trailer'),
            'search_results',
            {'url': url, 'kind': 'trailer'},
            page=page,
        )
    else:
        _build_paged(
            lambda limit: yt.search_videos(url, limit=limit),
            lambda entry: _video_item(*entry),
            'search_results',
            {'url': url, 'kind': 'video'},
            page=page,
        )


def _playlist_item(item):
    title = item.get('title') or 'Untitled playlist'
    url = item.get('url', '')
    marked = any(mark.get('url') == url for mark in storage.get_bookmarks())
    image = item.get('image', '')
    return {
        'title': title,
        'action': 'playlist',
        'query': _state(url=url),
        'image': image,
        'artwork': _artwork(image),
        'fanart': '',
        'isFolder': 'True',
        'isPlayable': 'False',
        'cm': [{
            'title': 30029 if marked else 30028,
            'query': {'action': 'unbookmark' if marked else 'bookmark',
                      'url': url, 'title': title, 'image': image},
        }],
    }


@urldispatcher.register('channel', kwargs=['url', 'title'])
def channel(url, title=''):
    subscriptions = storage.get_subscriptions()
    known = next((sub for sub in subscriptions if sub.get('url') == url), None)
    name = title or (known.get('title') if known else '') or url
    toggle = {'title': 30015, 'query': {'action': 'unsubscribe', 'url': url}} if known else \
        {'title': 30013, 'query': {'action': 'subscribe', 'url': url, 'title': name}}
    _build([
        _route_folder(30016, 'channel_videos', _icon('search'), url=url, tab='videos'),
        _route_folder(30017, 'channel_videos', _icon('search'), url=url, tab='shorts'),
        _route_folder(30018, 'channel_videos', _icon('live'), url=url, tab='streams'),
        _route_folder(30012, 'channel_playlists', _icon('bookmarks'), url=url),
        dict(toggle, action='unsubscribe' if known else 'subscribe', isFolder='False', isPlayable='False'),
    ])


@urldispatcher.register('channel_videos', kwargs=['url', 'tab', 'page', 'query'])
def channel_videos(url, tab='videos', page=1, query=None):
    # ``query`` keeps links made by pre-pagination NewPipe builds working.
    tab = query or tab or 'videos'
    subscriptions = storage.get_subscriptions()
    known = next((sub for sub in subscriptions if sub.get('url') == url), None)
    _build_paged(
        lambda limit: yt.channel_videos(url, tab=tab, limit=limit),
        lambda video: _video_item(video, channel_url=url,
                                  channel_title=known.get('title') if known else ''),
        'channel_videos',
        {'url': url, 'tab': tab},
        page=page,
    )


@urldispatcher.register('channel_playlists', kwargs=['url', 'page'])
def channel_playlists(url, page=1):
    _build_paged(
        lambda limit: yt.channel_playlists(url, limit=limit),
        _playlist_item,
        'channel_playlists',
        {'url': url},
        page=page,
    )


@urldispatcher.register('playlist', kwargs=['url', 'page'])
def playlist(url, page=1):
    _build_paged(
        lambda limit: yt.playlist_videos(url, limit=limit),
        _video_item,
        'playlist',
        {'url': url},
        page=page,
    )


@urldispatcher.register('subscribe', kwargs=['url', 'title'])
def subscribe(url, title=''):
    storage.subscribe(title or url, url)
    kodi.infoDialog(kodi.i18n(30014))
    kodi.refresh()


@urldispatcher.register('unsubscribe', kwargs=['url'])
def unsubscribe(url):
    storage.unsubscribe(url)
    kodi.refresh()


@urldispatcher.register('bookmark', kwargs=['url', 'title', 'image'])
def bookmark(url, title='', image=''):
    storage.bookmark(title or url, url, image)
    kodi.infoDialog(kodi.i18n(30030))
    kodi.refresh()


@urldispatcher.register('unbookmark', kwargs=['url'])
def unbookmark(url):
    storage.unbookmark(url)
    kodi.refresh()


@urldispatcher.register('bookmarks', kwargs=['page'])
def bookmarks(page=1):
    _build_paged(
        lambda limit: storage.get_bookmarks(),
        _playlist_item,
        'bookmarks',
        page=page,
    )


@urldispatcher.register('subscriptions')
def subscriptions():
    account = youtube_sync.status()
    # Match the account hub of plugin.video.youtube: account folders first,
    # then connection controls. Every folder reads a locally saved snapshot;
    # the only network call is the explicit Sync action.
    controls = [
        _route_folder(30085, 'subscription_feed', _icon('feed')),
        _route_folder(30083, 'subscription_channels', _icon('subscriptions')),
        _route_folder(30086, 'watch_later', _icon('bookmarks')),
        _route_folder(30087, 'saved_playlists', _icon('bookmarks')),
        _route_folder(30004, 'account_history', _icon('history')),
    ]
    if account.get('pending'):
        controls.append({
            'title': 30064, 'action': 'youtube_connect', 'image': _icon('subscriptions'),
            'artwork': _artwork(_icon('subscriptions')), 'isFolder': 'True', 'isPlayable': 'False',
        })
    elif not account.get('connected'):
        controls.append({
            'title': 30060, 'action': 'youtube_connect', 'image': _icon('subscriptions'),
            'artwork': _artwork(_icon('subscriptions')), 'isFolder': 'True', 'isPlayable': 'False',
        })
    else:
        # A linked account can exist before an earlier catalogue import
        # succeeds. Keep a visible retry action instead of forcing a new QR.
        controls.extend([
            {
                'title': 30061, 'action': 'youtube_sync_now', 'image': _icon('subscriptions'),
                'artwork': _artwork(_icon('subscriptions')), 'isFolder': 'False', 'isPlayable': 'False',
            },
            {
                'title': 30062, 'action': 'youtube_disconnect', 'image': _icon('history'),
                'artwork': _artwork(_icon('history')), 'isFolder': 'False', 'isPlayable': 'False',
            },
        ])
    _build(controls, content='files')


def _subscription_channel_item(sub):
    image = sub.get('image') or _icon('subscriptions')
    return {
        'title': sub.get('title') or sub.get('url'), 'action': 'channel', 'url': sub.get('url'),
        'image': image, 'artwork': _artwork(image), 'fanart': '',
        'isFolder': 'True', 'isPlayable': 'False',
        'cm': [{'title': 30015, 'query': {'action': 'unsubscribe', 'url': sub.get('url')}}],
    }


@urldispatcher.register('subscription_channels', kwargs=['page'])
def subscription_channels(page=1):
    """List the imported/local channel cards in their own NewPipe MOD-style folder."""
    _build_paged(
        lambda limit: storage.get_subscriptions(),
        _subscription_channel_item,
        'subscription_channels',
        page=page,
        content='videos',
    )


def _account_video_item(entry, remove_watch_later=False):
    item = _video_item(
        entry,
        entry.get('channel_url', ''),
        entry.get('channel_title', ''),
    )
    if remove_watch_later:
        item['cm'] = [menu for menu in item.get('cm', [])
                      if menu.get('query', {}).get('action') != 'watch_later_add']
        item['cm'].append({
            'title': 30089,
            'query': {'action': 'watch_later_remove',
                      'url': entry.get('video_id') or entry.get('url', '')},
        })
    return item


@urldispatcher.register('subscription_feed', kwargs=['page'])
def subscription_feed(page=1):
    """Display the saved authenticated TV feed, with a local-feed fallback."""
    source = storage.get_youtube_library('subscription_feed')
    if not source:
        # Existing manual channel subscriptions still work without a TV login.
        feed(page)
        return
    _build_paged(
        lambda limit: source,
        _account_video_item,
        'subscription_feed',
        page=page,
    )


def _unique_videos(*collections):
    found = {}
    for collection in collections:
        for entry in collection or []:
            video_id = entry.get('video_id') or entry.get('url') or ''
            if video_id and video_id not in found:
                found[video_id] = dict(entry)
    return list(found.values())


@urldispatcher.register('watch_later', kwargs=['page'])
def watch_later(page=1):
    """Account Watch Later snapshot plus the private local fallback list."""
    source = _unique_videos(
        storage.get_youtube_library('watch_later'), storage.get_watch_later())
    _build_paged(
        lambda limit: source,
        lambda entry: _account_video_item(entry, remove_watch_later=True),
        'watch_later',
        page=page,
    )


@urldispatcher.register('watch_later_add', kwargs=['url', 'title', 'image', 'channel_url', 'channel_title'])
def watch_later_add(url, title='', image='', channel_url='', channel_title=''):
    video_id = _video_id(url)
    storage.add_watch_later({
        'video_id': video_id,
        'url': video_id,
        'title': title or video_id,
        'image': image or _THUMBNAIL_URL.format(video_id),
        'channel_url': channel_url,
        'channel_title': channel_title,
    })
    kodi.infoDialog(_text(30088, 'Add to Watch Later'))
    kodi.refresh()


@urldispatcher.register('watch_later_remove', kwargs=['url'])
def watch_later_remove(url):
    storage.remove_watch_later(_video_id(url))
    kodi.refresh()


@urldispatcher.register('saved_playlists', kwargs=['page'])
def saved_playlists(page=1):
    """Saved account playlists followed by the old local bookmark list."""
    remote = storage.get_youtube_library('saved_playlists')
    local = storage.get_bookmarks()
    seen = set()
    source = []
    for entry in list(remote) + list(local):
        url = entry.get('url', '')
        if url and url not in seen:
            seen.add(url)
            source.append(entry)
    _build_paged(lambda limit: source, _playlist_item, 'saved_playlists', page=page)


@urldispatcher.register('account_history', kwargs=['page'])
def account_history(page=1):
    """Use the account-history snapshot when present; retain local history offline."""
    source = storage.get_youtube_library('remote_history')
    if not source:
        history(page)
        return
    _build_paged(lambda limit: source, _account_video_item, 'account_history', page=page)


@urldispatcher.register('youtube_connect')
def youtube_connect():
    existing = youtube_sync.status()
    if existing.get('pending'):
        youtube_login_menu()
        return
    elif existing.get('connected'):
        kodi.infoDialog(_text(30079, 'YouTube account is already connected'))
        return
    else:
        try:
            pending = youtube_sync.start_device_link()
        except Exception as exc:
            kodi.text_viewer(_text(30060, 'Connect YouTube account'),
                             '{0}\n\n{1}'.format(_text(30067, 'Connection setup failed'), exc))
            return
    youtube_login_menu()


@urldispatcher.register('youtube_new_code')
def youtube_new_code():
    """Discard an old device code and open a freshly generated login submenu."""
    youtube_sync.cancel_device_link()
    try:
        youtube_sync.start_device_link()
    except Exception as exc:
        kodi.text_viewer(_text(30060, 'Connect YouTube account'),
                         '{0}\n\n{1}'.format(
                             _text(30067, 'Connection setup failed'), exc))
        return
    youtube_login_menu()


@urldispatcher.register('youtube_login_menu')
def youtube_login_menu():
    """Open the activation controls as a NewPipe submenu, not a popup."""
    pending = youtube_sync.pending_device_link()
    if not pending:
        youtube_connect()
        return

    try:
        qr_path = qr_login.create(pending.get('qr_url', ''))
    except Exception as exc:
        log('NewPipe QR image failed: {0}'.format(exc))
        kodi.text_viewer(_text(30060, 'Connect YouTube account'),
                         '{0}\n\n{1}\n\n{2}\n[B]{3}[/B]\n\n{4}'.format(
                             _text(30065, 'Open this address in a browser:'),
                             pending.get('verification_url', 'https://yt.be/activate'),
                             _text(30066, 'Enter this code:'),
                             pending.get('user_code', ''),
                             _text(30068, 'After authorization, NewPipe synchronizes automatically.')))
        return

    _build([
        {
            'title': _text(30091, 'Step 1 — Scan QR code'), 'action': 'youtube_show_qr', 'url': qr_path,
            'image': qr_path, 'artwork': _artwork(qr_path), 'fanart': '',
            'isFolder': 'False', 'isPlayable': 'False',
        },
        {
            'title': _text(30092, 'Step 2 — Use manual code: {0}').format(
                pending.get('user_code', '')),
            'action': 'youtube_show_code', 'image': _icon('subscriptions'),
            'artwork': _artwork(_icon('subscriptions')), 'isFolder': 'False', 'isPlayable': 'False',
        },
        {
            'title': _text(30094, 'Generate new code'), 'action': 'youtube_new_code',
            'image': _icon('history'), 'artwork': _artwork(_icon('history')),
            'isFolder': 'False', 'isPlayable': 'False',
        },
        {
            'title': _text(30093, 'Step 3 — Confirm connection'), 'action': 'youtube_sync_now',
            'image': _icon('subscriptions'), 'artwork': _artwork(_icon('subscriptions')),
            'isFolder': 'False', 'isPlayable': 'False',
        },
        {
            'title': _text(30095, 'Cancel connection'), 'action': 'youtube_cancel_login',
            'image': _icon('history'), 'artwork': _artwork(_icon('history')),
            'isFolder': 'False', 'isPlayable': 'False',
        },
    ], content='files')


@urldispatcher.register('youtube_show_qr', kwargs=['url'])
def youtube_show_qr(url):
    """Use Kodi's native aspect-ratio-aware picture viewer for the QR."""
    if url:
        safe_url = url.replace('"', '')
        log('NewPipe abrindo QR: {0}'.format(safe_url))
        xbmc.executebuiltin('ShowPicture({0})'.format(safe_url))


@urldispatcher.register('youtube_show_code')
def youtube_show_code():
    pending = youtube_sync.pending_device_link()
    if not pending:
        kodi.infoDialog(_text(30180, 'Activation code expired. Start again.'))
        return
    kodi.text_viewer(_text(30181, 'Sign in to YouTube'),
                     _text(30182, 'Open: {0}\n\nEnter the code:\n[B]{1}[/B]\n\nAfter authorizing, return to this submenu and choose “Step 3 — Confirm connection”.').format(
                         pending.get('verification_url', 'https://yt.be/activate'),
                         pending.get('user_code', '')))


@urldispatcher.register('youtube_cancel_login')
def youtube_cancel_login():
    youtube_sync.cancel_device_link()
    kodi.refresh()


@urldispatcher.register('youtube_sync_now')
def youtube_sync_now():
    def open_account_menu():
        """Replace the transient QR submenu with the linked-account hub."""
        try:
            xbmc.executebuiltin(
                'Container.Update(plugin://plugin.video.newpipe/?action=subscriptions,replace)')
        except Exception as exc:
            log('NewPipe não abriu o menu de sincronização: {0}'.format(exc))

    def refresh_library():
        # DialogProgress is not available in some Android Kodi builds. Use the
        # native notification API instead: it is displayed immediately, does
        # not block the request and works with the installed Estuary skin.
        try:
            xbmcgui.Dialog().notification(
                'NewPipe MOD',
                _text(30184, 'Synchronizing YouTube subscriptions…'), time=10000)
        except Exception as exc:
            log('NewPipe não mostrou aviso de sincronização: {0}'.format(exc))
        summary = youtube_sync.sync_library()
        message = _text(30183, '{0} channels, {1} videos').format(
            summary.get('channels', 0), summary.get('videos', 0))
        kodi.infoDialog(_text(30069, 'YouTube subscriptions synchronized: {0}').format(message))

    result = youtube_sync.poll_pending_once()
    if result.get('state') == 'authorized':
        try:
            refresh_library()
            open_account_menu()
            return
        except Exception as exc:
            kodi.infoDialog(_text(30070, 'YouTube sync failed: {0}').format(exc))
    elif result.get('state') == 'waiting':
        kodi.infoDialog(_text(30064, 'YouTube authorization is pending'))
    elif result.get('state') == 'expired':
        kodi.infoDialog(_text(30071, 'The YouTube authorization code expired. Start again.'))
    elif result.get('state') == 'failed':
        kodi.infoDialog(_text(30070, 'YouTube sync failed: {0}').format(
            result.get('message', _text(30185, 'Unknown error'))))
    else:
        try:
            refresh_library()
            open_account_menu()
            return
        except Exception as exc:
            kodi.infoDialog(_text(30070, 'YouTube sync failed: {0}').format(exc))
    kodi.refresh()


@urldispatcher.register('youtube_disconnect')
def youtube_disconnect():
    if kodi.yesnoDialog(_text(30072, 'Disconnect from YouTube? Local subscriptions remain.')):
        youtube_sync.disconnect()
        kodi.infoDialog(_text(30073, 'YouTube account disconnected'))
        kodi.refresh()


def _feed_item(entry):
    video, channel_url, channel_title = entry
    item = _video_item(video, channel_url, channel_title)
    item['title'] = '{0} - {1}'.format(channel_title, item['title'])
    return item


@urldispatcher.register('feed', kwargs=['page'])
def feed(page=1):
    per_channel = _limit(default_key='feed_per_channel', fallback=5)
    items = []
    for subscription in storage.get_subscriptions():
        try:
            videos = yt.channel_videos(subscription.get('url'), limit=per_channel)[:per_channel]
            items.extend((video, subscription.get('url'), subscription.get('title') or '') for video in videos)
        except Exception as exc:
            log('NewPipe feed error for {0}: {1}'.format(subscription.get('url'), exc))
    _build_paged(lambda limit: items, _feed_item, 'feed', page=page)


def _history_item(entry):
    item = _video_item({
        'url': entry.get('video_id'),
        'title': entry.get('title') or entry.get('video_id'),
        'image': entry.get('image', ''),
    })
    item['cm'].append({
        'title': 30057,
        'query': {'action': 'remove_history', 'url': entry.get('video_id', '')},
    })
    return item


def _clear_history_item():
    image = _icon('history')
    return {
        'title': 30056,
        'action': 'clear_history',
        'image': image,
        'artwork': _artwork(image),
        'fanart': '',
        'isFolder': 'False',
        'isPlayable': 'False',
    }


@urldispatcher.register('history', kwargs=['page'])
def history(page=1):
    page = _page_number(page)
    per_page = _limit()
    source = storage.get_history()
    start = (page - 1) * per_page
    end = start + per_page
    items = [_history_item(entry) for entry in source[start:end]]
    if page == 1:
        items.insert(0, _clear_history_item())
    if len(source) > end:
        items.append(_next_page('history', page))
    _build(items, content='videos')


@urldispatcher.register('clear_history')
def clear_history():
    if kodi.yesnoDialog(_text(30058), heading=_text(30004)):
        storage.clear_history()
        kodi.refresh()


@urldispatcher.register('remove_history', kwargs=['url'])
def remove_history(url):
    storage.remove_history(url)
    kodi.refresh()


@urldispatcher.register('play', kwargs=['url', 'title', 'image', 'profile'])
def play(url, title='', image='', profile='default'):
    video_id = _video_id(url)
    storage.add_history({'video_id': video_id, 'title': title or video_id, 'image': image or ''})
    playback.play(video_id, title=title, image=image, profile=profile)
