# -*- coding: utf-8 -*-
"""Fast, native progressive playback for NewPipe.

The add-on obtains one combined audio/video URL through PluginsGR and gives it
straight to Kodi. No DASH/MPD manifest, localhost proxy or plugin.video.youtube
is used. The resolver is intentionally limited to the iOS mobile client first:
the generic PluginsGR client chain also probes TV clients that are anonymous-
blocked by YouTube and needlessly delay every playback attempt.
"""

from __future__ import absolute_import

import json
import os
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

from tulip import directory, kodi
from tulip.log import log

from . import ui
from . import localization


# The lightweight YouTube resolver is bundled in resources/lib/ytresolver.
# It replaces the external PluginsGR / ResolveURL add-on chain so installation
# does not depend on any script.module package being present in Kodi.
_BUNDLED_ENGINE_PATH = os.path.dirname(__file__)
# Keep fallbacks mobile-only.  TV clients cause anonymous "Please sign in" and
# "The page needs to be reloaded" responses on this device.
_DIRECT_CLIENT_ATTEMPTS = (
    ('iOS', ('ios',)),
    ('iOS compatibility', ('ios_testsuite_params',)),
)
# The Android compatibility client returns the standard combined MP4 stream
# (normally 360p/480p) for music videos.  It avoids YouTube's pseudo-live HLS
# manifest, whose pending segment request can keep Kodi's Stop screen open for
# many seconds on Android.  HLS remains a fallback when no MP4 is available.
_MUSIC_CLIENT_ATTEMPTS = (
    ('Android compatibility', ('android_testsuite_params',)),
    ('iOS compatibility', ('ios_testsuite_params',)),
)
_SAFE_HEADERS = (
    'User-Agent',
    'Referer',
    'Origin',
    'Accept-Language',
    'X-YouTube-Client-Name',
    'X-YouTube-Client-Version',
    'X-Goog-Visitor-Id',
)
_STREAM_CACHE_TTL = 15 * 60
_STREAM_CACHE_CAP = 30
_STREAM_CACHE_VERSION = 6
_RESOLVE_LOCK_TTL = 35
_HLS_STREAM_CACHE_TTL = 60


def _error(message):
    """Log errors at Kodi's visible error level; Tulip logging may be debug-only."""

    try:
        import xbmc
        xbmc.log('[NewPipe] {0}'.format(message), xbmc.LOGERROR)
    except Exception:
        log('NewPipe: {0}'.format(message))


def _info(message):
    try:
        import xbmc
        xbmc.log('[NewPipe] {0}'.format(message), xbmc.LOGINFO)
    except Exception:
        log('NewPipe: {0}'.format(message))


def _profile_dir():
    try:
        path = kodi.transPath('special://profile/addon_data/plugin.video.newpipe/')
    except Exception:
        path = ''
    if not path or path.startswith('special://'):
        path = os.path.join(os.getcwd(), 'newpipe-progressive')
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _state_path(name):
    return os.path.join(_profile_dir(), name)


def _read_state(name, default):
    try:
        with open(_state_path(name), encoding='utf-8') as handle:
            value = json.load(handle)
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError, TypeError):
        return default


def _write_state(name, value):
    path = _state_path(name)
    temporary = path + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(',', ':'))
        os.replace(temporary, path)
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _playback_profile(profile):
    value = str(profile or '').lower()
    if value == 'trailer':
        return 'trailer'
    if value == 'music':
        return 'music'
    return 'default'


def _quality_value(profile='default'):
    profile = _playback_profile(profile)
    setting = 'trailer_max_height' if profile == 'trailer' else 'direct_max_height'
    default = '1080' if profile == 'trailer' else '720'
    value = kodi.setting(setting) or default
    try:
        height = int(value)
    except (TypeError, ValueError):
        height = int(default)
    # This profile is private to Random music.  YouTube's compatible Android
    # client exposes a far more reliable combined MP4 stream at 480p, which
    # lets native Kodi Stop close immediately instead of waiting on HLS.
    return min(height, 480) if profile == 'music' else height


def _quality_index(max_height):
    """Map the NewPipe setting to the native resolver's progressive quality."""

    return {360: 1, 480: 2, 720: 3, 1080: 4, 1440: 5, 2160: 6}.get(max_height, 3)


def _fast_start_enabled():
    # Existing installations have no stored value, so the new safe default is on.
    return (kodi.setting('fast_start') or 'true').lower() != 'false'


def _audio_preference():
    """Map the NewPipe content-language setting to an audio-selection policy.

    YouTube can provide translated/dubbed tracks alongside the creator's audio.
    The direct resolver used by this add-on must not inherit the account or UI
    language as an implicit instruction to choose a dub.  Original audio is
    therefore the standard policy.  Portuguese dubs are deliberately enabled
    only when the user explicitly selects Brazilian Portuguese as the NewPipe
    content language.
    """
    configured = localization.content_language().replace('_', '-').casefold()
    if configured == 'pt-br':
        return 'pt-br', 'pt', True
    return 'original', 'original', False


