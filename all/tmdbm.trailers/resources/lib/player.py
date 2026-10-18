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
        import config as _cfg
        return _cfg.get_setting(name, default)
    except Exception:
        pass
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


def _log(msg, level=xbmc.LOGINFO, always=False):
    try:
        import config
    except Exception:
        xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)
        return
    config.log(msg, level, always=always)


# An MPD is written by the clip that is about to play, and Kodi reads it a few
# hundred milliseconds later through the proxy. Removing every one of them at
# the start of the next playback therefore deletes the manifest of a clip that
# is still opening: opening another track a couple of seconds apart, or Kodi
# retrying a failed start, then asks the proxy for a file that is gone, and the
# answer is a playback failed dialog. Anything younger than this is left alone,
# and the manifest is also kept in memory so the file cannot break playback.
_MPD_GRACE_SECS = 10 * 60
_MPD_MEM = {}
_MPD_MEM_MAX = 8


def _mpd_remember(path, text):
    """Hold the manifest beside its file, so the file is only a convenience."""
    payload = text.encode('utf-8') if isinstance(text, str) else text
    _MPD_MEM[path] = (time.time(), payload)
    while len(_MPD_MEM) > _MPD_MEM_MAX:
        oldest = min(_MPD_MEM, key=lambda key: _MPD_MEM[key][0])
        _MPD_MEM.pop(oldest, None)


def _mpd_from_memory(path):
    item = _MPD_MEM.get(path)
    return item[1] if item else None


def _cleanup_old_mpd():
    cutoff = time.time() - _MPD_GRACE_SECS
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
                full = os.path.join(temp_dir, f)
                try:
                    if os.path.getmtime(full) > cutoff:
                        continue
                    os.remove(full)
                except Exception:
                    pass
    for path in [key for key, item in _MPD_MEM.items() if item[0] <= cutoff]:
        _MPD_MEM.pop(path, None)


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

def _new_session(profile=0):
    import config
    return config.new_session(profile)


