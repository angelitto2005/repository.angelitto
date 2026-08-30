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


def _get_setting(name, default=''):
    """Read a setting fresh at call time.
    With reuselanguageinvoker the single ADDON object caches setting values
    at import time, so values changed in Settings while the Python process
    stays alive are not seen. Reading through JSON-RPC (Settings Manager)
    bypasses that stale C++ cache; falls back to the cached getter."""
    try:
        import xbmc as _x
        res = _x.executeJSONRPC(
            '{{"jsonrpc":"2.0","method":"Settings.GetSettingValue",'
            '"params":{{"setting":"{}.{}"}},"id":1}}'.format(_ADDON_NS, name))
        import json as _json
        obj = _json.loads(res)
        val = obj.get('result', {}).get('value')
        if val is not None:
            return str(val)
    except Exception:
        pass
    try:
        return ADDON.getSetting(name)
    except Exception:
        return default


_ADDON_NS = 'tmdbm.trailers'



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
        global _proxy_last_req
        _proxy_last_req = time.time()
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


# ---------------------------------------------------------------------------
# Shutdown hygiene: Kodi's Python invoker waits (up to 5s, then force-kills)
# for the resident interpreter to exit. Any non-daemon thread blocks that
# via threading._shutdown -> Kodi hangs ~20s on exit with the process stuck
# in Task Manager. We never rely on thread completion after playback, so
# EVERY thread in this interpreter is forced daemonic.
_orig_thread_init = threading.Thread.__init__


def _force_daemon_thread_init(self, *args, **kwargs):
    _orig_thread_init(self, *args, **kwargs)
    try:
        self.daemon = True
    except Exception:
        pass


threading.Thread.__init__ = _force_daemon_thread_init
# ---------------------------------------------------------------------------

_proxy_last_req = 0.0  # last time a client hit the proxy
_PROXY_IDLE_SECS = 120  # stop proxy after this much idle time w/o playback


def _proxy_idle_watchdog():
    """Daemon: shuts the local proxy down once playback stopped and no
    request arrived for _PROXY_IDLE_SECS - releases port/sockets so neither
    Kodi shutdown nor the next launch ever waits on them."""
    mon = xbmc.Monitor()
    pl = xbmc.Player()
    while not mon.abortRequested():
        if mon.waitForAbort(5):
            break
        try:
            playing = pl.isPlayingVideo()
        except Exception:
            playing = False
        if playing:
            continue
        try:
            idle = time.time() - _proxy_last_req
        except Exception:
            continue
        if idle > _PROXY_IDLE_SECS:
            break
    _cleanup_player('idle watchdog')


def _cleanup_player(reason):
    """Close proxy server + pooled session; log any surviving threads so a
    future shutdown hang is diagnosable from kodi.log."""
    global _proxy_server, _proxy_port
    try:
        names = sorted(t.name for t in threading.enumerate() if t.is_alive())
        _log('Cleanup ({}): live_threads={}'.format(reason, names))
    except Exception:
        pass
    srv = _proxy_server
    if srv:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
        _proxy_server = None
        _proxy_port = None
        _log('Proxy stopped ({})'.format(reason))
    sess = getattr(_ProxyHandler, '_session', None)
    if sess:
        try:
            sess.close()
        except Exception:
            pass
        _ProxyHandler._session = None


import atexit as _atexit

_atexit.register(_cleanup_player, 'atexit')


def _start_proxy():
    global _proxy_server, _proxy_port, _proxy_last_req
    if _proxy_server:
        return _proxy_port

    _proxy_last_req = time.time()
    _proxy_port = _find_free_port()
    _proxy_server = _ThreadedHTTPServer(('127.0.0.1', _proxy_port), _ProxyHandler)
    t = threading.Thread(target=_proxy_server.serve_forever, daemon=True)
    t.start()
    w = threading.Thread(target=_proxy_idle_watchdog, daemon=True)
    w.start()
    _log('Proxy started on port {}'.format(_proxy_port))
    return _proxy_port


