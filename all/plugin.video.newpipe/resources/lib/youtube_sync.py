# -*- coding: utf-8 -*-
"""YouTube TV device linking and subscription synchronization.

This module implements the current public YouTube TV activation flow:

* retrieve the current YouTube TV client pair from the public TV base script;
* request a device code from the YouTube OAuth endpoint using the TV payload;
* show the official yt.be/activate and youtube.com/qr/activate routes; and
* exchange the approved device code for a local refresh token.

No Client ID or secret is embedded in the add-on. The short-lived client data
is fetched from the public JavaScript served to the official YouTube TV client,
then cached only in the local Kodi add-on profile. No plugin.video.youtube
component is used.
"""
from __future__ import absolute_import

import base64
import binascii
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote, urljoin
from urllib.request import Request, urlopen

from . import storage

_DEVICE_CODE_URL = 'https://www.youtube.com/o/oauth2/device/code'
_TOKEN_URL = 'https://www.youtube.com/o/oauth2/token'
_TV_BROWSE_URL = 'https://www.youtube.com/youtubei/v1/browse'
_TV_HOME_URL = 'https://www.youtube.com/tv'
_MANUAL_ACTIVATE_URL = 'https://yt.be/activate'
_QR_ACTIVATE_PREFIX = 'https://youtube.com/qr/activate/'
_SCOPE = 'http://gdata.youtube.com https://www.googleapis.com/auth/youtube-paid-content'
_GRANT_TYPE_DEVICE = 'http://oauth.net/grant_type/device/1.0'
_FLOW = 'newpipe_mod_youtube_tv_v2'
_PROVIDER_FLOW = 'youtube_tv_public_client_v1'
_TIMEOUT = 20
_PROVIDER_CACHE_SECONDS = 10 * 60 * 60
_STALE_PROVIDER_SECONDS = 30 * 24 * 60 * 60
_TV_CLIENT_NAME = 'TVHTML5'
_TV_CLIENT_NAME_ID = '7'
_TV_CLIENT_VERSION_FALLBACK = '7.20260901.15.00'
_TV_USER_AGENT = (
    'Mozilla/5.0 (Linux armeabi-v7a; Android 7.1.2; Fire OS 6.0) '
    'Cobalt/22.lts.3.306369-gold (unlike Gecko) v8/8.8.278.8-jit gles '
    'Starboard/13, Amazon_ATV_mediatek8695_2019/NS6294 '
    '(Amazon, AFTMM, Wireless) com.amazon.firetv.youtube/22.3.r2.v66.0'
)
_TV_BROWSER_NAME = 'Cobalt'
_TV_BROWSER_VERSION = '22.lts.3.306369-gold'

_BASE_SCRIPT_PATTERNS = (
    re.compile(r'<script[^>]+id="base-js"[^>]+src="([^"]+)"'),
    re.compile(r"\.src\s*=\s*'(.*?m=base)'"),
    re.compile(r"\.src\s*=\s*'(.*?)';\s*\.id\s*=\s*'base-js'"),
)
# Modern YouTube TV base JS first declares the Android-TV client as e.g.
# ``var ZZa={clientId:"...",Th:"..."}``. The first matching pair is important:
# later entries may be clients for a different product and fail with HTTP 401.
_CLIENT_PAIR_PATTERNS = (
    re.compile(
        r'var\s+[A-Za-z_$][\w$]*\s*=\s*\{clientId:"([\w-]+\.apps\.googleusercontent\.com)",Th:"([\w-]+)"\}'),
    re.compile(
        r'clientId:"([\w-]+\.apps\.googleusercontent\.com)",\s*(?:[A-Za-z_$][\w$]*|Th):"([\w-]+)"'),
)
_TV_CLIENT_VERSION_PATTERN = re.compile(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"\\]+)"')
_VISITOR_DATA_PATTERNS = (
    re.compile(r'"visitorData"\s*:\s*"([^"\\]+)"'),
    re.compile(r'"VISITOR_DATA"\s*:\s*"([^"\\]+)"'),
)
_CHANNEL_RENDERER_KEYS = (
    'gridChannelRenderer', 'pivotChannelRenderer', 'compactChannelRenderer',
    'channelRenderer',
)
_VIDEO_RENDERER_KEYS = (
    'videoRenderer', 'gridVideoRenderer', 'compactVideoRenderer',
    'playlistVideoRenderer', 'reelItemRenderer',
)
_PLAYLIST_RENDERER_KEYS = (
    'gridPlaylistRenderer', 'playlistRenderer', 'compactPlaylistRenderer',
)


class YouTubeSyncError(Exception):
    """An actionable sign-in or subscription synchronization error."""


def _log(message, level=None):
    """Write diagnostic metadata to Kodi without ever writing OAuth tokens."""
    try:
        import xbmc
        xbmc.log('[NewPipe YouTube] {0}'.format(message),
                 xbmc.LOGINFO if level is None else level)
    except Exception:
        pass


def _error_message(payload, fallback='Unknown YouTube error'):
    if isinstance(payload, dict):
        error = payload.get('error_description') or payload.get('error')
        if isinstance(error, dict):
            error = error.get('message') or error.get('status')
        if error:
            return str(error)
    return fallback


def _request(url, form_body=None, json_body=None, headers=None):
    """Perform a JSON, form-encoded, or ordinary JSON API request."""
    request_headers = {
        'Accept': 'application/json',
        'User-Agent': _TV_USER_AGENT,
    }
    request_headers.update(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body, separators=(',', ':')).encode('utf-8')
        request_headers.setdefault('Content-Type', 'application/json')
    elif form_body is not None:
        data = urlencode(form_body).encode('utf-8')
        request_headers.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    request = Request(url, data=data, headers=request_headers)
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read().decode('utf-8')
            return response.getcode(), json.loads(raw or '{}')
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode('utf-8') or '{}')
        except (TypeError, ValueError):
            payload = {}
        return exc.code, payload
    except (URLError, ValueError) as exc:
        raise YouTubeSyncError('Network error: {0}'.format(exc))


