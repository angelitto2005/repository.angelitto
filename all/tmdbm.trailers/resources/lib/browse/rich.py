from .scrapetube.scrapetube import get_channel, get_playlist, get_search
from .scrapetube.wrapper import duration_converter


def search(query, limit=None, sort='relevance', results_type='video'):
    return list(get_search(query, limit, 0, sort, results_type))


def channel_videos(url, tab='videos', limit=None):
    return list(get_channel(channel_url=url, limit=limit, sleep=0,
                            content_type=tab))


def channel_playlists(url, limit=None):
    return list(get_channel(channel_url=url, limit=limit, sleep=0,
                            content_type='playlists'))


def playlist_videos(playlist_id, limit=None):
    return list(get_playlist(playlist_id, limit, 0))


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


def _browse_id(node):
    if not isinstance(node, dict):
        return ''
    endpoint = (node.get('navigationEndpoint') or {}).get('browseEndpoint') or {}
    return endpoint.get('browseId') or ''


def _thumbnail(raw):
    thumbs = ((raw.get('thumbnail') or {}).get('thumbnails') or []) if raw else []
    for thumb in reversed(thumbs):
        url = (thumb or {}).get('url')
        if url:
            return 'https:' + url if url.startswith('//') else url
    return ''


def _is_live(raw):
    if raw.get('is_live') or raw.get('isLiveNow'):
        return True
    for badge in list(raw.get('badges') or []) + list(raw.get('ownerBadges') or []):
        renderer = (badge or {}).get('metadataBadgeRenderer') or {}
        label = (_text(renderer.get('label')) or '').lower()
        if 'live' in label or 'live' == str(renderer.get('style') or '').lower():
            return True
    return False


def video(raw):
    raw = raw if isinstance(raw, dict) else {}
    video_id = raw.get('videoId') or ''
    owner = None
    for field in ('ownerText', 'shortBylineText', 'longBylineText'):
        candidate = raw.get(field)
        if isinstance(candidate, dict) and (candidate.get('runs') or candidate.get('simpleText')):
            owner = candidate
            break
    channel_id = _browse_id((owner or {}).get('runs', [{}])[0]) if owner and owner.get('runs') else ''
    if not channel_id:
        channel_id = _browse_id(raw)
    snippet = ''
    for block in raw.get('detailedMetadataSnippets') or []:
        text = _text((block or {}).get('snippetText'))
        if text:
            snippet = text
            break
    return {
        'video_id': video_id,
        'title': _text(raw.get('title')) or video_id,
        'image': _thumbnail(raw),
        'duration': duration_converter(_text(raw.get('lengthText'))),
        'is_live': _is_live(raw),
        'channel': _text(owner) if owner else '',
        'channel_id': channel_id if str(channel_id).startswith('UC') else '',
        'views': _text(raw.get('viewCountText')) or _text(raw.get('shortViewCountText')),
        'vdate': _text(raw.get('publishedTimeText')),
        'published': _text(raw.get('publishedTimeText')),
        'snippet': snippet,
    }


def playlist(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        'playlist_id': raw.get('playlistId') or '',
        'title': _text(raw.get('title')) or raw.get('playlistId', ''),
        'image': _thumbnail(raw),
        'count': _text(raw.get('videoCount')) or _text(raw.get('shortBylineText')),
        'channel': _text(raw.get('ownerText')),
    }


def channel(raw):
    raw = raw if isinstance(raw, dict) else {}
    channel_id = raw.get('channelId') or raw.get('browseId') or ''
    return {
        'channel_id': channel_id,
        'title': _text(raw.get('title')) or channel_id,
        'image': _thumbnail(raw),
        'subs': _text(raw.get('subscriberCountText')),
        'count': _text(raw.get('videoCountText')),
    }