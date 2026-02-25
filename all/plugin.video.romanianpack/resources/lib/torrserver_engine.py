# -*- coding: utf-8 -*-
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
    from resources.lib.torrserver_api import TorrServer
except ImportError:
    from torrserver_api import TorrServer
try:
    from resources.lib import requests
except ImportError:
    import requests

ADDON = xbmcaddon.Addon('plugin.video.romanianpack')
TMDB_API_KEY = "f090bb54758cabf231fb605d3e3e0468"

_CANCEL_ACTIONS = frozenset([9, 10, 13, 92, 110, 216])

# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _cancel_sleep(cancel_event, duration):
    """Returnează True dacă a fost anulat."""
    return cancel_event.wait(timeout=duration)


def _async_cleanup(ts, info_hash):
    try: ts.remove_torrent(info_hash)
    except: pass
    try:
        addon = xbmcaddon.Addon('plugin.video.romanianpack')
        ts.cleanup_current(addon)
    except: pass
    xbmc.log("[MRSP Lite] Async cleanup done: %s" % info_hash[:16], xbmc.LOGINFO)

# ══════════════════════════════════════════════════════════════
#  PLAYBACK MONITOR
# ══════════════════════════════════════════════════════════════

class TorrServerPlayerMonitor(xbmc.Player):
    def __init__(self):
        super(TorrServerPlayerMonitor, self).__init__()
        self._ts = None
        self._hash = None
        self._is_torrserver = False

    def setup(self, ts, info_hash):
        self._ts = ts
        self._hash = info_hash
        self._is_torrserver = True

    def onPlayBackStopped(self):  self._do_cleanup("stop")
    def onPlayBackEnded(self):   self._do_cleanup("ended")
    def onPlayBackError(self):   self._do_cleanup("error")

    def _do_cleanup(self, reason):
        if not self._is_torrserver or not self._hash: return
        try:
            addon = xbmcaddon.Addon('plugin.video.romanianpack')
            if self._ts: self._ts.cleanup_current(addon)
            self._is_torrserver = False
        except: pass

_player_monitor = None
def _get_player_monitor():
    global _player_monitor
    if _player_monitor is None:
        _player_monitor = TorrServerPlayerMonitor()
    return _player_monitor

# ══════════════════════════════════════════════════════════════
#  FEREASTRA CINEBOX — cu doModal() + threading.Event
# ══════════════════════════════════════════════════════════════

_WINDOW_PROPS = ['info.fanart', 'info.clearlogo',
                 'CineboxBuffering', 'CineboxStatus', 'CineboxFileName']

def _clear_all_window_props():
    win = xbmcgui.Window(10000)
    for p in _WINDOW_PROPS:
        win.clearProperty(p)


class CineboxResolver(xbmcgui.WindowXMLDialog):
    """Dialog modal — onAction primește Back/Escape doar cu doModal()."""

    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback=True):
        super(CineboxResolver, self).__init__(strXMLname, strFallbackPath, strDefaultName, forceFallback)
        self._cancel_event = threading.Event()
        self._closed = False
        self._result_url = None          # worker-ul pune URL-ul aici

    def onInit(self):
        try:
            self.setFocusId(10)
        except:
            pass

    def update_status(self, text, subtext="", filename=""):
        if self._cancel_event.is_set():
            return
        win = xbmcgui.Window(10000)
        win.setProperty('CineboxBuffering', text)
        if subtext:  win.setProperty('CineboxStatus', subtext)
        if filename: win.setProperty('CineboxFileName', filename)

    def iscanceled(self):
        return self._cancel_event.is_set() or xbmc.Monitor().abortRequested()

    def close_window(self):
        """Apelat din worker SAU din onAction. Închide dialogul → doModal() se termină."""
        if self._closed:
            return
        self._closed = True
        self._cancel_event.set()
        try:
            self.close()            # ← termină doModal()
        except:
            pass
        _clear_all_window_props()

    def onAction(self, action):
        aid = action.getId()
        if aid in _CANCEL_ACTIONS:
            xbmc.log("[MRSP Lite] ← CANCEL (action %d)" % aid, xbmc.LOGINFO)
            self._cancel_event.set()
            self.close_window()