def _cache_key(video_id, audio_only, profile):
    audio_mode, _language, _prefer_default = _audio_preference()
    return 'v{0}:{1}:{2}:{3}:{4}:{5}:{6}'.format(
        _STREAM_CACHE_VERSION,
        video_id,
        int(bool(audio_only)),
        _playback_profile(profile),
        _quality_value(profile),
        int(_fast_start_enabled()),
        audio_mode)


def _stream_expiry(stream, now, cache_ttl=_STREAM_CACHE_TTL):
    """Return a conservative local expiry, respecting YouTube URL expiry if present."""

    expires = now + cache_ttl
    try:
        query = parse_qs(urlparse(stream.split('|', 1)[0]).query)
        remote = int((query.get('expire') or ['0'])[0])
        if remote:
            # Leave two minutes before Google's signature expiry.
            expires = min(expires, remote - 120)
    except (TypeError, ValueError):
        pass
    return expires


def _cached_stream(video_id, audio_only, profile):
    now = int(time.time())
    payload = _read_state('progressive_streams.json', {'items': {}})
    entry = (payload.get('items') or {}).get(_cache_key(video_id, audio_only, profile), {})
    stream = entry.get('stream') if isinstance(entry, dict) else ''
    expires = entry.get('expires', 0) if isinstance(entry, dict) else 0
    if isinstance(stream, str) and stream.startswith(('http://', 'https://')) and expires > now:
        _info('stream direto em cache para {0}'.format(video_id))
        return {'url': stream, 'hls': bool(entry.get('hls', False))}
    return None


def _save_stream(video_id, audio_only, profile, resolved):
    stream = resolved.get('url', '') if isinstance(resolved, dict) else ''
    if not stream:
        return
    now = int(time.time())
    # HLS manifests contain short-lived signed chunk URLs.  Do not retain one
    # after a transient 403: a subsequent play should obtain a fresh manifest.
    cache_ttl = _HLS_STREAM_CACHE_TTL if resolved.get('hls') else _STREAM_CACHE_TTL
    expires = _stream_expiry(stream, now, cache_ttl=cache_ttl)
    if expires <= now:
        return
    payload = _read_state('progressive_streams.json', {'items': {}})
    items = payload.get('items') or {}
    items = {
        key: item for key, item in items.items()
        if isinstance(item, dict) and item.get('expires', 0) > now
    }
    items[_cache_key(video_id, audio_only, profile)] = {
        'stream': stream,
        'hls': bool(resolved.get('hls', False)),
        'expires': expires,
        'saved': now,
    }
    if len(items) > _STREAM_CACHE_CAP:
        ordered = sorted(items.items(), key=lambda pair: pair[1].get('saved', 0), reverse=True)
        items = dict(ordered[:_STREAM_CACHE_CAP])
    _write_state('progressive_streams.json', {'items': items})


def _acquire_resolve_slot(video_id):
    """Avoid overlapping Kodi demuxers when the user changes video while loading."""

    now = int(time.time())
    active = _read_state('progressive_resolve_lock.json', {})
    started = active.get('started', 0) if isinstance(active, dict) else 0
    try:
        busy = now - int(started) < _RESOLVE_LOCK_TTL
    except (TypeError, ValueError):
        busy = False
    if busy:
        return False
    _write_state('progressive_resolve_lock.json', {'video_id': video_id, 'started': now})
    return True


def _clear_resolve_slot():
    try:
        os.remove(_state_path('progressive_resolve_lock.json'))
    except OSError:
        pass


def _pluginsgr_path():
    path = _BUNDLED_ENGINE_PATH
    if not os.path.isdir(os.path.join(path, 'ytresolver')):
        raise RuntimeError('O motor interno de reprodução não foi encontrado.')
    if path not in sys.path:
        sys.path.insert(0, path)
    return path


def _engine_context(max_height, audio_language, prefer_default_audio):
    """Create an isolated PluginsGR engine context configured without MPD."""

    _pluginsgr_path()
    from ytresolver.kodion.context.standalone import StandaloneContext

    class NewPipePlaybackContext(StandaloneContext):
        """Standalone engine context with NewPipe's explicit audio policy."""

        def get_player_language(self):
            # The bundled resolver expects ``(language, prefer_default)``.
            # Its stock standalone context returns the bare string ``en`` and
            # thus turns an English account/UI into an unintended dub bias.
            return audio_language, prefer_default_audio

    try:
        temp_dir = kodi.transPath('special://temp/newpipe-progressive/')
        profile_dir = _profile_dir()
    except Exception:
        temp_dir = profile_dir = ''

    if not temp_dir or temp_dir.startswith('special://'):
        temp_dir = os.path.join(os.getcwd(), 'newpipe-progressive')
    if not profile_dir or profile_dir.startswith('special://'):
        profile_dir = temp_dir
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(profile_dir, exist_ok=True)

    context = NewPipePlaybackContext(
        data_dir=temp_dir,
        config_file=os.path.join(profile_dir, 'ytresolver-progressive.json'),
        # H.264/AAC is the safest combined stream for the Android device.
        video_codecs=['avc1'],
    )
    settings = context.get_settings()
    settings.use_mpd_videos(False)
    settings.fixed_video_quality(_quality_index(max_height))
    return context


