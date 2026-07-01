import os
import sys
import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse

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


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _ProxyHandler(BaseHTTPRequestHandler):
    _mpd_content = None
    _mpd_headers = None
    _segment_headers = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.lstrip('/')

        if path.startswith('special://'):
            local_path = xbmcvfs.translatePath(path)
            if path.endswith('.mpd'):
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

        parsed = urlparse(self.path)
        url = unquote(parsed.path[1:])

        if not url.startswith(('http://', 'https://')):
            self.send_error(404)
            return

        try:
            import requests as req
            headers = {}
            if self._segment_headers:
                for k, v in self._segment_headers.items():
                    headers[k] = v

            range_header = self.headers.get('Range')
            if range_header:
                headers['Range'] = range_header

            resp = req.get(url, headers=headers, timeout=30, stream=True)
            self.send_response(resp.status_code)
            for key, value in resp.headers.items():
                if key.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(key, value)
            self.end_headers()
            for chunk in resp.iter_content(chunk_size=65536):
                self.wfile.write(chunk)
        except Exception as e:
            self.send_error(502)


def _start_proxy():
    global _proxy_server, _proxy_port
    if _proxy_server:
        return _proxy_port

    _proxy_port = _find_free_port()
    _proxy_server = HTTPServer(('127.0.0.1', _proxy_port), _ProxyHandler)
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
        if container == 'webm_dash':
            if fmt['vcodec'] != 'none':
                groups['video/webm'].append(fmt)
            else:
                groups['audio/webm'].append(fmt)
        elif container == 'mp4_dash':
            groups['video/mp4'].append(fmt)
        elif container == 'm4a_dash':
            groups['audio/mp4'].append(fmt)

    if not groups:
        return None, {}

    def fix_url(url):
        return unquote(url).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    headers = {}
    mpd = '<MPD minBufferTime="PT1.5S" mediaPresentationDuration="PT{}S" type="static" profiles="urn:mpeg:dash:profile:isoff-main:2011">\n<Period>'.format(duration)

    for idx, (group, formats) in enumerate(groups.items()):
        mpd += '\n<AdaptationSet id="{}" mimeType="{}"><Role schemeIdUri="urn:mpeg:DASH:role:2011" value="main"/>'.format(idx, group)
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
            mpd += '\n<BaseURL>{}</BaseURL>\n<SegmentBase indexRange="{}-{}">\n<Initialization range="{}-{}" />\n</SegmentBase>'.format(
                fmt_url,
                fmt['indexRange']['start'], fmt['indexRange']['end'],
                fmt['initRange']['start'], fmt['initRange']['end']
            )
            mpd += '\n</Representation>'
        mpd += '\n</AdaptationSet>'

    mpd += '\n</Period>\n</MPD>'
    return mpd, headers


def play_youtube(video_id, title=None, genre=None, year=None):
    ydl_opts = {
        'format': 'best/bestvideo+bestaudio',
        'check_formats': False,
        'cachedir': ADDON_PROFILE,
        'js_runtimes': _get_js_runtimes(),
        'quiet': True,
        'no_warnings': True,
    }

    url = 'https://www.youtube.com/watch?v={}'.format(video_id)
    _log('Extracting: {}'.format(url))

    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception as e:
        _log('yt-dlp failed: {}'.format(e), xbmc.LOGERROR)
        raise

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

    mpd, headers = _build_mpd(data)
    if mpd:
        mpd_path = 'special://temp/yt_{}.mpd'.format(video_id)
        with open(xbmcvfs.translatePath(mpd_path), 'w') as f:
            f.write(mpd)

        port = _start_proxy()
        proxy_url = 'http://127.0.0.1:{}/{}'.format(port, mpd_path)

        _ProxyHandler._segment_headers = headers

        max_height = 0
        max_width = 0
        for fmt in data.get('formats', []):
            if fmt.get('vcodec', 'none') != 'none' and fmt.get('height', 0) > max_height:
                max_height = fmt['height']
                max_width = fmt.get('width', 0)

        li.setPath(proxy_url)
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        li.setProperty('inputstream.adaptive.manifest_type', 'mpd')
        if max_width and max_height:
            li.setProperty('inputstream.adaptive.stream_res', '{}x{}'.format(max_width, max_height))
        _log('DASH MPD via proxy on port {} (max res: {}x{})'.format(port, max_width, max_height))
        return li

    if data.get('manifest_url'):
        _log('HLS manifest')
        li.setPath(data['manifest_url'])
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        li.setProperty('inputstream.adaptive.manifest_type', 'hls')
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
