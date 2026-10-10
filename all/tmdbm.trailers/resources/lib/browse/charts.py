import time

import config
from .constants import cache_duration, cache_function
from .scrapetube.wrapper import duration_converter

_YTM_API = 'https://music.youtube.com/youtubei/v1/{}?prettyPrint=false'
_YTM_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           'Chrome/120.0 Safari/537.36')
_YTM_HEADERS = {
    'User-Agent': _YTM_UA,
    'Origin': 'https://music.youtube.com',
    'Accept': '*/*',
    'Content-Type': 'application/json',
}

_visitor = {'value': '', 'ts': 0.0}


def _client_version():
    return '1.' + time.strftime('%Y%m%d', time.gmtime()) + '.01.00'


def _visitor_id():
    if _visitor['value'] and time.time() - _visitor['ts'] < 3600:
        return _visitor['value']
    try:
        import re
        import requests
        response = requests.get('https://music.youtube.com/',
                                headers={'User-Agent': _YTM_UA}, timeout=15)
        found = re.findall(r'ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;',
                           response.text)
        import json
        if found:
            _visitor['value'] = json.loads(found[0]).get('VISITOR_DATA') or ''
            _visitor['ts'] = time.time()
    except Exception:
        pass
    return _visitor['value']


def _post(endpoint, payload, timeout=20):
    import json
    import requests
    body = {'context': {'client': {
        'clientName': 'WEB_REMIX',
        'clientVersion': _client_version(),
    }}}
    body.update(payload)
    headers = dict(_YTM_HEADERS)
    visitor = _visitor_id()
    if visitor:
        headers['X-Goog-Visitor-Id'] = visitor
    response = requests.post(_YTM_API.format(endpoint),
                             data=json.dumps(body), headers=headers,
                             timeout=timeout)
    return response.json()


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


def _thumb(node):
    thumbs = ((((node.get('thumbnailRenderer') or {}).get(
        'musicThumbnailRenderer') or {}).get('thumbnail') or {}).get(
            'thumbnails') or [])
    for thumb in reversed(thumbs):
        url = (thumb or {}).get('url')
        if url:
            return url
    thumbs = ((node.get('thumbnail') or {}).get('thumbnails') or [])
    for thumb in reversed(thumbs):
        url = (thumb or {}).get('url')
        if url:
            return 'https:' + url if url.startswith('//') else url
    return ''


def _column_text(item, index):
    try:
        columns = item.get('flexColumns') or []
        column = columns[index].get(
            'musicResponsiveListItemFlexColumnRenderer') or {}
        return _text(column.get('text'))
    except (AttributeError, IndexError, KeyError, TypeError):
        return ''


def _artist_column(item):
    try:
        columns = item.get('flexColumns') or []
    except (AttributeError, TypeError):
        return '', ''
    for column in list(columns)[1:4]:
        try:
            runs = ((column.get(
                'musicResponsiveListItemFlexColumnRenderer') or {}).get(
                    'text') or {}).get('runs') or []
        except (AttributeError, TypeError):
            continue
        for run in runs:
            if not isinstance(run, dict):
                continue
            browse_id = (((run.get('navigationEndpoint') or {}).get(
                'browseEndpoint') or {}).get('browseId') or '')
            if browse_id.startswith('UC'):
                return _text((column.get(
                    'musicResponsiveListItemFlexColumnRenderer') or {}).get(
                        'text')), browse_id
    return _column_text(item, 1), ''


def chart_sections(country):
    return _chart_sections(country or '')


@cache_function(cache_duration(120))
def _chart_sections(country):
    body = {'browseId': 'FEmusic_charts'}
    if country:
        body['formData'] = {'selectedValues': [country]}
    data = _post('browse', body)
    sections = []
    seen = set()
    for node in _walk(data):
        card = node.get('musicTwoRowItemRenderer')
        if not isinstance(card, dict):
            continue
        title = _text(card.get('title'))
        browse_id = ((card.get('navigationEndpoint') or {}).get(
            'browseEndpoint') or {}).get('browseId') or ''
        if not title or not browse_id.startswith('VL') or browse_id in seen:
            continue
        seen.add(browse_id)
        sections.append({'title': title, 'playlist_id': browse_id[2:],
                         'image': _thumb(card)})
    config.debug('charts sections for {}: {}'.format(country, len(sections)))
    return sections


def chart_artists(country):
    return _chart_artists(country or '')


@cache_function(cache_duration(120))
def _chart_artists(country):
    body = {'browseId': 'FEmusic_charts'}
    if country:
        body['formData'] = {'selectedValues': [country]}
    data = _post('browse', body)
    artists = []
    seen = set()
    for node in _walk(data):
        item = node.get('musicResponsiveListItemRenderer')
        if not isinstance(item, dict):
            continue
        nav = (item.get('navigationEndpoint') or {}).get(
            'browseEndpoint') or {}
        browse_id = nav.get('browseId') or ''
        if not browse_id.startswith('UC') or browse_id in seen:
            continue
        text = _column_text(item, 1)
        if 'subscriber' not in text.lower():
            continue
        seen.add(browse_id)
        title = _column_text(item, 0)
        artists.append({
            'title': title,
            'url': 'https://www.youtube.com/channel/' + browse_id,
            'image': _thumb(item),
            'subs': text,
        })
    return artists


def chart_tracks(playlist_id, limit=100):
    return _chart_tracks(str(playlist_id or ''), int(limit or 0))


@cache_function(cache_duration(60))
def _chart_tracks(playlist_id, limit):
    browse_id = playlist_id if playlist_id.startswith('VL') else 'VL' + playlist_id
    entries = []
    seen = set()
    continuation = ''
    for _ in range(6):
        if continuation:
            data = _post('browse', {'browseId': browse_id,
                                    'continuation': continuation})
        else:
            data = _post('browse', {'browseId': browse_id})
        for node in _walk(data):
            item = node.get('musicResponsiveListItemRenderer')
            if not isinstance(item, dict):
                continue
            video_id = (item.get('playlistItemData') or {}).get('videoId') or ''
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            title = _column_text(item, 0) or video_id
            try:
                fixed = item.get('fixedColumns') or []
                duration = duration_converter(_text(
                    (fixed[0].get('musicResponsiveListItemFixedColumnRenderer')
                     or {}).get('text')))
            except (AttributeError, IndexError, KeyError, TypeError):
                duration = 0
            rank = ''
            try:
                rank = _text(((item.get('customIndexColumn') or {}).get(
                    'musicCustomIndexColumnRenderer') or {}).get('text'))
            except (AttributeError, KeyError, TypeError):
                pass
            if rank:
                title = '{}. {}'.format(rank, title)
            artist, artist_id = _artist_column(item)
            entries.append({
                'video_id': video_id,
                'title': title,
                'image': _thumb(item),
                'duration': duration,
                'is_live': False,
                'channel': artist,
                'channel_id': artist_id,
                'views': '',
                'vdate': '',
                'snippet': '',
            })
            if limit and len(entries) >= limit:
                return entries
        continuation = ''
        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            token = (node.get('nextContinuationData') or {}).get(
                'continuation') or ''
            if token:
                continuation = token
                break
        if not continuation:
            break
    return entries
