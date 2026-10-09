"""YouTube TV device linking and account library synchronisation.

Implements the public YouTube TV activation flow: read the current TV client
pair from the public TV page, request a device code, show the official
yt.be/activate and youtube.com/qr/activate routes, then exchange the approved
code for a local refresh token. The client pair is discovered, never embedded.
"""
import base64
import binascii
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

import xbmc

import config
import store

_DEVICE_CODE_URL = 'https://www.youtube.com/o/oauth2/device/code'
_TOKEN_URL = 'https://www.youtube.com/o/oauth2/token'
_TV_BROWSE_URL = 'https://www.youtube.com/youtubei/v1/browse'
_TV_HOME_URL = 'https://www.youtube.com/tv'
_MANUAL_ACTIVATE_URL = 'https://yt.be/activate'
_QR_ACTIVATE_PREFIX = 'https://youtube.com/qr/activate/'
_SCOPE = ('http://gdata.youtube.com '
          'https://www.googleapis.com/auth/youtube-paid-content')
_GRANT_TYPE_DEVICE = 'http://oauth.net/grant_type/device/1.0'
_PROVIDER_CACHE_SECONDS = 10 * 60 * 60
_STALE_PROVIDER_SECONDS = 30 * 24 * 60 * 60
_TV_CLIENT_NAME = 'TVHTML5'
_TV_CLIENT_NAME_ID = '7'
_TV_CLIENT_VERSION_FALLBACK = '7.20260901.15.00'
_TV_USER_AGENT = (
    'Mozilla/5.0 (Linux armeabi-v7a; Android 7.1.2; Fire OS 6.0) '
    'Cobalt/22.lts.3.306369-gold (unlike Gecko) v8/8.8.278.8-jit gles '
    'Starboard/13, Amazon_ATV_mediatek8695_2019/NS6294 '
    '(Amazon, AFTMM, Wireless) com.amazon.firetv.youtube/22.3.r2.v66.0')
_TV_BROWSER_NAME = 'Cobalt'
_TV_BROWSER_VERSION = '22.lts.3.306369-gold'

_BASE_SCRIPT_PATTERNS = (
    re.compile(r'<script[^>]+id="base-js"[^>]+src="([^"]+)"'),
    re.compile(r"\.src\s*=\s*'(.*?m=base)'"),
    re.compile(r"\.src\s*=\s*'(.*?)';\s*\.id\s*=\s*'base-js'"),
)
_CLIENT_PAIR_PATTERNS = (
    re.compile(
        r'var\s+[A-Za-z_$][\w$]*\s*=\s*\{clientId:"([\w-]+\.apps\.googleusercontent\.com)",Th:"([\w-]+)"\}'),
    re.compile(
        r'clientId:"([\w-]+\.apps\.googleusercontent\.com)",\s*(?:[A-Za-z_$][\w$]*|Th):"([\w-]+)"'),
)
_TV_CLIENT_VERSION_PATTERN = re.compile(
    r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"\\]+)"')
_VISITOR_DATA_PATTERNS = (
    re.compile(r'"visitorData"\s*:\s*"([^"\\]+)"'),
    re.compile(r'"VISITOR_DATA"\s*:\s*"([^"\\]+)"'),
)

_CHANNEL_RENDERER_KEYS = ('gridChannelRenderer', 'pivotChannelRenderer',
                          'compactChannelRenderer', 'channelRenderer')
_VIDEO_RENDERER_KEYS = ('videoRenderer', 'gridVideoRenderer',
                        'compactVideoRenderer', 'playlistVideoRenderer',
                        'reelItemRenderer')
_PLAYLIST_RENDERER_KEYS = ('gridPlaylistRenderer', 'playlistRenderer',
                           'compactPlaylistRenderer')


class AccountError(Exception):
    pass


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('[tmdbm.trailers] [YT] {0}'.format(message), level)


def _error_message(payload, fallback='Unknown YouTube error'):
    if isinstance(payload, dict):
        error = payload.get('error_description') or payload.get('error')
        if error:
            return str(error)
    return fallback


def _request(url, form_body=None, json_body=None, headers=None):
    request_headers = {'Accept': 'application/json',
                       'User-Agent': _TV_USER_AGENT}
    request_headers.update(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(',', ':')).encode('utf-8')
        request_headers.setdefault('Content-Type', 'application/json')
    elif form_body is not None:
        data = urlencode(form_body).encode('utf-8')
        request_headers.setdefault('Content-Type',
                                   'application/x-www-form-urlencoded')
    request = Request(url, data=data, headers=request_headers)
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode('utf-8')
            return response.getcode(), json.loads(raw or '{}')
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode('utf-8') or '{}')
        except (TypeError, ValueError):
            payload = {}
        return exc.code, payload
    except (URLError, ValueError) as exc:
        raise AccountError('Network error: {0}'.format(exc))