def _fetch_text(url):
    request = Request(url, headers={
        'Accept': 'text/html,application/javascript,*/*;q=0.8',
        'User-Agent': _TV_USER_AGENT,
    })
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            return response.read().decode('utf-8', 'replace')
    except (HTTPError, URLError, ValueError) as exc:
        raise YouTubeSyncError('Could not load YouTube TV login data: {0}'.format(exc))


def _base_script_url(html):
    for pattern in _BASE_SCRIPT_PATTERNS:
        match = pattern.search(html or '')
        if match:
            candidate = match.group(1).replace('\\u0026', '&').replace('&amp;', '&')
            url = urljoin('https://www.youtube.com', candidate)
            if url.startswith('https://www.youtube.com/'):
                return url
    raise YouTubeSyncError('Could not locate the YouTube TV client script')


def _extract_tv_client(script):
    for pattern in _CLIENT_PAIR_PATTERNS:
        match = pattern.search(script or '')
        if match:
            client_id, client_secret = match.groups()
            if client_id and client_secret:
                return client_id, client_secret
    raise YouTubeSyncError('Could not read the current YouTube TV login client')


def _cached_provider_is_usable(provider, maximum_age):
    if not isinstance(provider, dict):
        return False
    if provider.get('flow') != _PROVIDER_FLOW:
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
        'flow': _PROVIDER_FLOW,
        'client_id': client_id,
        'client_secret': client_secret,
        'tv_client_version': (version_match.group(1) if version_match else _TV_CLIENT_VERSION_FALLBACK),
        'visitor_data': visitor_data,
        'fetched_at': int(time.time()),
    }
    storage.set_youtube_auth_provider(provider)
    return provider


def _tv_provider(force_refresh=False):
    cached = storage.get_youtube_auth_provider()
    if not force_refresh and _cached_provider_is_usable(cached, _PROVIDER_CACHE_SECONDS):
        return cached
    try:
        return _fetch_tv_provider()
    except YouTubeSyncError:
        # A known TV client remains better than failing a login solely because
        # a temporary network or YouTube-TV page problem happened at refresh.
        if not force_refresh and _cached_provider_is_usable(cached, _STALE_PROVIDER_SECONDS):
            return cached
        raise


def _device_id():
    device_id = storage.get_youtube_device_id()
    return device_id or storage.set_youtube_device_id()


def _request_device_code(provider):
    return _request(_DEVICE_CODE_URL, json_body={
        'client_id': provider['client_id'],
        'device_id': _device_id(),
        'model_name': 'ytlr::',
        'scope': _SCOPE,
    })


def _qr_url(user_code):
    # This is a YouTube-TV code issued by the endpoint above, never a generic
    # Google device code.
    return _QR_ACTIVATE_PREFIX + str(user_code or '').replace(' ', '-')


def _clear_legacy_session():
    token = storage.get_youtube_oauth_token()
    if token and not _valid_token(token):
        storage.clear_youtube_oauth_token()
    pending = storage.get_youtube_oauth_pending()
    if pending and not _valid_pending(pending):
        storage.clear_youtube_oauth_pending()


