from urllib.parse import urlencode
import re

import xbmcgui

import config
import router
import store
from browse.constants import results_per_page

THUMBNAIL_URL = 'https://i.ytimg.com/vi/{}/mqdefault.jpg'

_BAD_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x1D100, 0x1D1FF),
    (0x2100, 0x214F),
    (0x2190, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF),
    (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2B00, 0x2BFF),
    (0x3000, 0x303F),
    (0x3200, 0x33FF),
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
    (0x20000, 0x2FFFF),
    (0x3040, 0x30FF), (0x1100, 0x11FF),
    (0x3130, 0x318F), (0xAC00, 0xD7AF),
    (0xE000, 0xF8FF), (0xE0000, 0xE007F),
)
_SILENT_RANGES = (
    (0x200B, 0x200F), (0x2028, 0x2029), (0x20D0, 0x20FF),
    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
)
_BAD_SINGLE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_BAD_CODEPOINTS = frozenset((0xA9, 0xAE))
_BAD_COLLAPSE = re.compile(r'\|\s*\|')


def _is_bad(code):
    if code in _BAD_CODEPOINTS:
        return True
    for low, high in _BAD_RANGES:
        if low <= code <= high:
            return True
    return False


def _is_silent(code):
    for low, high in _SILENT_RANGES:
        if low <= code <= high:
            return True
    return False


def clean_title(value, single_line=True):
    return _clean_lines(str(value or ''), single_line)


def _clean_lines(text, single_line):
    if single_line:
        return _clean_run(text)
    return '\n'.join(_clean_run(line) for line in text.split('\n'))


def _clean_run(text):
    text = _BAD_SINGLE.sub('', text)
    out = []
    bad_run = False
    for char in text:
        code = ord(char)
        if _is_silent(code):
            continue
        if _is_bad(code):
            bad_run = True
            continue
        if bad_run:
            out.append('|')
            bad_run = False
        out.append(char)
    if bad_run:
        out.append('|')
    return _BAD_COLLAPSE.sub(
        '|', re.sub(r'\s+', ' ', ''.join(out))).strip().strip('|').strip()

_SUB_NAMES = {}


def _sub_channel_name(channel_id):
    if not channel_id:
        return ''
    if not _SUB_NAMES:
        try:
            subs = store.get_subscriptions() or []
        except Exception:
            subs = []
        for sub in subs:
            cid = sub.get('youtube_subscription_id') or ''
            if not cid and sub.get('url'):
                cid = sub['url'].rstrip('/').rsplit('/', 1)[-1]
            if cid:
                _SUB_NAMES.setdefault(cid, sub.get('title') or '')
    return _SUB_NAMES.get(channel_id, '')
_CLEAN_RE = re.compile(r'\[/?(?:B|I)\]|\[COLOR[^\]]*\]|\[/COLOR\]')


def video_id(value):
    value = str(value or '')
    if value.startswith('http'):
        if 'v=' in value:
            return value.split('v=', 1)[1].split('&', 1)[0].split('?', 1)[0]
        tail = value.rstrip('/').rsplit('/', 1)[-1]
        return tail[:11]
    return value


def set_context(entries):
    """Remember the list the user is looking at, in the order shown.

    Autoplay continues with exactly these videos, in this order, instead of
    building a separate playlist out of something else.
    """
    items = []
    seen = set()
    for entry in entries or []:
        vid = video_id(entry.get('video_id'))
        if not vid or vid in seen:
            continue
        seen.add(vid)
        items.append({
            'video_id': vid,
            'title': entry.get('title') or '',
            'image': entry.get('image') or thumbnail(vid),
            'duration': int(entry.get('duration') or 0),
            'is_live': bool(entry.get('is_live')),
            'channel': entry.get('channel') or '',
            'channel_id': entry.get('channel_id') or '',
            'views': entry.get('views') or '',
            'vdate': entry_date(entry),
            'snippet': entry.get('snippet') or '',
        })
    if items:
        store.set_state('list_context', {'entries': items})


