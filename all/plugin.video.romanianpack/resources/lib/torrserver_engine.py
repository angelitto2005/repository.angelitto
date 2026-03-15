# -*- coding: utf-8 -*-
# v1.2.33 — fixes: notification pe worker thread, close_window dupa succes,
#            race condition finally/picker, is_file_upload pentru .torrent HTTP
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

def log(msg):
    try:
        from resources.functions import log as central_log
        central_log(msg)
    except:
        pass

# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _cancel_sleep(cancel_event, duration):
    return cancel_event.wait(timeout=duration)

def _async_cleanup(ts, info_hash):
    try: ts.remove_torrent(info_hash)
    except: pass
    try: ts.cleanup_current(xbmcaddon.Addon('plugin.video.romanianpack'))
    except: pass
    log("[MRSP Lite] Async cleanup: %s" % info_hash[:16])

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
            if self._ts: self._ts.cleanup_current(xbmcaddon.Addon('plugin.video.romanianpack'))
            self._is_torrserver = False
        except: pass

_player_monitor = None
def _get_player_monitor():
    global _player_monitor
    if _player_monitor is None: _player_monitor = TorrServerPlayerMonitor()
    return _player_monitor

# ══════════════════════════════════════════════════════════════
#  FEREASTRA CINEBOX
# ══════════════════════════════════════════════════════════════

_WINDOW_PROPS = ['info.fanart', 'info.clearlogo',
                 'CineboxBuffering', 'CineboxStatus', 'CineboxFileName']

def _clear_all_window_props():
    win = xbmcgui.Window(10000)
    for p in _WINDOW_PROPS:
        win.clearProperty(p)


class CineboxResolver(xbmcgui.WindowXMLDialog):
    def __init__(self, strXMLname, strFallbackPath, strDefaultName, forceFallback=True):
        super(CineboxResolver, self).__init__(strXMLname, strFallbackPath, strDefaultName, forceFallback)
        self._cancel_event = threading.Event()
        self._closed = False
        self._result_url = None
        # ── Handoff pentru file picker ──
        self._pick_files = None          # lista de candidati video
        self._pick_info_hash = None      # hash-ul torrentului

    def onInit(self):
        try: self.setFocusId(10)
        except: pass

    def update_status(self, text, subtext="", filename=""):
        if self._cancel_event.is_set(): return
        win = xbmcgui.Window(10000)
        win.setProperty('CineboxBuffering', text)
        if subtext:  win.setProperty('CineboxStatus', subtext)
        if filename: win.setProperty('CineboxFileName', filename)

    def iscanceled(self):
        return self._cancel_event.is_set() or xbmc.Monitor().abortRequested()

    def close_window(self):
        if self._closed: return
        self._closed = True
        self._cancel_event.set()
        try:    self.close()
        except: pass
        _clear_all_window_props()

    def onAction(self, action):
        if action.getId() in _CANCEL_ACTIONS:
            log("[MRSP Lite] ← CANCEL (action %d)" % action.getId())
            self._cancel_event.set()
            self.close_window()

# ══════════════════════════════════════════════════════════════
#  PLATFORMĂ
# ══════════════════════════════════════════════════════════════

def _detect_platform():
    is_android = False
    try: is_android = xbmc.getCondVisibility('System.Platform.Android')
    except:
        if 'android' in sys.platform.lower() or os.path.exists('/storage/emulated'):
            is_android = True
    free = 0
    try: free = int(xbmc.getInfoLabel('System.FreeMemory').replace(' MB', '').replace(',', ''))
    except: pass
    log("[MRSP Lite] Platform: android=%s, ram=%dMB" % (is_android, free))
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
    if p <= 1: return 20
    elif p <= 3: return 12
    elif p <= 5: return 8
    else: return 5