def _valid_token(token):
    """Accept a complete local YouTube TV session, including pre-MOD state."""
    return bool(
        isinstance(token, dict) and
        token.get('refresh_token') and
        token.get('client_id') and
        token.get('client_secret') and
        token.get('scope') == _SCOPE
    )


def _valid_pending(pending):
    if not isinstance(pending, dict):
        return False
    try:
        expires_at = int(pending.get('expires_at', 0) or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        pending.get('device_code') and
        pending.get('user_code') and
        pending.get('client_id') and
        pending.get('client_secret') and
        expires_at > int(time.time())
    )


def status():
    _clear_legacy_session()
    pending = storage.get_youtube_oauth_pending()
    if pending and not _valid_pending(pending):
        storage.clear_youtube_oauth_pending()
        pending = {}
    token = storage.get_youtube_oauth_token()
    return {
        'connected': _valid_token(token),
        'pending': bool(pending),
    }


def pending_device_link():
    """Return the active YouTube TV code and QR target."""
    pending = storage.get_youtube_oauth_pending()
    if not _valid_pending(pending):
        if pending:
            storage.clear_youtube_oauth_pending()
        return {}
    expected_qr = _qr_url(pending['user_code'])
    if pending.get('verification_url') != _MANUAL_ACTIVATE_URL or pending.get('qr_url') != expected_qr:
        pending = dict(pending)
        pending['verification_url'] = _MANUAL_ACTIVATE_URL
        pending['qr_url'] = expected_qr
        storage.set_youtube_oauth_pending(pending)
    return pending