def context_entries():
    return store.get_state('list_context').get('entries') or []


def set_listing(mode, params=None, page=1):
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    store.set_state('list_route', {
        'mode': mode,
        'params': dict(params or {}),
        'page': max(1, page),
    })


def queue_play_url(entry):
    query = entry_params(entry)
    query['mode'] = 'queue_play'
    return router.BASE_URL + '?' + urlencode(query)


def playlist_item(entry):
    entry = entry or {}
    vid = video_id(entry.get('video_id'))
    title = clean_title(entry.get('title')) or vid or ''
    li = xbmcgui.ListItem(label=title)
    image = entry.get('image') or thumbnail(vid)
    if image:
        li.setArt({'icon': image, 'thumb': image, 'fanart': image})
    info = video_info(entry)
    _set_video_info(li, title, info, entry.get('duration'))
    li.setProperty('IsPlayable', 'true')
    menus = _song_menus(entry, vid)
    if menus:
        li.addContextMenuItems(menus)
    return li


_MENU_MEMO_SUBS = {}
_MENU_MEMO_BLOCKED = [None]


def clear_menu_memo():
    _MENU_MEMO_SUBS.clear()
    _MENU_MEMO_BLOCKED[0] = None


def _menu_is_subscribed(channel_url):
    if channel_url not in _MENU_MEMO_SUBS:
        _MENU_MEMO_SUBS[channel_url] = store.is_subscribed(channel_url)
    return _MENU_MEMO_SUBS[channel_url]


def _menu_is_blocked(vid):
    if _MENU_MEMO_BLOCKED[0] is None:
        try:
            from music import queue as _queue
            _MENU_MEMO_BLOCKED[0] = _queue.blocked()
        except Exception:
            _MENU_MEMO_BLOCKED[0] = set()
    return bool(vid) and vid in _MENU_MEMO_BLOCKED[0]


def _menu_channel_id(entry, vid):
    """Channel id for the subscribe menu: the entry, else the metadata cache.

    Trending and friends only keep a channel id that starts with UC, so plenty
    of rows arrive without one - and without it the menu had no way to tell
    whether the channel was already joined, which is why it kept saying
    Subscribe forever. The metadata cache the listing already filled in holds
    it, and reading it is a file read, not a network call.
    """
    channel_id = str(entry.get('channel_id') or '').strip()
    if channel_id:
        return channel_id
    try:
        return str((store.get_yt_meta(vid) or {}).get('channel_id')
                   or '').strip()
    except Exception:
        return ''


def _song_menus(entry, vid, in_watch_later=False):
    entry = entry or {}
    menus = []
    channel_url = ''
    channel_id = _menu_channel_id(entry, vid)
    if channel_id:
        channel_url = 'https://www.youtube.com/channel/' + channel_id
        menus.append((
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32152)),
            'ActivateWindow(Videos,{})'.format(
                router.BASE_URL + '?' + urlencode(
                    {'mode': 'channel', 'url': channel_url,
                     'title': entry.get('channel') or ''}))))
        known = _menu_is_subscribed(channel_url)
        menus.append((
            '[B][COLOR {}]{}[/COLOR][/B]'.format(
                'FFFF5555' if known else 'FF00FF7F',
                config.T(32154) if known else config.T(32153)),
            run_plugin('unsubscribe' if known else 'subscribe',
                       {'url': channel_url,
                        'title': entry.get('channel') or '',
                        'image': ''})))
    elif vid:
        # Channel still unknown at build time: the action decides when clicked.
        menus.append((
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32152)),
            run_plugin('go_channel', {'video_id': vid})))
        menus.append((
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32309)),
            run_plugin('sub_channel', {'video_id': vid})))
    if vid:
        if not in_watch_later:
            menus.append(('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(config.T(32155)),
                          run_plugin('watch_later_add', entry_params(entry))))
        menus.append(('[B][COLOR yellow]{}[/COLOR][/B]'.format(config.T(32110)),
                      run_plugin('local_playlist_add', entry_params(entry))))
        _is_blocked = _menu_is_blocked(vid)
        if _is_blocked:
            menus.append(('[B][COLOR FF00FF7F]{}[/COLOR][/B]'.format(config.T(32157)),
                          run_plugin('unblock', {'video_id': vid})))
        else:
            menus.append(('[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32158)),
                          run_plugin('no_autoplay', {'video_id': vid})))
        artist = str(entry.get('channel') or '').strip()
        title_artist = artist_from_title(entry.get('title'))
        if artist or store.is_name_blocked(title_artist):
            hits = store.blocked_matches(entry, title_artist)
            if hits:
                menus.append((
                    '[B][COLOR FF00FF7F]{}[/COLOR][/B]'.format(config.T(32515)),
                    run_plugin('unblock_artist', entry_params(entry))))
            else:
                menus.append((
                    '[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32516)),
                    run_plugin('block_channel', entry_params(entry))))
                if title_artist:
                    menus.append((
                        '[B][COLOR FFFF5555]{}[/COLOR][/B]'.format(config.T(32517)),
                        run_plugin('block_artist', entry_params(entry))))
    return menus