def _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform):
    """Calculeaza runway-ul necesar (secunde de buffer) inainte de start.
    
    Pentru trackere private (viteze mari, putini peers): aggressive=True da startul mai repede.
    Pentru trackere publice (viteze variabile, multi peers): aggressive=False e mai conservator.
    Valori mai mari = mai putine deconectari dar start mai lent.
    """
    if bitrate <= 0: return 5
    ratio = max(avg_speed, peak_speed * 0.7) / bitrate
    if platform['aggressive']:
        # Desktop: start rapid, accept riscul unui mic re-buffer
        if ratio >= 5: b = 2
        elif ratio >= 3: b = 4
        elif ratio >= 2: b = 6
        elif ratio >= 1.5: b = 8
        elif ratio >= 1: b = 12
        elif ratio >= .7: b = 20
        elif ratio >= .4: b = 30
        else: b = 40
    else:
        # Android: mai conservator — mai putine deconectari pe retele mobile
        if ratio >= 5: b = 5
        elif ratio >= 3: b = 8
        elif ratio >= 2: b = 12
        elif ratio >= 1.5: b = 15
        elif ratio >= 1: b = 20
        elif ratio >= .7: b = 30
        elif ratio >= .4: b = 45
        else: b = 60
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
    try: return unquote(urlparse.parse_qs(urlparse.urlparse(uri).query).get('dn', [''])[0]).strip()
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
#  TMDB
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
#  FILE PICKER — pentru season packs
# ══════════════════════════════════════════════════════════════

def _format_file_label(f):
    """Formatează un fișier pentru afișare în picker."""
    path = f.get('path', 'Unknown')
    name = os.path.basename(path)

    # Scoate extensia
    name_no_ext = name.rsplit('.', 1)[0] if '.' in name else name

    # Înlocuiește puncte și underscore cu spații
    display = name_no_ext.replace('.', ' ').replace('_', ' ')

    # Extrage S01E01 dacă există
    ep_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', name)
    if ep_match:
        ep_tag = "S%02dE%02d" % (int(ep_match.group(1)), int(ep_match.group(2)))
    else:
        ep_tag = ""

    # Mărime
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
    """Arată dialog de selecție. Returnează fișierul ales sau None."""
    # Sortează după path (ordine episoade)
    sorted_files = sorted(candidates, key=lambda f: f.get('path', '').lower())

    items = [_format_file_label(f) for f in sorted_files]

    log("[MRSP Lite] File picker: %d fișiere" % len(items))

    idx = xbmcgui.Dialog().select(
        'Alege fișierul / episodul  (%d disponibile)' % len(items),
        items,
        useDetails=False
    )

    if idx < 0:
        log("[MRSP Lite] File picker: ANULAT")
        return None

    chosen = sorted_files[idx]
    log("[MRSP Lite] File picker: ales [%d] %s" % (idx, chosen.get('path', '')[:60]))
    return chosen

# ══════════════════════════════════════════════════════════════
#  BUFFERING LOGIC (folosit de ambele faze)
# ══════════════════════════════════════════════════════════════

def _do_preload(ts, info_hash, file_id, title):
    try: ts.preload_torrent(info_hash, file_id=file_id, title=title)
    except: pass


def _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size, title,
                        ui_window, ce, platform):
    """Preload + buffer + verify. Setează ui_window._result_url la succes."""
    bitrate = _estimate_bitrate(file_size)

    ui_window.update_status("Pregătire fișier...", "", os.path.basename(file_path))

    if ce.is_set(): return

    # Preload
    t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
    t.daemon = True; t.start()

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if ce.is_set(): return

        log("[MRSP Lite] ═══ Buffer #%d/%d ═══" % (attempt, max_attempts))

        result = _wait_for_ready(ts, info_hash, file_id, title, file_path,
                                 file_size, bitrate, ui_window, ce, platform, attempt)

        if result == 'dead':
            log("[MRSP Lite] ✗ TORRENT MORT")
            # FIX: notificarea GUI trebuie pe thread separat — nu pe worker thread
            # (pe Android/AKP, GUI calls de pe non-main thread cauzează "not responding")
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

        # Verify
        ui_window.update_status("[COLOR dodgerblue]Verificare stream...[/COLOR]",
                                "[COLOR silver]Aproape gata...[/COLOR]")

        if ts.verify_stream(info_hash, file_path, file_id, timeout=15):
            log("[MRSP Lite] ✓ Stream VERIFICAT")
            _get_player_monitor().setup(ts, info_hash)
            ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
            # FIX: inchidem dialogul IMEDIAT dupa ce avem URL-ul, nu asteptam finally
            # (dialogul deschis cand Kodi incearca sa porneasca playerul cauzeaza
            #  conflicte de focus UI pe Android - sursa de deconectari)
            ui_window.close_window()
            return

        if ce.is_set(): return

        if attempt < max_attempts:
            t = threading.Thread(target=_do_preload, args=(ts, info_hash, file_id, title))
            t.daemon = True; t.start()
            if _cancel_sleep(ce, 3): return
        else:
            log("[MRSP Lite] ✗ Pornire directa (fara verificare)")
            _get_player_monitor().setup(ts, info_hash)
            ui_window._result_url = ts.get_stream_url(info_hash, file_path, file_id)
            # FIX: idem - inchidem imediat
            ui_window.close_window()
            return

