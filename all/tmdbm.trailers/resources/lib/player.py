import os
import sys
import json
import socket
import glob
import random
import time
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
    _base_url = None  # set by play_youtube to replace BaseURL prefix

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

        for attempt in range(3):
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
                if resp.status_code >= 500 and attempt < 2:
                    _log('Proxy retry {} after HTTP {}'.format(attempt + 1, resp.status_code), xbmc.LOGWARNING)
                    resp.close()
                    continue
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
                resp.close()
                return
            except Exception as e:
                _log('Proxy segment error (attempt {}): {}'.format(attempt + 1, str(e)), xbmc.LOGERROR)
                if attempt < 2:
                    continue
                self.send_error(502)
                _log('Proxy 502 after 3 retries: {}'.format(url[:120]), xbmc.LOGERROR)


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


def _build_mpd(data):
    from collections import defaultdict

    duration = data.get('duration', 0)
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

    for idx, (group, formats) in enumerate(groups.items()):
        contentType = 'video' if group == 'video/mp4' else 'audio'
        mpd += '\n<AdaptationSet id="{}" group="{}" contentType="{}" mimeType="{}" subsegmentAlignment="true" subsegmentStartsWithSAP="1" bitstreamSwitching="true"><Role schemeIdUri="urn:mpeg:DASH:role:2011" value="main"/>'.format(
            idx, idx + 1, contentType, group
        )
        for fmt in formats:
            headers.update(fmt.get('http_headers', {}))
            fmt_url = fix_url(fmt['url'])
            codec = fmt['vcodec'] if fmt['vcodec'] != 'none' else fmt['acodec']
            mpd += '\n<Representation id="{}" codecs="{}" bandwidth="{}"'.format(
                fmt['format_id'], codec, fmt['bitrate']
            )
            if fmt['vcodec'] != 'none':
                mpd += ' width="{}" height="{}" frameRate="{}"'.format(
                    fmt['width'], fmt['height'], fmt['fps']
                )
            mpd += '>'
            if fmt['acodec'] != 'none':
                mpd += '\n<AudioChannelConfiguration schemeIdUri="urn:mpeg:dash:23003:3:audio_channel_configuration:2011" value="2"/>'
            mpd += '\n<BaseURL>{}</BaseURL>\n<SegmentBase indexRange="{}-{}" timescale="1000">\n<Initialization range="{}-{}" />\n</SegmentBase>'.format(
                fmt_url,
                fmt['indexRange']['start'], fmt['indexRange']['end'],
                fmt['initRange']['start'], fmt['initRange']['end']
            )
            mpd += '\n</Representation>'
        mpd += '\n</AdaptationSet>'

    mpd += '\n</Period>\n</MPD>'
    return mpd, headers


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

    # Rotate player clients on each call; if blocked, try next client
    global _client_idx
    errors = []
    for _ in range(len(_CLIENT_ROTATION)):
        clients = _CLIENT_ROTATION[_client_idx % len(_CLIENT_ROTATION)]
        _client_idx += 1
        extractor_args = {'youtube': {'player_client': clients}}
        ydl_opts['extractor_args'] = extractor_args
        client_label = '+'.join(clients)
        _log('Attempt with client: {}'.format(client_label))

        try:
            from yt_dlp import YoutubeDL
            with YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(url, download=False)
            if data:
                break
        except Exception as e:
            msg = str(e)
            errors.append('{}: {}'.format(client_label, msg))
            _log('Client {} failed: {}'.format(client_label, msg), xbmc.LOGWARNING)
            if 'Sign in to confirm' not in msg and 'HTTP Error' not in msg:
                raise
            xbmc.sleep(int(2000 + random.random() * 3000))
            continue
    else:
        err_msg = 'All clients failed: {}'.format(' | '.join(errors))
        _log(err_msg, xbmc.LOGERROR)
        raise Exception(err_msg)

    if not data:
        raise Exception('No data returned for video_id: {}'.format(video_id))

    _log('Title: {} | Duration: {}s'.format(data.get('title', '?'), data.get('duration', '?')))

    li = xbmcgui.ListItem()
    display_title = data.get('title') or title or 'Trailer'
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
    for fmt in data.get('formats', []):
        fh = fmt.get('http_headers') or {}
        yt_headers.update(fh)

    mpd, headers = _build_mpd(data)
    if mpd:
        port = _start_proxy()

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

    if data.get('manifest_url'):
        _log('HLS manifest')
        li.setPath(data['manifest_url'])
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        http_headers = data.get('http_headers', {})
        if http_headers:
            li.setProperty('inputstream.adaptive.stream_headers', json.dumps(http_headers))
        return li

    direct_url = data.get('url')
    if direct_url:
        _log('Direct URL: ext={}'.format(data.get('ext', '?')))
        li.setPath(direct_url)
        http_headers = data.get('http_headers', {})
        if http_headers:
            hdr = '&'.join('{}={}'.format(k, v) for k, v in http_headers.items())
            li.setProperty('inputstream.adaptive.stream_headers', hdr)
        return li

    raise Exception('No playable streams found for video_id: {}'.format(video_id))
