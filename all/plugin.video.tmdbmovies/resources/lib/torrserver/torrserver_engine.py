import xbmc
import xbmcaddon
import xbmcgui
import time
import threading
import os
import sys
import re

try:
    import urllib.parse as urlparse
    from urllib.parse import quote, unquote
except ImportError:
    import urlparse
    from urllib import quote, unquote

try:
    from resources.lib.torrserver.torrserver_api import TorrServer
except ImportError:
    try:
        from torrserver_api import TorrServer
    except ImportError:
        TorrServer = None

try:
    import requests as req_lib
except ImportError:
    req_lib = None

from resources.lib.config import ADDON, ADDON_PATH, get_torrserver_host

_CANCEL_ACTIONS = frozenset([9, 10, 13, 92, 110, 216])

def log(msg):
    try:
        from resources.lib.scraper import log as scraper_log
        scraper_log(msg)
    except:
        xbmc.log("[TorrServer] %s" % msg)

def _cancel_sleep(cancel_event, duration):
    return cancel_event.wait(timeout=duration)

def _async_cleanup(ts, info_hash):
    try:
        ts.remove_torrent(info_hash)
    except:
        pass
    try:
        ts.cleanup_current(xbmcaddon.Addon('plugin.video.tmdbmovies'))
    except:
        pass

class TorrServerPlayerMonitor(xbmc.Player):
    def __init__(self):
        super(TorrServerPlayerMonitor, self).__init__()
        self._ts = None
        self._hash = None
        self._is_torrserver = False

    def setup(self, ts, info_hash):
        if self._is_torrserver and self._ts and self._hash:
            try:
                self._ts.remove_torrent(self._hash)
            except:
                pass
        self._ts = ts
        self._hash = info_hash
        self._is_torrserver = True

    def onPlayBackStopped(self):
        self._is_torrserver = False

    def onPlayBackEnded(self):
        self._is_torrserver = False

    def onPlayBackError(self):
        self._is_torrserver = False

_player_monitor = None

def _get_player_monitor():
    global _player_monitor
    if _player_monitor is None:
        _player_monitor = TorrServerPlayerMonitor()
    return _player_monitor

_WINDOW_PROPS = [
    'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
    'tmdbmovies.torrserver_buffering', 'tmdbmovies.torrserver_details',
    'tmdbmovies.torrserver_filename'
]

def _clear_all_window_props():
    win = xbmcgui.Window(10000)
    for p in _WINDOW_PROPS:
        win.clearProperty(p)

class TorrServerResolver(xbmcgui.WindowXMLDialog):
    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback=True):
        super(TorrServerResolver, self).__init__(strXMLname, strFallbackPath, strDefaultName, forceFallback)
        self._cancel_event = threading.Event()
        self._closed = False
        self._result_url = None
        self._pick_files = None
        self._pick_info_hash = None

    def onInit(self):
        try:
            self.setFocusId(10)
        except:
            pass

    def update_status(self, text, subtext="", filename=""):
        if self._cancel_event.is_set():
            return
        win = xbmcgui.Window(10000)
        win.setProperty('tmdbmovies.torrserver_buffering', text)
        if subtext:
            win.setProperty('tmdbmovies.torrserver_details', subtext)
        if filename:
            win.setProperty('tmdbmovies.torrserver_filename', filename)

    def iscanceled(self):
        return self._cancel_event.is_set() or xbmc.Monitor().abortRequested()

    def close_window(self):
        if self._closed:
            return
        self._closed = True
        self._cancel_event.set()
        try:
            self.close()
        except:
            pass
        _clear_all_window_props()

    def onAction(self, action):
        if action.getId() in _CANCEL_ACTIONS:
            self._cancel_event.set()
            self.close_window()