# ══════════════════════════════════════════════════════════════
#  WORKER FAZA 1: add torrent + metadata + file selection/buffer
# ══════════════════════════════════════════════════════════════

_VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.ts', '.m4v', '.webm', '.flv', '.m2ts')
_MIN_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB — sub asta e sample/bonus

def _worker_phase1(ts, magnet_uri, item_info, ui_window, platform, title, poster_for_ts):
    """Faza 1: add torrent, metadata, selectare fișier, buffer."""
    info_hash = None
    ce = ui_window._cancel_event

    try:
        ts.cleanup_tracked_hashes(ADDON)
        if ce.is_set(): return

        # ═══ ADD TORRENT ═══
        is_file_upload = False
        if os.path.exists(magnet_uri) and os.path.isfile(magnet_uri):
            log("[MRSP Lite] Fisier .torrent LOCAL: %s" % magnet_uri)
            info_hash = ts.add_file(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        elif magnet_uri.startswith('magnet:'):
            log("[MRSP Lite] Magnet: %s..." % magnet_uri[:80])
            info_hash = ts.add_magnet_fast(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        elif magnet_uri.lower().endswith('.torrent') or urlparse.urlparse(magnet_uri).path.lower().endswith('.torrent'):
            log("[MRSP Lite] Link .torrent HTTP: %s..." % magnet_uri[:80])
            info_hash = ts.add_magnet(magnet_uri, title=title, poster=poster_for_ts)
            is_file_upload = True
        else:
            log("[MRSP Lite] Link: %s..." % magnet_uri[:80])
            info_hash = ts.add_magnet(magnet_uri, title=title, poster=poster_for_ts)

        if not info_hash:
            log("[MRSP Lite] EROARE: hash!")
            return
        ts.save_hash_to_settings(ADDON, info_hash)
        log("[MRSP Lite] Hash: %s | upload=%s" % (info_hash, is_file_upload))

        if ce.is_set(): return

        # ═══ METADATA ═══
        if not _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
            return

        if ce.is_set(): return

        # ═══ GET FILES ═══
        info = ts.get_torrent_info_api(info_hash) or ts.get_torrent_info(info_hash)
        if not info or not info.get('file_stats'): return

        files = info['file_stats']
        if not files: return

        candidates = [f for f in files
                      if any(f.get('path', '').lower().endswith(e) for e in _VIDEO_EXT)]

        if not candidates:
            candidates = files

        # ═══ FILE SELECTION LOGIC ═══
        significant = [f for f in candidates if f.get('length', 0) > _MIN_VIDEO_SIZE]

        season = item_info.get('Season')
        episode = item_info.get('Episode')

        chosen = None

        # Dacă avem Season+Episode, încercăm auto-match
        if season and episode:
            try:
                patterns = ["s%02de%02d" % (int(season), int(episode)),
                            "%dx%02d" % (int(season), int(episode)),
                            "%dx%d" % (int(season), int(episode))]
                exact = [f for f in candidates
                         if any(p in f.get('path', '').lower() for p in patterns)]
                if exact:
                    chosen = max(exact, key=lambda x: x.get('length', 0))
                    log("[MRSP Lite] Auto-match S%sE%s: %s" % (
                        season, episode, chosen.get('path', '')[:60]))
            except: pass

        # Dacă nu am găsit match și sunt MULTIPLE fișiere → PICKER
        if not chosen and len(significant) > 1:
            log("[MRSP Lite] Multiple fișiere (%d) → handoff la picker" % len(significant))
            ui_window._pick_files = significant
            ui_window._pick_info_hash = info_hash
            ui_window.close_window()
            return          # ← NU face cleanup! Main thread preia controlul

        # Un singur fișier sau doar samples → auto-select cel mai mare
        if not chosen:
            chosen = max(candidates, key=lambda x: x.get('length', 0))

        # ═══ BUFFER FIȘIERUL ALES ═══
        file_id = chosen.get('id', 1)
        file_path = chosen.get('path', '')
        file_size = chosen.get('length', 0)

        log("[MRSP Lite] Fisier: [id=%s] %s (%d MB) | Total: %d" % (
            file_id, file_path, file_size // (1024 * 1024), len(files)))

        if 'bdmv' in file_path.lower() or len(files) > 50:
            log("[MRSP Lite] ⚠ BDMV: file_id=%s din %d" % (file_id, len(files)))

        _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size,
                            title, ui_window, ce, platform)

    except Exception as e:
        log("[MRSP Lite] Worker EXCEPTIE: %s" % str(e))
    finally:
        # Cleanup DOAR dacă NU am URL și NU facem handoff la picker
        if ui_window._result_url is None and ui_window._pick_files is None:
            if info_hash:
                t = threading.Thread(target=_async_cleanup, args=(ts, info_hash))
                t.daemon = True; t.start()
        # FIX: close_window() are garda interna (_closed), deci apelul dublu e sigur.
        # Dar il apelam oricum ca safety net — _do_buffer_and_play il cheama deja la succes.
        ui_window.close_window()

# ══════════════════════════════════════════════════════════════
#  WORKER FAZA 2: buffer fișierul ales din picker
# ══════════════════════════════════════════════════════════════

def _worker_phase2(ts, info_hash, chosen, title, ui_window, platform):
    """Faza 2: buffer + verify un fișier specific ales de user."""
    ce = ui_window._cancel_event
    try:
        file_id = chosen.get('id', 1)
        file_path = chosen.get('path', '')
        file_size = chosen.get('length', 0)

        log("[MRSP Lite] Faza 2: [id=%s] %s (%d MB)" % (
            file_id, file_path, file_size // (1024 * 1024)))

        _do_buffer_and_play(ts, info_hash, file_id, file_path, file_size,
                            title, ui_window, ce, platform)

    except Exception as e:
        log("[MRSP Lite] Worker2 EXCEPTIE: %s" % str(e))
    finally:
        if ui_window._result_url is None:
            t = threading.Thread(target=_async_cleanup, args=(ts, info_hash))
            t.daemon = True; t.start()
        ui_window.close_window()

# ══════════════════════════════════════════════════════════════
#  METADATA
# ══════════════════════════════════════════════════════════════

def _wait_for_metadata(ts, info_hash, ui_window, ce, is_file_upload, platform):
    if is_file_upload:
        for _ in range(5):
            if ce.is_set(): return False
            info = ts.get_torrent_info_api(info_hash)
            if info and info.get('file_stats'):
                log("[MRSP Lite] ✓ Metadata INSTANT")
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
                log("[MRSP Lite] ✓ Metadata OK (%.1fs)" % elapsed)
                return True

        ui_window.update_status(
            "[COLOR dodgerblue]Descarcă metadate...[/COLOR]  [COLOR grey](%.0fs)[/COLOR]" % elapsed)

        if elapsed < 5:    sd = platform['poll_fast']
        elif elapsed < 15: sd = platform['poll_normal']
        else:              sd = platform['poll_slow']
        if _cancel_sleep(ce, sd): return False

    return False

# ══════════════════════════════════════════════════════════════
#  BUFFERING
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
                    log("[MRSP Lite] STALLED: %.1fMB (t=%ds, p=%d)" % (
                        preloaded / 1048576.0, cst, peers))
                buffer_stalled = True

            runway = preloaded / bitrate if bitrate > 0 else 999
            needed = _dynamic_runway(avg_speed, peak_speed, bitrate, peers, platform)

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
                if rok and sok: can_start, reason = True, "runway(%.0f/%.0f)" % (runway, needed)
                elif avg_speed > bitrate * 2 and runway >= 1 and preloaded >= absolute_min: can_start, reason = True, "fast"
                elif buffer_stalled and preloaded >= absolute_min and runway >= 3: can_start, reason = True, "stalled+rw"
                elif buffer_stalled and preloaded >= 5 * 1024 * 1024: can_start, reason = True, "stalled+buf"
                elif elapsed > max_wait and preloaded >= absolute_min: can_start, reason = True, "timeout"
            else:
                if rok and sok: can_start, reason = True, "runway+speed"
                elif runway >= needed * 2 and preloaded >= absolute_min: can_start, reason = True, "double_rw"
                elif buffer_stalled and preloaded >= absolute_min and runway >= 5: can_start, reason = True, "stalled+rw"
                elif buffer_stalled and preloaded >= 8 * 1024 * 1024: can_start, reason = True, "stalled+buf"
                elif elapsed > max_wait and preloaded >= absolute_min: can_start, reason = True, "timeout"

            if can_start:
                if stabilize_start is None:
                    stabilize_start = time.time()
                    stabilize_reason = reason
                    log("[MRSP Lite] Stabilizare: %.1fMB, rw=%.0fs, r=%.1fx, p=%d | %s"
                             % (pmb, runway, ratio, peers, reason))
                elif time.time() - stabilize_start >= stabilize_dur:
                    log("[MRSP Lite] ▶ START [%s #%d]: %.1fMB, rw=%.0f/%.0fs, "
                             "spd=%.2f(pk %.1f), p=%d, %.0fs | %s"
                             % (platform['name'], attempt, pmb, runway, needed,
                                avg_speed / 1048576.0, peak_speed / 1048576.0,
                                peers, elapsed, stabilize_reason))
                    return 'ok'
            else:
                if stabilize_start is not None:
                    reset = True
                    if buffer_stalled and preloaded >= absolute_min: reset = False
                    elif peak_speed > bitrate * 1.5 and preloaded >= absolute_min: reset = False
                    elif avg_speed > bitrate * 0.5 and preloaded >= absolute_min: reset = False
                    if reset: stabilize_start = None

            if elapsed < 5:    sd = platform['poll_fast']
            elif elapsed < 20: sd = platform['poll_normal']
            else:              sd = platform['poll_slow']
            if _cancel_sleep(ce, sd): return 'cancel'

        return 'cancel'
    except Exception as e:
        log("[MRSP Lite] Buffer EXCEPTIE: %s" % str(e))
        return 'error'

# ══════════════════════════════════════════════════════════════
#  FUNCȚIA PRINCIPALĂ — 2 FAZE cu file picker
# ══════════════════════════════════════════════════════════════

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
        ct, cy = _best_title_and_year(item_info, magnet_uri)
        tmdb_id = item_info.get('tmdb_id')
        imdb_id = item_info.get('imdb_id') or item_info.get('IMDBNumber')
        fanart, logo_api = get_tmdb_metadata(tmdb_id=tmdb_id, imdb_id=imdb_id, title=ct, year=cy)
        if not logo: logo = logo_api
    
    if not fanart or not str(fanart).startswith('http'):
        fanart = "special://home/addons/plugin.video.romanianpack/icon.png"

    poster_for_ts = _sanitize_poster(fanart)
    fanart_prop = _sanitize_fanart(fanart)
    logo_prop = logo or ''
    
    def _setup_window_props():
        win = xbmcgui.Window(10000)
        win.setProperty('info.fanart', fanart_prop)
        win.setProperty('info.clearlogo', logo_prop)
        win.setProperty('CineboxFileName', title)
        win.setProperty('CineboxBuffering', 'Inițializare motor...')
        win.setProperty('CineboxStatus', 'Vă rugăm așteptați')

    _setup_window_props()
    xbmc.sleep(100)

    ui1 = CineboxResolver('resolver_window.xml', ADDON.getAddonInfo('path'), 'Default')

    worker1 = threading.Thread(
        target=_worker_phase1,
        args=(ts, magnet_uri, item_info, ui1, platform, title, poster_for_ts))
    worker1.daemon = True
    worker1.start()

    ui1.doModal()
    worker1.join(timeout=5)
    _clear_all_window_props()

    final_url = None
    chosen_file_path = None

    if ui1._result_url:
        log("[MRSP Lite] Faza 1: URL OK")
        final_url = ui1._result_url
        chosen_file_path = "direct"

    if ui1._pick_files and ui1._pick_info_hash:
        log("[MRSP Lite] File picker: %d candidați" % len(ui1._pick_files))

        chosen = _show_file_picker(ui1._pick_files)

        if not chosen:
            log("[MRSP Lite] File picker: anulat → cleanup")
            t = threading.Thread(target=_async_cleanup, args=(ts, ui1._pick_info_hash))
            t.daemon = True; t.start()
            return None

        log("[MRSP Lite] Faza 2: buffer '%s'" % os.path.basename(chosen.get('path', '')))
        chosen_file_path = chosen.get('path', '')

        _setup_window_props()
        xbmc.sleep(100)

        ui2 = CineboxResolver('resolver_window.xml', ADDON.getAddonInfo('path'), 'Default')

        worker2 = threading.Thread(
            target=_worker_phase2,
            args=(ts, ui1._pick_info_hash, chosen, title, ui2, platform))
        worker2.daemon = True
        worker2.start()

        ui2.doModal()
        worker2.join(timeout=5)
        _clear_all_window_props()

        if ui2._result_url:
            log("[MRSP Lite] Faza 2: URL OK")
            final_url = ui2._result_url

    # -------------------------------------------------------------
    # GENERARE ID DE RESUME CONSISTENT CU MRSPSERVICE
    # -------------------------------------------------------------
    if final_url:
        t_id = item_info.get('tmdb_id')
        i_id = item_info.get('imdb_id') or item_info.get('IMDBNumber')
        s_val = item_info.get('Season') or item_info.get('season')
        e_val = item_info.get('Episode') or item_info.get('episode')

        # Dacă a ales un fișier din picker, extragem S##E## din calea lui
        if chosen_file_path and chosen_file_path != "direct":
            m_ep = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', chosen_file_path)
            if m_ep:
                s_val = m_ep.group(1)
                e_val = m_ep.group(2)

        # Auto-lookup dacă lipsesc ID-urile
        if not t_id and not i_id:
            _lookup_fname = ''
            # Încercăm din chosen_file_path
            if chosen_file_path and chosen_file_path != "direct":
                _lookup_fname = os.path.basename(chosen_file_path)
            # Dacă e "direct" (un singur fișier), luăm din URL-ul final
            if not _lookup_fname and final_url:
                try:
                    from urllib.parse import unquote as _uq
                except:
                    from urllib import unquote as _uq
                _clean = _uq(final_url.split('?')[0])
                _lookup_fname = _clean.rsplit('/', 1)[-1] if '/' in _clean else ''
            
            if _lookup_fname and len(_lookup_fname) > 5:
                try:
                    from resources.lib import PTN
                    from resources.functions import get_show_ids_from_tmdb, get_movie_ids_from_tmdb
                    parsed = PTN.parse(_lookup_fname.replace('.', ' '))
                    lookup_title = parsed.get('title', '')
                    lookup_year = parsed.get('year')
                    is_show = bool(parsed.get('season') or re.search(r'(?i)S\d+', _lookup_fname))
                    log('[MRSP-RESUME] TorrServer auto-lookup: "%s" year=%s show=%s' % (lookup_title, lookup_year, is_show))
                    if lookup_title and len(lookup_title) > 2:
                        if is_show:
                            api_tmdb, api_imdb = get_show_ids_from_tmdb(lookup_title)
                        else:
                            api_tmdb, api_imdb = get_movie_ids_from_tmdb(lookup_title, lookup_year)
                        if api_tmdb: t_id = str(api_tmdb)
                        if api_imdb: i_id = str(api_imdb)
                        if t_id or i_id:
                            log('[MRSP-RESUME] TorrServer auto-lookup SUCCES: tmdb=%s, imdb=%s' % (t_id, i_id))
                            item_info['tmdb_id'] = t_id
                            item_info['imdb_id'] = i_id
                except Exception as e:
                    log('[MRSP-RESUME] TorrServer auto-lookup eroare: %s' % str(e))

        
        # Construim base
        base_val = ""
        if i_id: base_val = "imdb_%s" % i_id
        elif t_id: base_val = "tmdb_%s" % t_id
        
        # Construim sufixul (identic cu mrspservice)
        file_suffix = ""
        if s_val and e_val:
            try: file_suffix = "_S%02dE%02d" % (int(s_val), int(e_val))
            except: file_suffix = "_S%sE%s" % (s_val, e_val)
        elif chosen_file_path and chosen_file_path != "direct":
            # Fișiere fără S##E## (concerte) - file hash
            import hashlib as hl
            fname = os.path.basename(chosen_file_path)
            if fname and len(fname) > 5:
                fhash = hl.md5(fname.encode('utf-8', 'ignore')).hexdigest()[:8]
                file_suffix = "_F%s" % fhash
        
        if not file_suffix:
            file_suffix = "_movie"

        # ID final
        if base_val:
            link_to_check = base_val + file_suffix
        else:
            # Fallback pe hash torrent
            btih_match = re.search(r'btih:([a-zA-Z0-9]+)', magnet_uri, re.I)
            if btih_match:
                link_to_check = 'hash_%s%s' % (btih_match.group(1).lower(), file_suffix)
            elif 'id=' in magnet_uri:
                id_match = re.search(r'id=(\d+)', magnet_uri)
                if id_match:
                    link_to_check = 'filelist_%s%s' % (id_match.group(1), file_suffix)
                else:
                    link_to_check = magnet_uri + file_suffix
            else:
                md5_match = re.search(r'([a-f0-9]{32})\.torrent', magnet_uri)
                if md5_match:
                    link_to_check = 'local_%s%s' % (md5_match.group(1), file_suffix)
                else:
                    link_to_check = magnet_uri

        link_to_check = link_to_check.replace('\\', '/').strip()
        log('[MRSP-RESUME] TorrServer Resume ID: %s' % link_to_check)
        
        # Salvăm în pb_data și item_info
        try:
            import json
            home_window = xbmcgui.Window(10000)
            existing_pb = home_window.getProperty('mrsp.playback.info')
            pb_data = json.loads(existing_pb) if existing_pb else {}
            
            pb_data['mrsp_resume_id'] = link_to_check
            if s_val: pb_data['season'] = s_val
            if e_val: pb_data['episode'] = e_val
            
            item_info['mrsp_resume_id'] = link_to_check
            
            home_window.setProperty('mrsp.playback.info', json.dumps(pb_data))
            log('[MRSP-RESUME] ID Salvat: %s' % link_to_check)
        except: pass
        
        # Facem dialogul de Resume chiar aici, inainte sa dea inapoi URL-ul catre player
        try:
            from resources.functions import get_resume_time
            
            resume_time, total_time = get_resume_time(link_to_check)
            seek_to = 0
            
            if resume_time > 0 and total_time > 0:
                pct = (resume_time / total_time) * 100
                if 1 < pct < 95:
                    import datetime
                    time_str = str(datetime.timedelta(seconds=int(resume_time)))
                    dialog = xbmcgui.Dialog()
                    ret = dialog.contextmenu(['Reluare de la %s' % time_str, 'De la început'])
                    
                    if ret == 0:
                        seek_to = resume_time
                    elif ret == -1:
                        return None 
            
            if seek_to > 0:
                def seek_after_start(target):
                    p = xbmc.Player()
                    for _ in range(120): 
                        if p.isPlayingVideo() and p.getTotalTime() > 0:
                            xbmc.sleep(2000)
                            try: p.seekTime(float(target))
                            except: pass
                            break
                        if xbmc.Monitor().abortRequested(): break
                        xbmc.sleep(500)
                        
                t_resume = threading.Thread(target=seek_after_start, args=(seek_to,))
                t_resume.daemon = True
                t_resume.start()
        except Exception as e:
            log('[MRSP-RESUME] Eroare la trigger dialog resume: %s' % str(e))
            
        return final_url

    log("[MRSP Lite] Rezultat: ANULAT/EROARE")
    return None