class _ProxyHandler(BaseHTTPRequestHandler):
    _mpd_content = None
    _mpd_headers = None
    _segment_headers = None
    _session = None
    _subs_cache_dir = None
    _SUBS_CACHE_TTL = 30 * 86400
    _SUBS_CACHE_CAP = 200

    def log_message(self, format, *args):
        pass

    @classmethod
    def _subs_cache_path(cls, url):
        try:
            import re as _re
            from urllib.parse import urlparse as _up, parse_qs as _pq
            query = _pq(_up(url).query)
            vid = (query.get('v', ['']) or [''])[0]
            vid = _re.sub(r'[^A-Za-z0-9_-]', '', vid)[:16]
            lang = (query.get('tlang') or query.get('lang') or ['und'])[0]
            lang = _re.sub(r'[^A-Za-z-]', '', lang)[:12] or 'und'
            if not vid:
                return ''
            if cls._subs_cache_dir is None:
                cls._subs_cache_dir = xbmcvfs.translatePath('special://temp/yt_subs')
            try:
                os.makedirs(cls._subs_cache_dir, exist_ok=True)
            except OSError:
                pass
            return os.path.join(cls._subs_cache_dir, '{}_{}.vtt'.format(vid, lang))
        except Exception:
            return ''

    def _serve_cached_subs(self, path):
        try:
            if not path or not os.path.isfile(path):
                return False
            if time.time() - os.path.getmtime(path) > _ProxyHandler._SUBS_CACHE_TTL:
                return False
            with open(path, 'rb') as handle:
                payload = handle.read()
            if not payload:
                return False
            self.send_response(200)
            self.send_header('Content-Type', 'text/vtt')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            _log('Subtitle served from cache')
            return True
        except Exception:
            return False

    def _store_cached_subs(self, path, payload):
        try:
            if not path or not payload:
                return
            tmp_path = path + '.tmp'
            with open(tmp_path, 'wb') as handle:
                handle.write(payload)
            os.replace(tmp_path, path)
            try:
                entries = [(os.path.getmtime(os.path.join(self._subs_cache_dir, name)), name)
                           for name in os.listdir(self._subs_cache_dir)]
            except OSError:
                return
            for _, name in sorted(entries)[:-self._SUBS_CACHE_CAP]:
                try:
                    os.remove(os.path.join(self._subs_cache_dir, name))
                except OSError:
                    pass
        except Exception:
            pass

    def do_GET(self):
        global _proxy_last_req
        _proxy_last_req = time.time()
        raw = self.path.lstrip('/')

        if raw.startswith('special://'):
            local_path = xbmcvfs.translatePath(raw)
            if raw.endswith('.mpd'):
                payload = _mpd_from_memory(raw)
                if payload is None and os.path.exists(local_path):
                    try:
                        with open(local_path, 'rb') as f:
                            payload = f.read()
                    except Exception:
                        payload = None
                if payload is None:
                    # nothing to serve: a plain 404 keeps ISA and the log calm
                    # instead of an unreadable file raised inside the handler
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/dash+xml')
                self.end_headers()
                self.wfile.write(payload)
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

        subs_path = ''
        if '/api/timedtext' in url:
            subs_path = _ProxyHandler._subs_cache_path(url)
            if subs_path and self._serve_cached_subs(subs_path):
                return

        max_attempts = 5
        backoff = (0.3, 0.6, 1.2, 2.4)
        for attempt in range(max_attempts):
            try:
                if not _ProxyHandler._session:
                    _ProxyHandler._session = _api_session()

                headers = dict(_YT_HEADERS)
                if self._segment_headers:
                    for k, v in self._segment_headers.items():
                        headers[k] = v

                range_header = self.headers.get('Range')
                if range_header:
                    headers['Range'] = range_header
                headers['Accept-Encoding'] = 'identity'

                resp = _ProxyHandler._session.get(url, headers=headers, timeout=120, stream=True)
                do_retry = attempt < max_attempts - 1 and (
                    (resp.status_code in (403, 429)
                     and ('googlevideo.com' in url or 'youtube.com' in url))
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
                if subs_path and resp.status_code == 200 and not range_header:
                    try:
                        payload = resp.content
                    except Exception:
                        payload = b''
                    if payload.startswith(b'WEBVTT'):
                        self._store_cached_subs(subs_path, payload)
                    try:
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/vtt')
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    except ConnectionError:
                        _log('Proxy client aborted during response (Range: {})'.format(
                            range_header or '-'))
                    finally:
                        resp.close()
                    return
                try:
                    self.send_response(resp.status_code)
                    with_lower = {k.lower() for k in resp.headers}
                    has_content_range = 'content-range' in with_lower
                    for key, value in resp.headers.items():
                        kl = key.lower()
                        if kl in ('transfer-encoding', 'connection',
                                  'content-encoding'):
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


def _true_fps(url, declared=None, headers=None, timeout=15):
    """Measure the real frame rate from tfhd default sample duration.

    YouTube reports integer fps (24 for 23.976 content), and our MPD repeats
    it: Kodi picks 24.0 at start, then resyncs mid-play when the demuxer
    measures 23.976 (the 1-2s freeze ~9s in). Neither stts (empty in DASH
    init segments) nor SPS VUI timing (absent in YouTube encodes) is usable,
    but the first moof carries tfhd default_sample_duration, which combined
    with the video mdhd timescale gives the exact rate (24000/1001 here).
    Cross-checked against declared: full and half candidates, whichever lands
    within 2% wins. Returns '24000/1001', '24', etc., or None.
    """
    import math as _math
    try:
        session = _ProxyHandler._session
        if session is None:
            session = _new_session()
        h = dict(_YT_HEADERS)
        for k, v in (headers or {}).items():
            if k.lower() not in ('user-agent', 'accept'):
                h[k] = v

        def _u32(buf, off):
            return struct.unpack('>I', buf[off:off + 4])[0]

        def _kids(buf, start, end):
            off = start
            while off + 8 <= end:
                size = _u32(buf, off)
                typ = buf[off + 4:off + 8].decode('latin1', 'replace')
                head = 8
                if size == 1:
                    if off + 16 > end:
                        return
                    size = struct.unpack('>Q', buf[off + 8:off + 16])[0]
                    head = 16
                if size == 0:
                    size = end - off
                if size < head or off + size > end:
                    return
                yield typ, off + head, off + size
                off += size

        buf = b''
        pos = 0
        chunk = 65536
        timescale = 0
        duration = 0
        while (not timescale or not duration) and len(buf) < 262144:
            h['Range'] = 'bytes={}-{}'.format(pos, pos + chunk - 1)
            resp = session.get(url, headers=h, timeout=timeout, stream=True)
            if resp.status_code not in (200, 206):
                resp.close()
                break
            got = resp.raw.read(chunk + 1)
            resp.close()
            if not got:
                break
            buf += got
            pos += len(got)
            n = len(buf)
            for _typ, _ps, _pe in _kids(buf, 0, n):
                if _typ == 'moov' and not timescale:
                    for _t, tps, tpe in _kids(buf, _ps, _pe):
                        if _t != 'trak':
                            continue
                        _handler = ''
                        _ts = 0
                        for _m, mps, mpe in _kids(buf, tps, tpe):
                            if _m != 'mdia':
                                continue
                            for _d, dps, dpe in _kids(buf, mps, mpe):
                                if _d == 'mdhd':
                                    ver = buf[dps]
                                    tpos = dps + 20 if ver == 1 else dps + 12
                                    if tpos + 4 <= dpe:
                                        _ts = _u32(buf, tpos)
                                elif _d == 'hdlr' and dps + 12 <= dpe:
                                    _handler = buf[dps + 8:dps + 12].decode(
                                        'latin1', 'replace')
                            if _handler == 'vide' and _ts:
                                timescale = _ts
                                break
                            if _handler == 'vide':
                                break
                        if timescale:
                            break
                elif _typ == 'moof' and not duration:
                    for _t, tps, tpe in _kids(buf, _ps, _pe):
                        if _t != 'traf':
                            continue
                        for _u, ups, upe in _kids(buf, tps, tpe):
                            if _u != 'tfhd':
                                continue
                            flags = (buf[ups + 1] << 16) | (buf[ups + 2] << 8) | buf[ups + 3]
                            if not flags & 8:
                                continue
                            _p = ups + 8
                            if flags & 2:
                                _p += 4
                            if _p + 4 <= upe:
                                duration = _u32(buf, _p)
                        if duration:
                            break
            if len(got) < chunk:
                break
        if not timescale or not duration:
            return None
        try:
            declared = float(declared)
        except (TypeError, ValueError):
            declared = 0
        best = None
        for num, den in ((timescale, duration), (timescale, 2 * duration)):
            val = num / float(den)
            if val < 19 or val > 65:
                continue
            if declared and abs(val - declared) / declared > 0.02:
                continue
            best = (val, num, den)
            break
        if best is None:
            return None
        val, num, den = best
        if abs(val - round(val)) < 0.005:
            return str(int(round(val)))
        gcd = _math.gcd(int(num), int(den))
        return '{}/{}'.format(int(num) // gcd, int(den) // gcd)
    except Exception as e:
        _log('fps probe failed: {}'.format(str(e)[:120]), xbmc.LOGWARNING)
        return None


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
        session = _ProxyHandler._session
        if session is None:
            session = _new_session()
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


def _api_session():
    session = _ProxyHandler._session
    if session is None:
        session = _new_session(0)
        _ProxyHandler._session = session
    return session


def _flip_ip_family_on_gate():
    """Auto mode: try the other address family while the gate is active.

    YouTube decides the anonymous gate on the address the request arrives from,
    and one device can present two of them (shared IPv4 through the router, its
    own IPv6). With the setting on auto the cheapest test is to switch family
    for the next attempt; when that attempt succeeds the family is remembered
    (config.learn_ip_family), so later sessions start with the working one.
    Returns True when a switch was applied. Never flips toward a family whose
    own gate bucket is still active, so two banned families cannot ping-pong.
    """
    try:
        import config
        if config.ip_family_setting() != config.IP_FAMILY_AUTO:
            _log('Anti-bot gate; IP family stays {} (pinned in settings)'.format(
                config.current_ip_family()), xbmc.LOGWARNING)
            return False
        current = config.current_ip_family()
        if current == config.IP_FAMILY_AUTO:
            target = 'ipv4' if config.family_reachable('ipv6', fresh=True) \
                else 'ipv6'
        else:
            target = 'ipv4' if current == 'ipv6' else 'ipv6'
        if not config.family_reachable(target, fresh=True):
            _log('Anti-bot gate; no other IP family is usable here (v4 {}, v6 {}), '
                 'the gate is not a family problem'.format(
                     config.family_reachable('ipv4', fresh=True),
                     config.family_reachable('ipv6', fresh=True)),
                 xbmc.LOGWARNING)
            return False
        if _gate_remaining(target) > 0:
            _log('Anti-bot gate; {} is also rate-limited right now, '
                 'staying on {}'.format(target, current), xbmc.LOGWARNING)
            return False
        config.force_ip_family(target)
        _log('Anti-bot gate; switched IP family {} -> {} for the next attempt'.format(
            current, target), xbmc.LOGWARNING)
        return True
    except Exception as exc:
        _log('IP family switch failed: {}'.format(str(exc)[:100]))
        return False


def _norm_fps(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


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
    r = _api_session().post('https://www.youtube.com/youtubei/v1/player?prettyPrint=false',
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
            'fps': _norm_fps(f.get('fps')),
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
        ps = body.get('playabilityStatus') or {}
        raise Exception('playability {} {} no usable formats'.format(
            status, (ps.get('reason') or ''))[:160])
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
        'captions': _collect_captions(body),
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


_TV_UA = ('Mozilla/5.0 (Linux armeabi-v7a; Android 7.1.2; Fire OS 6.0) '
          'Cobalt/22.lts.3.306369-gold (unlike Gecko) v8/8.8.278.8-jit gles '
          'Starboard/13, Amazon_ATV_mediatek8695_2019/NS6294 '
          '(Amazon, AFTMM, Wireless) com.amazon.firetv.youtube/22.3.r2.v66.0')


def _account_connected():
    try:
        from account import youtube_sync
        return bool(youtube_sync.status().get('connected'))
    except Exception:
        return False


def _extract_innertube_tv_auth(video_id):
    """Last resort extraction with the linked YouTube TV account.

    Only reached when the anonymous client is rejected by YouTube's anti bot
    gate, which is an IP level decision. The TV client pair is the one already
    discovered at activation time, so no credential is embedded here. The
    returned dict has the same shape as _extract_innertube_ios, so the MPD
    builder, the progressive fallback and the resolution cap are untouched.
    """
    import re as _re
    import requests as _rq
    import store as _store
    from account import youtube_sync
    provider = youtube_sync.tv_provider()
    token = youtube_sync.access_token()
    page_id = (_store.get_oauth_token() or {}).get('page_id') or ''
    version = provider.get('tv_client_version') or '7.20260901.15.00'
    visitor_data = provider.get('visitor_data') or ''
    payload = {
        'context': {
            'client': {
                'clientName': 'TVHTML5',
                'clientVersion': version,
                'clientScreen': 'WATCH',
                'userAgent': _TV_UA,
                'browserName': 'Cobalt',
                'browserVersion': '22.lts.3.306369-gold',
                'tvAppInfo': {'appQuality': 'TV_APP_QUALITY_FULL_ANIMATION',
                              'zylonLeftNav': True},
                'webpSupport': False,
                'animatedWebpSupport': True,
                'visitorData': visitor_data,
            },
            'user': {'lockedSafetyMode': False},
        },
        'videoId': video_id,
        'contentCheckOk': True,
        'racyCheckOk': True,
    }
    if page_id:
        payload['context']['user']['pageId'] = page_id
    headers = {
        'Authorization': 'Bearer {}'.format(token),
        'Origin': 'https://www.youtube.com',
        'Referer': 'https://www.youtube.com/tv',
        'User-Agent': _TV_UA,
        'X-Youtube-Client-Name': '7',
        'X-Youtube-Client-Version': version,
        'Content-Type': 'application/json',
    }
    if visitor_data:
        headers['X-Goog-Visitor-Id'] = visitor_data
    if page_id:
        headers['X-Goog-Pageid'] = page_id
    r = _api_session().post('https://www.youtube.com/youtubei/v1/player?prettyPrint=false',
                              data=json.dumps(payload), headers=headers, timeout=25)
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
            continue
        mime = f.get('mimeType', '')
        match = _re.search(r'codecs="([^"]+)"', mime)
        codecs = match.group(1) if match else ''
        kind = mime.split('/', 1)[0]
        sub = mime.split('/', 1)[1].split(';')[0].strip() if '/' in mime else ''
        fmt = {
            'format_id': str(f.get('itag')),
            'url': f['url'],
            'width': f.get('width', 0) or 0,
            'height': f.get('height', 0) or 0,
            'fps': _norm_fps(f.get('fps')),
            'bitrate': f.get('bitrate') or f.get('averageBitrate'),
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
            at_id = (f.get('audioTrack') or {}).get('id') or ''
            fmt['_arole'] = at_id.rsplit('.', 1)[-1] if '.' in at_id else '4'
        else:
            continue
        formats.append(fmt)
    if not formats:
        raise Exception('TV client returned no usable format')
    orig_audio = [f for f in formats
                  if f.get('container') == 'm4a_dash' and f.get('_arole') == '4']
    if orig_audio:
        kept = set(id(f) for f in orig_audio)
        formats = [f for f in formats
                   if f.get('container') != 'm4a_dash' or id(f) in kept]
    _log('authenticated TV extraction OK: {} formats'.format(len(formats)))
    return {
        'formats': formats,
        'title': vd.get('title'),
        'duration': int(vd.get('lengthSeconds') or 0),
        'manifest_url': sd.get('hlsManifestUrl'),
        'captions': _collect_captions(body),
        'authenticated': True,
    }


def _authenticated_extract(video_id):
    """Run the TV extraction and keep it only when the URLs really serve."""
    try:
        data = _extract_innertube_tv_auth(video_id)
    except Exception as exc:
        _log('authenticated extraction failed: {}'.format(str(exc)[:150]),
             xbmc.LOGWARNING)
        return None
    try:
        ok, bad = _check_urls_servable(data)
    except Exception:
        ok = False
    if not ok:
        _log('authenticated URLs tainted on {}; discarding'.format(bad),
             xbmc.LOGWARNING)
        return None
    return data


_TMDB_API_KEY = '8ad3c21a92a64da832c559d58cc63ab4'

SUBTITLE_OFF = 0
SUBTITLE_ORIGINAL = 1
SUBTITLE_PREFERRED = 2
# Mirrors the Content language enum in settings.xml. Kept local so this module
# never depends on the browsing package.
_CONTENT_LANGUAGES = ('pt-PT', 'pt-BR', 'en', 'es', 'fr', 'de', 'it', 'nl',
                      'ro', 'tr', 'ja', 'ko')


def _subtitle_mode():
    raw = str(_get_setting('subtitles', '') or '').strip().lower()
    if raw in ('original', '1'):
        return SUBTITLE_ORIGINAL
    if raw in ('preferred language', 'preferred', '2'):
        return SUBTITLE_PREFERRED
    try:
        return int(raw) if int(raw) in (SUBTITLE_ORIGINAL, SUBTITLE_PREFERRED) else SUBTITLE_OFF
    except (TypeError, ValueError):
        return SUBTITLE_OFF


def _preferred_subtitle_lang():
    custom = str(_get_setting('subtitle_language', '') or '').strip().replace('_', '-')
    if not custom:
        custom = str(_get_setting('content_language_custom', '') or '').strip().replace('_', '-')
    if not custom:
        raw = str(_get_setting('content_language', '') or '').strip()
        if raw in _CONTENT_LANGUAGES:
            custom = raw
        else:
            try:
                index = int(raw)
                if 0 <= index < len(_CONTENT_LANGUAGES):
                    custom = _CONTENT_LANGUAGES[index]
            except (TypeError, ValueError):
                custom = 'en'
    return custom or 'en'


def _subtitle_label(track):
    name = ((track or {}).get('name') or {})
    if isinstance(name.get('simpleText'), str) and name['simpleText']:
        return name['simpleText']
    runs = name.get('runs') or []
    label = ''.join(str(run.get('text') or '') for run in runs
                    if isinstance(run, dict)).strip()
    if label:
        return label
    return (track or {}).get('languageCode') or ''


def _subtitle_url(track, translate_to=''):
    base = (track or {}).get('baseUrl') or ''
    if not base:
        return ''
    base = base.replace('&amp;', '&')
    if 'xosf' in base:
        parts = [part for part in base.split('&') if not part.startswith('xosf=')]
        base = '&'.join(parts)
    joiner = '&' if '?' in base else '?'
    url = '{}{}fmt=vtt'.format(base, joiner)
    if translate_to:
        url = '{}&tlang={}'.format(url, translate_to)
    return url


def _collect_captions(body):
    """Pick the subtitle tracks to expose, following the Subtitles setting.

    Mirrors plugin.video.youtube: fmt=vtt is requested so Kodi receives plain
    WebVTT with no conversion, and tlang asks YouTube for its own automatic
    translation when the uploader has no track in that language.
    """
    mode = _subtitle_mode()
    if mode == SUBTITLE_OFF:
        return []
    try:
        renderer = ((body.get('captions') or {})
                    .get('playerCaptionsTracklistRenderer') or {})
        tracks = renderer.get('captionTracks') or []
    except AttributeError:
        return []
    if not tracks:
        return []
    preferred = _preferred_subtitle_lang()
    picked = []

    def add(track, translate_to='', default=False):
        url = _subtitle_url(track, translate_to)
        if not url:
            return
        lang = track.get('languageCode') or ''
        if translate_to:
            label = '{} (auto)'.format(translate_to)
            lang = translate_to
        else:
            label = _subtitle_label(track)
        if track.get('kind') == 'asr':
            label = '{} (auto)'.format(label)
        picked.append({'url': url, 'lang': lang or 'und',
                       'label': label or lang,
                       'default': bool(default)})

    def base_lang(track):
        return str(track.get('languageCode') or '').lower()

    exact = None
    asr = None
    original = None
    translatable = None
    for track in tracks:
        lang = base_lang(track)
        if lang == preferred.lower() or lang.split('-')[0] == preferred.lower().split('-')[0]:
            if track.get('kind') == 'asr':
                asr = asr or track
            else:
                exact = exact or track
        if track.get('audioTrackType') == 'default' and not original:
            original = track
        if track.get('isTranslatable') and not translatable:
            translatable = track
    if original is None:
        original = next((t for t in tracks if t.get('kind') != 'asr'), tracks[0])

    if mode == SUBTITLE_ORIGINAL:
        add(original, default=True)
        return picked
    if exact:
        add(exact, default=True)
    elif asr:
        add(asr, default=True)
    elif translatable:
        add(translatable, translate_to=preferred, default=True)
    if not picked and original:
        add(original, default=True)
    if original is not None and len(picked) < 4:
        for track in tracks:
            if any(item['url'] == _subtitle_url(track) for item in picked):
                continue
            add(track)
            if len(picked) >= 4:
                break
    return picked


def _is_permanent_error(msg):
    """True when an extraction error means the video can never be played
    (private/geo-block/deleted/age-restricted), so retries are pointless and
    we should skip straight to an alternate trailer."""
    if not msg:
        return False
    low = msg.lower()
    if _is_bot_gate(msg):
        return False
    return any(h in low for h in ('unplayable', 'not available',
                                  'unavailable', 'private', 'deleted',
                                  'removed')) or 'country' in low


def _is_bot_gate(msg):
    """True for YouTube's IP level anti bot challenge.

    LOGIN_REQUIRED carrying "not a bot" is not permanent: it clears after a
    pause, an alternate video is gated exactly the same way, and an
    authenticated client is accepted. Retrying with a longer pause is worth
    more than switching trailer.
    """
    if not msg:
        return False
    low = msg.lower()
    if 'not a bot' in low or 'confirm you' in low or 'are not a bot' in low:
        return True
    return 'login_required' in low and 'sign in' in low

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


def _tmdb_alt_videos(tmdb_id, dbtype, season=None, excluded=None):
    """Other playable TMDb videos for the same title, prioritizing by what the
    user actually clicked:
      - season context: the requested season's trailer first (#100), else the
        show-level trailer as fallback (#40); other seasons are dropped.
      - show/tv context: show-level trailers only - season trailers are
        excluded so a show click never falls on a season 4 trailer.
    Real trailers (name contains 'trailer') outrank teasers/clips/spots."""
    import re as _re
    import requests as _rq
    if not tmdb_id:
        return []
    excluded = excluded or set()
    media_type = 'tv' if (dbtype or '').lower() in ('tvshow', 'tv', 'season') else 'movie'
    want_season = season is not None and str(season).isdigit()
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
        name = (v.get('name') or '')
        low = name.lower()
        vtype = (v.get('type') or '').lower()
        m = _re.search(r'(?:season|sezonul|sezoane|sezon)\s*(\d{1,2})|\bs(\d{1,2})\b', low)
        named_season = int(m.group(1) or m.group(2)) if m else None
        is_season_trailer = named_season is not None
        score = 0
        if media_type == 'tv':
            if want_season:
                if named_season == int(season):
                    score = 100
                elif is_season_trailer:
                    continue  # other seasons are not what we want
                else:
                    score = 40  # show-level trailer as fallback
            else:
                if is_season_trailer:
                    continue  # show click must not pick a season trailer
                score = 0
        if 'trailer' in low:
            score += 3
        if vtype == 'trailer':
            score += 2
        elif vtype == 'teaser':
            score += 1
        scored.append((score, v['key']))
    scored.sort(key=lambda x: -x[0])
    result = [k for _, k in scored]
    if result:
        _log('Found {} alt TMDb trailer candidate(s) (dbtype={}, season={})'.format(
            len(result), dbtype, season))
    return result


def _try_alt_trailer(video_id, title, year, tmdb_id, dbtype, season=None, excluded=None):
    """Find and return playable data for an ALTERNATIVE trailer when the
    requested one is blocked (private/geo/availability).

    TMDb alternates are authoritative: they share the same tmdb_id and are
    already filtered by context (_tmdb_alt_videos excludes season trailers on
    a show click, and prefers the requested season on a season click), so they
    are tried first in priority order. The YouTube search is only a last resort
    when every TMDb candidate is unservable, and its loose results are filtered
    by title match + season context so we never return a trailer from a
    different show or the wrong season. Returns data or None."""
    import re as _re
    excluded = excluded or set()
    excluded.add(video_id)
    want_season = season is not None and str(season).isdigit()

    def _pick_servable(cands, prefer_first):
        """Return extracted data for a servable candidate. When prefer_first is
        True the candidate order is meaningful (TMDb priority: requested season
        first, then show-level), so we keep that order; otherwise we fall back
        to a longer-trailer preference like the original code."""
        servable = []
        for vid in cands:
            if vid in excluded or vid in _pick_servable._seen:
                continue
            _pick_servable._seen.add(vid)
            try:
                data = _extract_innertube_ios(vid)
            except Exception:
                continue
            try:
                ok, _bad = _check_urls_servable(data)
            except Exception:
                ok = False
            if not ok:
                continue
            dur = 0
            try:
                dur = int(float(data.get('duration') or 0))
            except Exception:
                dur = 0
            _log('Alt trailer {vid} playable (duration {d}s)'.format(vid=vid, d=dur))
            servable.append((dur, vid, data))
        if not servable:
            return None
        if prefer_first:
            for dur, vid, data in servable:
                if dur >= _MIN_TRAILER_DURATION:
                    _log('Selected alt trailer {vid} (duration {d}s)'.format(
                        vid=vid, d=dur))
                    return data
            return servable[0][2]
        servable.sort(key=lambda x: x[0], reverse=True)
        for dur, vid, data in servable:
            if dur >= _MIN_TRAILER_DURATION:
                _log('Selected alt trailer {vid} (duration {d}s)'.format(vid=vid, d=dur))
                return data
        return servable[0][2]
    _pick_servable._seen = set()

    # 1) Authoritative TMDb alternates, in priority order (season-first).
    tmdb_candidates = []
    try:
        tmdb_candidates = _tmdb_alt_videos(tmdb_id, dbtype, season=season,
                                           excluded=excluded)
    except Exception:
        pass
    if tmdb_candidates:
        data = _pick_servable(tmdb_candidates, prefer_first=True)
        if data:
            return data

    # 2) Last resort: strict YouTube search, filtered by context + title match.
    if not title:
        return None
    title_low = title.lower()
    show_query = title
    if want_season:
        show_query = '{} season {}'.format(title, season)
    queries = []
    if year and str(year).isdigit():
        queries.append('{title} {year} official trailer'.format(
            title=show_query, year=year))
    queries.append('{t} trailer'.format(t=show_query))
    if not want_season:
        queries.append(title)

    def _yt_search(strict, require_title=True, require_kw=True):
        found = []
        for q in queries:
            for vid, t in _search_innertube(q):
                tl = (t or '').lower()
                if require_kw and 'trailer' not in tl and 'teaser' not in tl:
                    continue
                if require_title and not _title_similar(title_low, tl):
                    continue
                if strict and not want_season and _re.search(
                        r'\b(?:season|sezon|sezoane)\b|\bs\d{1,2}\b', tl):
                    continue
                if vid in excluded or vid in found:
                    continue
                found.append(vid)
            if found:
                break
        return found

    def _try_yt(strict, **kw):
        cands = _yt_search(strict, **kw)
        if not cands:
            return None
        return _pick_servable(cands, prefer_first=False)

    # Prefer exact show + trailer + context, then relax step by step so a
    # private/odd search result never leaves the user with no fallback trailer.
    data = _try_yt(strict=True)
    if data:
        return data
    data = _try_yt(strict=False, require_kw=True)
    if data:
        return data
    # last resorts: give up on the title/season match but still want a real
    # trailer clip (and finally any servable video) so playback never blanks.
    data = _try_yt(strict=False, require_title=False, require_kw=True)
    if data:
        return data
    data = _try_yt(strict=False, require_title=False, require_kw=False)
    return data


def _title_similar(show_low, result_low):
    """Return True when a YouTube result title plausibly belongs to the show we
    are looking for. The show's base name must appear in the result; this stops
    loose searches from picking a trailer of a completely different show (e.g.
    'Outer Banks ...' returning a 'From ...' trailer)."""
    base = show_low.strip()
    if not base:
        return True
    base = base.split('  ')[0].strip()
    if base in result_low:
        return True
    # tolerate a parenthetical year in the show part
    no_year = base.split('(')[0].strip()
    return bool(no_year) and no_year in result_low


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


_RES_HEIGHTS = {'720p': 720, '1080p': 1080, '2160p': 2160,
                 '2160p (4k)': 2160}


def _max_res_height():
    """User-selected maximum trailer resolution.

    Stored either as text (Auto, 720p, 1080p, 2160p) or as the previous
    enum index (0=Auto, 1=720p, 2=1080p, 3=4K). Auto follows the TV's native
    resolution and falls back to 1080p when the display size is unknown."""
    raw = str(_get_setting('trailer_max_res', '') or '').strip()
    low = raw.lower()
    if low in _RES_HEIGHTS:
        height = _RES_HEIGHTS[low]
    else:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            idx = 0
        height = {1: 720, 2: 1080, 3: 2160}.get(idx, 0)
    h = _screen_height()
    _log('max_res: raw={} screen={}'.format(raw, h), getattr(xbmc, 'LOGDEBUG', 4))
    if height:
        return height
    if h >= 2160:
        return 2160
    if h >= 1080:
        return 1080
    if h > 0:
        return 720
    return 1080


_RANGE_CACHE = {}
_RANGE_CACHE_LOADED = False


def _range_cache_load():
    global _RANGE_CACHE_LOADED
    if _RANGE_CACHE_LOADED:
        return
    _RANGE_CACHE_LOADED = True
    try:
        p = xbmcvfs.translatePath('special://temp/yt_ranges.json')
        with open(p, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            now = time.time()
            _RANGE_CACHE = {k: v for k, v in data.items()
                            if isinstance(v, dict) and now - v.get('ts', 0) < 2592000}
    except:
        pass


def _range_cache_store(video_id, format_id, dinit, dindex):
    if not video_id or not format_id:
        return
    try:
        _RANGE_CACHE['{}:{}'.format(video_id, format_id)] = {
            'init': list(dinit), 'index': list(dindex), 'ts': time.time()}
        while len(_RANGE_CACHE) > 200:
            _RANGE_CACHE.pop(next(iter(_RANGE_CACHE)))
        p = xbmcvfs.translatePath('special://temp/yt_ranges.json')
        with open(p, 'w') as f:
            json.dump(_RANGE_CACHE, f)
    except:
        pass


def _build_mpd(data, proxy_base='', video_id=''):
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

    probe = None
    for fmt in data.get('formats', []):
        if (fmt.get('container') == 'mp4_dash'
                and _is_video_codec(fmt)
                and fmt.get('height') == target_height
                and fmt.get('fps') in (24, 30, 60)
                and fmt.get('url')):
            probe = fmt
            break
    if probe is None:
        for fmt in data.get('formats', []):
            if (fmt.get('container') == 'mp4_dash'
                    and _is_video_codec(fmt)
                    and fmt.get('fps') in (24, 30, 60)
                    and fmt.get('url')):
                probe = fmt
                break
    if probe is not None:
        exact = _true_fps(probe['url'], declared=probe['fps'])
        if exact and exact != probe['fps']:
            _log('Measured fps {} instead of declared {}'.format(exact, probe['fps']))
            for fmt in data.get('formats', []):
                if fmt.get('fps') == probe['fps']:
                    fmt['fps'] = exact

    # Fixed mode (1=720p, 2=1080p, 3=4K): pin the video ladder to the single
    # target height so ISA cannot drop below it on a smaller window/network.
    # Auto (0) keeps the full ladder below the cap (adaptive).
    fixed_mode = False
    try:
        raw = str(_get_setting('trailer_max_res', '') or '').strip()
        fixed_mode = raw.lower() in _RES_HEIGHTS or raw in ('1', '2', '3')
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
    disc_needed = []
    for group, formats in groups.items():
        for fmt in formats:
            if not fmt.get('indexRange') or not fmt.get('initRange'):
                disc_needed.append(fmt)
    disc_results = {}
    if disc_needed:
        _range_cache_load()
        pending = []
        for fmt in disc_needed:
            hit = _RANGE_CACHE.get('{}:{}'.format(video_id, fmt.get('format_id'))) if video_id else None
            if hit and hit.get('init') and hit.get('index'):
                disc_results[id(fmt)] = (tuple(hit['init']), tuple(hit['index']))
            else:
                pending.append(fmt)
        if pending:
            try:
                from concurrent.futures import ThreadPoolExecutor, wait
                ex = ThreadPoolExecutor(max_workers=2)
                try:
                    fm = {ex.submit(_discover_dash_ranges, unquote(fmt['url']), fmt.get('http_headers', {})): fmt for fmt in pending}
                    done, _ = wait(set(fm), timeout=90)
                finally:
                    try:
                        ex.shutdown(wait=False, cancel_futures=True)
                    except:
                        pass
                for f in done:
                    try:
                        dinit, dindex = f.result()
                    except:
                        dinit, dindex = None, None
                    fmt = fm[f]
                    if dinit and dindex:
                        disc_results[id(fmt)] = (dinit, dindex)
                        _range_cache_store(video_id, fmt.get('format_id'), dinit, dindex)
            except Exception as e:
                _log('Parallel range discovery error: {}'.format(str(e)[:120]), xbmc.LOGWARNING)
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
                got = disc_results.get(id(fmt))
                if got:
                    dinit, dindex = got
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

    captions = (data or {}).get('captions') or []
    for index, track in enumerate(captions):
        url = fix_url(proxy_base + track['url'])
        flag = 'yes' if track.get('default') else 'no'
        label = track.get('label') or track.get('lang') or ''
        mpd += ('\n<AdaptationSet id="subs_{i}" contentType="text" '
                'mimeType="text/vtt" lang="{lang}" name="[B]{label}[/B]" '
                'original="{flag}" default="{flag}">\n'
                '    <Label>{label}</Label>\n'
                '    <Role schemeIdUri="urn:mpeg:dash:role:2011" '
                'value="subtitle"/>\n'
                '    <Representation id="subs_{i}" codecs="wvtt" '
                'mimeType="text/vtt">\n'
                '        <BaseURL>{url}</BaseURL>\n'
                '    </Representation>\n'
                '</AdaptationSet>').format(i=written_sets + index,
                                          lang=track.get('lang') or 'und',
                                          label=label, flag=flag, url=url)
        written_sets += 1
    if captions:
        _log('MPD subtitle sets: {}'.format(len(captions)))
    mpd += '\n</Period>\n</MPD>'
    return mpd, headers


def _check_urls_servable(data):
    """Probe a byte near 80% of the top video and top audio files.

    googlevideo sometimes issues URL-sets whose tail is rejected (HTTP 403):
    only the first ~47% of every file in the set is servable (audio and video
    alike, identical byte fraction). The stream plays ~70s then audio dies and
    ISA aborts the whole playback (ActiveAE sync errors). The taint is baked
    into the URL at extraction time and does not heal (verified 20+ min).
    A re-extraction usually returns a clean set. Taint hits whole URL-sets
    uniformly, so probing the top video plus the top audio detects it with
    2 requests instead of ~20. One retry per probe before verdict (transient
    403s happen). Returns (ok, failed_format_id).
    """
    import re as _re
    try:
        session = _ProxyHandler._session
        if session is None:
            session = _new_session()
        h = dict(_YT_HEADERS)
        formats = data.get('formats', []) or []
        videos = [fmt for fmt in formats
                  if fmt.get('container') in ('mp4_dash', 'webm_dash')
                  and fmt.get('vcodec', 'none') != 'none'
                  and not fmt.get('vcodec', '').startswith('av01')]
        audios = [fmt for fmt in formats
                  if fmt.get('container') == 'm4a_dash']
        picks = []
        if videos:
            picks.append(max(videos, key=lambda f: f.get('height', 0) or 0))
        if audios:
            picks.append(max(audios, key=lambda f: f.get('bitrate', 0) or 0))
        if not picks:
            return True, None
        for fmt in picks:
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
            status = 0
            for _ in range(2):
                resp = session.get(url, headers=h, timeout=10)
                status = resp.status_code
                resp.close()
                if status == 206:
                    break
            if status != 206:
                _log('Format {} NOT fully servable (HTTP {} at byte {}/{})'.format(
                    fmt.get('format_id'), status, pos, size), xbmc.LOGWARNING)
                return False, fmt.get('format_id')
        _log('URL servability check passed ({} formats)'.format(len(picks)))
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
            session = _new_session()
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

_EXTRACT_CAP = 50
_GATE_MINUTES = 15
_gate_until = {}


def _gate_key():
    try:
        import config as _config
        return _config.current_ip_family()
    except Exception:
        return 'auto'


def _gate_read_file():
    try:
        import json as _js
        with open(_gate_file()) as _fh:
            data = _js.load(_fh)
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items()}
        return {'ipv4': float(data), 'ipv6': float(data),
                'auto': float(data)}
    except Exception:
        return {}


def _gate_write_file():
    try:
        import json as _js
        with open(_gate_file(), 'w') as _fh:
            _js.dump({k: v for k, v in _gate_until.items() if v}, _fh)
    except Exception:
        pass


def _extract_ttl():
    try:
        return max(3600, int(str(_get_setting('extract_cache_ttl', '') or '').split()[0]) * 3600)
    except Exception:
        return 6 * 3600


def _extract_cache_dir():
    import os as _os
    path = os.path.join(ADDON_PROFILE, 'extract_cache')
    try:
        _os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _cached_extract(video_id):
    import os as _os
    import pickle as _pk
    path = _os.path.join(_extract_cache_dir(), '{}.bin'.format(video_id))
    try:
        if time.time() - _os.path.getmtime(path) > _extract_ttl():
            try:
                _os.remove(path)
            except Exception:
                pass
            return None
        with open(path, 'rb') as _fh:
            data = _pk.load(_fh)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get('formats'):
        return None
    try:
        ok, _bad = _check_urls_servable(data)
    except Exception:
        return None
    if not ok:
        try:
            _os.remove(path)
        except Exception:
            pass
        return None
    _log('Extraction cache hit: {} ({} formats)'.format(video_id, len(data.get('formats') or [])), always=True)
    return data


def _store_extract(video_id, data):
    import os as _os
    import pickle as _pk
    if not isinstance(data, dict) or not data.get('formats'):
        return
    try:
        path = _os.path.join(_extract_cache_dir(), '{}.bin'.format(video_id))
        with open(path, 'wb') as _fh:
            _pk.dump(data, _fh)
        entries = sorted(
            ((_os.path.getmtime(_os.path.join(_extract_cache_dir(), name)), name)
             for name in _os.listdir(_extract_cache_dir())),
            reverse=False)
        for _, name in entries[:-_EXTRACT_CAP]:
            try:
                _os.remove(_os.path.join(_extract_cache_dir(), name))
            except Exception:
                pass
    except Exception:
        pass


def _clear_extract_cache():
    import os as _os
    import shutil as _sh
    try:
        _sh.rmtree(_extract_cache_dir(), ignore_errors=True)
        return True
    except Exception:
        return False


def _gate_file():
    return xbmcvfs.translatePath('special://temp/yt_gate_until')


def _gate_remaining(family=None):
    now = time.time()
    key = family or _gate_key()
    until = _gate_until.get(key, 0.0)
    if now < until:
        return until - now
    for stored_key, stored_until in _gate_read_file().items():
        if stored_until > _gate_until.get(stored_key, 0.0):
            _gate_until[stored_key] = stored_until
    until = _gate_until.get(key, 0.0)
    if now < until:
        return until - now
    return 0


def _other_family_clean(key):
    other = {'ipv4': 'ipv6', 'ipv6': 'ipv4'}.get(key)
    if not other:
        return ''
    if _gate_remaining(other) > 0:
        return ''
    try:
        import config as _config
        if not _config.family_reachable(other, fresh=True):
            return ''
    except Exception:
        pass
    return other


def _set_gate(family=None):
    key = family or _gate_key()
    _gate_until[key] = time.time() + _GATE_MINUTES * 60
    _gate_write_file()



def _tmdb_details_plot(tmdb_id, dbtype):
    try:
        import requests as _rq
        media_type = 'tv' if (dbtype or '').lower() in ('tvshow', 'tv', 'season', 'episode') else 'movie'
        r = _rq.get('https://api.themoviedb.org/3/{}/{}?api_key={}&language=en-US'.format(
            media_type, tmdb_id, _TMDB_API_KEY), timeout=10)
        d = r.json()
        if not isinstance(d, dict):
            return '', '', '', ''
        ov = d.get('overview') or ''
        cos = d.get('production_companies') or [] or d.get('networks') or []
        st = cos[0].get('name') if cos and isinstance(cos, list) and cos[0].get('name') else ''
        tg = (d.get('tagline') or '').strip()
        gn = [g.get('name') for g in (d.get('genres') or []) if g.get('name')]
        return ov, st, tg, gn
    except Exception as e:
        _log('TMDb details plot error: {}'.format(str(e)[:120]), xbmc.LOGWARNING)
        return '', '', '', []


def _youtube_info_plot(channel='', views='', vdate='', dur=0, snippet=''):
    """Info panel block, identical to the TMDb Movies one."""
    views = views or ''
    import config
    vdate = config.relative_date(vdate)
    if vdate and vdate in views:
        vdate = ''
    lines = []
    if channel:
        lines.append('[B][COLOR FF00CED1]{}[/COLOR][/B]'.format(channel))
    stats = []
    if views:
        stats.append('[B][COLOR FFFFD700]{}[/COLOR][/B]'.format(views))
    if vdate:
        stats.append('[B][COLOR FFFF69B4]{}[/COLOR][/B]'.format(vdate))
    if dur:
        try:
            seconds = int(dur)
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            hours, rest = divmod(seconds, 3600)
            minutes, secs = divmod(rest, 60)
            label = ('{}:{:02d}:{:02d}'.format(hours, minutes, secs) if hours
                     else '{}:{:02d}'.format(minutes, secs))
            stats.append('[B][COLOR FF87CEEB]{}[/COLOR][/B]'.format(label))
    if stats:
        lines.append(' - '.join(stats))
    head = '\n'.join(lines)
    try:
        from lists import clean_title
        body = clean_title(snippet, single_line=False)
    except Exception:
        body = str(snippet or '').strip()
    if body:
        return (head + '\n\n' + body) if head else body
    return head


def _set_progressive_subtitles(li, captions, port):
    """External subtitle tracks for the non DASH playback paths."""
    if not captions:
        return
    base = 'http://127.0.0.1:{}/'.format(port) if port else ''
    urls = []
    for track in captions:
        url = unquote(track.get('url') or '')
        if not url:
            continue
        urls.append(base + url)
    if urls:
        try:
            li.setSubtitles(urls)
            _log('External subtitle tracks attached: {}'.format(len(urls)))
        except Exception as exc:
            _log('setSubtitles failed: {}'.format(str(exc)[:90]), xbmc.LOGWARNING)


def play_youtube(video_id, title=None, genre=None, year=None,
                 tmdb_id=None, dbtype=None, season=None, episode_num=None,
                 plot=None, studio=None, tagline=None, lang=None,
                 channel=None, views=None, vdate=None, dur=None, snippet=None):
    _cleanup_old_mpd()

    _gate_family = _gate_key()
    _remaining = _gate_remaining(_gate_family)
    if _remaining > 0:
        _mins = int(_remaining // 60) + 1
        _alt = _other_family_clean(_gate_family)
        if _alt:
            raise Exception('YouTube is rate-limiting {} right now (anti-bot). '
                            'Switch IP family to {} and retry at once, or leave '
                            'it alone for about {} min.'.format(
                                _gate_family.upper(), _alt, _mins))
        raise Exception('YouTube is rate-limiting this IP right now (anti-bot). '
                        'Leave it alone for about {} min, then retry.'.format(_mins))

    # Rate-limit: random delay between extractions to avoid bot detection.
    # Cache hits skip the wait entirely (no API call follows anyway).
    data = _cached_extract(video_id)
    raw_tainted = None
    last_err = ''
    permanent = False
    gated = False
    fresh = False
    family_switched = False
    if data is None:
        global _last_extract_time
        elapsed = time.time() - _last_extract_time
        min_gap = 3 + random.random() * 5  # 3-8 seconds
        if _last_extract_time > 0 and elapsed < min_gap:
            wait = min_gap - elapsed
            _log('Waiting {:.1f}s before next extraction to avoid bot detection'.format(wait))
            xbmc.sleep(int(wait * 1000))
        _last_extract_time = time.time()

        url = 'https://www.youtube.com/watch?v={}'.format(video_id)
        _log('Extracting: {}'.format(url), always=True)

    # Innertube-only extraction (pure Python, no yt-dlp, no JS runtime,
    # no third-party binaries): replicates plugin.video.youtube's working
    # ios_testsuite client. Falls back to an emergency progressive (muxed)
    # format when the DASH URL-set is tainted/blocked.
    for attempt in range(3):
        if data is None:
            data = _fast_extract(video_id)
            fresh = bool(data)
        if data:
            break
        try:
            raw_tainted = _extract_innertube_ios(video_id)
        except Exception as _e:
            last_err = str(_e)
            raw_tainted = None
        gated = _is_bot_gate(last_err)
        permanent = _is_permanent_error(last_err)
        if permanent:
            _log('Permanent unavailability (private/geo-block); skipping retries',
                 xbmc.LOGWARNING)
            break
        if gated:
            # IP level penalty: seconds matter far more than milliseconds.
            _pause = 8000 + int(random.random() * 4000)
            _log('YouTube anti bot gate; retrying in {}ms (attempt {}/3)'.format(
                _pause, attempt + 1), xbmc.LOGWARNING)
            if _flip_ip_family_on_gate():
                family_switched = True
            xbmc.sleep(_pause)
            continue
        _log('Extraction attempt {} failed; retrying ({}/3)'.format(
            attempt + 1, attempt + 1), xbmc.LOGWARNING)
        xbmc.sleep(int(1500 + random.random() * 2000))

    fallback_fmt = None
    if not data:
        fallback_fmt = _find_clean_progressive(raw_tainted) if raw_tainted else None
        if fallback_fmt:
            _log('All DASH extractions tainted; falling back to progressive itag {}'.format(
                fallback_fmt.get('format_id')), xbmc.LOGWARNING)
        elif gated and _account_connected():
            # Alternate trailers are gated exactly the same way, so go straight
            # to the account instead of burning more requests.
            if _gate_remaining() > 0:
                _log('Bot gate already known active; skipping authenticated retry')
            else:
                _log('Bot gate active and no alternate trailer; trying the linked account')
                data = _authenticated_extract(video_id)
                if data:
                    fresh = True
                    gated = False
        if gated and not data and not fallback_fmt:
            _log('Bot gate active, authenticated extract failed too; cannot recover',
                 xbmc.LOGWARNING)
            _set_gate()
            raise Exception('YouTube blocked this IP ("Sign in to confirm you are '
                            'not a bot"). Wait about 15 min without playing, then retry.')
        elif gated:
            _log('Bot gate active and no account linked; cannot recover',
                 xbmc.LOGWARNING)
            _set_gate()
            raise Exception('YouTube blocked this IP ("Sign in to confirm you are '
                            'not a bot"). Link your YouTube account in My YouTube '
                            'to keep playing, or try another network.')
        else:
            permanent = _is_permanent_error(last_err)
            if permanent:
                alt = _try_alt_trailer(video_id, title, year, tmdb_id, dbtype,
                                       season=season, excluded={video_id})
                if alt:
                    data = alt
            if not data:
                err_msg = 'Extraction failed for ' + video_id
                _log(err_msg, xbmc.LOGERROR)
                raise Exception(err_msg)

    if data and fresh and family_switched:
        # A fresh extraction succeeded only after the family switch: that is
        # evidence, so auto mode keeps using it from now on.
        import config
        _log('Extraction succeeded on IP family {}'.format(
            config.current_ip_family()), xbmc.LOGWARNING)
        config.learn_ip_family(config.current_ip_family())

    if data:
        _store_extract(video_id, data)
    _log('Title: {} | Duration: {}s'.format(
        (data or {}).get('title', '?'), (data or {}).get('duration', '?')))

    li = xbmcgui.ListItem()
    display_title = (data or {}).get('title') or title or 'Trailer'
    try:
        from lists import clean_title
        display_title = clean_title(display_title) or display_title
    except Exception:
        pass
    tag = li.getVideoInfoTag()
    tag.setTitle(display_title)
    tag.setOriginalTitle(display_title)
    if year and str(year).isdigit():
        tag.setYear(int(year))
    if season is not None:
        try:
            tag.setSeason(int(season))
            if episode_num:
                tag.setEpisode(int(episode_num))
        except Exception:
            pass
    genres_list = []
    if genre:
        genres_list = [g.strip() for g in genre.replace('/', ',').split(',') if g.strip()]
        tag.setGenres(genres_list)
    if tagline:
        tag.setTagLine(tagline)
    _thumb = 'https://i.ytimg.com/vi/{}/hqdefault.jpg'.format(video_id)
    li.setArt({'thumb': _thumb, 'poster': _thumb, 'fanart': _thumb})
    yt_plot = _youtube_info_plot(channel, views, vdate, dur, snippet)
    try:
        from lists import clean_title
    except Exception:
        clean_title = None

    def _cleaned(text):
        try:
            return clean_title(text, single_line=False) if clean_title else text
        except Exception:
            return text

    if plot:
        tag.setPlot(_cleaned(plot))
    elif yt_plot:
        tag.setPlot(yt_plot)
    if studio:
        tag.setStudios([studio])
    try:
        if dur and int(dur) > 0:
            tag.setDuration(int(dur))
    except (TypeError, ValueError):
        pass
    if dbtype and (dbtype.lower() in ('episode', 'season')) and tmdb_id and season is not None and not plot:
        # Episoade: overview-ul EPISODULUI cu eticheta SxxEyy (plotul serialului
        # e separat si derutant, ex "The Chronicle of 1812"). Sezoane:
        # overview-ul SEZONULUI. Interogam direct: harta veche dbtype->tip
        # mediu nu cunostea 'episode' si interoga /movie/{id}!
        try:
            import requests as _rq2
            _lng = lang or 'en-US'

            def _req(path):
                r2 = _rq2.get('https://api.themoviedb.org/3/{}?api_key={}&language={}'.format(
                    path, _TMDB_API_KEY, _lng), timeout=10)
                d2 = r2.json() if r2.status_code == 200 else {}
                if (not d2 or d2.get('success') is False) and _lng != 'en-US':
                    r2 = _rq2.get('https://api.themoviedb.org/3/{}?api_key={}&language=en-US'.format(
                        path, _TMDB_API_KEY), timeout=10)
                    d2 = r2.json() if r2.status_code == 200 else {}
                return d2 or {}

            if dbtype.lower() == 'episode' and episode_num:
                _ep = _req('tv/{}/season/{}/episode/{}'.format(tmdb_id, season, episode_num))
                if _ep.get('overview'):
                    tag.setPlot('[COLOR FF20B2AA]S{:02d}E{:02d}[/COLOR]  {}'.format(
                        season, episode_num, _cleaned(_ep['overview'])))
            else:
                _se = _req('tv/{}/season/{}'.format(tmdb_id, season))
                if _se.get('overview'):
                    tag.setPlot(_cleaned(_se['overview']))
        except Exception as _e:
            _log('Season/episode plot error: {}'.format(str(_e)[:120]), xbmc.LOGWARNING)
    elif (not plot or not studio) and tmdb_id:
        _dov, _dst, _dtg, _dgn = _tmdb_details_plot(tmdb_id, dbtype)
        if not plot and (_dov or _dtg):
            _head = ''
            _gns = ', '.join(_dgn) if isinstance(_dgn, list) else (_dgn or '')
            if _dtg and _gns:
                _head = '[B][COLOR yellow]' + _dtg + '[/COLOR][/B] | [B][COLOR FF00CED1]' + _gns + '[/COLOR][/B]\n'
            elif _dtg:
                _head = '[B][COLOR yellow]' + _dtg + '[/COLOR][/B]\n'
            elif _gns:
                _head = '[B][COLOR FF00CED1]' + _gns + '[/COLOR][/B]\n'
            tag.setPlot(_head + _cleaned(_dov))
        if _dst and not studio:
            tag.setStudios([_dst])
    try:
        _log('Resolve tag plot={} chars studios={} tagline={} genre_len={}'.format(len(plot or ''), [studio] if studio else [], len(tagline or ''), len(genre or '')))
    except:
        pass

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
    mpd, headers = _build_mpd(data, proxy_base, video_id) if data else (None, {})

    if fallback_fmt:
        direct_url = fallback_fmt.get('url')
        _log('Progressive fallback direct URL (ext={})'.format(fallback_fmt.get('ext', '?')))
        li.setPath(direct_url)
        fh = fallback_fmt.get('http_headers') or {}
        hdr = '&'.join('{}={}'.format(k, v) for k, v in fh.items())
        if hdr:
            li.setProperty('inputstream.adaptive.stream_headers', hdr)
        li.setProperty(IA_PROP, 'inputstream.adaptive')
        _set_progressive_subtitles(li, (data or {}).get('captions') or [], port)
        return li

    if mpd:

        mpd_path = 'special://temp/yt_{}.mpd'.format(video_id)
        local_mpd = xbmcvfs.translatePath(mpd_path)
        try:
            with open(local_mpd, 'w') as f:
                f.write(mpd)
        except Exception as exc:
            _log('MPD write failed: {}'.format(str(exc)[:90]),
                 xbmc.LOGWARNING)
        _mpd_remember(mpd_path, mpd)

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