def _stream_with_headers(url, headers):
    """Encode the YouTube client headers Kodi needs for direct Googlevideo I/O."""

    selected = {}
    for name in _SAFE_HEADERS:
        value = (headers or {}).get(name)
        if value:
            selected[name] = str(value)
    return '{0}|{1}'.format(url, urlencode(selected)) if selected else url


def _is_hls_stream(item, url):
    """Identify manifests so Kodi uses inputstream.adaptive instead of file demuxing."""

    container = str((item or {}).get('container') or '').lower()
    base_url = (url or '').split('|', 1)[0].lower()
    return container in ('hls', 'm3u8') or '.m3u8' in base_url or '/manifest/hls' in base_url


def _inputstream_quality_properties(max_height):
    """Constrain HLS selections to the same quality chosen in NewPipe settings.

    InputStream Adaptive otherwise uses the Android screen size (3120x1440 on
    the test device) and selected YouTube's 1080p HLS ladder although the add-on
    was configured for 720p.  Its documented chooser values use resolution
    families, so 360p is deliberately capped at the nearest supported 480p
    family instead of falling back to the unrestricted display resolution.
    """
    try:
        height = int(max_height)
    except (TypeError, ValueError):
        height = 720
    family = 480 if height <= 480 else 720 if height <= 720 else 1080
    return {
        'inputstream.adaptive.stream_selection_type': 'fixed-res',
        'inputstream.adaptive.chooser_resolution_max': '{0}p'.format(family),
    }


def _audio_track_priority(item, audio_mode):
    """Rank a progressive stream by the requested audio policy.

    ``audioTrack.id`` is provided by YouTube in the form ``language.role``.
    Role 4/-1 identifies original/main audio, while 3 and 10 are respectively
    published and automatically generated dubs.  Unknown single-track formats
    remain a valid fallback but never outrank a confirmed original track.
    """
    track = item.get('audio_track') or {}
    if not isinstance(track, dict):
        track = {}
    track_id = str(track.get('id') or '').casefold().replace('_', '-')
    language, _separator, role = track_id.partition('.')
    name = str(track.get('name') or '').casefold()
    is_default = bool(track.get('is_default'))
    is_original = role in ('4', '-1') or 'original' in name
    is_dub = role in ('3', '10') or 'dub' in name

    if audio_mode == 'pt-br':
        if language == 'pt-br':
            language_rank = 2
        elif language == 'pt' or language.startswith('pt-'):
            language_rank = 1
        else:
            language_rank = 0
        if language_rank:
            return (4, language_rank, int(is_original), int(is_default))
        # An unmarked one-track response is safer than a known non-Portuguese
        # dub when Brazilian Portuguese was explicitly requested.
        return (2, 0, 0, 0) if not track else (0, 0, 0, 0)

    if is_original:
        return (4, int(is_default), 0, 0)
    if not track:
        return (2, 0, 0, 0)
    # A default flag can be useful when no original track is exposed, but a
    # declared translated/dubbed track must be the last fallback.
    return (1 if is_default and not is_dub else 0, 0, 0, 0)


def _prefer_audio_candidates(candidates, audio_mode):
    if not candidates:
        return candidates
    ranked = [(_audio_track_priority(item, audio_mode), item) for item in candidates]
    best = max(rank for rank, _item in ranked)
    return [item for rank, item in ranked if rank == best]


def _pick_progressive(streams, audio_only, fast_start, audio_mode='original'):
    if audio_only:
        candidates = [
            item for item in streams
            if item.get('url') and item.get('audio') and not item.get('video')
        ]
    else:
        candidates = [
            item for item in streams
            if item.get('url') and item.get('video') and item.get('audio')
        ]
    candidates = _prefer_audio_candidates(candidates, audio_mode)
    if audio_only:
        key = lambda item: (item.get('audio') or {}).get('bitrate', 0)
    else:
        # Prefer a true progressive file when a client also returns HLS; HLS
        # remains a valid fallback when it is the only combined stream.
        regular = [item for item in candidates
                   if not _is_hls_stream(item, item.get('url', ''))]
        if regular:
            candidates = regular
        if fast_start and regular:
            # A 360/480p combined stream starts much faster than a high-bitrate
            # progressive stream on Android. If none is available, use the best
            # stream the selected quality limit permits.
            quick = [item for item in candidates
                     if (item.get('video') or {}).get('height', 0) <= 480]
            if quick:
                candidates = quick
        key = lambda item: (
            (item.get('video') or {}).get('height', 0),
            (item.get('audio') or {}).get('bitrate', 0),
        )
    return max(candidates, key=key) if candidates else None