def _stop_proxy():
    global _proxy_server, _proxy_port
    if _proxy_server:
        _proxy_server.shutdown()
        _proxy_server = None
        _proxy_port = None


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
            # Pin locale: prevents the server from auto-selecting a localized
            # DUBBED audio track based on IP/language (original audio request).
            'hl': 'en',
            'gl': 'US',
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
            # Audio track role: '.4' = original/main, '.3' = dub,
            # '.6' = secondary, '.0' = descriptive (yt-dlp convention).
            at_id = (f.get('audioTrack') or {}).get('id') or ''
            fmt['_arole'] = at_id.rsplit('.', 1)[-1] if '.' in at_id else '4'
        elif kind == 'video' and sub == 'webm':
            # VP9 - only used when the user caps at 4K (no h264 exists >1080p)
            fmt['container'] = 'webm_dash'
            fmt['vcodec'] = codecs or 'vp9'
            fmt['acodec'] = 'none'
        else:
            continue  # webm/vp9 etc - not used by our MPD pipeline
        formats.append(fmt)
    if not formats:
        raise Exception('innertube returned no usable formats')
    # Original audio only: when the response carries multiple audio tracks
    # (original + dubs), keep exclusively the original/main ones.
    orig_audio = [f for f in formats
                  if f.get('container') == 'm4a_dash' and f.get('_arole') == '4']
    if orig_audio:
        kept = set(id(f) for f in orig_audio)
        formats = [f for f in formats
                   if f.get('container') != 'm4a_dash' or id(f) in kept]
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


_TMDB_API_KEY = '8ad3c21a92a64da832c559d58cc63ab4'

# Clip/spot alternative videos shorter than this (seconds) are deprioritized
# in favor of real trailer-length clips.
_MIN_TRAILER_DURATION = 30


def _search_innertube(query, max_results=5):
    """Search YouTube via the same ios_testsuite client used for playback.
    Returns a list of (video_id, title) for real video results."""
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
            'hl': 'en',
            'gl': 'US',
        }},
        'cpn': cpn,
        'query': query,
    }
    headers = {
        'Origin': 'https://m.youtube.com',
        'User-Agent': _IOS_TS_UA,
        'X-YouTube-Client-Name': '5',
        'X-YouTube-Client-Version': '20.20.7',
        'Content-Type': 'application/json',
    }
    try:
        r = _rq.post('https://www.youtube.com/youtubei/v1/search?prettyPrint=false',
                     data=json.dumps(payload), headers=headers, timeout=20)
        body = r.json()
    except Exception as e:
        _log('search innertube error: {}'.format(str(e)[:120]), xbmc.LOGWARNING)
        return []

    out = []
    seen_ids = set()

    def push(vid, title):
        if vid in seen_ids or not vid:
            return
        seen_ids.add(vid)
        out.append((vid, title.strip()))
        return len(out) >= max_results

    def walk(node, cur_title=''):
        if len(out) >= max_results:
            return True
        if isinstance(node, dict):
            vr = node.get('videoRenderer')
            if isinstance(vr, dict):
                vid = vr.get('videoId') or ''
                runs = (vr.get('title') or {}).get('runs') or []
                t = ''.join(x.get('text', '') for x in runs) if runs else (
                    (vr.get('title') or {}).get('simpleText') or '')
                if push(vid, t):
                    return True
            # New 'element' format: compactVideoModel holds title+watchEndpoint
            cvm = node.get('compactVideoModel')
            if isinstance(cvm, dict):
                try:
                    cur_title = cvm['compactVideoData']['videoData']['metadata']['title']
                except Exception:
                    cur_title = ''
            w = node.get('watchEndpoint')
            if isinstance(w, dict) and w.get('videoId'):
                if push(w['videoId'], cur_title or ''):
                    return True
            for v in node.values():
                if walk(v, cur_title):
                    return True
        elif isinstance(node, list):
            for v in node:
                if walk(v, cur_title):
                    return True
        return False

    try:
        contents = body['contents']['sectionListRenderer']['contents']
    except Exception:
        contents = None
    if contents is None:
        try:
            contents = body['contents']['twoColumnSearchResultsRenderer'][
                'primaryContents']['sectionListRenderer']['contents']
        except Exception:
            contents = []

    done = False
    for sec in contents:
        if done:
            break
        done = walk(sec)

    if not out and contents:
        _log('search returned no parseable results for "{}"'.format(query),
             xbmc.LOGWARNING)
    return out


def _tmdb_alt_videos(tmdb_id, dbtype, excluded):
    """Other playable TMDb videos for the same title, prioritizing real
    trailers (with 'trailer' in the name) over teasers/clips/spots."""
    import requests as _rq
    if not tmdb_id:
        return []
    media_type = 'tv' if (dbtype or '').lower() in ('tvshow', 'tv') else 'movie'
    try:
        url = ('https://api.themoviedb.org/3/{}/{}'
               '/videos?api_key={}&language=en-US').format(
                   media_type, tmdb_id, _TMDB_API_KEY)
        r = _rq.get(url, timeout=10)
        data = r.json()
    except Exception as e:
        _log('TMDb alt videos error: {}'.format(str(e)[:120]), xbmc.LOGWARNING)
        return []
    scored = []
    for v in (data.get('results') or []):
        if not (v.get('site') == 'YouTube' and v.get('key')):
            continue
        if v['key'] in excluded:
            continue
        name = (v.get('name') or '').lower()
        vtype = (v.get('type') or '').lower()
        score = 0
        if 'trailer' in name:
            score += 3
        if vtype == 'trailer':
            score += 2
        elif vtype == 'teaser':
            score += 1
        scored.append((score, v['key']))
    scored.sort(key=lambda x: -x[0])
    result = [k for _, k in scored]
    if result:
        _log('Found {} alt TMDb trailer candidate(s)'.format(len(result)))
    return result