def _queue_entry(entry):
    entry = entry or {}
    vid = video_id(entry.get('video_id'))
    return {
        'video_id': vid,
        'title': entry.get('title') or '',
        'image': entry.get('image') or thumbnail(vid),
        'duration': int(entry.get('duration') or 0),
        'is_live': bool(entry.get('is_live')),
        'channel': entry.get('channel') or '',
        'channel_id': entry.get('channel_id') or '',
        'views': entry.get('views') or '',
        'vdate': entry_date(entry),
        'snippet': entry.get('snippet') or '',
    }


def fill_missing_meta(entries, timeout=5.0):
    from browse import meta
    from concurrent.futures import ThreadPoolExecutor, wait
    import store as _store
    entries = list(entries or [])
    pending = [dict(entry or {}) for entry in entries
               if (entry or {}).get('video_id')
               and (not (entry or {}).get('channel')
                    or not (entry or {}).get('snippet')
                    or not entry_date(entry or {}))]
    if not pending:
        return entries
    cached = {}
    fetch = []
    for entry in pending:
        vid = video_id(entry.get('video_id'))
        info = _store.get_yt_meta(vid)
        if not info and _store.is_yt_meta_failed(vid):
            continue
        # A cached row without a date is not complete: the music chart parser
        # has no date to begin with, so it must be refilled instead of
        # serving the same empty value for the whole store TTL.
        needs_date = not entry_date(entry)
        if info and not (needs_date and not info.get('published')):
            merged = dict(entry)
            merged['channel'] = merged.get('channel') or info.get('channel') or ''
            merged['channel_id'] = merged.get('channel_id') or info.get('channel_id') or ''
            merged['views'] = merged.get('views') or info.get('views') or ''
            merged['vdate'] = entry_date(merged) or info.get('published') or ''
            if not merged.get('duration'):
                try:
                    merged['duration'] = int(info.get('duration') or 0)
                except (TypeError, ValueError):
                    pass
            merged['snippet'] = merged.get('snippet') or info.get('description') or ''
            cached[vid] = merged
        else:
            fetch.append(entry)
    pending = fetch
    if not pending:
        return [cached.get(video_id(entry.get('video_id')), entry)
                for entry in entries]
    try:
        pool = ThreadPoolExecutor(max_workers=8)
    except Exception:
        return list(entries or [])
    try:
        futures = {pool.submit(meta.full_entry_meta,
                               video_id(entry.get('video_id'))): entry
                   for entry in pending}
        done, _ = wait(set(futures), timeout=timeout)
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
    filled = {}
    failed = 0
    first_error = ''
    for future in done:
        entry = futures.get(future)
        try:
            info = future.result() or {}
        except Exception as exc:
            failed += 1
            try:
                _store.set_yt_meta_failed(
                    video_id((entry or {}).get('video_id')))
            except Exception:
                pass
            if not first_error:
                first_error = str(exc)[:160]
            continue
        if not info:
            failed += 1
            try:
                _store.set_yt_meta_failed(
                    video_id((entry or {}).get('video_id')))
            except Exception:
                pass
            if not first_error:
                first_error = 'empty meta'
            continue
        merged = dict(entry)
        merged['channel'] = merged.get('channel') or info.get('channel') or ''
        merged['channel_id'] = merged.get('channel_id') or info.get('channel_id') or ''
        merged['views'] = merged.get('views') or info.get('views') or ''
        merged['vdate'] = entry_date(merged) or info.get('published') or ''
        if not merged.get('duration'):
            try:
                merged['duration'] = int(info.get('duration') or 0)
            except (TypeError, ValueError):
                pass
        merged['snippet'] = merged.get('snippet') or info.get('description') or ''
        filled[merged['video_id']] = merged
        try:
            stored = {
                'channel': merged.get('channel') or '',
                'channel_id': merged.get('channel_id') or '',
                'views': merged.get('views') or '',
                'duration': merged.get('duration') or 0,
                'description': merged.get('snippet') or ''}
            if merged.get('vdate'):
                stored['published'] = merged['vdate']
            else:
                # No date anywhere: park it like a failed lookup so the next
                # visit retries instead of trusting an undated cache row.
                _store.set_yt_meta_failed(merged['video_id'])
            _store.set_yt_meta(merged['video_id'], stored)
        except Exception:
            pass
    for future in set(futures) - done:
        # Unfinished means the deadline cut the queue short, not that the
        # lookup failed: parking it as a failed lookup would hide the metadata
        # for the whole failure TTL. Real failures are parked in the loop above.
        try:
            future.cancel()
        except Exception:
            pass
    if failed:
        config.log('meta fill: {}/{} filled, {} failed (first error: {})'.format(
            len(filled), len(pending), failed, first_error or '?'),
            always=True)
    else:
        config.debug('meta fill: {}/{} filled'.format(len(filled),
                                                      len(pending)))
    filled.update(cached)
    return [filled.get(video_id(entry.get('video_id')), entry)
            for entry in entries]