def start_device_link():
    """Issue a genuine YouTube-TV code using the public TV request shape."""
    _clear_legacy_session()
    provider = _tv_provider()
    status_code, payload = _request_device_code(provider)

    # The TV client is fetched dynamically. If YouTube rolls it while Kodi has
    # a cached value, refresh once before surfacing an error.
    if (status_code < 200 or status_code >= 300) and str(payload.get('error') or '') in (
            'invalid_client', 'unauthorized_client'):
        storage.clear_youtube_auth_provider()
        provider = _tv_provider(force_refresh=True)
        status_code, payload = _request_device_code(provider)

    if status_code < 200 or status_code >= 300:
        raise YouTubeSyncError(_error_message(payload, 'Could not generate YouTube TV activation code'))

    device_code = payload.get('device_code')
    user_code = payload.get('user_code')
    if not device_code or not user_code:
        raise YouTubeSyncError('YouTube did not return a usable TV activation code')

    now = int(time.time())
    pending = {
        'flow': _FLOW,
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
    storage.set_youtube_oauth_pending(pending)
    return pending


def poll_pending_once():
    """Poll the YouTube TV token endpoint once."""
    pending = storage.get_youtube_oauth_pending()
    if not pending:
        return {'state': 'idle'}
    if not _valid_pending(pending):
        storage.clear_youtube_oauth_pending()
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
            storage.clear_youtube_oauth_pending()
            return {'state': 'failed', 'message': 'YouTube did not return a refresh token'}
        storage.set_youtube_oauth_token({
            'flow': _FLOW,
            'client_id': pending['client_id'],
            'client_secret': pending['client_secret'],
            'access_token': payload.get('access_token', ''),
            'refresh_token': refresh_token,
            'expires_at': now + int(payload.get('expires_in', 3600)),
            'scope': _SCOPE,
        })
        storage.clear_youtube_oauth_pending()
        return {'state': 'authorized'}

    # YouTube currently returns a JSON ``authorization_pending`` result with
    # HTTP 200, although older client variants use an HTTP error. Preserve the
    # code for both behaviours until the person approves it in the browser.
    error = str((payload or {}).get('error') or '')
    if error in ('authorization_pending', 'slow_down'):
        interval = int(pending.get('interval', 5) or 5)
        if error == 'slow_down':
            interval += 5
            pending['interval'] = interval
        pending['next_poll_at'] = now + interval
        storage.set_youtube_oauth_pending(pending)
        return {'state': 'waiting'}

    storage.clear_youtube_oauth_pending()
    return {'state': 'failed', 'message': _error_message(payload)}


def _access_token():
    _clear_legacy_session()
    token = storage.get_youtube_oauth_token()
    if not _valid_token(token):
        raise YouTubeSyncError('YouTube account is not connected')

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
        raise YouTubeSyncError(_error_message(payload, 'Could not refresh YouTube login'))
    token.update({
        'access_token': payload['access_token'],
        'expires_at': now + int(payload.get('expires_in', 3600)),
    })
    storage.set_youtube_oauth_token(token)
    return token['access_token']


def _text_value(value):
    """Extract a visible label from YouTube's simpleText/runs structures."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ''
    if value.get('simpleText'):
        return str(value['simpleText'])
    return ''.join(str(item.get('text') or '') for item in (value.get('runs') or [])
                   if isinstance(item, dict))


def _nested_value(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key) or {}
    return value


def _thumbnail_url(value):
    """Return the largest visible image from an InnerTube renderer."""
    candidates = []
    for key in ('thumbnail', 'thumbnailRenderer'):
        item = value.get(key) if isinstance(value, dict) else {}
        candidates.extend((item or {}).get('thumbnails') or [])
    for image in reversed(candidates):
        if isinstance(image, dict) and image.get('url'):
            url = str(image['url'])
            # YouTube TV sends profile artwork as ``//yt3…``. Browsers infer
            # HTTPS, but Kodi's ListItem texture loader does not, so it falls
            # back to the generic folder icon instead of the profile photo.
            return 'https:' + url if url.startswith('//') else url
    return ''


def _browse_id(value):
    """Read a channel browse ID from the common YouTube TV command shapes."""
    if not isinstance(value, dict):
        return ''
    if value.get('channelId'):
        return str(value['channelId'])
    candidates = (
        # NewPipe MOD's authenticated TV response uses this exact tab shape.
        _nested_value(value, 'endpoint', 'browseEndpoint'),
        _nested_value(value, 'navigationEndpoint', 'browseEndpoint'),
        _nested_value(value, 'onSelectCommand', 'browseEndpoint'),
        _nested_value(value, 'rendererContext', 'commandContext', 'onTap',
                      'innertubeCommand', 'browseEndpoint'),
    )
    for endpoint in candidates:
        if endpoint.get('browseId'):
            return str(endpoint['browseId'])
    return ''


def _channel_id_from_tv_params(value):
    """Extract the channel ID encoded in a YouTube TV subscription-tab URL.

    Current TVHTML5 does not place the subscribed channel's ``UC…`` ID in
    ``browseId``.  Each tab instead uses ``FEsubscriptions`` and carries the
    actual channel identifier in the URL-safe/base64 ``params`` value.  This
    is the tab format used by NewPipe MOD's ``ChannelListMediaGroup``.  Looking
    only at ``browseId`` therefore turns a valid account response into an
    empty list of channels.
    """
    if not isinstance(value, dict):
        return ''
    endpoints = (
        _nested_value(value, 'endpoint', 'browseEndpoint'),
        _nested_value(value, 'navigationEndpoint', 'browseEndpoint'),
        _nested_value(value, 'onSelectCommand', 'browseEndpoint'),
        _nested_value(value, 'rendererContext', 'commandContext', 'onTap',
                      'innertubeCommand', 'browseEndpoint'),
    )
    for endpoint in endpoints:
        params = str((endpoint or {}).get('params') or '')
        if not params:
            continue
        # Some TV responses encode the base64 padding twice.  Normalize a
        # bounded number of times before decoding; this preserves ordinary
        # base64 data and avoids treating arbitrary text as a URL forever.
        decoded_params = params
        for _ in range(2):
            candidate = unquote(decoded_params)
            if candidate == decoded_params:
                break
            decoded_params = candidate
        candidates = [decoded_params]
        try:
            padded = decoded_params + ('=' * (-len(decoded_params) % 4))
            candidates.append(base64.urlsafe_b64decode(padded).decode('latin-1'))
        except (TypeError, ValueError, UnicodeError, binascii.Error):
            pass
        for candidate in candidates:
            match = re.search(r'UC[A-Za-z0-9_-]{4,}', candidate or '')
            if match:
                return match.group(0)
    return ''


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            for item in _walk_dicts(child):
                yield item
    elif isinstance(value, list):
        for child in value:
            for item in _walk_dicts(child):
                yield item


def _youtube_tv_channels(payload):
    """Normalize channel cards and subscription tabs from the TV feed.

    NewPipe MOD reads the ``tvSecondaryNavRenderer`` tabs returned by
    ``FEsubscriptions``: the first one is All subscriptions and every later
    tab is a subscribed channel. Modern YouTube TV can also return ordinary
    channel cards, so accept both response layouts.
    """
    found = {}

    def add_channel(renderer):
        channel_id = _browse_id(renderer)
        if not channel_id.startswith('UC'):
            channel_id = _channel_id_from_tv_params(renderer)
        # YouTube channel browse IDs are canonical ``UC…`` identifiers. This
        # also skips the first FEsubscriptions tab, whose params do not carry
        # a channel ID, and other library navigation entries returned beside
        # actual channels.
        if not channel_id.startswith('UC') or channel_id in found:
            return
        title = (_text_value(renderer.get('title')) or
                 _text_value(renderer.get('formattedTitle')) or
                 _text_value(renderer.get('displayName')) or channel_id)
        image = _thumbnail_url(renderer)
        if isinstance(renderer.get('header'), dict):
            header = renderer['header'].get('tileHeaderRenderer') or {}
            if title == channel_id:
                title = _text_value(header.get('title')) or title
            if not image:
                image = _thumbnail_url(header)
        found[channel_id] = {
            'title': title,
            'url': 'https://www.youtube.com/channel/{0}'.format(channel_id),
            'image': image,
            'youtube_subscription_id': channel_id,
        }

    for parent in _walk_dicts(payload):
        renderers = [parent.get(key) for key in _CHANNEL_RENDERER_KEYS if isinstance(parent.get(key), dict)]
        # Recent TV responses may present channel folders as tileRenderer.
        if isinstance(parent.get('tileRenderer'), dict):
            renderers.append(parent['tileRenderer'])
        for renderer in renderers:
            add_channel(renderer)
        # NewPipe MOD's subscribed-channel menu is built from these tab shapes.
        for key in ('tabRenderer', 'expandableTabRenderer', 'guideEntryRenderer'):
            renderer = parent.get(key)
            if isinstance(renderer, dict):
                add_channel(renderer)
    return list(found.values())


def _prepare_channel_profiles(channels):
    """Create circular local profile images when Kodi's optional PIL exists."""
    try:
        from .profile_art import prepare_channel_profiles
        return prepare_channel_profiles(channels)
    except Exception:
        # Artwork must never make an authenticated subscription sync fail. The
        # normalized remote profile URL returned by _thumbnail_url still gives
        # Kodi a visible thumbnail when circular caching is unavailable.
        return channels


def _duration_seconds(value):
    """Convert a YouTube lengthText label such as ``1:02:03`` to seconds."""
    label = _text_value(value)
    try:
        parts = [int(part) for part in label.split(':')]
    except (TypeError, ValueError):
        return 0
    if not parts or len(parts) > 3:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _channel_details(renderer):
    """Find the visible channel title and browse ID carried by a video card."""
    for field in ('shortBylineText', 'longBylineText', 'ownerText',
                  'shortByline', 'longByline'):
        value = renderer.get(field) if isinstance(renderer, dict) else None
        if not isinstance(value, dict):
            continue
        for run in value.get('runs') or []:
            if not isinstance(run, dict):
                continue
            endpoint = _nested_value(run, 'navigationEndpoint', 'browseEndpoint')
            channel_id = endpoint.get('browseId') or ''
            if channel_id.startswith('UC'):
                return str(channel_id), str(run.get('text') or channel_id)
    channel_id = _browse_id(renderer)
    return channel_id, _text_value(renderer.get('channelTitle')) or channel_id


def _is_live(renderer):
    if renderer.get('isLive') or renderer.get('isLiveNow'):
        return True
    badges = list(renderer.get('badges') or []) + list(renderer.get('ownerBadges') or [])
    for badge in badges:
        label = _text_value(_nested_value(badge, 'metadataBadgeRenderer', 'label')).lower()
        if 'live' in label or 'ao vivo' in label:
            return True
    return False


def _first_text_in(value):
    """Find a visible label in nested TV tile metadata."""
    if isinstance(value, dict):
        text = _text_value(value)
        if text:
            return text
        for child in value.values():
            text = _first_text_in(child)
            if text:
                return text
    elif isinstance(value, list):
        for child in value:
            text = _first_text_in(child)
            if text:
                return text
    return ''


def _first_video_id(value):
    """Find a video id carried by a TV tile's watch endpoint."""
    if isinstance(value, dict):
        watch = value.get('watchEndpoint')
        if isinstance(watch, dict) and watch.get('videoId'):
            return str(watch['videoId'])
        if value.get('videoId'):
            return str(value['videoId'])
        for child in value.values():
            video_id = _first_video_id(child)
            if video_id:
                return video_id
    elif isinstance(value, list):
        for child in value:
            video_id = _first_video_id(child)
            if video_id:
                return video_id
    return ''


def _first_channel_id(value):
    """Find the channel carried by a tile without mistaking FE folders for one."""
    if isinstance(value, dict):
        browse = value.get('browseEndpoint')
        if isinstance(browse, dict) and str(browse.get('browseId') or '').startswith('UC'):
            return str(browse['browseId'])
        channel_id = str(value.get('channelId') or '')
        if channel_id.startswith('UC'):
            return channel_id
        for child in value.values():
            channel_id = _first_channel_id(child)
            if channel_id:
                return channel_id
    elif isinstance(value, list):
        for child in value:
            channel_id = _first_channel_id(child)
            if channel_id:
                return channel_id
    return ''


def _tile_thumbnail(tile):
    header = _nested_value(tile, 'header', 'tileHeaderRenderer')
    return _thumbnail_url(header) or _thumbnail_url(tile)


def _tile_duration(tile):
    overlays = _nested_value(tile, 'header', 'tileHeaderRenderer').get('thumbnailOverlays') or []
    for overlay in overlays:
        label = _text_value(_nested_value(overlay, 'thumbnailOverlayTimeStatusRenderer', 'text'))
        if label:
            return _duration_seconds(label)
    return 0


def _tile_is_live(tile):
    overlays = _nested_value(tile, 'header', 'tileHeaderRenderer').get('thumbnailOverlays') or []
    for overlay in overlays:
        renderer = overlay.get('thumbnailOverlayTimeStatusRenderer') if isinstance(overlay, dict) else {}
        label = _text_value((renderer or {}).get('text')).lower()
        style = str((renderer or {}).get('style') or '').lower()
        if 'live' in label or 'ao vivo' in label or style == 'live':
            return True
    return False


def _youtube_tv_tile_video(tile):
    """Convert current TVHTML5 ``tileRenderer`` video cards to Kodi items."""
    video_id = _first_video_id(tile)
    if not video_id:
        return {}
    metadata = _nested_value(tile, 'metadata', 'tileMetadataRenderer')
    header = _nested_value(tile, 'header', 'tileHeaderRenderer')
    title = (_text_value(metadata.get('title')) or
             _text_value(header.get('title')) or
             _first_text_in(metadata) or video_id)
    channel_id = _first_channel_id(tile)
    return {
        'video_id': video_id,
        'url': video_id,
        'title': title,
        'image': _tile_thumbnail(tile),
        'duration': _tile_duration(tile),
        'is_live': _tile_is_live(tile),
        'channel_id': channel_id,
        'channel_title': '',
        'channel_url': ('https://www.youtube.com/channel/{0}'.format(channel_id)
                        if channel_id else ''),
    }


def _youtube_tv_videos(payload):
    """Normalize video cards in the authenticated TV subscriptions response."""
    found = {}
    for parent in _walk_dicts(payload):
        for key in _VIDEO_RENDERER_KEYS:
            renderer = parent.get(key)
            if not isinstance(renderer, dict):
                continue
            video_id = renderer.get('videoId') or renderer.get('video_id') or ''
            if not video_id or video_id in found:
                continue
            channel_id, channel_title = _channel_details(renderer)
            title = _text_value(renderer.get('title')) or str(video_id)
            found[video_id] = {
                'video_id': str(video_id),
                'url': str(video_id),
                'title': title,
                'image': _thumbnail_url(renderer),
                'duration': _duration_seconds(renderer.get('lengthText')),
                'is_live': _is_live(renderer),
                'channel_id': channel_id,
                'channel_title': channel_title,
                'channel_url': ('https://www.youtube.com/channel/{0}'.format(channel_id)
                                if channel_id.startswith('UC') else ''),
            }
        # Modern authenticated TVHTML5 responses use tileRenderer instead of
        # gridVideoRenderer.  NewPipe MOD handles this separately; accepting it
        # here is essential for current subscription feeds.
        tile = parent.get('tileRenderer')
        if isinstance(tile, dict):
            item = _youtube_tv_tile_video(tile)
            if item and item['video_id'] not in found:
                found[item['video_id']] = item
    return list(found.values())


def _playlist_id(renderer):
    if not isinstance(renderer, dict):
        return ''
    return (renderer.get('playlistId') or renderer.get('playlist_id') or
            _nested_value(renderer, 'navigationEndpoint', 'watchEndpoint').get('playlistId') or '')


def _youtube_tv_playlists(payload):
    """Normalize saved-playlist cards from the authenticated YouTube TV view."""
    found = {}
    for parent in _walk_dicts(payload):
        for key in _PLAYLIST_RENDERER_KEYS:
            renderer = parent.get(key)
            if not isinstance(renderer, dict):
                continue
            playlist_id = _playlist_id(renderer)
            if not playlist_id or playlist_id in found:
                continue
            found[playlist_id] = {
                'title': _text_value(renderer.get('title')) or str(playlist_id),
                'url': str(playlist_id),
                'image': _thumbnail_url(renderer),
            }
    return list(found.values())


def _tv_browse_context(browse_id='FEsubscriptions', params='', extra=None):
    """Build the same TVHTML5 browse envelope as NewPipe MOD's AppClient.TV.

    The prior version returned before applying ``params`` and omitted Cobalt's
    browser identity.  Those differences are harmless for a public search but
    make some authenticated library endpoints return an empty surface.
    """
    provider = storage.get_youtube_auth_provider()
    # Accounts linked before 1.4.4 lack visitorData. Fetching this public TV
    # metadata migrates the request without asking the user to link again.
    if not provider.get('visitor_data'):
        provider = _tv_provider(force_refresh=True)
    version = (provider or {}).get('tv_client_version') or _TV_CLIENT_VERSION_FALLBACK
    visitor_data = (provider or {}).get('visitor_data') or ''
    offset_minutes = int(-time.timezone / 60)
    body = {
        'context': {
            'client': {
                'clientName': _TV_CLIENT_NAME,
                'clientVersion': version,
                'clientScreen': 'WATCH',
                'userAgent': _TV_USER_AGENT,
                'browserName': _TV_BROWSER_NAME,
                'browserVersion': _TV_BROWSER_VERSION,
                'tvAppInfo': {
                    'appQuality': 'TV_APP_QUALITY_FULL_ANIMATION',
                    'zylonLeftNav': True,
                },
                'webpSupport': False,
                'animatedWebpSupport': True,
                'acceptLanguage': 'pt-PT',
                'acceptRegion': 'PT',
                'utcOffsetMinutes': str(offset_minutes),
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


def _account_items(payload):
    """Yield account cards from the TV ``account/accounts_list`` response."""
    try:
        contents = payload.get('contents') or []
        section = contents[0]['accountSectionListRenderer']['contents'][0]
        items = section['accountItemSectionRenderer']['contents']
    except (AttributeError, IndexError, KeyError, TypeError):
        return []
    result = []
    for item in items or []:
        account = item.get('accountItem') if isinstance(item, dict) else None
        if isinstance(account, dict):
            result.append(account)
    return result


def _page_id_from_account(account):
    """Extract NewPipe MOD's selected-account page id without saving account PII."""
    try:
        tokens = account['serviceEndpoint']['selectActiveIdentityEndpoint']['supportedTokens']
    except (KeyError, TypeError):
        return ''
    for token in tokens or []:
        page_id = _nested_value(token, 'pageIdToken').get('pageId')
        if page_id:
            return str(page_id)
    return ''


def _youtube_tv_headers(access_token, version, visitor_data, page_id=''):
    """Return the authenticated headers applied by NewPipe MOD's HTTP client."""
    headers = {
        'Authorization': 'Bearer {0}'.format(access_token),
        'Referer': _TV_HOME_URL,
        'X-Youtube-Client-Name': _TV_CLIENT_NAME_ID,
        'X-Youtube-Client-Version': version,
    }
    if visitor_data:
        headers['X-Goog-Visitor-Id'] = visitor_data
    # NewPipe MOD attaches this after selecting the current personal/brand account.
    if page_id:
        headers['X-Goog-Pageid'] = page_id
    return headers


def _youtube_tv_request(access_token, url, browse_id='', params='', extra=None,
                        page_id=''):
    version, visitor_data, body = _tv_browse_context(browse_id, params, extra)
    status_code, payload = _request(url, json_body=body, headers=
                                    _youtube_tv_headers(access_token, version,
                                                        visitor_data, page_id))
    if status_code < 200 or status_code >= 300:
        raise YouTubeSyncError(_error_message(payload, 'Could not load YouTube TV account data'))
    response_context = payload.get('responseContext') if isinstance(payload, dict) else {}
    refreshed_visitor = (response_context or {}).get('visitorData')
    if refreshed_visitor and refreshed_visitor != visitor_data:
        provider = storage.get_youtube_auth_provider()
        provider['visitor_data'] = refreshed_visitor
        provider['fetched_at'] = int(time.time())
        storage.set_youtube_auth_provider(provider)
    return payload


def _update_account_identity(access_token):
    """Resolve the selected YouTube/brand account exactly like NewPipe MOD.

    OAuth approval alone provides a token, while NewPipe MOD immediately calls
    ``account/accounts_list`` and then includes ``X-Goog-Pageid`` on library
    requests.  Omitting that selected identity is why an approved session can
    look like an empty anonymous account in Kodi.
    """
    payload = _youtube_tv_request(
        access_token,
        'https://www.youtube.com/youtubei/v1/account/accounts_list',
        extra={'accountReadMask': {
            'returnOwner': True,
            'returnBrandAccounts': True,
            'returnPersonaAccounts': False,
        }},
    )
    accounts = _account_items(payload)
    selected = next((item for item in accounts if item.get('isSelected')), None)
    selected = selected or (accounts[0] if accounts else {})
    page_id = _page_id_from_account(selected)
    token = storage.get_youtube_oauth_token()
    if token:
        # Do not persist name, email or avatar; the page ID is only the opaque
        # context token the TV API requires for the chosen account.
        token['page_id'] = page_id
        token['account_ready'] = bool(accounts)
        storage.set_youtube_oauth_token(token)
    _log('conta TV selecionada: {0} identidade(s), PageId={1}'.format(
        len(accounts), 'sim' if page_id else 'não'))
    return page_id


def _youtube_tv_browse(access_token, browse_id, params=''):
    """Load an authenticated YouTube TV browse screen without Data API v3.

    The request shape and endpoint are the ones used by NewPipe MOD's TV browse
    client. It deliberately never calls youtube.googleapis.com/youtube/v3.
    """
    page_id = storage.get_youtube_oauth_token().get('page_id') or ''
    return _youtube_tv_request(access_token, _TV_BROWSE_URL, browse_id, params,
                               page_id=page_id)


def _youtube_tv_subscription_feed(access_token):
    return _youtube_tv_browse(access_token, 'FEsubscriptions')


def _contains_renderer(payload, renderer_name):
    return any(renderer_name in value for value in _walk_dicts(payload))


def sync_library():
    """Refresh account menus explicitly and save the result for Kodi folders.

    There are no authenticated calls while a folder is opening. This prevents
    a slow or malformed YouTube TV response from making Kodi appear frozen or
    forcing the process to close. The cached records are private to the Kodi
    add-on profile and are replaced only by this explicit action.
    """
    access_token = _access_token()
    # NewPipe MOD performs this identity selection directly after device linking.
    # It is also required for accounts that were linked by earlier NewPipe
    # packages, which did not keep a page-id token.
    _update_account_identity(access_token)
    subscriptions = _youtube_tv_subscription_feed(access_token)
    channels = _prepare_channel_profiles(_youtube_tv_channels(subscriptions))
    feed = _youtube_tv_videos(subscriptions)
    _log('sincronização TV: {0} canais, {1} vídeos, tiles={2}, promoção={3}'.format(
        len(channels), len(feed),
        'sim' if _contains_renderer(subscriptions, 'tileRenderer') else 'não',
        'sim' if _contains_renderer(subscriptions, 'genericPromoRenderer') else 'não'))
    # Do not claim success when YouTube returned its anonymous sign-in surface.
    # A truly empty subscribed feed may still have an account card, while this
    # promotion-only layout is the documented signed-out TV response.
    if (not channels and not feed and
            _contains_renderer(subscriptions, 'genericPromoRenderer')):
        raise YouTubeSyncError(
            'YouTube TV did not accept the linked account for the subscriptions screen')
    storage.set_youtube_library('subscription_feed', feed)
    storage.set_youtube_library('subscribed_channels', channels)

    # These are the same YouTube TV browse IDs used by NewPipe MOD. A failure in
    # an optional account section must not discard a successfully read feed.
    optional = (
        ('watch_later', 'FEmy_youtube', 'cAc=', _youtube_tv_videos),
        ('remote_history', 'FEhistory', '', _youtube_tv_videos),
        ('saved_playlists', 'FEplaylist_aggregation', '', _youtube_tv_playlists),
    )
    for name, browse_id, params, parser in optional:
        try:
            storage.set_youtube_library(
                name, parser(_youtube_tv_browse(access_token, browse_id, params)))
        except Exception:
            # Keep a prior saved screen if an optional endpoint has changed.
            # The core Subscriptions/Channels data above remains usable.
            pass

    storage.sync_youtube_subscriptions(channels)
    return {
        'channels': len(channels),
        'videos': len(feed),
        'watch_later': len(storage.get_youtube_library('watch_later')),
        'history': len(storage.get_youtube_library('remote_history')),
        'playlists': len(storage.get_youtube_library('saved_playlists')),
    }


def sync_subscriptions():
    """Import subscribed channels via the NewPipe MOD-compatible TV browse feed."""
    return sync_library().get('channels', 0)


def disconnect():
    """Forget local account data while preserving manually added channels."""
    storage.clear_youtube_oauth_pending()
    storage.clear_youtube_oauth_token()
    storage.clear_youtube_library()
    storage.clear_youtube_auth_provider()
    removed = storage.clear_youtube_subscriptions()
    _log('conta desconectada: {0} canais importados removidos'.format(removed))
    return {'removed_channels': removed}


def cancel_device_link():
    """Forget only the temporary activation code, retaining any linked account."""
    storage.clear_youtube_oauth_pending()
