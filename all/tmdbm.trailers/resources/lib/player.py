import os
import sys
import json
import socket
import glob
import random
import time
import struct
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, quote

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon('tmdbm.trailers')
ADDON_PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))

_lib_path = os.path.join(ADDON_PATH, 'resources', 'lib')
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

if not os.path.exists(ADDON_PROFILE):
    os.makedirs(ADDON_PROFILE)

KODI_VERSION = int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0])
IA_PROP = 'inputstream' if KODI_VERSION >= 20 else 'inputstreamaddon'

_proxy_server = None
_proxy_port = None


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)


def _cleanup_old_mpd():
    dirs = set()
    dirs.add(xbmcvfs.translatePath('special://temp'))
    profile = xbmcvfs.translatePath('special://profile')
    if profile:
        kodi_root = os.path.dirname(profile.rstrip('/\\'))
        dirs.add(os.path.join(kodi_root, 'cache'))
    for temp_dir in dirs:
        if not temp_dir or not os.path.exists(temp_dir):
            continue
        for f in os.listdir(temp_dir):
            if f.startswith('yt') and f.endswith('.mpd'):
                try:
                    os.remove(os.path.join(temp_dir, f))
                except Exception:
                    pass


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


_YT_UA = 'com.google.android.youtube/19.17.36 (Linux; U; Android 14; MiTV-AFMU0 Build/AP3A.240805.005) gzip'
_YT_HEADERS = {
    'User-Agent': _YT_UA,
    'Origin': 'https://www.youtube.com',
    'Referer': 'https://www.youtube.com/',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.5',
}