def _try_alt_trailer(video_id, title, year, tmdb_id, dbtype, excluded):
    """Find and return playable data for an ALTERNATIVE trailer when the
    requested one is blocked (geo/availability). Tries TMDb alternates first,
    then a YouTube search by title. Prefers real trailer-length clips
    (>= MIN_TRAILER_DURATION s) over short spots/teasers; falls back to the
    longest servable clip if none is trailer-length. Returns data or None."""
    import re as _re
    candidates = []
    try:
        candidates += _tmdb_alt_videos(tmdb_id, dbtype, excluded)
    except Exception:
        pass
    if title:
        queries = []
        if year and str(year).isdigit():
            queries.append('{title} {year} official trailer'.format(
                title=title, year=year))
        queries.append('{t} trailer'.format(t=title))
        if not candidates:
            queries.append(title)
        for q in queries:
            for vid, _t in _search_innertube(q):
                if vid not in excluded and vid not in candidates:
                    candidates.append(vid)
            if candidates:
                break
    seen = set()
    servable = []
    for vid in candidates:
        if vid in seen:
            continue
        seen.add(vid)
        try:
            data = _extract_innertube_ios(vid)
        except Exception:
            continue
        try:
            ok, bad = _check_urls_servable(data)
        except Exception:
            ok, bad = False, '?'
        if ok:
            dur = 0
            try:
                dur = int(float(data.get('duration') or 0))
            except Exception:
                dur = 0
            _log('Alt trailer {vid} playable (duration {d}s)'.format(vid=vid, d=dur))
            servable.append((dur, vid, data))
    if not servable:
        return None
    servable.sort(key=lambda x: x[0], reverse=True)
    pick = None
    for dur, vid, data in servable:
        if dur >= _MIN_TRAILER_DURATION:
            pick = (vid, data)
            break
    if pick is None:
        pick = (servable[0][1], servable[0][2])
    _log('Selected alt trailer {vid} (duration {d}s)'.format(
        vid=pick[0], d=pick[1].get('duration')))
    return pick[1]


_RES_LEVELS = (720, 1080, 2160)


def _screen_height():
    """Native display height (second dimension of System.ScreenResolution),
    e.g. '3840x2160@60.00' -> 2160. Returns 0 when unavailable."""
    import re as _re
    try:
        res = xbmc.getInfoLabel('System.ScreenResolution') or ''
        m = _re.search(r'(\d{3,5})\s*x\s*(\d{3,5})', res)
        if m:
            return int(m.group(2))
    except Exception:
        pass
    return 0


def _max_res_height():
    """User-selected maximum trailer resolution.
    Enum order: 0=Auto, 1=720p, 2=1080p, 3=4K.
    'Auto' follows the TV's native resolution (falls back to 1080p when
    the display size is unknown)."""
    try:
        idx = int(_get_setting('trailer_max_res', '0') or 0)
    except Exception:
        idx = 0
    h = _screen_height()
    _log('max_res: idx={} screen={}'.format(idx, h), getattr(xbmc, 'LOGDEBUG', 4))
    if idx == 0:
        # Auto: snap the panel height onto our quality ladder
        if h >= 2160:
            return 2160
        if h >= 1080:
            return 1080
        if h > 0:
            return 720
        return 1080
    if idx == 1:
        return 720
    if idx == 2:
        return 1080
    return 2160


