from urllib.parse import urlencode
import re

import xbmcgui

import config
import router
import store
from browse.constants import results_per_page

THUMBNAIL_URL = 'https://i.ytimg.com/vi/{}/mqdefault.jpg'
CHANNEL_ART_URL = 'https://yt3.googleusercontent.com/{}=s176-c-k-c0x00ffffff-no-rj'

_BAD_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x1D100, 0x1D1FF),
    (0x2300, 0x23FF), (0x2460, 0x24FF),
    (0x2700, 0x27BF), (0x2B00, 0x2BFF),
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
_BAD_COLLAPSE = re.compile(r'\|\s*\|')


def _is_bad(code):
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
    info = {'title': title, 'mediatype': 'video'}
    plot = video_info(entry)
    if plot:
        info['plot'] = plot
    if entry.get('duration'):
        info['duration'] = int(entry['duration'])
    li.setInfo('video', info)
    li.setProperty('IsPlayable', 'true')
    return li


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
    entries = list(entries or [])
    pending = [dict(entry or {}) for entry in entries
               if (entry or {}).get('video_id')
               and (not (entry or {}).get('channel')
                    or not (entry or {}).get('snippet')
                    or not entry_date(entry or {}))]
    if not pending:
        return entries
    try:
        pool = ThreadPoolExecutor(max_workers=10)
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
    for future in done:
        entry = futures.get(future)
        try:
            info = future.result() or {}
        except Exception:
            failed += 1
            continue
        if not info:
            failed += 1
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
    config.log('meta fill: {}/{} filled, {} failed'.format(
        len(filled), len(pending), failed))
    return [filled.get(video_id(entry.get('video_id')), entry)
            for entry in entries]


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
            category = localization.category_query(constants.trending_category())
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
            return yt.playlist_videos(params.get('url') or '',
                                      limit=page * per_page + 1)[start:end]
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
    image = entry.get('image') or thumbnail(vid)
    url = play_url(entry, mode)
    li = xbmcgui.ListItem(label=title, path=url)
    if image:
        li.setArt({'icon': image, 'thumb': image, 'landscape': image,
                   'banner': image, 'fanart': image})
    info = {'title': title, 'mediatype': 'video'}
    plot = video_info(entry)
    if plot:
        info['plot'] = plot
    if entry.get('duration'):
        info['duration'] = int(entry['duration'])
    li.setInfo('video', info)
    li.setProperty('IsPlayable', 'true')
    li.setProperty('video_id', vid)

    menus = list(cm or [])
    channel_url = ''
    if entry.get('channel_id'):
        channel_url = 'https://www.youtube.com/channel/' + entry['channel_id']
        menus.append((
            '[B][COLOR FF00CED1]Go to Channel[/COLOR][/B]',
            'Container.Update({}?{})'.format(
                router.BASE_URL,
                urlencode({'mode': 'channel', 'url': channel_url,
                           'title': entry.get('channel') or ''}))))
        known = store.is_subscribed(channel_url)
        menus.append((
            '[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(
                'Unsubscribe' if known else 'Subscribe'),
            run_plugin('unsubscribe' if known else 'subscribe',
                       {'url': channel_url,
                        'title': entry.get('channel') or '',
                        'image': CHANNEL_ART_URL.format(entry['channel_id'])})))
    elif vid:
        menus.append((
            '[B][COLOR FF00CED1]Go to Channel[/COLOR][/B]',
            run_plugin('go_channel', {'video_id': vid})))
        menus.append((
            '[B][COLOR FF00CED1]Subscribe[/COLOR][/B]',
            run_plugin('sub_channel', {'video_id': vid})))
    if vid:
        if not in_watch_later:
            menus.append(('[B][COLOR FF00CED1]Add to Watch Later[/COLOR][/B]',
                          run_plugin('watch_later_add', entry_params(entry))))
        menus.append(('[B][COLOR FF00CED1]No autoplay for this video[/COLOR][/B]',
                      run_plugin('no_autoplay', {'video_id': vid})))
    if menus:
        li.addContextMenuItems(menus)
    return url, li, False


def _set_folder_info(li, label, description=''):
    title = _CLEAN_RE.sub('', label)
    try:
        tag = li.getVideoInfoTag()
    except Exception:
        tag = None
    if tag is not None:
        try:
            tag.setTitle(title)
            if description:
                tag.setPlot(description)
            return
        except Exception:
            pass
    info = {'title': title}
    if description:
        info['plot'] = description
    li.setInfo('video', info)


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


def paged(fetch, builder, mode, params=None, page=1, content='videos'):
    page = max(1, int(page or 1))
    per_page = results_per_page()
    try:
        source = list(fetch(page * per_page + 1) or [])
    except Exception as exc:
        config.log('{} page {} failed: {}'.format(mode, page, exc))
        source = []
    start = (page - 1) * per_page
    end = start + per_page
    set_context(source)
    set_listing(mode, params, page)
    items = [builder(entry) for entry in source[start:end]]
    if len(source) > end:
        next_params = dict(params or {})
        next_params['page'] = page + 1
        items.append(folder_item(
            '[B]Next page {}  [COLOR FFFF4500]>>>[/COLOR][/B]'.format(page + 1),
            mode, config.icon('nextpage'), next_params))
    return items, content