def _fetch_text(url):
    request = Request(url, headers={
        'Accept': 'text/html,application/javascript,*/*;q=0.8',
        'User-Agent': _TV_USER_AGENT,
    })
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode('utf-8', 'replace')
    except (HTTPError, URLError, ValueError) as exc:
        raise AccountError('Could not load YouTube TV login data: {0}'.format(exc))


def _base_script_url(html):
    for pattern in _BASE_SCRIPT_PATTERNS:
        match = pattern.search(html or '')
        if match:
            candidate = match.group(1).replace('\\u0026', '&').replace('&amp;', '&')
            if candidate.startswith('/'):
                candidate = 'https://www.youtube.com' + candidate
            if candidate.startswith('https://www.youtube.com/'):
                return candidate
    raise AccountError('Could not locate the YouTube TV client script')


def _extract_tv_client(script):
    for pattern in _CLIENT_PAIR_PATTERNS:
        match = pattern.search(script or '')
        if match:
            client_id, client_secret = match.groups()
            if client_id and client_secret:
                return client_id, client_secret
    raise AccountError('Could not read the current YouTube TV login client')


def _cached_provider_is_usable(provider, maximum_age):
    if not isinstance(provider, dict):
        return False
    if not provider.get('client_id') or not provider.get('client_secret'):
        return False
    try:
        age = int(time.time()) - int(provider.get('fetched_at', 0) or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age < maximum_age


def _fetch_tv_provider():
    html = _fetch_text(_TV_HOME_URL)
    script_url = _base_script_url(html)
    client_id, client_secret = _extract_tv_client(_fetch_text(script_url))
    version_match = _TV_CLIENT_VERSION_PATTERN.search(html)
    visitor_data = ''
    for pattern in _VISITOR_DATA_PATTERNS:
        match = pattern.search(html)
        if match:
            visitor_data = match.group(1)
            break
    provider = {
        'client_id': client_id,
        'client_secret': client_secret,
        'tv_client_version': (version_match.group(1)
                               if version_match else _TV_CLIENT_VERSION_FALLBACK),
        'visitor_data': visitor_data,
        'fetched_at': int(time.time()),
    }
    store.set_auth_provider(provider)
    return provider


def tv_provider(force_refresh=False):
    cached = store.get_auth_provider()
    if not force_refresh and _cached_provider_is_usable(
            cached, _PROVIDER_CACHE_SECONDS):
        return cached
    try:
        return _fetch_tv_provider()
    except AccountError:
        if not force_refresh and _cached_provider_is_usable(
                cached, _STALE_PROVIDER_SECONDS):
            return cached
        raise


def _device_id():
    return store.get_device_id() or store.set_device_id()


def _qr_url(user_code):
    return _QR_ACTIVATE_PREFIX + str(user_code or '').replace(' ', '-')


def _valid_token(token):
    return bool(isinstance(token, dict) and token.get('refresh_token')
                and token.get('client_id') and token.get('client_secret')
                and token.get('scope') == _SCOPE)


def _valid_pending(pending):
    if not isinstance(pending, dict):
        return False
    try:
        expires_at = int(pending.get('expires_at', 0) or 0)
    except (TypeError, ValueError):
        return False
    return bool(pending.get('device_code') and pending.get('user_code')
                and pending.get('client_id') and pending.get('client_secret')
                and expires_at > int(time.time()))


def status():
    pending = store.get_oauth_pending()
    if pending and not _valid_pending(pending):
        store.clear_oauth_pending()
        pending = {}
    return {'connected': _valid_token(store.get_oauth_token()),
            'pending': bool(pending)}


def pending_device_link():
    pending = store.get_oauth_pending()
    if not _valid_pending(pending):
        if pending:
            store.clear_oauth_pending()
        return {}
    expected = _qr_url(pending['user_code'])
    if pending.get('verification_url') != _MANUAL_ACTIVATE_URL or \
            pending.get('qr_url') != expected:
        pending = dict(pending)
        pending['verification_url'] = _MANUAL_ACTIVATE_URL
        pending['qr_url'] = expected
        store.set_oauth_pending(pending)
    return pending


def start_device_link():
    provider = tv_provider()
    status_code, payload = _request(_DEVICE_CODE_URL, json_body={
        'client_id': provider['client_id'],
        'device_id': _device_id(),
        'model_name': 'ytlr::',
        'scope': _SCOPE,
    })
    if (status_code < 200 or status_code >= 300) and \
            str(payload.get('error') or '') in ('invalid_client',
                                               'unauthorized_client'):
        store.clear_auth_provider()
        provider = tv_provider(force_refresh=True)
        status_code, payload = _request(_DEVICE_CODE_URL, json_body={
            'client_id': provider['client_id'],
            'device_id': _device_id(),
            'model_name': 'ytlr::',
            'scope': _SCOPE,
        })
    if status_code < 200 or status_code >= 300:
        raise AccountError(_error_message(
            payload, 'Could not generate YouTube TV activation code'))
    device_code = payload.get('device_code')
    user_code = payload.get('user_code')
    if not device_code or not user_code:
        raise AccountError('YouTube did not return a usable TV activation code')
    now = int(time.time())
    pending = {
        'device_code': device_code,
        'user_code': str(user_code),
        'verification_url': _MANUAL_ACTIVATE_URL,
        'qr_url': _qr_url(user_code),
        'expires_at': now + int(payload.get('expires_in', 1800)),
        'interval': max(1, int(payload.get('interval', 5))),
        'next_poll_at': now,
        'client_id': provider['client_id'],
        'client_secret': provider['client_secret'],
        'scope': _SCOPE,
    }
    store.set_oauth_pending(pending)
    _log('device code issued for activation')
    return pending


def poll_pending_once():
    pending = store.get_oauth_pending()
    if not pending:
        return {'state': 'idle'}
    if not _valid_pending(pending):
        store.clear_oauth_pending()
        return {'state': 'expired'}
    now = int(time.time())
    if now < int(pending.get('next_poll_at', 0) or 0):
        return {'state': 'waiting'}
    status_code, payload = _request(_TOKEN_URL, json_body={
        'code': pending['device_code'],
        'client_id': pending['client_id'],
        'client_secret': pending['client_secret'],
        'grant_type': _GRANT_TYPE_DEVICE,
    })
    if 200 <= status_code < 300 and payload.get('access_token'):
        refresh_token = payload.get('refresh_token')
        if not refresh_token:
            store.clear_oauth_pending()
            return {'state': 'failed',
                    'message': 'YouTube did not return a refresh token'}
        store.set_oauth_token({
            'client_id': pending['client_id'],
            'client_secret': pending['client_secret'],
            'access_token': payload.get('access_token', ''),
            'refresh_token': refresh_token,
            'expires_at': now + int(payload.get('expires_in', 3600)),
            'scope': _SCOPE,
        })
        store.clear_oauth_pending()
        _log('account authorised')
        return {'state': 'authorized'}
    error = str((payload or {}).get('error') or '')
    if error in ('authorization_pending', 'slow_down'):
        interval = int(pending.get('interval', 5) or 5)
        if error == 'slow_down':
            interval += 5
        pending['interval'] = interval
        pending['next_poll_at'] = now + interval
        store.set_oauth_pending(pending)
        return {'state': 'waiting'}
    store.clear_oauth_pending()
    return {'state': 'failed', 'message': _error_message(payload)}


def access_token():
    token = store.get_oauth_token()
    if not _valid_token(token):
        raise AccountError('YouTube account is not connected')
    now = int(time.time())
    if token.get('access_token') and int(token.get('expires_at', 0) or 0) > now + 60:
        return token['access_token']
    status_code, payload = _request(_TOKEN_URL, json_body={
        'refresh_token': token.get('refresh_token', ''),
        'client_id': token.get('client_id', ''),
        'client_secret': token.get('client_secret', ''),
        'grant_type': 'refresh_token',
    })
    if status_code < 200 or status_code >= 300 or not payload.get('access_token'):
        raise AccountError(_error_message(payload, 'Could not refresh YouTube login'))
    token.update({'access_token': payload['access_token'],
                  'expires_at': now + int(payload.get('expires_in', 3600))})
    store.set_oauth_token(token)
    return token['access_token']


def _text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ''
    if value.get('simpleText'):
        return str(value['simpleText'])
    return ''.join(str(item.get('text') or '') for item in (value.get('runs') or [])
                   if isinstance(item, dict))


def _nested(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key) or {}
    return value


def _thumbnail(value):
    candidates = []
    for key in ('thumbnail', 'thumbnailRenderer'):
        item = value.get(key) if isinstance(value, dict) else {}
        candidates.extend((item or {}).get('thumbnails') or [])
    for image in reversed(candidates):
        url = (image or {}).get('url')
        if url:
            url = str(url)
            return 'https:' + url if url.startswith('//') else url
    return ''


def _duration(value):
    try:
        parts = [int(part) for part in _text(value).split(':')]
    except (TypeError, ValueError):
        return 0
    if not parts or len(parts) > 3:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _browse_id(value):
    if not isinstance(value, dict):
        return ''
    if value.get('channelId'):
        return str(value['channelId'])
    for endpoint in (_nested(value, 'endpoint', 'browseEndpoint'),
                     _nested(value, 'navigationEndpoint', 'browseEndpoint'),
                     _nested(value, 'onSelectCommand', 'browseEndpoint'),
                     _nested(value, 'rendererContext', 'commandContext', 'onTap',
                             'innertubeCommand', 'browseEndpoint')):
        if endpoint.get('browseId'):
            return str(endpoint['browseId'])
    return ''


def _channel_id_from_params(value):
    if not isinstance(value, dict):
        return ''
    for endpoint in (_nested(value, 'endpoint', 'browseEndpoint'),
                     _nested(value, 'navigationEndpoint', 'browseEndpoint'),
                     _nested(value, 'onSelectCommand', 'browseEndpoint')):
        params = str((endpoint or {}).get('params') or '')
        if not params:
            continue
        decoded = params
        for _ in range(2):
            candidate = unquote(decoded)
            if candidate == decoded:
                break
            decoded = candidate
        candidates = [decoded]
        try:
            padded = decoded + ('=' * (-len(decoded) % 4))
            candidates.append(base64.urlsafe_b64decode(padded).decode('latin-1'))
        except (TypeError, ValueError, UnicodeError, binascii.Error):
            pass
        for candidate in candidates:
            match = re.search(r'UC[A-Za-z0-9_-]{4,}', candidate or '')
            if match:
                return match.group(0)
    return ''


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            for item in _walk(child):
                yield item
    elif isinstance(value, list):
        for child in value:
            for item in _walk(child):
                yield item


def _is_live(renderer):
    if renderer.get('isLive') or renderer.get('isLiveNow'):
        return True
    for badge in list(renderer.get('badges') or []) + list(renderer.get('ownerBadges') or []):
        label = _text(_nested(badge, 'metadataBadgeRenderer', 'label')).lower()
        if 'live' in label:
            return True
    return False


def _channel_details(renderer):
    for field in ('shortBylineText', 'longBylineText', 'ownerText'):
        value = renderer.get(field)
        if not isinstance(value, dict):
            continue
        for run in value.get('runs') or []:
            if not isinstance(run, dict):
                continue
            endpoint = _nested(run, 'navigationEndpoint', 'browseEndpoint')
            channel_id = endpoint.get('browseId') or ''
            if str(channel_id).startswith('UC'):
                return str(channel_id), str(run.get('text') or channel_id)
    channel_id = _browse_id(renderer)
    return channel_id, _text(renderer.get('channelTitle')) or channel_id


def _tile_video(tile):
    video_id = ''
    for node in _walk(tile):
        watch = node.get('watchEndpoint') if isinstance(node, dict) else None
        if isinstance(watch, dict) and watch.get('videoId'):
            video_id = str(watch['videoId'])
            break
        if isinstance(node, dict) and node.get('videoId'):
            video_id = str(node['videoId'])
            break
    if not video_id:
        return {}
    metadata = _nested(tile, 'metadata', 'tileMetadataRenderer')
    header = _nested(tile, 'header', 'tileHeaderRenderer')
    overlays = _nested(tile, 'header', 'tileHeaderRenderer').get('thumbnailOverlays') or []
    label = ''
    live = False
    for overlay in overlays:
        renderer = (overlay or {}).get('thumbnailOverlayTimeStatusRenderer') or {}
        label = label or _text(renderer.get('text'))
        if 'live' in label.lower() or str(renderer.get('style') or '').lower() == 'live':
            live = True
    channel_id = ''
    for node in _walk(tile):
        browse = node.get('browseEndpoint') if isinstance(node, dict) else None
        if isinstance(browse, dict) and str(browse.get('browseId') or '').startswith('UC'):
            channel_id = str(browse['browseId'])
            break
    return {
        'video_id': video_id,
        'title': _text(metadata.get('title')) or _text(header.get('title')) or video_id,
        'image': _thumbnail(header) or _thumbnail(tile),
        'duration': _duration(label),
        'is_live': live,
        'channel': '',
        'channel_id': channel_id,
        'channel_url': ('https://www.youtube.com/channel/' + channel_id
                        if channel_id else ''),
    }


def _videos(payload):
    found = {}
    for parent in _walk(payload):
        for key in _VIDEO_RENDERER_KEYS:
            renderer = parent.get(key)
            if not isinstance(renderer, dict):
                continue
            video_id = renderer.get('videoId') or renderer.get('video_id') or ''
            if not video_id or video_id in found:
                continue
            channel_id, channel_title = _channel_details(renderer)
            found[str(video_id)] = {
                'video_id': str(video_id),
                'title': _text(renderer.get('title')) or str(video_id),
                'image': _thumbnail(renderer),
                'duration': _duration(renderer.get('lengthText')),
                'is_live': _is_live(renderer),
                'channel': channel_title,
                'channel_id': channel_id,
                'channel_url': ('https://www.youtube.com/channel/' + channel_id
                                if str(channel_id).startswith('UC') else ''),
                'views': _text(renderer.get('viewCountText')) or _text(renderer.get('shortViewCountText')),
                'vdate': _text(renderer.get('publishedTimeText')),
            }
        tile = parent.get('tileRenderer')
        if isinstance(tile, dict):
            item = _tile_video(tile)
            if item and item['video_id'] not in found:
                found[item['video_id']] = item
    return list(found.values())


def _channels(payload):
    found = {}

    def add(renderer):
        channel_id = _browse_id(renderer)
        if not str(channel_id).startswith('UC'):
            channel_id = _channel_id_from_params(renderer)
        if not str(channel_id).startswith('UC') or channel_id in found:
            return
        title = (_text(renderer.get('title')) or
                 _text(renderer.get('formattedTitle')) or
                 _text(renderer.get('displayName')) or channel_id)
        image = _thumbnail(renderer)
        if isinstance(renderer.get('header'), dict):
            header = renderer['header'].get('tileHeaderRenderer') or {}
            if title == channel_id:
                title = _text(header.get('title')) or title
            if not image:
                image = _thumbnail(header)
        found[channel_id] = {'title': title,
                             'url': 'https://www.youtube.com/channel/' + channel_id,
                             'image': image,
                             'youtube_subscription_id': channel_id}

    for parent in _walk(payload):
        renderers = [parent.get(key) for key in _CHANNEL_RENDERER_KEYS
                     if isinstance(parent.get(key), dict)]
        if isinstance(parent.get('tileRenderer'), dict):
            renderers.append(parent['tileRenderer'])
        for renderer in renderers:
            add(renderer)
        for key in ('tabRenderer', 'expandableTabRenderer', 'guideEntryRenderer'):
            if isinstance(parent.get(key), dict):
                add(parent[key])
    return list(found.values())


def _playlists(payload):
    found = {}
    for parent in _walk(payload):
        for key in _PLAYLIST_RENDERER_KEYS:
            renderer = parent.get(key)
            if not isinstance(renderer, dict):
                continue
            playlist_id = (renderer.get('playlistId') or
                           _nested(renderer, 'navigationEndpoint',
                                   'watchEndpoint').get('playlistId') or '')
            if not playlist_id or playlist_id in found:
                continue
            found[playlist_id] = {'title': _text(renderer.get('title')) or str(playlist_id),
                                  'playlist_id': str(playlist_id),
                                  'image': _thumbnail(renderer)}
    return list(found.values())


def _browse_context(browse_id='', params='', extra=None):
    provider = store.get_auth_provider()
    if not provider.get('visitor_data'):
        provider = tv_provider(force_refresh=True)
    version = provider.get('tv_client_version') or _TV_CLIENT_VERSION_FALLBACK
    visitor_data = provider.get('visitor_data') or ''
    body = {
        'context': {
            'client': {
                'clientName': _TV_CLIENT_NAME,
                'clientVersion': version,
                'clientScreen': 'WATCH',
                'userAgent': _TV_USER_AGENT,
                'browserName': _TV_BROWSER_NAME,
                'browserVersion': _TV_BROWSER_VERSION,
                'tvAppInfo': {'appQuality': 'TV_APP_QUALITY_FULL_ANIMATION',
                              'zylonLeftNav': True},
                'webpSupport': False,
                'animatedWebpSupport': True,
                'utcOffsetMinutes': str(int(-time.timezone / 60)),
                'visitorData': visitor_data,
            },
            'user': {'enableSafetyMode': False, 'lockedSafetyMode': False},
        },
        'racyCheckOk': True,
        'contentCheckOk': True,
    }
    if browse_id:
        body['browseId'] = browse_id
    if params:
        body['params'] = params
    if isinstance(extra, dict):
        body.update(extra)
    return version, visitor_data, body


def _headers(token, version, visitor_data, page_id=''):
    headers = {'Authorization': 'Bearer {0}'.format(token),
               'Referer': _TV_HOME_URL,
               'X-Youtube-Client-Name': _TV_CLIENT_NAME_ID,
               'X-Youtube-Client-Version': version}
    if visitor_data:
        headers['X-Goog-Visitor-Id'] = visitor_data
    if page_id:
        headers['X-Goog-Pageid'] = page_id
    return headers


def _tv_request(token, url, browse_id='', params='', extra=None, page_id=''):
    version, visitor_data, body = _browse_context(browse_id, params, extra)
    status_code, payload = _request(url, json_body=body,
                                    headers=_headers(token, version,
                                                      visitor_data, page_id))
    if status_code < 200 or status_code >= 300:
        raise AccountError(_error_message(
            payload, 'Could not load YouTube TV account data'))
    refreshed = ((payload.get('responseContext') or {}).get('visitorData')
                 if isinstance(payload, dict) else None)
    if refreshed and refreshed != visitor_data:
        provider = store.get_auth_provider()
        provider['visitor_data'] = refreshed
        provider['fetched_at'] = int(time.time())
        store.set_auth_provider(provider)
    return payload


def _account_items(payload):
    try:
        contents = payload.get('contents') or []
        section = contents[0]['accountSectionListRenderer']['contents'][0]
        return section['accountItemSectionRenderer']['contents']
    except (AttributeError, IndexError, KeyError, TypeError):
        return []


def _update_identity(token):
    payload = _tv_request(
        token, 'https://www.youtube.com/youtubei/v1/account/accounts_list',
        extra={'accountReadMask': {'returnOwner': True,
                                   'returnBrandAccounts': True,
                                   'returnPersonaAccounts': False}})
    accounts = []
    for item in _account_items(payload):
        account = item.get('accountItem') if isinstance(item, dict) else None
        if isinstance(account, dict):
            accounts.append(account)
    selected = next((item for item in accounts if item.get('isSelected')), None)
    selected = selected or (accounts[0] if accounts else {})
    page_id = ''
    try:
        tokens = selected['serviceEndpoint']['selectActiveIdentityEndpoint']['supportedTokens']
        for item in tokens or []:
            page_id = _nested(item, 'pageIdToken').get('pageId') or ''
            if page_id:
                break
    except (KeyError, TypeError, IndexError):
        page_id = ''
    stored = store.get_oauth_token()
    if stored:
        stored['page_id'] = page_id
        stored['account_ready'] = bool(accounts)
        store.set_oauth_token(stored)
    _log('identity resolved: {0} account(s)'.format(len(accounts)))
    return page_id


def _browse(token, browse_id, params=''):
    page_id = store.get_oauth_token().get('page_id') or ''
    return _tv_request(token, _TV_BROWSE_URL, browse_id, params, page_id=page_id)


def _contains(payload, renderer_name):
    return any(renderer_name in value for value in _walk(payload))


def sync_library():
    token = access_token()
    _update_identity(token)
    subscriptions = _browse(token, 'FEsubscriptions')
    channels = _channels(subscriptions)
    feed = _videos(subscriptions)
    _log('sync: {0} channels, {1} videos'.format(len(channels), len(feed)))
    if not channels and not feed and _contains(subscriptions, 'genericPromoRenderer'):
        raise AccountError('YouTube TV did not accept the linked account')
    store.set_library('subscription_feed', feed)
    store.set_library('subscribed_channels', channels)
    optional = (
        ('watch_later_remote', 'FEmy_youtube', 'cAc=', _videos),
        ('remote_history', 'FEhistory', '', _videos),
        ('saved_playlists', 'FEplaylist_aggregation', '', _playlists),
    )
    for name, browse_id, params, parser in optional:
        try:
            store.set_library(name, parser(_browse(token, browse_id, params)))
        except Exception as exc:
            _log('optional {0} failed: {1}'.format(name, str(exc)[:90]),
                 xbmc.LOGWARNING)
    store.merge_youtube_subscriptions(channels)
    return {'channels': len(channels), 'videos': len(feed)}


def disconnect():
    store.clear_oauth_pending()
    store.clear_oauth_token()
    store.clear_library()