def _detect_platform():
    is_android = False
    try:
        is_android = xbmc.getCondVisibility('System.Platform.Android')
    except:
        if 'android' in sys.platform.lower() or os.path.exists('/storage/emulated'):
            is_android = True
    free = 0
    try:
        free = int(xbmc.getInfoLabel('System.FreeMemory').replace(' MB', '').replace(',', ''))
    except:
        pass
    if is_android:
        if free > 0 and free < 300:
            return {'name': 'ANDROID_LOW', 'poll_fast': 1.0, 'poll_normal': 2.0, 'poll_slow': 3.0,
                    'speed_samples': 4, 'stabilize': 4, 'aggressive': False, 'dead_timeout': 30}
        return {'name': 'ANDROID_TV', 'poll_fast': 0.8, 'poll_normal': 1.5, 'poll_slow': 2.0,
                'speed_samples': 3, 'stabilize': 3, 'aggressive': False, 'dead_timeout': 25}
    return {'name': 'DESKTOP', 'poll_fast': 0.4, 'poll_normal': 0.8, 'poll_slow': 1.5,
            'speed_samples': 2, 'stabilize': 2, 'aggressive': True, 'dead_timeout': 20}

_PLATFORM = None

def get_platform():
    global _PLATFORM
    if _PLATFORM is None:
        _PLATFORM = _detect_platform()
    return _PLATFORM

def _sanitize_poster(p):
    if not p:
        return ""
    return p if p.startswith(('http://', 'https://')) else ""

def _sanitize_fanart(p):
    if not p:
        return ""
    return p if p.startswith(('http://', 'https://', 'special://', 'image://')) else ""

def _estimate_bitrate(fs):
    if fs > 15e9:
        d = 7200
    elif fs > 4e9:
        d = 7200
    elif fs > 1.5e9:
        d = 5400
    elif fs > 700e6:
        d = 2700
    else:
        d = 1800
    return fs / d

def _stall_timeout(p):
    if p <= 1:
        return 20
    elif p <= 3:
        return 12
    elif p <= 5:
        return 8
    else:
        return 5

def _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform):
    if bitrate <= 0:
        return 5
    ratio = max(avg_speed, peak_speed * 0.7) / bitrate
    if platform['aggressive']:
        if ratio >= 5:
            b = 2
        elif ratio >= 3:
            b = 4
        elif ratio >= 2:
            b = 6
        elif ratio >= 1.5:
            b = 8
        elif ratio >= 1:
            b = 12
        elif ratio >= .7:
            b = 20
        elif ratio >= .4:
            b = 30
        else:
            b = 40
    else:
        if ratio >= 5:
            b = 5
        elif ratio >= 3:
            b = 8
        elif ratio >= 2:
            b = 12
        elif ratio >= 1.5:
            b = 15
        elif ratio >= 1:
            b = 20
        elif ratio >= .7:
            b = 30
        elif ratio >= .4:
            b = 45
        else:
            b = 60
    return b + (5 if peers <= 1 else (2 if peers <= 3 else 0))

def _create_ts():
    host_full = get_torrserver_host()
    p = urlparse.urlparse(host_full)
    return TorrServer(p.hostname or '127.0.0.1', p.port or 8090,
                      ADDON.getSetting('torrserver_user') or "",
                      ADDON.getSetting('torrserver_pass') or "",
                      p.scheme == 'https')

def cleanup_torrserver():
    try:
        ts = _create_ts()
        ts.cleanup_tracked_hashes(xbmcaddon.Addon('plugin.video.tmdbmovies'))
    except:
        pass

_CUT_TAGS = re.compile(
    r'\b(1080p|2160p|720p|480p|4[Kk]|UHD|SD|'
    r'WEB[\.\- ]?DL|WEB[\.\- ]?Rip|WEBRip|BluRay|BDRip|BRRip|HDRip|'
    r'DVDRip|HDTV|PDTV|CAM|HDCAM|TS|TELESYNC|TC|SCR|DVDScr|R5|'
    r'[HhXx][\.\s]?264|[HhXx][\.\s]?265|HEVC|AVC|XviD|DivX|AV1|'
    r'AAC|AC3|DTS|DD[P]?[\.\s]?[257][\.\s]?[01]|Atmos|TrueHD|FLAC|MP3|EAC3|'
    r'REMUX|PROPER|REPACK|EXTENDED|UNRATED|DIRECTORS[\.\s]?CUT|DC|'
    r'MULTI|MULTi|DUAL|DUBBED|SUBBED|HQ|'
    r'YIFY|YTS|RARBG|FGT|EVO|SPARKS|GECKOS|NTG|FLUX|CMRG|'
    r'ESub|ESubs|HC|'
    r'10bit|HDR|HDR10|DV|DoVi|Dolby[\.\s]?Vision|IMAX|'
    r'NF|AMZN|DSNP|ATVP|HMAX|PCOK|PMTP|STAN)\b', re.IGNORECASE)
