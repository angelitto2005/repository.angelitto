import json
import random

import xbmc

import config
from .constants import cache_function

_IOS_UA = ('com.google.ios.youtube/20.20.7'
           ' (iPhone16,2; U; CPU iOS 18_5_0 like Mac OS X)')
_CLIENT_VERSION = '20.20.7'
_HEADERS = {
    'Origin': 'https://m.youtube.com',
    'User-Agent': _IOS_UA,
    'X-YouTube-Client-Name': '5',
    'X-YouTube-Client-Version': _CLIENT_VERSION,
    'Content-Type': 'application/json',
}
_ENDPOINT = 'https://www.youtube.com/youtubei/v1/{}?prettyPrint=false'


def _context():
    return {'client': {
        'clientName': 'IOS',
        'clientVersion': _CLIENT_VERSION,
        'deviceMake': 'Apple',
        'deviceModel': 'iPhone16,2',
        'osName': 'iOS',
        'osVersion': '18.5.0.22F76',
        'platform': 'MOBILE',
    }}


def _post(endpoint, payload, timeout=20):
    import requests
    body = {'context': _context(),
            'cpn': ''.join(random.choice(
                'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
                for _ in range(16))}
    body.update(payload)
    response = requests.post(_ENDPOINT.format(endpoint),
                             data=json.dumps(body), headers=_HEADERS,
                             timeout=timeout)
    return response.json()


def _text(node):
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ''
    simple = node.get('simpleText')
    if isinstance(simple, str) and simple:
        return simple
    runs = node.get('runs')
    if isinstance(runs, list):
        return ''.join(str(run.get('text') or '') for run in runs
                       if isinstance(run, dict)).strip()
    return ''


def _duration(value):
    parts = str(value or '').split(':')
    try:
        numbers = [int(part) for part in parts]
    except (TypeError, ValueError):
        return 0
    if not numbers or len(numbers) > 3:
        return 0
    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _short_views(value):
    try:
        total = int(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return ''
    if total < 0:
        return ''
    for divider, suffix in ((1000000000, 'B'), (1000000, 'M'), (1000, 'K')):
        if total >= divider:
            number = ('%.1f' % (total / divider)).rstrip('0').rstrip('.')
            return '{}{} views'.format(number, suffix)
    return '{} views'.format(total)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.values():
            for item in _walk(child):
                yield item
    elif isinstance(node, list):
        for child in node:
            for item in _walk(child):
                yield item


def _browse_id(renderer):
    for field in ('longBylineText', 'shortBylineText', 'ownerText'):
        value = renderer.get(field)
        if isinstance(value, dict):
            endpoint = ((value.get('runs') or [{}])[0].get('navigationEndpoint')
                        or {}).get('browseEndpoint') or {}
            if str(endpoint.get('browseId') or '').startswith('UC'):
                return endpoint['browseId']
    return ''


def _thumbnail(renderer):
    thumbs = ((renderer.get('thumbnail') or {}).get('thumbnails') or [])
    for thumb in reversed(thumbs):
        url = (thumb or {}).get('url')
        if url:
            return 'https:' + url if url.startswith('//') else url
    return ''


def _is_live(renderer):
    if renderer.get('isLiveNow') or renderer.get('is_live'):
        return True
    for badge in list(renderer.get('badges') or []) + list(renderer.get('ownerBadges') or []):
        renderer_badge = (badge or {}).get('metadataBadgeRenderer') or {}
        if 'live' in (_text(renderer_badge.get('label')) or '').lower():
            return True
        if str(renderer_badge.get('style') or '').lower() == 'live':
            return True
    return False


def _compact(entry):
    return {
        'video_id': entry.get('video_id') or '',
        'title': entry.get('title') or '',
        'image': entry.get('image') or '',
        'duration': int(entry.get('duration') or 0),
        'is_live': bool(entry.get('is_live')),
        'channel': entry.get('channel') or '',
        'channel_id': entry.get('channel_id') or '',
        'views': entry.get('views') or '',
        'vdate': entry.get('vdate') or '',
        'snippet': entry.get('snippet') or '',
    }


def related(video_id, limit=20):
    """YouTube's own recommended list for a video (the right hand column)."""
    try:
        payload = _post('next', {'videoId': video_id,
                                 'contentCheckOk': True,
                                 'racyCheckOk': True})
    except Exception as exc:
        config.log('related {} failed: {}'.format(video_id, str(exc)[:120]),
                   xbmc.LOGWARNING)
        return []
    found = []
    seen = set()
    for node in _walk(payload):
        renderer = None
        for key in ('compactVideoRenderer', 'videoRenderer', 'gridVideoRenderer'):
            if isinstance(node.get(key), dict):
                renderer = node[key]
                break
        if not renderer:
            continue
        endpoint = renderer.get('watchEndpoint') or {}
        vid = endpoint.get('videoId') or renderer.get('videoId') or ''
        if not vid or vid == video_id or vid in seen:
            continue
        seen.add(vid)
        found.append(_compact({
            'video_id': vid,
            'title': _text(renderer.get('title')),
            'image': _thumbnail(renderer),
            'duration': _duration(_text(renderer.get('lengthText'))),
            'is_live': _is_live(renderer),
            'channel': _text(renderer.get('ownerText') or
                             renderer.get('shortBylineText') or
                             renderer.get('longBylineText')),
            'channel_id': _browse_id(renderer),
            'views': _text(renderer.get('viewCountText')),
            'vdate': _text(renderer.get('publishedTimeText')),
        }))
        if len(found) >= limit:
            break
    config.debug('related {} -> {} items'.format(video_id, len(found)))
    return found


def video_meta(video_id):
    try:
        payload = _post('player', {'videoId': video_id,
                                   'contentCheckOk': True,
                                   'racyCheckOk': True})
    except Exception as exc:
        config.log('meta {} failed: {}'.format(video_id, str(exc)[:120]))
        return {}
    details = payload.get('videoDetails') or {}
    micro = (payload.get('microformat') or {}).get('playerMicroformatRenderer') or {}
    if not details and not micro:
        return {}
    return {
        'title': details.get('title') or '',
        'description': details.get('shortDescription') or '',
        'channel': details.get('author') or '',
        'channel_id': details.get('channelId') or '',
        'duration': int(details.get('lengthSeconds') or 0),
        'published': _text(micro.get('publishDate') or micro.get('uploadDate')),
        'views': _short_views(details.get('viewCount')) or _text(micro.get('viewCount')),
    }


@cache_function(7 * 24 * 60)
def video_meta_cached(video_id):
    data = video_meta(video_id)
    if not data:
        raise ValueError('empty video meta')
    return data


@cache_function(7 * 24 * 60)
def watch_upload_date(video_id):
    import re as _re
    import requests as _rq
    try:
        response = _rq.get(
            'https://www.youtube.com/watch?v={}'.format(video_id),
            headers={'User-Agent': _HEADERS['User-Agent'],
                     'Accept-Language': 'en-US,en;q=0.9'},
            cookies={'CONSENT': 'YES+cb'}, timeout=15)
    except Exception:
        raise ValueError('watch page unreachable')
    if response.status_code != 200:
        raise ValueError('watch page HTTP {}'.format(response.status_code))
    match = _re.search(r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
                       response.text or '')
    if not match:
        raise ValueError('no uploadDate')
    return match.group(1)


def full_entry_meta(video_id):
    try:
        info = video_meta_cached(video_id)
    except Exception:
        info = {}
    if not info:
        return {}
    out = dict(info)
    if not out.get('published'):
        try:
            out['published'] = watch_upload_date(video_id)
        except Exception:
            pass
    return out