def _client_attempts(profile):
    """Choose the bounded mobile client sequence for the playback profile."""
    return _MUSIC_CLIENT_ATTEMPTS if _playback_profile(profile) == 'music' else _DIRECT_CLIENT_ATTEMPTS


def _resolve_from_mobile_clients(video_id, audio_only, profile):
    """Resolve from one mobile-client group at a time, never probing TV clients."""

    _pluginsgr_path()
    from ytresolver.youtube.client.player_client import YouTubePlayerClient

    max_height = _quality_value(profile)
    fast_start = profile != 'trailer' and _fast_start_enabled()
    audio_mode, audio_language, prefer_default_audio = _audio_preference()
    failures = []
    for label, client_names in _client_attempts(profile):
        try:
            client = YouTubePlayerClient(
                context=_engine_context(
                    max_height, audio_language, prefer_default_audio),
                clients=client_names)
            # `clients=` only inserts a custom group; without this override the
            # engine still continues into TV/test/VR groups after the iOS call.
            client._client_groups = (('newpipe_direct', client_names),)
            streams, _item = client.load_stream_info(
                video_id=video_id,
                use_mpd=False,
                audio_only=audio_only,
            )
            selected = _pick_progressive(
                list(streams), audio_only, fast_start, audio_mode=audio_mode)
            if not selected:
                failures.append('{0}: sem stream A/V direto'.format(label))
                continue

            url = selected.get('url') or ''
            if not url.startswith(('http://', 'https://')):
                failures.append('{0}: URL inválida'.format(label))
                continue
            if '127.0.0.1' in url or '.mpd' in url:
                failures.append('{0}: retornou DASH/proxy'.format(label))
                continue

            hls = _is_hls_stream(selected, url)
            _info('stream direto via {0} para {1}: itag={2}, formato={3}, altura={4}, hls={5}, perfil={6}, limite={7}p, áudio={8}'.format(
                label,
                video_id,
                selected.get('itag', '?'),
                selected.get('container', '?'),
                (selected.get('video') or {}).get('height', '?'),
                hls,
                profile,
                max_height,
                audio_mode))
            return {
                'url': _stream_with_headers(url, selected.get('headers') or {}),
                'hls': hls,
            }
        except Exception as exc:
            failures.append('{0}: {1}'.format(label, exc))

    raise RuntimeError('; '.join(failures) or 'Nenhum cliente móvel retornou vídeo direto.')


def resolve(video_id, audio_only=False, profile='default'):
    """Return a direct progressive URL from PluginsGR, with no local proxy."""

    profile = _playback_profile(profile)
    cached = _cached_stream(video_id, audio_only, profile)
    if cached:
        return cached
    try:
        stream = _resolve_from_mobile_clients(video_id, audio_only, profile)
        _save_stream(video_id, audio_only, profile, stream)
        return stream
    except Exception as exc:
        _error('Falha no stream progressivo para {0}: {1}'.format(video_id, exc))
        return None


def _resolve_failure():
    from tulip.init import syshandle
    kodi.resolve(syshandle, False, kodi.item())


def play(video_id, title='', image='', profile='default'):
    audio_only = kodi.setting('audio_only') == 'true'
    resolved = resolve(video_id, audio_only=audio_only, profile=profile)
    if not resolved:
        _clear_resolve_slot()
        kodi.infoDialog(ui.text(30179, 'Unable to obtain a playable video.'))
        _resolve_failure()
        return

    # A progressive file is given straight to Kodi. A HLS manifest is given
    # straight to inputstream.adaptive, avoiding both normal-file demux latency
    # and the former PluginsGR localhost proxy.
    is_hls = bool(resolved.get('hls'))
    max_height = _quality_value(profile)
    log('NewPipe: reprodução direta selecionada ({0})'.format(
        'HLS adaptive' if is_hls else 'arquivo A/V'))
    inputstream_properties = _inputstream_quality_properties(max_height) if is_hls else None
    if is_hls:
        _info('HLS entregue ao InputStream com limite {0}'.format(
            inputstream_properties.get('inputstream.adaptive.chooser_resolution_max')))
    directory.resolve(
        resolved.get('url'), meta={'title': title}, icon=image,
        dash=is_hls,
        manifest_type='hls' if is_hls else None,
        inputstream_type='adaptive',
        mimetype='application/x-mpegURL' if is_hls else None,
        inputstream_properties=inputstream_properties,
    )