_BRACKETS = re.compile(r'[\[\(].*?[\)\]]')
_SEASON_EP = re.compile(r'\b[Ss]\d{1,2}(?:[Ee]\d{1,2})?\b')

def _extract_magnet_name(uri):
    if not uri or not uri.startswith('magnet:'):
        return ''
    try:
        return unquote(urlparse.parse_qs(urlparse.urlparse(uri).query).get('dn', [''])[0]).strip()
    except:
        return ''

def _clean_torrent_title(raw):
    if not raw:
        return '', None
    t = raw.strip()
    t = re.sub(r'\.(mkv|mp4|avi|mov|ts|srt|sub|nfo|txt)$', '', t, flags=re.IGNORECASE)
    ym = re.search(r'[\.\s\(\[\-]((?:19|20)\d{2})[\.\s\)\]\-]', t) or re.search(r'\b((?:19|20)\d{2})\b', t)
    year = ym.group(1) if ym else None
    t = t.replace('.', ' ').replace('_', ' ')
    t = _BRACKETS.sub(' ', t)
    t = _SEASON_EP.sub(' ', t)
    m = _CUT_TAGS.search(t)
    if m and m.start() > 2:
        t = t[:m.start()]
    if year:
        yp = t.find(year)
        if yp > 2:
            t = t[:yp]
    t = re.sub(r'\s+', ' ', t).strip(' -:,')
    return (t, year) if len(t) > 2 else ('', year)

def _best_title_and_year(info, magnet=''):
    cands = []
    for k in ('Title', 'title', 'originaltitle', 'tvshowtitle'):
        v = info.get(k, '')
        if v and v != 'Torrent Stream' and len(v) > 2:
            cands.append(v)
    mn = _extract_magnet_name(magnet)
    if mn and len(mn) > 3:
        cands.append(mn)
    ey = None
    for k in ('year', 'Year', 'premiered'):
        m = re.search(r'((?:19|20)\d{2})', str(info.get(k, '')))
        if m:
            ey = m.group(1)
            break
    bt, by = '', ey
    for raw in cands:
        c, y = _clean_torrent_title(raw)
        if c and (not bt or len(c) < len(bt)):
            bt = c
        if y and not by:
            by = y
    if not bt:
        bt = (info.get('Title', '') or info.get('title', '')).strip()
    return bt, by

_VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.ts', '.m4v', '.webm', '.flv', '.m2ts')
_MIN_VIDEO_SIZE = 50 * 1024 * 1024