def persist_filled(source_name, original, filled):
    try:
        original = list(original or [])
        filled = list(filled or [])
        if len(original) != len(filled) or not original:
            return
        if all(dict(f or {}) == dict(o or {})
               for f, o in zip(filled, original)):
            return
        store.set_library(str(source_name or ''), filled)
    except Exception:
        pass


def fetch_listing_page(listing, per_page):
    from browse import constants, localization, yt
    listing = listing or {}
    mode = listing.get('mode') or ''
    params = listing.get('params') or {}
    try:
        page = max(2, int(listing.get('page') or 1) + 1)
    except (TypeError, ValueError):
        return []
    try:
        per_page = max(1, int(per_page or 0))
    except (TypeError, ValueError):
        return []
    start = (page - 1) * per_page
    end = start + per_page
    try:
        if mode == 'trending':
            category = localization.trending_query(constants.trending_category())
            return yt.trending_videos(category, limit=page * per_page + 1)[start:end]
        if mode == 'live':
            category = localization.category_query(constants.live_category(), live=True)
            return yt.live_videos(category, limit=page * per_page + 1)[start:end]
        if mode == 'trailers':
            return yt.trailer_videos(localization.trailer_query(),
                                     limit=page * per_page + 1)[start:end]
        if mode == 'random_music':
            category = localization.category_query('music')
            limit = max(page * per_page + 1, 60)
            return yt.trending_videos(category, limit=limit)[start:end]
        if mode == 'search_results':
            query = params.get('q') or ''
            kind = params.get('kind') or 'video'
            if kind == 'video':
                return yt.search_videos(query, limit=page * per_page + 1)[start:end]
            if kind == 'trailer':
                search_query = '{} {}'.format(query, localization.trailer_query()).strip()
                return yt.trailer_videos(search_query,
                                         limit=page * per_page + 1)[start:end]
            return []
        if mode == 'channel_videos':
            return yt.channel_videos(params.get('url') or '',
                                     tab=params.get('tab') or 'videos',
                                     limit=page * per_page + 1)[start:end]
        if mode == 'playlist':
            pid = params.get('url') or ''
            try:
                from urllib.parse import urlparse, parse_qs
                if '://' in pid:
                    pid = (parse_qs(urlparse(pid).query).get('list') or [''])[0].strip()
            except Exception:
                pass
            if not pid:
                return []
            return yt.playlist_videos(pid,
                                      limit=page * per_page + 1)[start:end]
        if mode == 'local_playlist':
            pid = params.get('pid') or ''
            if not pid:
                return []
            return store.get_local_playlist_tracks(pid)[start:end]
        if mode in ('watch_later', 'history', 'subscription_feed'):
            if mode == 'watch_later':
                entries = store.get_watch_later()
            elif mode == 'history':
                entries = store.get_history()
            else:
                entries = store.get_library('subscription_feed')
            return entries[start:end]
    except Exception as exc:
        config.log('listing page {} failed: {}'.format(page, exc))
    return []