class _ProxyHandler(BaseHTTPRequestHandler):
    _mpd_content = None
    _mpd_headers = None
    _segment_headers = None
    _session = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        raw = self.path.lstrip('/')

        if raw.startswith('special://'):
            local_path = xbmcvfs.translatePath(raw)
            if raw.endswith('.mpd'):
                self.send_response(200)
                self.send_header('Content-Type', 'application/dash+xml')
                self.end_headers()
                with open(local_path, 'rb') as f:
                    self.wfile.write(f.read())
                return

            if os.path.exists(local_path):
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.end_headers()
                with open(local_path, 'rb') as f:
                    self.wfile.write(f.read())
                return

        url = unquote(raw).replace('&amp;', '&')
        if not url.startswith(('http://', 'https://')):
            self.send_error(404)
            return

        max_attempts = 5
        backoff = (0.3, 0.6, 1.2, 2.4)
        for attempt in range(max_attempts):
            try:
                if not _ProxyHandler._session:
                    import requests as req
                    _ProxyHandler._session = req.Session()

                headers = dict(_YT_HEADERS)
                if self._segment_headers:
                    for k, v in self._segment_headers.items():
                        headers[k] = v

                range_header = self.headers.get('Range')
                if range_header:
                    headers['Range'] = range_header

                resp = _ProxyHandler._session.get(url, headers=headers, timeout=120, stream=True)
                # googlevideo intermittently rejects (403/429) requests into a
                # "penalty window" that lasts seconds-to-minutes; retrying with
                # backoff rides out short windows so ISA never sees the failure.
                do_retry = attempt < max_attempts - 1 and (
                    (resp.status_code in (403, 429) and 'googlevideo.com' in url)
                    or resp.status_code >= 500)
                if do_retry:
                    _log('Proxy HTTP {} retry {}/{} (Range: {})'.format(
                        resp.status_code, attempt + 1, max_attempts - 1, range_header or '-'))
                    resp.close()
                    time.sleep(backoff[attempt] if attempt < len(backoff) else 4.0)
                    continue
                if resp.status_code >= 400:
                    _log('Proxy segment HTTP {} (Range: {}) for {}'.format(
                        resp.status_code, range_header or '-', url[:140]), xbmc.LOGWARNING)
                try:
                    self.send_response(resp.status_code)
                    with_lower = {k.lower() for k in resp.headers}
                    has_content_range = 'content-range' in with_lower
                    for key, value in resp.headers.items():
                        kl = key.lower()
                        if kl in ('transfer-encoding', 'connection'):
                            continue
                        if not has_content_range and kl == 'content-length':
                            continue
                        self.send_header(key, value)
                    if not has_content_range:
                        self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()
                    for chunk in resp.iter_content(chunk_size=65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except ConnectionError:
                    # Client (Kodi/ISA) aborted the connection while we were
                    # forwarding — e.g. it gave up on the segment after the
                    # 403-retry backoff. Nothing to deliver, nothing to log.
                    _log('Proxy client aborted during response (Range: {})'.format(
                        range_header or '-'))
                    return
                finally:
                    resp.close()
                return
            except Exception as e:
                _log('Proxy segment error (attempt {}): {}'.format(attempt + 1, str(e)), xbmc.LOGERROR)
                if attempt < max_attempts - 1:
                    time.sleep(backoff[attempt] if attempt < len(backoff) else 4.0)
                    continue
                try:
                    self.send_error(502)
                except Exception:
                    pass
                _log('Proxy 502 after {} retries: {}'.format(max_attempts, url[:120]), xbmc.LOGERROR)


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _start_proxy():
    global _proxy_server, _proxy_port
    if _proxy_server:
        return _proxy_port

    _proxy_port = _find_free_port()
    _proxy_server = _ThreadedHTTPServer(('127.0.0.1', _proxy_port), _ProxyHandler)
    t = threading.Thread(target=_proxy_server.serve_forever, daemon=True)
    t.start()
    _log('Proxy started on port {}'.format(_proxy_port))
    return _proxy_port


def _stop_proxy():
    global _proxy_server, _proxy_port
    if _proxy_server:
        _proxy_server.shutdown()
        _proxy_server = None
        _proxy_port = None


_js_runtimes_cache = None

def _get_js_runtimes():
    global _js_runtimes_cache
    if _js_runtimes_cache is not None:
        return _js_runtimes_cache
    try:
        from js_runtime import install_js
        runtime = install_js()
        _js_runtimes_cache = runtime or {}
        if _js_runtimes_cache:
            _log('JS runtime: {}'.format(list(_js_runtimes_cache.keys())[0]))
        return _js_runtimes_cache
    except Exception as e:
        _log('JS runtime install failed: {}'.format(e), xbmc.LOGWARNING)
        _js_runtimes_cache = {}
        return _js_runtimes_cache


def _discover_dash_ranges(url, headers=None, timeout=15):
    """Discover initRange/indexRange by walking top-level MP4 boxes (ftyp/moov/sidx).

    YouTube responses sometimes omit initRange/indexRange (and even bitrate).
    For gir=yes streams the layout is ftyp|moov|sidx|moof|mdat..., so the init
    segment is bytes 0..moov_end-1 and the sidx is the next box.
    Fetched in small 64KB chunks: large range requests are intermittently
    rejected by googlevideo (HTTP 403), so we never ask for more than a chunk.
    Returns ((init_start, init_end), (idx_start, idx_end)) or (None, None).
    """
    try:
        import requests as _req
        session = _ProxyHandler._session
        if session is None:
            session = _req.Session()
        h = dict(_YT_HEADERS)
        for k, v in (headers or {}).items():
            if k.lower() not in ('user-agent', 'accept'):
                h[k] = v
        buf = b''
        pos = 0
        chunk = 65536
        while len(buf) < 2097152:
            h['Range'] = 'bytes={}-{}'.format(pos, pos + chunk - 1)
            resp = session.get(url, headers=h, timeout=timeout, stream=True)
            if resp.status_code not in (200, 206):
                resp.close()
                time.sleep(0.5)
                resp = session.get(url, headers=h, timeout=timeout, stream=True)
            if resp.status_code not in (200, 206):
                resp.close()
                return None, None
            got = resp.raw.read(chunk + 1)
            resp.close()
            if not got:
                break
            buf += got
            if len(got) < chunk:
                break
            pos += len(got)
        if len(buf) < 64:
            return None, None
        moov_end = None
        sidx_off = None
        sidx_size = None
        off = 0
        n = len(buf)
        while off + 8 <= n:
            size = struct.unpack('>I', buf[off:off + 4])[0]
            typ = buf[off + 4:off + 8].decode('latin1', 'replace')
            if size == 1:
                if off + 16 > n:
                    break
                size = struct.unpack('>Q', buf[off + 8:off + 16])[0]
            if size == 0:
                size = n - off
            if size < 8 or off + size > n:
                break
            if typ == 'moov':
                moov_end = off + size
            elif typ == 'sidx' and sidx_off is None:
                sidx_off = off
                sidx_size = size
            off += size
        if moov_end is not None and sidx_off is not None and sidx_size:
            return (0, moov_end - 1), (sidx_off, sidx_off + sidx_size - 1)
    except Exception as e:
        _log('Range discovery failed: {}'.format(str(e)[:150]), xbmc.LOGWARNING)
    return None, None


_IOS_TS_UA = ('com.google.ios.youtube/20.20.7'
              ' (iPhone16,2; U; CPU iOS 18_5_0 like Mac OS X)')


def _extract_innertube_ios(video_id):
    """Pure-innertube extraction replicating plugin.video.youtube's working
    'ios_testsuite_params' client (IOS 20.20.7 / iPhone16,2 / osVersion
    18.5.0.22F76 / params=2AMB / cpn). Returns CLEAN stream URLs up to 4K
    without any PO tokens - immune to the Aug-2026 googlevideo enforcement
    that poisons android_vr/web URL-sets. No JS runtime needed.

    Returns a yt-dlp-like dict {formats, title, duration, manifest_url}.
    Raises on failure; caller falls back to the yt-dlp rotation.
    """
    import re as _re
    import requests as _rq
    cpn = ''.join(random.choice(
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        for _ in range(16))
    payload = {
        'context': {'client': {
            'clientName': 'IOS',
            'clientVersion': '20.20.7',
            'deviceMake': 'Apple',
            'deviceModel': 'iPhone16,2',
            'osName': 'iOS',
            'osVersion': '18.5.0.22F76',
            'platform': 'MOBILE',
        }},
        'cpn': cpn,
        'params': '2AMB',
        'videoId': video_id,
        'contentCheckOk': True,
        'racyCheckOk': True,
    }
    headers = {
        'Origin': 'https://m.youtube.com',
        'User-Agent': _IOS_TS_UA,
        'X-YouTube-Client-Name': '5',
        'X-YouTube-Client-Version': '20.20.7',
        'Content-Type': 'application/json',
    }
    r = _rq.post('https://www.youtube.com/youtubei/v1/player?prettyPrint=false',
                 data=json.dumps(payload), headers=headers, timeout=20)
    body = r.json()
    status = ((body.get('playabilityStatus') or {}).get('status') or '')
    if status != 'OK':
        reason = (body.get('playabilityStatus') or {}).get('reason') or ''
        raise Exception('playability {} {}'.format(status, reason)[:120])
    vd = body.get('videoDetails') or {}
    sd = body.get('streamingData') or {}
    raw = list(sd.get('formats') or []) + list(sd.get('adaptiveFormats') or [])
    formats = []
    for f in raw:
        if not f.get('url'):
            continue  # signatureCipher needs JS deciphering - skip
        mime = f.get('mimeType', '')
        m = _re.search(r'codecs="([^"]+)"', mime)
        codecs = m.group(1) if m else ''
        kind = mime.split('/', 1)[0]
        sub = (mime.split('/', 1)[1].split(';')[0].strip() if '/' in mime else '')
        fmt = {
            'format_id': str(f.get('itag')),
            'url': f['url'],
            'width': f.get('width', 0) or 0,
            'height': f.get('height', 0) or 0,
            'fps': f.get('fps'),
            'bitrate': f.get('bitrate'),
            'ext': sub,
            'protocol': 'https',
        }
        if f.get('contentLength'):
            fmt['filesize'] = int(f['contentLength'])
        if f.get('approxDurationMs'):
            try:
                fmt['duration'] = int(int(f['approxDurationMs']) / 1000)
            except Exception:
                pass
        ir = f.get('indexRange')
        ini = f.get('initRange')
        if ir and ini:
            fmt['indexRange'] = {'start': int(ir['start']), 'end': int(ir['end'])}
            fmt['initRange'] = {'start': int(ini['start']), 'end': int(ini['end'])}
        if ',' in codecs:
            # Muxed format (e.g. itag 18): keep both codecs for fallback paths
            vc, _, ac = codecs.partition(',')
            fmt['container'] = sub
            fmt['vcodec'] = vc.strip()
            fmt['acodec'] = ac.strip()
        elif kind == 'video' and sub == 'mp4':
            fmt['container'] = 'mp4_dash'
            fmt['vcodec'] = codecs or 'unknown'
            fmt['acodec'] = 'none'
        elif kind == 'audio' and sub == 'mp4':
            fmt['container'] = 'm4a_dash'
            fmt['vcodec'] = 'none'
            fmt['acodec'] = codecs or 'unknown'
        else:
            continue  # webm/vp9 etc - not used by our MPD pipeline
        formats.append(fmt)
    if not formats:
        raise Exception('innertube returned no usable formats')
    return {
        'formats': formats,
        'title': vd.get('title'),
        'duration': int(vd.get('lengthSeconds') or 0),
        'manifest_url': sd.get('hlsManifestUrl'),
    }


def _fast_extract(video_id):
    """Try the innertube ios_testsuite fast path; verify servability.
    Returns data dict or None (caller falls back to yt-dlp rotation)."""
    try:
        data = _extract_innertube_ios(video_id)
    except Exception as e:
        _log('innertube fast path failed: {}'.format(str(e)[:150]), xbmc.LOGWARNING)
        return None
    n = len(data.get('formats', []))
    ok, bad = _check_urls_servable(data)
    if not ok:
        _log('innertube URLs tainted on {}; discarding'.format(bad), xbmc.LOGWARNING)
        return None
    _log('innertube ios_testsuite OK: {} formats, servable'.format(n))
    return data


def _build_mpd(data, proxy_base=''):
    from collections import defaultdict

    duration = data.get('duration', 0) or 0
    if not duration:
        for fmt in data.get('formats', []):
            if fmt.get('duration'):
                duration = int(fmt['duration'])
                break
    groups = defaultdict(list)
    for fmt in data.get('formats', []):
        if 'container' not in fmt:
            continue
        container = fmt['container']
        if container == 'mp4_dash':
            if fmt['vcodec'] != 'none':
                if fmt['vcodec'].startswith('av01'):
                    continue
            else:
                groups['audio/mp4'].append(fmt)
        elif container == 'm4a_dash':
            groups['audio/mp4'].append(fmt)

    cap_height = 1080
    target_height = cap_height
    heights = {fmt.get('height', 0) for fmt in data.get('formats', [])
               if fmt.get('container') == 'mp4_dash'
               and fmt.get('vcodec', 'none') != 'none'
               and not fmt.get('vcodec', '').startswith('av01')
               and fmt.get('height', 0) > 0}
    if heights:
        candidates = [h for h in heights if h <= cap_height]
        target_height = max(candidates) if candidates else min(heights)

    for fmt in data.get('formats', []):
        if 'container' not in fmt:
            continue
        container = fmt['container']
        if container == 'mp4_dash':
            if fmt['vcodec'] != 'none':
                if fmt['vcodec'].startswith('av01'):
                    continue
                if fmt.get('height', 0) == target_height:
                    groups['video/mp4'].append(fmt)

    if not groups:
        return None, {}

    def fix_url(url):
        return unquote(url).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    headers = {}
    mpd = '<MPD minBufferTime="PT1.5S" mediaPresentationDuration="PT{}S" type="static" profiles="urn:mpeg:dash:profile:isoff-main:2011">\n<Period>'.format(duration)

    written_sets = 0
    for idx, (group, formats) in enumerate(groups.items()):
        contentType = 'video' if group == 'video/mp4' else 'audio'
        reps = []
        for fmt in formats:
            headers.update(fmt.get('http_headers', {}))
            fmt_url = fix_url(proxy_base + fmt['url'])
            codec = fmt.get('vcodec') if fmt.get('vcodec', 'none') != 'none' else fmt.get('acodec', '')
            index_range = fmt.get('indexRange')
            init_range = fmt.get('initRange')
            if not index_range or not init_range:
                dinit, dindex = _discover_dash_ranges(unquote(fmt['url']), fmt.get('http_headers', {}))
                if dinit and dindex:
                    index_range = {'start': dindex[0], 'end': dindex[1]}
                    init_range = {'start': dinit[0], 'end': dinit[1]}
                else:
                    _log('Skipping format {} (no discoverable ranges)'.format(fmt.get('format_id')), xbmc.LOGWARNING)
                    continue
            bandwidth = fmt.get('bitrate') or fmt.get('tbr') or 0
            rep = '\n<Representation id="{}" codecs="{}" bandwidth="{}"'.format(
                fmt.get('format_id', '?'), codec, int(bandwidth)
            )
            if fmt.get('vcodec', 'none') != 'none':
                rep += ' width="{}" height="{}"'.format(fmt.get('width', 0), fmt.get('height', 0))
                if fmt.get('fps'):
                    rep += ' frameRate="{}"'.format(fmt['fps'])
            rep += '>'
            if fmt.get('acodec', 'none') != 'none':
                rep += '\n<AudioChannelConfiguration schemeIdUri="urn:mpeg:dash:23003:3:audio_channel_configuration:2011" value="2"/>'
            rep += '\n<BaseURL>{}</BaseURL>\n<SegmentBase indexRange="{}-{}" timescale="1000">\n<Initialization range="{}-{}" />\n</SegmentBase>'.format(
                fmt_url,
                index_range['start'], index_range['end'],
                init_range['start'], init_range['end']
            )
            rep += '\n</Representation>'
            reps.append(rep)
        if not reps:
            continue
        written_sets += 1
        mpd += '\n<AdaptationSet id="{}" group="{}" contentType="{}" mimeType="{}" subsegmentAlignment="true" subsegmentStartsWithSAP="1" bitstreamSwitching="true"><Role schemeIdUri="urn:mpeg:DASH:role:2011" value="main"/>'.format(
            idx, idx + 1, contentType, group
        )
        mpd += ''.join(reps)
        mpd += '\n</AdaptationSet>'

    if not written_sets:
        return None, {}
    mpd += '\n</Period>\n</MPD>'
    return mpd, headers


def _check_urls_servable(data):
    """Probe a byte near 80% of each DASH format's file.

    googlevideo sometimes issues URL-sets whose tail is rejected (HTTP 403):
    only the first ~47% of every file in the set is servable (audio and video
    alike, identical byte fraction). The stream plays ~70s then audio dies and
    ISA aborts the whole playback (ActiveAE sync errors). The taint is baked
    into the URL at extraction time and does not heal (verified 20+ min).
    A re-extraction usually returns a clean set. Returns (ok, failed_format_id).
    """
    import re as _re
    try:
        session = _ProxyHandler._session
        if session is None:
            import requests as _req
            session = _req.Session()
        h = dict(_YT_HEADERS)
        checked = 0
        for fmt in data.get('formats', []):
            container = fmt.get('container', '')
            if container not in ('mp4_dash', 'm4a_dash'):
                continue
            if fmt.get('vcodec', 'none') != 'none' and fmt.get('vcodec', '').startswith('av01'):
                continue
            url = fmt.get('url', '')
            size = fmt.get('filesize') or fmt.get('filesize_approx')
            if not size:
                m = _re.search(r'[?&]clen=(\d+)', url)
                if m:
                    size = int(m.group(1))
            if not size:
                continue
            pos = int(size * 0.8)
            h['Range'] = 'bytes={}-{}'.format(pos, pos)
            resp = session.get(url, headers=h, timeout=10)
            status = resp.status_code
            resp.close()
            checked += 1
            if status != 206:
                _log('Format {} NOT fully servable (HTTP {} at byte {}/{})'.format(
                    fmt.get('format_id'), status, pos, size), xbmc.LOGWARNING)
                return False, fmt.get('format_id')
        _log('URL servability check passed ({} formats)'.format(checked))
        return True, None
    except Exception as e:
        _log('Servability check error: {}'.format(str(e)[:150]), xbmc.LOGWARNING)
        return True, None


def _find_clean_progressive(data):
    """Emergency fallback: return the first progressive (muxed) format whose
    URL is fully servable, or None. Used when every DASH extraction was tainted.
    """
    import re as _re
    try:
        session = _ProxyHandler._session
        if session is None:
            import requests as _req
            session = _req.Session()
        h = dict(_YT_HEADERS)
        for fmt in data.get('formats', []):
            if fmt.get('container', '') != 'mp4':
                continue
            if fmt.get('vcodec', 'none') == 'none' or fmt.get('acodec', 'none') == 'none':
                continue
            url = fmt.get('url', '')
            size = fmt.get('filesize') or fmt.get('filesize_approx')
            if not size:
                m = _re.search(r'[?&]clen=(\d+)', url)
                if m:
                    size = int(m.group(1))
            if not size:
                continue
            pos = int(size * 0.8)
            h['Range'] = 'bytes={}-{}'.format(pos, pos)
            resp = session.get(url, headers=h, timeout=10)
            status = resp.status_code
            resp.close()
            if status == 206:
                _log('Progressive fallback: itag {} fully servable'.format(fmt.get('format_id')))
                return fmt
            _log('Progressive itag {} also tainted (HTTP {})'.format(fmt.get('format_id'), status), xbmc.LOGWARNING)
    except Exception as e:
        _log('Progressive fallback error: {}'.format(str(e)[:150]), xbmc.LOGWARNING)
    return None


_last_extract_time = 0
_client_idx = 0
_CLIENT_ROTATION = [
    ['android_vr', 'android'],
    ['android', 'ios'],
    ['ios', 'web_embedded'],
    ['web_embedded', 'default'],
    ['default', 'android_vr'],
]



def play_youtube(video_id, title=None, genre=None, year=None):
    _cleanup_old_mpd()

    # Rate-limit: random delay between extractions to avoid bot detection
    global _last_extract_time
    elapsed = time.time() - _last_extract_time
    min_gap = 3 + random.random() * 5  # 3-8 seconds
    if _last_extract_time > 0 and elapsed < min_gap:
        wait = min_gap - elapsed
        _log('Waiting {:.1f}s before next extraction to avoid bot detection'.format(wait))
        xbmc.sleep(int(wait * 1000))
    _last_extract_time = time.time()

    js_runtimes = _get_js_runtimes()

    ydl_opts = {
        'format': 'best/bestvideo+bestaudio',
        'check_formats': False,
        'cachedir': ADDON_PROFILE,
        'js_runtimes': js_runtimes,
        'quiet': True,
        'no_warnings': True,
    }

    if not js_runtimes:
        # Patch INNERTUBE_CLIENTS with newer versions + testsuite params
        # (same as plugin.video.youtube's ios_testsuite/android_testsuite)
        try:
            from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS
            android = INNERTUBE_CLIENTS.get('android')
            if android:
                android['INNERTUBE_CONTEXT']['client']['clientVersion'] = '20.10.38'
                android['PLAYER_PARAMS'] = '2AMB'
            ios = INNERTUBE_CLIENTS.get('ios')
            if ios:
                ios['INNERTUBE_CONTEXT']['client']['clientVersion'] = '20.20.7'
                ios['PLAYER_PARAMS'] = '2AMB'
        except Exception:
            pass

    url = 'https://www.youtube.com/watch?v={}'.format(video_id)
    _log('Extracting: {}'.format(url))

    # Rotate player clients on each call; if blocked, try next client.
    # Re-extract (up to MAX_ATTEMPTS) when the URL-set is tainted: googlevideo
    # sometimes issues URLs whose tail is 403-rejected (see _check_urls_servable).
    global _client_idx
    rotation = list(_CLIENT_ROTATION)
    errors = []
    last_tainted = None
    fallback_fmt = None
    max_attempts = 3
    # Fast path first: pure-innertube ios_testsuite (no yt-dlp, no PO tokens,
    # clean URLs up to 4K). Falls back to the classic rotation on failure.
    data = _fast_extract(video_id)
    if not data:
        for attempt in range(max_attempts):
            for _ in range(len(rotation)):
                clients = rotation[_client_idx % len(rotation)]
                _client_idx += 1
                extractor_args = {'youtube': {'player_client': clients}}
                ydl_opts['extractor_args'] = extractor_args
                client_label = '+'.join(clients)
                _log('Attempt with client: {}'.format(client_label))

                try:
                    from yt_dlp import YoutubeDL
                    with YoutubeDL(ydl_opts) as ydl:
                        data = ydl.extract_info(url, download=False)
                except Exception as e:
                    msg = str(e)
                    errors.append('{}: {}'.format(client_label, msg))
                    _log('Client {} failed: {}'.format(client_label, msg), xbmc.LOGWARNING)
                    if 'Sign in to confirm' not in msg and 'HTTP Error' not in msg:
                        raise
                    xbmc.sleep(int(2000 + random.random() * 3000))
                    continue
                if data:
                    break
            if not data:
                continue
            ok, bad_id = _check_urls_servable(data)
            if ok:
                break
            last_tainted = data
            data = None
            _log('Extraction {} tainted on format {}; re-extracting ({}/{})'.format(
                attempt + 1, bad_id, attempt + 1, max_attempts), xbmc.LOGWARNING)
            xbmc.sleep(int(1500 + random.random() * 2000))
        if not data:
            fallback_fmt = _find_clean_progressive(last_tainted) if last_tainted else None
            if fallback_fmt:
                _log('All DASH extractions tainted; falling back to progressive itag {}'.format(
                    fallback_fmt.get('format_id')), xbmc.LOGWARNING)
            else:
                err_msg = 'All clients failed: {}'.format(' | '.join(errors))
                _log(err_msg, xbmc.LOGERROR)
                raise Exception(err_msg)

    if not data:
        raise Exception('No data returned for video_id: {}'.format(video_id))

    _log('Title: {} | Duration: {}s'.format(
        (data or {}).get('title', '?'), (data or {}).get('duration', '?')))

    li = xbmcgui.ListItem()
    display_title = (data or {}).get('title') or title or 'Trailer'
    tag = li.getVideoInfoTag()
    tag.setTitle(display_title)
    tag.setOriginalTitle(display_title)
    if year and str(year).isdigit():
        tag.setYear(int(year))
    if genre:
        genres_list = [g.strip() for g in genre.replace('/', ',').split(',') if g.strip()]
        tag.setGenres(genres_list)

    # Build YouTube CDN headers for InputStream Adaptive segment requests
    yt_headers = dict(_YT_HEADERS)
    for fmt in (data or {}).get('formats', []):
        fh = fmt.get('http_headers') or {}
        for k, v in fh.items():
            if k.lower() not in ('user-agent', 'accept'):
                yt_headers[k] = v

    port = None
    if data and data.get('formats'):
        port = _start_proxy()
    proxy_base = 'http://127.0.0.1:{}/'.format(port) if port else ''
    mpd, headers = _build_mpd(data, proxy_base) if data else (None, {})

    if fallback_fmt:
        direct_url = fallback_fmt.get('url')
        _log('Progressive fallback direct URL (ext={})'.format(fallback_fmt.get('ext', '?')))
        li.setPath(direct_url)
        fh = fallback_fmt.get('http_headers') or {}
        hdr = '&'.join('{}={}'.format(k, v) for k, v in fh.items())
        if hdr:
            li.setProperty('inputstream.adaptive.stream_headers', hdr)
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        return li

    if mpd:

        mpd_path = 'special://temp/yt_{}.mpd'.format(video_id)
        local_mpd = xbmcvfs.translatePath(mpd_path)
        with open(local_mpd, 'w') as f:
            f.write(mpd)

        # Set stream_headers so Kodi sends YouTube UA/Origin/Referer directly to CDN
        hdr_parts = []
        for k, v in yt_headers.items():
            hdr_parts.append('{}={}'.format(k, v))
        if hdr_parts:
            li.setProperty('inputstream.adaptive.stream_headers', '&'.join(hdr_parts))

        proxy_url = 'http://127.0.0.1:{}/{}'.format(port, mpd_path)

        max_height = 0
        max_width = 0
        for fmt in data.get('formats', []):
            if fmt.get('vcodec', 'none') != 'none' and fmt.get('height', 0) > max_height:
                max_height = fmt['height']
                max_width = fmt.get('width', 0)

        li.setPath(proxy_url)
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        if max_width and max_height:
            li.setProperty('inputstream.adaptive.stream_res', '{}x{}'.format(max_width, max_height))
        _log('DASH MPD via proxy on port {} (max res: {}x{})'.format(port, max_width, max_height))
        return li

    if data and data.get('manifest_url'):
        _log('HLS manifest')
        li.setPath(data['manifest_url'])
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        http_headers = data.get('http_headers', {})
        if http_headers:
            li.setProperty('inputstream.adaptive.stream_headers', json.dumps(http_headers))
        return li

    direct_url = (data or {}).get('url')
    if direct_url:
        _log('Direct URL: ext={}'.format(data.get('ext', '?')))
        li.setPath(direct_url)
        http_headers = data.get('http_headers', {})
        if http_headers:
            hdr = '&'.join('{}={}'.format(k, v) for k, v in http_headers.items())
            li.setProperty('inputstream.adaptive.stream_headers', hdr)
        return li

    raise Exception('No playable streams found for video_id: {}'.format(video_id))