def _format_file_label(f):
    path = f.get('path', 'Unknown')
    name = os.path.basename(path)
    name_no_ext = name.rsplit('.', 1)[0] if '.' in name else name
    display = name_no_ext.replace('.', ' ').replace('_', ' ')
    ep_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', name)
    if ep_match:
        ep_tag = "S%02dE%02d" % (int(ep_match.group(1)), int(ep_match.group(2)))
    else:
        ep_tag = ""
    size = f.get('length', 0)
    if size >= 1024 ** 3:
        sz = "%.1f GB" % (size / (1024.0 ** 3))
    else:
        sz = "%d MB" % (size // (1024 * 1024))
    if ep_tag:
        return "[B]%s[/B]  -  %s  (%s)" % (ep_tag, display, sz)
    else:
        return "%s  (%s)" % (display, sz)

def _show_file_picker(candidates):
    sorted_files = sorted(candidates, key=lambda f: f.get('path', '').lower())
    items = [_format_file_label(f) for f in sorted_files]
    idx = xbmcgui.Dialog().select(
        'Select file / episode (%d available)' % len(items),
        items, useDetails=False
    )
    if idx < 0:
        return None
    chosen = sorted_files[idx]
    return chosen

def _do_preload(ts, info_hash, file_id, title):
    try:
        ts.preload_torrent(info_hash, file_id=file_id, title=title)
    except:
        pass

def _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size, title,
                        ui_window, ce, platform):
    bitrate = _estimate_bitrate(file_size)
    ui_window.update_status("Preparing file...", "", os.path.basename(file_path))
    if ce.is_set():
        return
    t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
    t.daemon = True
    t.start()
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if ce.is_set():
            return
        result = _wait_for_ready(ts, info_hash, file_id, title, file_path,
                                 file_size, bitrate, ui_window, ce, platform, attempt)
        if result == 'dead':
            def _notify_dead():
                try:
                    xbmcgui.Dialog().notification('TorrServer', 'No seeders available',
                                                  xbmcgui.NOTIFICATION_WARNING, 5000)
                except:
                    pass
            threading.Thread(target=_notify_dead, daemon=True).start()
            return
        if result in ('cancel', 'error') or result != 'ok':
            return
        if ce.is_set():
            return
        ui_window.update_status("[COLOR dodgerblue]Verifying stream...[/COLOR]",
                                "[COLOR silver]Almost ready...[/COLOR]")
        if ts.verify_stream(info_hash, file_path, file_id, timeout=15):
            if ce.is_set():
                return
            _get_player_monitor().setup(ts, info_hash)
            ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
            ui_window.close_window()
            return
        if ce.is_set():
            return
        if attempt < max_attempts:
            t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
            t.daemon = True
            t.start()
            if _cancel_sleep(ce, 3):
                return
        else:
            if ce.is_set():
                return
            _get_player_monitor().setup(ts, info_hash)
            ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
            ui_window.close_window()
            return