def append_next_page(listing, started, per_page):
    from music import queue
    entries = fetch_listing_page(listing, per_page)
    if not entries:
        queue.extend_tracks([], started)
        return []
    return queue.extend_tracks([_queue_entry(entry) for entry in entries], started)


def thumbnail(vid):
    return THUMBNAIL_URL.format(vid) if vid else ''


def duration_label(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ''
    if seconds <= 0:
        return ''
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return '{}:{:02d}:{:02d}'.format(hours, minutes, secs)
    return '{}:{:02d}'.format(minutes, secs)


def entry_date(entry):
    """Date of an entry: the parsers use vdate or published, take both."""
    entry = entry or {}
    return entry.get('vdate') or entry.get('published') or ''


def entry_params(entry):
    query = {'video_id': video_id(entry.get('video_id'))}
    for key in ('title', 'channel', 'channel_id', 'views', 'snippet', 'profile'):
        value = entry.get(key)
        if value:
            query[key] = str(value)[:400]
    date = entry_date(entry)
    if date:
        query['vdate'] = str(date)[:400]
    if entry.get('duration'):
        query['dur'] = int(entry['duration'])
    return query


def play_url(entry, mode='play'):
    query = entry_params(entry)
    query['mode'] = mode
    return router.BASE_URL + '?' + urlencode(query)


def video_info(entry):
    """Info column of a video row: identical to the TMDb Movies one."""
    channel = entry.get('channel') or ''
    views = entry.get('views') or ''
    date = config.relative_date(entry_date(entry))
    if date and date in views:
        date = ''
    lines = []
    if channel:
        lines.append('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(channel))
    stats = []
    if views:
        stats.append('[B][COLOR FFFFD700]{}[/COLOR][/B]'.format(views))
    if date:
        stats.append('[B][COLOR FFFF69B4]{}[/COLOR][/B]'.format(date))
    label = duration_label(entry.get('duration'))
    if label:
        stats.append('[B][COLOR FF87CEEB]{}[/COLOR][/B]'.format(label))
    if stats:
        lines.append(' - '.join(stats))
    head = '\n'.join(lines)
    snippet = clean_title(entry.get('snippet'), single_line=False)
    if snippet:
        return (head + '\n\n' + snippet) if head else snippet
    return head


def history_entry(params):
    params = params or {}
    vid = video_id(params.get('video_id'))
    try:
        duration = int(str(params.get('dur') or 0))
    except (TypeError, ValueError):
        duration = 0
    return {
        'video_id': vid,
        'title': params.get('title') or '',
        'image': thumbnail(vid),
        'channel': params.get('channel') or '',
        'channel_id': params.get('channel_id') or '',
        'views': params.get('views') or '',
        'vdate': params.get('vdate') or params.get('year') or '',
        'duration': duration,
        'snippet': params.get('snippet') or '',
    }


def run_plugin(mode, params=None):
    query = urlencode(params or {})
    return 'RunPlugin({}?mode={}{})'.format(
        router.BASE_URL, mode, '&' + query if query else '')


def video_item(entry, mode='play', cm=None, in_watch_later=False):
    entry = dict(entry or {})
    if not entry.get('channel') and entry.get('channel_id'):
        entry['channel'] = _sub_channel_name(entry['channel_id'])
    vid = video_id(entry.get('video_id'))
    title = clean_title(entry.get('title')) or vid
    if entry.get('is_live'):
        title = '[COLOR FFFF4500][LIVE][/COLOR] {}'.format(title)
    if entry.get('_local_only'):
        title = '{} [COLOR FF00FF7F][LOCAL][/COLOR]'.format(title)
    _is_blocked = _menu_is_blocked(vid)
    if _is_blocked:
        title = '{} [COLOR FFFF5555][blocked][/COLOR]'.format(title)
    image = entry.get('image') or thumbnail(vid)
    url = play_url(entry, mode)
    li = xbmcgui.ListItem(label=title, path=url)
    if image:
        li.setArt({'icon': image, 'thumb': image, 'landscape': image,
                   'banner': image, 'fanart': image})
    info = video_info(entry)
    _set_video_info(li, title, info, entry.get('duration'))
    li.setProperty('IsPlayable', 'true')
    li.setProperty('video_id', vid)

    menus = list(cm or []) + _song_menus(entry, vid, in_watch_later)
    if menus:
        li.addContextMenuItems(menus)
    return url, li, False


def _set_video_info(li, title, plot='', duration=0):
    try:
        length = int(duration or 0)
    except (TypeError, ValueError):
        length = 0
    try:
        tag = li.getVideoInfoTag()
    except Exception:
        tag = None
    if tag is not None:
        try:
            tag.setMediaType('video')
            tag.setTitle(title)
            if plot:
                tag.setPlot(plot)
            if length:
                tag.setDuration(length)
            return
        except Exception:
            pass
    info = {'title': title, 'mediatype': 'video'}
    if plot:
        info['plot'] = plot
    if length:
        info['duration'] = length
    li.setInfo('video', info)


def _set_folder_info(li, label, description=''):
    _set_video_info(li, _CLEAN_RE.sub('', label), description)


def folder_item(label, mode, image, params=None, description='', cm=None,
                folder=True):
    query = {'mode': mode}
    query.update(params or {})
    url = router.BASE_URL + '?' + urlencode(query)
    li = xbmcgui.ListItem(label=label, path=url)
    art = image or config.icon('search')
    if art:
        li.setArt({'icon': art, 'thumb': art, 'poster': art, 'landscape': art,
                   'banner': art, 'fanart': ''})
    li.setProperty('IsFolder', 'true' if folder else 'false')
    li.setProperty('IsPlayable', 'false')
    _set_folder_info(li, label, description)
    li.setIsFolder(folder)
    if cm:
        li.addContextMenuItems(cm)
    return url, li, folder


def action_item(label, mode, image, params=None, description='', folder=True):
    query = {'mode': mode}
    query.update(params or {})
    url = router.BASE_URL + '?' + urlencode(query)
    li = xbmcgui.ListItem(label=label, path=url)
    art = image or config.icon('settings')
    if art:
        li.setArt({'icon': art, 'thumb': art, 'poster': art, 'landscape': art,
                   'banner': art, 'fanart': ''})
    li.setProperty('IsFolder', 'true' if folder else 'false')
    li.setProperty('IsPlayable', 'false')
    _set_folder_info(li, label, description)
    li.setIsFolder(folder)
    return url, li, folder


_TITLE_SEPARATOR = re.compile(r'\s+[-\u2013\u2014]\s+')
_TRACK_SUFFIX = re.compile(r'\s*[\(\[][^)\]]*[\)\]]\s*$')
# what the last filtered listing had to drop, reused to size the next fetch
_DROP_RATE = [0.0]


def artist_from_title(title):
    """The artist part of an "Artist - Song" title, or '' when there is none.

    Music video titles are written that way almost every time, and the browse
    response carries no artist field, so this is what lets an artist rule hide
    one artist on a channel that posts many. Deliberately conservative: no
    separator, no match, and a first part long enough to be a sentence is
    rejected rather than guessed at.
    """
    text = _TRACK_SUFFIX.sub('', str(title or '').strip())
    parts = _TITLE_SEPARATOR.split(text, 1)
    if len(parts) < 2:
        return ''
    artist = parts[0].strip(' \t-\u2013\u2014')
    if not artist or len(artist) > 60:
        return ''
    return artist


def filter_blocked(entries, name_key='channel'):
    """Drop the rows a block rule hides.

    A channel rule hides every row whose channel matches; an artist rule hides
    only the rows whose title names that artist, so a channel with several
    artists keeps the rest. The two kinds never cross over: a channel rule does
    not hide an artist that merely appears on that channel, and an artist rule
    does not hide the rest of the channel.

    Name based on both counts, because most browse rows arrive without a
    channel id and a name typed by hand is all we have. The dictionary is read
    once per listing, so this is a set lookup per row and no network.
    name_key is where the chart artist list keeps its name - it is a list of
    artists, so it is matched against the artist rules.
    """
    entries = list(entries or [])
    channel_keys = store.get_blocked_keys(store.KIND_CHANNEL)
    artist_keys = store.get_blocked_keys(store.KIND_ARTIST)
    if not channel_keys and not artist_keys:
        return entries
    out = []
    for entry in entries:
        entry = entry or {}
        artist = artist_from_title(entry.get('title'))
        if artist and store.is_name_blocked(artist, artist_keys):
            continue
        if name_key:
            name = entry.get(name_key) or ''
            # The chart artist list is a list of artists, so either kind of
            # rule removes the entry there: blocking an artist's channel should
            # also take it out of the charts. For video rows the two stay
            # apart, which is the whole point of having both.
            wanted = (artist_keys | channel_keys) if name_key == 'title' \
                else channel_keys
            if store.is_name_blocked(name, wanted):
                continue
        out.append(entry)
    return out


def filter_blocked_names(names):
    """Same rule for a list of plain names (the chart artists)."""
    items = [str(name or '') for name in names or []]
    keys = store.get_blocked_keys()
    if not keys:
        return items
    return [name for name in items if not store.is_name_blocked(name, keys)]


def blocked_headroom():
    """Extra rows to ask for while a block list is active.

    The listings fetch one row past the page to decide on the Next page button,
    and dropping blocked rows can eat that spare row, so ask for enough to cover
    it. How much is enough depends on the drop rate, which the first listing
    measures (see paged) and the next ones reuse, because guessing it wrong is
    what made an entry cost a request several times its normal size. With
    nothing blocked this is zero and the request stays identical to before.
    """
    try:
        rules = len(store.get_blocked_names())
    except Exception:
        return 0
    if not rules:
        return 0
    # generous on purpose: one request that is a little too big is cheaper
    # than a first page that comes up short and asks again
    return min(rules * 8, 40) / 100.0


def _note_drop_rate(raw, kept):
    """Record how much the last filter dropped, for the debug line only.

    It must not feed back into how many rows are asked for: the browse cache
    keys on the limit, so a measured amount would change the key and miss the
    cache on the next visit.
    """
    if len(raw) >= 20:
        _DROP_RATE[0] = max(0.0, min(0.6, 1 - float(len(kept)) / len(raw)))


def _want_rows(end):
    """Raw rows needed for `end` rows to survive the filter.

    Built from the rule count only, never from a measurement: the browse cache
    keys on the limit as well as the query, so an amount that moved between
    visits would miss the cache every time and re-fetch on every entry - which
    is exactly the ten second Trending this is meant to avoid. Stability beats
    precision here.
    """
    rate = min(0.35, blocked_headroom())
    if rate <= 0:
        return end + 1
    try:
        need = int((end + 1) / (1 - rate)) + 2
    except ZeroDivisionError:
        need = end + 1
    return min(need, end * 3 + results_per_page())


def rows_to_fetch(end):
    """How many rows a route should ask for to fill `end` rows.

    The routes that fetch before calling paged() - Trending and Random music -
    use this, so they ask for the same amount paged() would and the two paths
    cannot drift apart.
    """
    if not blocked_headroom():
        return end + 1
    return _want_rows(end)


def page_fetch_amount(page, blocked=False):
    """How many rows a listing asks for on this page.

    Shared with the prefetch so the warmed amount is exactly the amount the
    route will ask for later. That is what makes a warmed listing a cache
    hit: the cache keys on the amount too, so warming 31 and then asking 42
    misses and costs a fresh request."""
    page = max(1, int(page or 1))
    per_page = results_per_page()
    end = page * per_page
    if blocked and blocked_headroom():
        return _want_rows(end)
    return end + 1


def _paged_number(value):
    """A page total may arrive late, so it may be a callable.

    A playlist only states its length on the page that also brings the first
    rows, so the route cannot know it before fetching and passes a function.
    """
    try:
        value = value() if callable(value) else value
        return int(value)
    except (TypeError, ValueError):
        return None


def paged(fetch, builder, mode, params=None, page=1, content='videos',
          blocked=False, total=None, next_extra=''):
    """Build one page of a listing.

    `total` is the length of the whole list when it is known, as a number or as
    a callable for one that only shows up after fetching. The Next page button
    follows the rows that arrived rather than the number, because rows go down
    in the making: the parser skips some and a song listed twice counts once.
    With 50 per page a 130 track playlist asked for 51 rows, received 50 and
    took that as the end of the list, so it stopped with no way forward. When
    the list is known to be longer and the rows came up short, the page asks
    once more for the whole length it was promised.
    """
    page = max(1, int(page or 1))
    per_page = results_per_page()
    start = (page - 1) * per_page
    end = start + per_page
    active = blocked and bool(blocked_headroom())
    want = page_fetch_amount(page, blocked)
    source = []
    known = None
    # One extra request at most, and only when the guess came out short: the
    # retry rescues the Next page button, it does not chase a long tail. Both
    # amounts derive from the rule count, so repeated visits ask for the same
    # thing and the browse cache keeps hitting.
    ceiling = min(_want_rows(end * 2) if active else want,
                  end * 3 + per_page)
    for attempt in range(2):
        try:
            raw = list(fetch(want) or [])
        except Exception as exc:
            config.log('{} page {} failed: {}'.format(mode, page, exc))
            source = []
            break
        source = raw
        if blocked:
            # before the slice, otherwise a blocked artist shortens the page
            # and the Next page button walks into nothing
            source = filter_blocked(source)
            _note_drop_rate(raw, source)
        if known is None:
            known = _paged_number(total)
        if known is not None:
            if known <= end:
                break
            if len(source) > end:
                break
            if want < known and attempt == 0:
                want = min(known, end * 3 + per_page)
                continue
            break
        if len(source) > end or want >= ceiling:
            break
        want = ceiling
    set_context(source)
    set_listing(mode, params, page)
    items = [built for built in
             (builder(entry) for entry in source[start:end]) if built]
    more = len(source) > end
    if known is not None and known <= end:
        more = False
    if more:
        next_params = dict(params or {})
        next_params['page'] = page + 1
        extra = next_extra() if callable(next_extra) else next_extra
        items.append(folder_item(
            '[B]{}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(
                config.T(32160).format(page + 1)) + (extra or ''),
            mode, config.icon('nextpage'), next_params))
    return items, content