# ══════════════════════════════════════════════════════════════
#  PLATFORMĂ
# ══════════════════════════════════════════════════════════════

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
    except: pass
    xbmc.log("[MRSP Lite] Platform: android=%s, ram=%dMB" % (is_android, free), xbmc.LOGINFO)
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
    if _PLATFORM is None: _PLATFORM = _detect_platform()
    return _PLATFORM

# ══════════════════════════════════════════════════════════════
#  UTILITĂȚI
# ══════════════════════════════════════════════════════════════

def _sanitize_poster(p):
    if not p: return ""
    return p if p.startswith(('http://', 'https://')) else ""

def _sanitize_fanart(p):
    if not p: return ""
    return p if p.startswith(('http://', 'https://', 'special://', 'image://')) else ""

def _estimate_bitrate(fs):
    if fs > 15e9:   d = 7200
    elif fs > 4e9:  d = 7200
    elif fs > 1.5e9:d = 5400
    elif fs > 700e6:d = 2700
    else:           d = 1800
    return fs / d

def _stall_timeout(p):
    if p <= 1:   return 20
    elif p <= 3: return 12
    elif p <= 5: return 8
    else:        return 5

def _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform):
    if bitrate <= 0: return 5
    ratio = max(avg_speed, peak_speed * 0.7) / bitrate
    if platform['aggressive']:
        if ratio >= 5:   b = 2
        elif ratio >= 3: b = 4
        elif ratio >= 2: b = 6
        elif ratio >= 1.5:b= 8
        elif ratio >= 1: b = 12
        elif ratio >= .7:b = 20
        elif ratio >= .4:b = 30
        else:            b = 40
    else:
        if ratio >= 5:   b = 5
        elif ratio >= 3: b = 8
        elif ratio >= 2: b = 12
        elif ratio >= 1.5:b= 15
        elif ratio >= 1: b = 20
        elif ratio >= .7:b = 30
        elif ratio >= .4:b = 45
        else:            b = 60
    return b + (5 if peers <= 1 else (2 if peers <= 3 else 0))

def _create_ts():
    host_full = (ADDON.getSetting('torrserver_host') or 'http://127.0.0.1:8090').rstrip('/')
    p = urlparse.urlparse(host_full)
    return TorrServer(p.hostname or '127.0.0.1', p.port or 8090,
                      ADDON.getSetting('torrserver_user') or "",
                      ADDON.getSetting('torrserver_pass') or "",
                      p.scheme == 'https')

def cleanup_torrserver():
    try:
        ts = _create_ts()
        ts.cleanup_tracked_hashes(xbmcaddon.Addon('plugin.video.romanianpack'))
    except: pass

# ══════════════════════════════════════════════════════════════
#  TITLU CURAT
# ══════════════════════════════════════════════════════════════

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
_BRACKETS = re.compile(r'[\[\(].*?[\]\)]')
_SEASON_EP = re.compile(r'\b[Ss]\d{1,2}(?:[Ee]\d{1,2})?\b')

def _extract_magnet_name(uri):
    if not uri or not uri.startswith('magnet:'): return ''
    try:
        return unquote(urlparse.parse_qs(urlparse.urlparse(uri).query).get('dn', [''])[0]).strip()
    except: return ''

def _clean_torrent_title(raw):
    if not raw: return '', None
    t = raw.strip()
    t = re.sub(r'\.(mkv|mp4|avi|mov|ts|srt|sub|nfo|txt)$', '', t, flags=re.IGNORECASE)
    ym = re.search(r'[\.\s\(\[\-]((?:19|20)\d{2})[\.\s\)\]\-]', t) or re.search(r'\b((?:19|20)\d{2})\b', t)
    year = ym.group(1) if ym else None
    t = t.replace('.', ' ').replace('_', ' ')
    t = _BRACKETS.sub(' ', t)
    t = _SEASON_EP.sub(' ', t)
    m = _CUT_TAGS.search(t)
    if m and m.start() > 2: t = t[:m.start()]
    if year:
        yp = t.find(year)
        if yp > 2: t = t[:yp]
    t = re.sub(r'\s+', ' ', t).strip(' -:,')
    return (t, year) if len(t) > 2 else ('', year)