def _worker_phase1(ts, magnet_uri, item_info, ui_window, platform, title, poster_for_ts):
    info_hash = None
    ce = ui_window._cancel_event
    try:
        ts.cleanup_tracked_hashes(ADDON)
        if ce.is_set():
            return
        is_file_upload = False
        if os.path.exists(magnet_uri) and os.path.isfile(magnet_uri):
            info_hash = ts.add_file(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        elif magnet_uri.startswith('magnet:'):
            info_hash = ts.add_magnet_fast(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        elif magnet_uri.lower().endswith('.torrent') or urlparse.urlparse(magnet_uri).path.lower().endswith('.torrent'):
            info_hash = ts.add_magnet(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        else:
            info_hash = ts.add_magnet(magnet_uri, title=title, poster=poster_for_ts)
        if not info_hash:
            return
        ts.save_hash_to_settings(ADDON, info_hash)
        if ce.is_set():
            return
        if not _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
            return
        if ce.is_set():
            return
        info = ts.get_torrent_info_api(info_hash) or ts.get_torrent_info(info_hash)
        if not info or not info.get('file_stats'):
            return
        files = info['file_stats']
        if not files:
            return
        candidates = [f for f in files
                      if any(f.get('path', '').lower().endswith(e) for e in _VIDEO_EXT)]
        if not candidates:
            candidates = files
        significant = [f for f in candidates if f.get('length', 0) > _MIN_VIDEO_SIZE]
        season = item_info.get('Season')
        episode = item_info.get('Episode')
        chosen = None
        if season and episode:
            try:
                patterns = ["s%02de%02d" % (int(season), int(episode)),
                            "%dx%02d" % (int(season), int(episode)),
                            "%dx%d" % (int(season), int(episode))]
                exact = [f for f in candidates
                         if any(p in f.get('path', '').lower() for p in patterns)]
                if exact:
                    chosen = max(exact, key=lambda x: x.get('length', 0))
            except:
                pass
        if not chosen and len(significant) > 1:
            ui_window._pick_files = significant
            ui_window._pick_info_hash = info_hash
            ui_window.close_window()
            return
        if not chosen:
            chosen = max(candidates, key=lambda x: x.get('length', 0))
        file_id = chosen.get('id', 1)
        file_path = chosen.get('path', '')
        file_size = chosen.get('length', 0)
        if 'bdmv' in file_path.lower() or len(files) > 50:
            pass
        _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size,
                            title, ui_window, ce, platform)
    except Exception as e:
        log("Worker EXCEPTIE: %s" % str(e))
    finally:
        if ui_window._result_url is None and ui_window._pick_files is None:
            if info_hash:
                t = threading.Thread(target=_async_cleanup, args=(ts, info_hash))
                t.daemon = True
                t.start()
        ui_window.close_window()

def _worker_phase2(ts, info_hash, chosen, title, ui_window, platform):
    ce = ui_window._cancel_event
    try:
        file_id = chosen.get('id', 1)
        file_path = chosen.get('path', '')
        file_size = chosen.get('length', 0)
        _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size,
                            title, ui_window, ce, platform)
    except Exception as e:
        log("Worker2 EXCEPTIE: %s" % str(e))
    finally:
        if ui_window._result_url is None:
            t = threading.Thread(target=_async_cleanup, args=(ts, info_hash))
            t.daemon = True
            t.start()
        ui_window.close_window()

def _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
    if is_file_upload:
        for _ in range(5):
            if ce.is_set():
                return False
            info = ts.get_torrent_info_api(info_hash)
            if info and info.get('file_stats'):
                return True
            time.sleep(0.3)
    timeout = 20 if is_file_upload else 45
    start = time.time()
    while time.time() - start < timeout:
        if ce.is_set():
            return False
        elapsed = time.time() - start
        for getter in (ts.get_torrent_info_api, ts.get_torrent_info):
            info = getter(info_hash)
            if info and info.get('file_stats'):
                return True
        ui_window.update_status(
            "[COLOR dodgerblue]Downloading metadata...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed)
        if elapsed < 5:
            sd = platform['poll_fast']
        elif elapsed < 15:
            sd = platform['poll_normal']
        else:
            sd = platform['poll_slow']
        if _cancel_sleep(ce, sd):
            return False
    return False

def _wait_for_ready(ts, info_hash, file_id, title, file_path, file_size,
                    bitrate, ui_window, ce, platform, attempt):
    start = time.time()
    speed_history = []
    samples = platform['speed_samples']
    peak_speed = 0
    last_preloaded = 0
    last_growth_time = time.time()
    buffer_stalled = False
    stabilize_start = None
    stabilize_reason = ""
    stabilize_dur = platform['stabilize']
    max_wait = 90 if attempt == 1 else 45
    absolute_min = 2 * 1024 * 1024
    dead_timeout = platform['dead_timeout']
    ever_had_peers = False
    ever_had_bytes = False
    try:
        while not ce.is_set():
            ti = ts.get_torrent_info_api(info_hash) or ts.get_torrent_info(info_hash)
            if not ti:
                if _cancel_sleep(ce, platform['poll_normal']):
                    return 'cancel'
                continue
            if ce.is_set():
                return 'cancel'
            fs = ts.get_torrent_file_info(info_hash, file_id)
            speed = ti.get('download_speed', 0)
            preloaded = fs.get('preloaded_bytes', 0) if fs else 0
            peers = ti.get('active_peers', 0)
            total_peers = ti.get('total_peers', 0)
            elapsed = time.time() - start
            if peers > 0 or total_peers > 0:
                ever_had_peers = True
            if preloaded > 0:
                ever_had_bytes = True
            speed_history.append(speed)
            if len(speed_history) > 30:
                speed_history = speed_history[-30:]
            recent = speed_history[-samples:]
            avg_speed = sum(recent) / len(recent) if recent else 0
            if speed > peak_speed:
                peak_speed = speed
            cst = _stall_timeout(peers)
            if preloaded > last_preloaded + 10000:
                last_preloaded, last_growth_time, buffer_stalled = preloaded, time.time(), False
            elif time.time() - last_growth_time > cst:
                buffer_stalled = True
            runway = preloaded / bitrate if bitrate > 0 else 999
            needed = _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform)
            is_dead = False
            if elapsed > dead_timeout:
                if preloaded == 0 and peers == 0 and not ever_had_bytes:
                    is_dead = True
                elif preloaded == 0 and not ever_had_peers and elapsed > dead_timeout * 1.5:
                    is_dead = True
                elif preloaded == 0 and speed == 0 and elapsed > dead_timeout * 2 and not ever_had_bytes:
                    is_dead = True
            if is_dead:
                return 'dead'
            smb = speed / 1048576.0
            pmb = preloaded / 1048576.0
            ratio = max(avg_speed, peak_speed * 0.7) / bitrate if bitrate > 0 else 0
            sc = 'lime' if smb >= 1 else ('gold' if smb >= 0.3 else 'orangered')
            pc = 'lime' if peers >= 5 else ('gold' if peers >= 1 else 'orangered')
            if preloaded == 0 and peers == 0:
                l1 = "[COLOR dodgerblue]Searching for seeders...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed
                l2 = "[COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B][COLOR white] / [/COLOR][COLOR silver]%d[/COLOR]" % (pc, peers, total_peers)
            elif preloaded == 0:
                l1 = "[COLOR dodgerblue]Connecting...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed
                l2 = "[COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B][COLOR white] / [/COLOR][COLOR silver]%d[/COLOR]" % (pc, peers, total_peers)
            else:
                l1 = "[COLOR dodgerblue]Buffer:[/COLOR]  [COLOR white]%.1f MB[/COLOR]  [COLOR grey](%.0fs / %.0fs)[/COLOR]" % (pmb, runway, needed)
                l2 = "[COLOR deepskyblue]Speed:[/COLOR] [B][COLOR %s]%.2f MB/s[/COLOR][/B]   [COLOR white]•[/COLOR]   [COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B]" % (sc, smb, pc, peers)
            ui_window.update_status(l1, l2)
            can_start = False
            reason = ""
            rok = runway >= needed and preloaded >= absolute_min
            sok = len(recent) >= samples and avg_speed > 0
            if platform['aggressive']:
                if rok and sok:
                    can_start, reason = True, "runway(%.0f/%.0f)" % (runway, needed)
                elif avg_speed > bitrate * 2 and runway >= 1 and preloaded >= absolute_min:
                    can_start, reason = True, "fast"
                elif buffer_stalled and preloaded >= absolute_min and runway >= 3:
                    can_start, reason = True, "stalled+rw"
                elif buffer_stalled and preloaded >= 5 * 1024 * 1024:
                    can_start, reason = True, "stalled+buf"
                elif elapsed > max_wait and preloaded >= absolute_min:
                    can_start, reason = True, "timeout"
            else:
                if rok and sok:
                    can_start, reason = True, "runway+speed"
                elif runway >= needed * 2 and preloaded >= absolute_min:
                    can_start, reason = True, "double_rw"
                elif buffer_stalled and preloaded >= absolute_min and runway >= 5:
                    can_start, reason = True, "stalled+rw"
                elif buffer_stalled and preloaded >= 8 * 1024 * 1024:
                    can_start, reason = True, "stalled+buf"
                elif elapsed > max_wait and preloaded >= absolute_min:
                    can_start, reason = True, "timeout"
            if can_start:
                if stabilize_start is None:
                    stabilize_start = time.time()
                    stabilize_reason = reason
                elif time.time() - stabilize_start >= stabilize_dur:
                    return 'ok'
            else:
                if stabilize_start is not None:
                    reset = True
                    if buffer_stalled and preloaded >= absolute_min:
                        reset = False
                    elif peak_speed > bitrate * 1.5 and preloaded >= absolute_min:
                        reset = False
                    elif avg_speed > bitrate * 0.5 and preloaded >= absolute_min:
                        reset = False
                    if reset:
                        stabilize_start = None
            if elapsed < 5:
                sd = platform['poll_fast']
            elif elapsed < 20:
                sd = platform['poll_normal']
            else:
                sd = platform['poll_slow']
            if _cancel_sleep(ce, sd):
                return 'cancel'
        return 'cancel'
    except Exception as e:
        log("Buffer EXCEPTIE: %s" % str(e))
        return 'error'

def get_torrserver_url(magnet_uri, item_info):
    if len(magnet_uri) == 40 and not magnet_uri.startswith(('http', 'magnet')):
        magnet_uri = "magnet:?xt=urn:btih:%s" % magnet_uri
    ts = _create_ts()
    platform = get_platform()
    title = item_info.get('Title', 'Torrent Stream')
    _clear_all_window_props()
    xbmc.sleep(50)
    fanart = item_info.get('Fanart') or item_info.get('fanart') or item_info.get('backdrop_path')
    poster = item_info.get('Poster') or item_info.get('poster')
    logo = item_info.get('ClearLogo') or item_info.get('clearlogo') or ""
    if not fanart or not str(fanart).startswith('http'):
        fanart = "special://home/addons/plugin.video.tmdbmovies/icon.png"
    poster_for_ts = _sanitize_poster(fanart)
    fanart_prop = _sanitize_fanart(fanart)
    logo_prop = logo or ''
    def _setup_window_props():
        win = xbmcgui.Window(10000)
        win.setProperty('tmdbmovies.fanart', fanart_prop)
        win.setProperty('tmdbmovies.clearlogo', logo_prop)
        win.setProperty('tmdbmovies.torrserver_filename', title)
        win.setProperty('tmdbmovies.torrserver_buffering', 'Initializing engine...')
        win.setProperty('tmdbmovies.torrserver_details', 'Please wait')
    _setup_window_props()
    xbmc.sleep(100)
    ui1 = TorrServerResolver('resolver_window.xml', ADDON_PATH, 'Default')
    worker1 = threading.Thread(
        target=_worker_phase1,
        args=(ts, magnet_uri, item_info, ui1, platform, title, poster_for_ts))
    worker1.daemon = True
    worker1.start()
    for _ in range(6):
        if ui1._closed or ui1._pick_files is not None or ui1._result_url is not None:
            break
        xbmc.sleep(50)
    if not ui1._closed and ui1._pick_files is None and ui1._result_url is None:
        ui1.doModal()
    if ui1._closed and ui1._result_url is None and ui1._pick_files is None:
        worker1.join(timeout=0.5)
        _clear_all_window_props()
        return None
    worker1.join(timeout=5)
    _clear_all_window_props()
    final_url = None
    chosen_file_path = None
    if ui1._result_url:
        final_url = ui1._result_url
        chosen_file_path = "direct"
    if ui1._pick_files and ui1._pick_info_hash:
        chosen = _show_file_picker(ui1._pick_files)
        if not chosen:
            t = threading.Thread(target=_async_cleanup, args=(ts, ui1._pick_info_hash))
            t.daemon = True
            t.start()
            return None
        chosen_file_path = chosen.get('path', '')
        _setup_window_props()
        xbmc.sleep(100)
        ui2 = TorrServerResolver('resolver_window.xml', ADDON_PATH, 'Default')
        worker2 = threading.Thread(
            target=_worker_phase2,
            args=(ts, ui1._pick_info_hash, chosen, title, ui2, platform))
        worker2.daemon = True
        worker2.start()
        ui2.doModal()
        if ui2._closed and ui2._result_url is None:
            worker2.join(timeout=0.5)
            _clear_all_window_props()
            return None
        worker2.join(timeout=5)
        _clear_all_window_props()
        if ui2._result_url:
            final_url = ui2._result_url
    if final_url:
        return final_url
    return None