def _build_mpd(data, proxy_base=''):
    from collections import defaultdict

    duration = data.get('duration', 0) or 0
    if not duration:
        for fmt in data.get('formats', []):
            if fmt.get('duration'):
                duration = int(fmt['duration'])
                break
    groups = defaultdict(list)
    # YouTube has NO h264 above 1080p - 1440p/2160p exist only as VP9 (webm)
    # or AV1. VP9 groups are included ONLY when the user explicitly selects
    # the 4K cap (opt-in; older/weaker devices should stay on 720/1080).
    allow_vp9 = _max_res_height() >= 2160
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

    cap_height = _max_res_height()
    target_height = cap_height

    def _is_video_codec(fmt):
        vc = fmt.get('vcodec', 'none')
        if vc == 'none' or vc.startswith('av01'):
            return False
        if not allow_vp9 and vc.startswith('vp'):
            return False
        return True

    heights = {fmt.get('height', 0) for fmt in data.get('formats', [])
               if fmt.get('container') in ('mp4_dash', 'webm_dash')
               and _is_video_codec(fmt)
               and fmt.get('height', 0) > 0}
    if heights:
        candidates = [h for h in heights if h <= cap_height]
        target_height = max(candidates) if candidates else min(heights)

    # Fixed mode (1=720p, 2=1080p, 3=4K): pin the video ladder to the single
    # target height so ISA cannot drop below it on a smaller window/network.
    # Auto (0) keeps the full ladder below the cap (adaptive).
    fixed_mode = False
    try:
        fixed_mode = int(_get_setting('trailer_max_res', '0') or 0) != 0
    except Exception:
        fixed_mode = False

    for fmt in data.get('formats', []):
        if 'container' not in fmt:
            continue
        container = fmt['container']
        if container == 'mp4_dash' and _is_video_codec(fmt):
            # Full ladder below the cap so ISA can adapt to network speed
            if fixed_mode:
                if fmt.get('height', 0) == target_height:
                    groups['video/mp4'].append(fmt)
            elif 0 < fmt.get('height', 0) <= target_height:
                groups['video/mp4'].append(fmt)
        elif (allow_vp9 and container == 'webm_dash'
              and _is_video_codec(fmt)):
            if fixed_mode:
                if fmt.get('height', 0) == target_height:
                    groups['video/webm'].append(fmt)
            elif 0 < fmt.get('height', 0) <= target_height:
                groups['video/webm'].append(fmt)

    if not groups:
        return None, {}

    def fix_url(url):
        return unquote(url).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    headers = {}
    mpd = '<MPD minBufferTime="PT1.5S" mediaPresentationDuration="PT{}S" type="static" profiles="urn:mpeg:dash:profile:isoff-main:2011">\n<Period>'.format(duration)

    written_sets = 0
    for idx, (group, formats) in enumerate(groups.items()):
        contentType = 'audio' if group == 'audio/mp4' else 'video'
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


def play_youtube(video_id, title=None, genre=None, year=None,
                 tmdb_id=None, dbtype=None):
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

    url = 'https://www.youtube.com/watch?v={}'.format(video_id)
    _log('Extracting: {}'.format(url))

    # Innertube-only extraction (pure Python, no yt-dlp, no JS runtime,
    # no third-party binaries): replicates plugin.video.youtube's working
    # ios_testsuite client. Falls back to an emergency progressive (muxed)
    # format when the DASH URL-set is tainted/blocked.
    data = None
    raw_tainted = None
    last_err = ''
    permanent = False
    for attempt in range(3):
        data = _fast_extract(video_id)
        if data:
            break
        try:
            raw_tainted = _extract_innertube_ios(video_id)
        except Exception as _e:
            last_err = str(_e)
            raw_tainted = None
        permanent = ('UNPLAYABLE' in last_err
                     or 'not available' in last_err
                     or 'country' in last_err.lower())
        if permanent:
            _log('Permanent unavailability (geo-block); skipping retries',
                 xbmc.LOGWARNING)
            break
        _log('Extraction attempt {} failed; retrying ({}/3)'.format(
            attempt + 1, attempt + 1), xbmc.LOGWARNING)
        xbmc.sleep(int(1500 + random.random() * 2000))

    fallback_fmt = None
    if not data:
        fallback_fmt = _find_clean_progressive(raw_tainted) if raw_tainted else None
        if fallback_fmt:
            _log('All DASH extractions tainted; falling back to progressive itag {}'.format(
                fallback_fmt.get('format_id')), xbmc.LOGWARNING)
        else:
            # Permanent unavailability (geo-block etc.) -> try an alternate
            # trailer automatically so playback still works.
            permanent = ('UNPLAYABLE' in last_err
                         or 'not available' in last_err
                         or 'country' in last_err.lower())
            if permanent:
                alt = _try_alt_trailer(video_id, title, year, tmdb_id, dbtype,
                                       excluded={video_id})
                if alt:
                    data = alt
            if not data:
                err_msg = 'Extraction failed for ' + video_id
                _log(err_msg, xbmc.LOGERROR)
                raise Exception(err_msg)

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
        cap_h = _max_res_height()
        for fmt in data.get('formats', []):
            h = fmt.get('height', 0) or 0
            if (fmt.get('vcodec', 'none') != 'none'
                    and 0 < h <= cap_h and h > max_height):
                max_height = h
                max_width = fmt.get('width', 0) or 0

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