def _best_title_and_year(info, magnet=''):
    cands = []
    for k in ('Title', 'title', 'originaltitle', 'tvshowtitle'):
        v = info.get(k, '')
        if v and v != 'Torrent Stream' and len(v) > 2: cands.append(v)
    mn = _extract_magnet_name(magnet)
    if mn and len(mn) > 3: cands.append(mn)
    ey = None
    for k in ('year', 'Year', 'premiered'):
        m = re.search(r'((?:19|20)\d{2})', str(info.get(k, '')))
        if m: ey = m.group(1); break
    bt, by = '', ey
    for raw in cands:
        c, y = _clean_torrent_title(raw)
        if c and (not bt or len(c) < len(bt)): bt = c
        if y and not by: by = y
    if not bt: bt = (info.get('Title', '') or info.get('title', '')).strip()
    return bt, by

# ══════════════════════════════════════════════════════════════
#  TMDB METADATA
# ══════════════════════════════════════════════════════════════

_tmdb_cache = {}

def _tmdb_get(url, retries=2):
    for i in range(retries):
        try:
            r = requests.get(url, verify=False, timeout=6)
            if r.status_code == 200: return r.json()
            if r.status_code == 429: time.sleep(1); continue
            return None
        except:
            if i < retries - 1: time.sleep(0.5)
    return None

def _tmdb_search(title, year=None):
    if not title or len(title) < 2: return None, None
    enc = quote(title)
    if year:
        d = _tmdb_get("https://api.themoviedb.org/3/search/movie?api_key=%s&query=%s&year=%s" % (TMDB_API_KEY, enc, year))
        if d and d.get('results'): return d['results'][0]['id'], 'movie'
    d = _tmdb_get("https://api.themoviedb.org/3/search/movie?api_key=%s&query=%s" % (TMDB_API_KEY, enc))
    if d and d.get('results'):
        if year:
            for r in d['results']:
                if r.get('release_date', '').startswith(str(year)): return r['id'], 'movie'
        return d['results'][0]['id'], 'movie'
    d = _tmdb_get("https://api.themoviedb.org/3/search/tv?api_key=%s&query=%s" % (TMDB_API_KEY, enc))
    if d and d.get('results'): return d['results'][0]['id'], 'tv'
    d = _tmdb_get("https://api.themoviedb.org/3/search/multi?api_key=%s&query=%s" % (TMDB_API_KEY, enc))
    if d and d.get('results'):
        for r in d['results']:
            if r.get('media_type') in ('movie', 'tv'): return r['id'], r['media_type']
    return None, None

def get_tmdb_metadata(tmdb_id=None, imdb_id=None, title=None, year=None):
    ck = "%s|%s|%s|%s" % (tmdb_id, imdb_id, (title or '')[:50], year)
    if ck in _tmdb_cache: return _tmdb_cache[ck]
    mt, rid = 'movie', tmdb_id
    if not rid and imdb_id and str(imdb_id).startswith('tt'):
        d = _tmdb_get("https://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id" % (imdb_id, TMDB_API_KEY))
        if d:
            if d.get('movie_results'): rid = d['movie_results'][0].get('id')
            elif d.get('tv_results'): rid = d['tv_results'][0].get('id'); mt = 'tv'
    if not rid and title:
        rid, ft = _tmdb_search(title, year)
        if ft: mt = ft
    fanart, logo = None, None
    if rid:
        d = _tmdb_get("https://api.themoviedb.org/3/%s/%s/images?api_key=%s" % (mt, rid, TMDB_API_KEY))
        if d:
            if d.get('backdrops'):
                bds = sorted(d['backdrops'], key=lambda x: x.get('vote_average', 0), reverse=True)
                fanart = "https://image.tmdb.org/t/p/original" + bds[0]['file_path']
            ls = d.get('logos', [])
            if ls:
                el = [l for l in ls if l.get('iso_639_1') == 'en']
                logo = "https://image.tmdb.org/t/p/w500" + (el[0] if el else ls[0])['file_path']
        if not fanart:
            d = _tmdb_get("https://api.themoviedb.org/3/%s/%s?api_key=%s" % (mt, rid, TMDB_API_KEY))
            if d:
                if d.get('backdrop_path'): fanart = "https://image.tmdb.org/t/p/original" + d['backdrop_path']
                elif d.get('poster_path'): fanart = "https://image.tmdb.org/t/p/original" + d['poster_path']
    _tmdb_cache[ck] = (fanart, logo)
    return fanart, logo

# ══════════════════════════════════════════════════════════════
#  WORKER THREAD — toată logica de buffering rulează aici
# ══════════════════════════════════════════════════════════════

def _torrserver_worker(ts, magnet_uri, item_info, ui_window, platform,
                       title, poster_for_ts):
    """Rulează pe thread separat. Setează ui_window._result_url și închide dialogul."""
    info_hash = None
    ce = ui_window._cancel_event      # scurtătură

    try:
        # ═══ CLEANUP ═══
        ts.cleanup_tracked_hashes(ADDON)
        if ce.is_set(): return

        # ═══ ADD TORRENT ═══
        is_file_upload = False
        if os.path.exists(magnet_uri) and os.path.isfile(magnet_uri):
            xbmc.log("[MRSP Lite] Fisier .torrent LOCAL: %s" % magnet_uri, xbmc.LOGINFO)
            info_hash = ts.add_file(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        elif magnet_uri.startswith('magnet:'):
            xbmc.log("[MRSP Lite] Magnet: %s..." % magnet_uri[:80], xbmc.LOGINFO)
            info_hash = ts.add_magnet_fast(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        else:
            xbmc.log("[MRSP Lite] Link: %s..." % magnet_uri[:80], xbmc.LOGINFO)
            info_hash = ts.add_magnet(magnet_uri, title=title, poster=poster_for_ts)

        if not info_hash:
            xbmc.log("[MRSP Lite] EROARE: hash!", xbmc.LOGERROR)
            return
        ts.save_hash_to_settings(ADDON, info_hash)
        xbmc.log("[MRSP Lite] Hash: %s | upload=%s" % (info_hash, is_file_upload), xbmc.LOGINFO)

        if ce.is_set(): return

        # ═══ METADATA ═══
        if not _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
            return

        if ce.is_set(): return

        # ═══ SELECT FILE ═══
        info = ts.get_torrent_info_api(info_hash) or ts.get_torrent_info(info_hash)
        if not info or not info.get('file_stats'): return

        files = info['file_stats']
        if not files: return

        video_ext = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.ts', '.m4v', '.webm', '.flv', '.m2ts')
        candidates = [f for f in files if any(f.get('path', '').lower().endswith(e) for e in video_ext)]

        chosen = None
        if candidates:
            season, episode = item_info.get('Season'), item_info.get('Episode')
            if season and episode:
                try:
                    pats = ["s%02de%02d" % (int(season), int(episode)),
                            "%dx%02d" % (int(season), int(episode))]
                    exact = [f for f in candidates if any(p in f.get('path', '').lower() for p in pats)]
                    chosen = max(exact or candidates, key=lambda x: x.get('length', 0))
                except:
                    chosen = max(candidates, key=lambda x: x.get('length', 0))
            else:
                chosen = max(candidates, key=lambda x: x.get('length', 0))
        elif files:
            chosen = max(files, key=lambda x: x.get('length', 0))
        if not chosen: return

        file_id = chosen.get('id', 1)
        file_path = chosen.get('path', '')
        file_size = chosen.get('length', 0)

        xbmc.log("[MRSP Lite] Fisier: [id=%s] %s (%d MB) | Total: %d" % (
            file_id, file_path, file_size // (1024 * 1024), len(files)), xbmc.LOGINFO)

        ui_window.update_status("Pregătire fișier...", "", os.path.basename(file_path))
        bitrate = _estimate_bitrate(file_size)

        if ce.is_set(): return

        # ═══ PRELOAD ═══
        t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
        t.daemon = True; t.start()

        # ═══ BUFFERING ═══
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if ce.is_set(): return

            xbmc.log("[MRSP Lite] ═══ Buffer #%d/%d ═══" % (attempt, max_attempts), xbmc.LOGINFO)

            result = _wait_for_ready(ts, info_hash, file_id, title, file_path,
                                     file_size, bitrate, ui_window, ce, platform, attempt)

            if result == 'dead':
                xbmc.log("[MRSP Lite] ✗ TORRENT MORT", xbmc.LOGERROR)
                # Notificare după cleanup
                def _notify_dead():
                    try:
                        xbmcgui.Dialog().notification('TorrServer', 'Torrentul nu are seederi',
                                                      xbmcgui.NOTIFICATION_WARNING, 5000)
                    except: pass
                threading.Thread(target=_notify_dead, daemon=True).start()
                return

            if result in ('cancel', 'error') or result != 'ok':
                return

            if ce.is_set(): return

            # ═══ VERIFY ═══
            ui_window.update_status(
                "[COLOR dodgerblue]Verificare stream...[/COLOR]",
                "[COLOR silver]Aproape gata...[/COLOR]")

            if ts.verify_stream(info_hash, file_path, file_id, timeout=15):
                xbmc.log("[MRSP Lite] ✓ Stream VERIFICAT", xbmc.LOGINFO)
                _get_player_monitor().setup(ts, info_hash)
                ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
                ui_window.close_window()
                return              # ← succes, nu face cleanup

            if ce.is_set(): return

            if attempt < max_attempts:
                t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
                t.daemon = True; t.start()
                if _cancel_sleep(ce, 3): return
            else:
                xbmc.log("[MRSP Lite] ✗ Pornire directa", xbmc.LOGINFO)
                _get_player_monitor().setup(ts, info_hash)
                ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
                ui_window.close_window()
                return              # ← succes

    except Exception as e:
        xbmc.log("[MRSP Lite] Worker EXCEPTIE: %s" % str(e), xbmc.LOGERROR)
    finally:
        # Dacă ajungem aici FĂRĂ result_url → cleanup
        if ui_window._result_url is None:
            if info_hash:
                t = threading.Thread(target=_async_cleanup, args=(ts, info_hash))
                t.daemon = True; t.start()
            ui_window.close_window()


def _do_preload(ts, info_hash, file_id, title):
    try: ts.preload_torrent(info_hash, file_id=file_id, title=title)
    except: pass

# ══════════════════════════════════════════════════════════════
#  METADATA — cancel-aware
# ══════════════════════════════════════════════════════════════

def _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
    if is_file_upload:
        for _ in range(5):
            if ce.is_set(): return False
            info = ts.get_torrent_info_api(info_hash)
            if info and info.get('file_stats'):
                xbmc.log("[MRSP Lite] ✓ Metadata INSTANT", xbmc.LOGINFO)
                return True
            time.sleep(0.3)

    timeout = 20 if is_file_upload else 45
    start = time.time()

    while time.time() - start < timeout:
        if ce.is_set(): return False
        elapsed = time.time() - start

        for getter in (ts.get_torrent_info_api, ts.get_torrent_info):
            info = getter(info_hash)
            if info and info.get('file_stats'):
                xbmc.log("[MRSP Lite] ✓ Metadata OK (%.1fs)" % elapsed, xbmc.LOGINFO)
                return True

        ui_window.update_status(
            "[COLOR dodgerblue]Descarcă metadate...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed)

        if elapsed < 5:    sd = platform['poll_fast']
        elif elapsed < 15: sd = platform['poll_normal']
        else:              sd = platform['poll_slow']

        if _cancel_sleep(ce, sd): return False

    return False

# ══════════════════════════════════════════════════════════════
#  BUFFERING — cancel-aware
# ══════════════════════════════════════════════════════════════

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
            ti = ts.get_torrent_info(info_hash) or ts.get_torrent_info_api(info_hash)
            if not ti:
                if _cancel_sleep(ce, platform['poll_normal']): return 'cancel'
                continue
            if ce.is_set(): return 'cancel'

            fs = ts.get_torrent_file_info(info_hash, file_id)
            speed = ti.get('download_speed', 0)
            preloaded = fs.get('preloaded_bytes', 0) if fs else 0
            peers = ti.get('active_peers', 0)
            total_peers = ti.get('total_peers', 0)
            elapsed = time.time() - start

            if peers > 0 or total_peers > 0: ever_had_peers = True
            if preloaded > 0: ever_had_bytes = True

            speed_history.append(speed)
            if len(speed_history) > 30: speed_history = speed_history[-30:]
            recent = speed_history[-samples:]
            avg_speed = sum(recent) / len(recent) if recent else 0
            if speed > peak_speed: peak_speed = speed

            cst = _stall_timeout(peers)
            if preloaded > last_preloaded + 10000:
                last_preloaded, last_growth_time, buffer_stalled = preloaded, time.time(), False
            elif time.time() - last_growth_time > cst:
                if not buffer_stalled:
                    xbmc.log("[MRSP Lite] STALLED: %.1fMB (t=%ds, p=%d)" % (
                        preloaded / 1048576.0, cst, peers), xbmc.LOGINFO)
                buffer_stalled = True

            runway = preloaded / bitrate if bitrate > 0 else 999
            needed = _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform)

            # Dead
            is_dead = False
            if elapsed > dead_timeout:
                if preloaded == 0 and peers == 0 and not ever_had_bytes: is_dead = True
                elif preloaded == 0 and not ever_had_peers and elapsed > dead_timeout * 1.5: is_dead = True
                elif preloaded == 0 and speed == 0 and elapsed > dead_timeout * 2 and not ever_had_bytes: is_dead = True
            if is_dead: return 'dead'

            # UI
            smb = speed / 1048576.0
            pmb = preloaded / 1048576.0
            ratio = max(avg_speed, peak_speed * 0.7) / bitrate if bitrate > 0 else 0

            sc = 'lime' if smb >= 1 else ('gold' if smb >= 0.3 else 'orangered')
            pc = 'lime' if peers >= 5 else ('gold' if peers >= 1 else 'orangered')

            if preloaded == 0 and peers == 0:
                l1 = "[COLOR dodgerblue]Caut seederi...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed
                l2 = "[COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B][COLOR white] / [/COLOR][COLOR silver]%d[/COLOR]" % (pc, peers, total_peers)
            elif preloaded == 0:
                l1 = "[COLOR dodgerblue]Conectare...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed
                l2 = "[COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B][COLOR white] / [/COLOR][COLOR silver]%d[/COLOR]" % (pc, peers, total_peers)
            else:
                l1 = "[COLOR dodgerblue]Buffer:[/COLOR]  [COLOR white]%.1f MB[/COLOR]  [COLOR grey](%.0fs / %.0fs)[/COLOR]" % (pmb, runway, needed)
                l2 = "[COLOR deepskyblue]Speed:[/COLOR] [B][COLOR %s]%.2f MB/s[/COLOR][/B]   [COLOR white]•[/COLOR]   [COLOR deepskyblue]Seeds:[/COLOR] [B][COLOR %s]%d[/COLOR][/B]" % (sc, smb, pc, peers)

            ui_window.update_status(l1, l2)

            # Start conditions
            can_start = False
            reason = ""
            rok = runway >= needed and preloaded >= absolute_min
            sok = len(recent) >= samples and avg_speed > 0

            if platform['aggressive']:
                if rok and sok:
                    can_start, reason = True, "runway(%.0f/%.0f)" % (runway, needed)
                elif avg_speed > bitrate * 2 and runway >= 1 and preloaded >= absolute_min:
                    can_start, reason = True, "fast(%.1fx)" % ratio
                elif buffer_stalled and preloaded >= absolute_min and runway >= 3:
                    can_start, reason = True, "stalled+%.0fs" % runway
                elif buffer_stalled and preloaded >= 5 * 1024 * 1024:
                    can_start, reason = True, "stalled+%.1fMB" % pmb
                elif elapsed > max_wait and preloaded >= absolute_min:
                    can_start, reason = True, "timeout"
            else:
                if rok and sok:
                    can_start, reason = True, "runway+speed"
                elif runway >= needed * 2 and preloaded >= absolute_min:
                    can_start, reason = True, "double_runway"
                elif buffer_stalled and preloaded >= absolute_min and runway >= 5:
                    can_start, reason = True, "stalled+runway"
                elif buffer_stalled and preloaded >= 8 * 1024 * 1024:
                    can_start, reason = True, "stalled+buffer"
                elif elapsed > max_wait and preloaded >= absolute_min:
                    can_start, reason = True, "timeout"

            # Stabilization
            if can_start:
                if stabilize_start is None:
                    stabilize_start = time.time()
                    stabilize_reason = reason
                    xbmc.log("[MRSP Lite] Stabilizare: %.1fMB, rw=%.0fs, r=%.1fx, p=%d | %s"
                             % (pmb, runway, ratio, peers, reason), xbmc.LOGINFO)
                elif time.time() - stabilize_start >= stabilize_dur:
                    xbmc.log("[MRSP Lite] ▶ START [%s #%d]: %.1fMB, rw=%.0f/%.0fs, "
                             "spd=%.2f(pk %.1f), p=%d, %.0fs | %s"
                             % (platform['name'], attempt, pmb, runway, needed,
                                avg_speed / 1048576.0, peak_speed / 1048576.0,
                                peers, elapsed, stabilize_reason), xbmc.LOGINFO)
                    return 'ok'
            else:
                if stabilize_start is not None:
                    reset = True
                    if buffer_stalled and preloaded >= absolute_min: reset = False
                    elif peak_speed > bitrate * 1.5 and preloaded >= absolute_min: reset = False
                    elif avg_speed > bitrate * 0.5 and preloaded >= absolute_min: reset = False
                    if reset:
                        xbmc.log("[MRSP Lite] Stabilizare RESET", xbmc.LOGINFO)
                        stabilize_start = None

            # Sleep
            if elapsed < 5:    sd = platform['poll_fast']
            elif elapsed < 20: sd = platform['poll_normal']
            else:              sd = platform['poll_slow']
            if _cancel_sleep(ce, sd): return 'cancel'

        return 'cancel'
    except Exception as e:
        xbmc.log("[MRSP Lite] Buffer EXCEPTIE: %s" % str(e), xbmc.LOGERROR)
        return 'error'

# ══════════════════════════════════════════════════════════════
#  FUNCȚIA PRINCIPALĂ — doModal() pe thread principal
# ══════════════════════════════════════════════════════════════

def get_torrserver_url(magnet_uri, item_info):
    if len(magnet_uri) == 40 and not magnet_uri.startswith(('http', 'magnet')):
        magnet_uri = "magnet:?xt=urn:btih:%s" % magnet_uri

    ts = _create_ts()
    platform = get_platform()
    title = item_info.get('Title', 'Torrent Stream')

    _clear_all_window_props()
    xbmc.sleep(50)

    # TMDB
    ct, cy = _best_title_and_year(item_info, magnet_uri)
    tmdb_id = item_info.get('tmdb_id')
    imdb_id = item_info.get('imdb_id') or item_info.get('IMDBNumber')
    fanart, logo = get_tmdb_metadata(tmdb_id=tmdb_id, imdb_id=imdb_id, title=ct, year=cy)

    if not fanart:
        for k in ('Fanart', 'fanart', 'landscape', 'thumb', 'Poster', 'poster'):
            v = item_info.get(k, '')
            if v and v.startswith('http'): fanart = v; break
    if not fanart:
        fanart = "special://home/addons/plugin.video.romanianpack/icon.png"

    poster_for_ts = _sanitize_poster(fanart)

    # Set window properties
    win = xbmcgui.Window(10000)
    win.setProperty('info.fanart', _sanitize_fanart(fanart))
    win.setProperty('info.clearlogo', logo or '')
    win.setProperty('CineboxFileName', title)
    win.setProperty('CineboxBuffering', 'Inițializare motor...')
    win.setProperty('CineboxStatus', 'Vă rugăm așteptați')
    xbmc.sleep(100)

    # Create dialog
    ui_window = CineboxResolver('resolver_window.xml', ADDON.getAddonInfo('path'), 'Default')

    # ╔════════════════════════════════════════════════╗
    # ║  START worker thread + doModal                 ║
    # ║  doModal BLOCHEAZĂ și PRIMEȘTE Back/Escape     ║
    # ║  Worker face buffering-ul pe thread separat    ║
    # ╚════════════════════════════════════════════════╝
    worker = threading.Thread(
        target=_torrserver_worker,
        args=(ts, magnet_uri, item_info, ui_window, platform, title, poster_for_ts))
    worker.daemon = True
    worker.start()

    ui_window.doModal()          # ← BLOCHEAZĂ — Back/Escape funcționează!

    worker.join(timeout=5)       # Așteaptă worker-ul să termine cleanup

    _clear_all_window_props()

    url = ui_window._result_url
    xbmc.log("[MRSP Lite] Rezultat final: %s" % ('URL OK' if url else 'ANULAT/EROARE'), xbmc.LOGINFO)
    return url