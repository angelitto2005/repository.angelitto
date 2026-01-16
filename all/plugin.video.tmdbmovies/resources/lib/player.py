import os
import sys
import xbmc
import xbmcgui
import xbmcplugin
import threading
import time
import requests
import urllib.parse
import json
from resources.lib.config import get_headers, BASE_URL, API_KEY, IMG_BASE, HANDLE, ADDON
from resources.lib.utils import log, get_json, extract_details, get_language, clean_text
from resources.lib.scraper import get_external_ids, get_stream_data
from resources.lib.tmdb_api import set_metadata
from resources.lib.trakt_api import mark_as_watched_internal
from resources.lib import subtitles
from resources.lib import trakt_sync
from resources.lib.cache import MainCache
from resources.lib.subtitles import run_wyzie_service

LANG = get_language()

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# =============================================================================
# CONFIGURĂRI PLAYER - MODIFICĂ AICI
# =============================================================================
PLAYER_CHECK_TIMEOUT = 10  # Secunde pentru verificare sursă (mărește dacă surse mari)
PLAYER_AUDIO_CHECK_ONLY_SD = True  # True = verifică audio-only doar pe SD/720p, False = verifică toate
PLAYER_KEEP_DUPLICATES = True  # True = păstrează surse duplicate, False = elimină duplicate
# =============================================================================
_active_player = None

def check_url_validity(url, headers=None, max_timeout=None):
    """Verifică DOAR dacă URL-ul este accesibil. RAPID cu timeout forțat."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT  # <-- Folosește constanta globală
    
    if not url:
        return False
    
    result = {'valid': False, 'done': False}
    
    def _check():
        try:
            clean_url = url.split('|')[0]
            
            if not clean_url.startswith(('http://', 'https://')):
                result['done'] = True
                return
            
            clean_url_lower = clean_url.lower()
            
            bad_domains = [
                'googleusercontent.com',
                'googlevideo.com', 
                'video-leech.pro',
                'video-seed.pro',
                'video-downloads.googleusercontent.com'
            ]
            
            for bad in bad_domains:
                if bad in clean_url_lower:
                    log(f"[PLAYER-CHECK] Bad domain ({bad}) - SKIP")
                    result['done'] = True
                    return
            
            custom_headers = headers if headers else {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            # Timeout intern = jumătate din max_timeout
            internal_timeout = max(1.5, max_timeout / 2)
            
            try:
                r = requests.head(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True)
                
                final_url = r.url.lower() if r.url else ''
                for bad in bad_domains:
                    if bad in final_url:
                        log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
                        result['done'] = True
                        return
                
                if r.status_code < 400:
                    result['valid'] = True
                    result['done'] = True
                    return
                    
                if r.status_code in [405, 403]:
                    r2 = requests.get(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True, stream=True)
                    final_url2 = r2.url.lower() if r2.url else ''
                    r2.close()
                    
                    for bad in bad_domains:
                        if bad in final_url2:
                            log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
                            result['done'] = True
                            return
                    
                    if r2.status_code < 400:
                        result['valid'] = True
                        result['done'] = True
                        return
                
                log(f"[PLAYER-CHECK] FAIL ({r.status_code})")
                result['done'] = True
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, 
                    requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                log(f"[PLAYER-CHECK] Network error: {type(e).__name__}")
                result['done'] = True
            except Exception as e:
                log(f"[PLAYER-CHECK] Eroare: {type(e).__name__}")
                result['done'] = True

        except Exception as e:
            log(f"[PLAYER-CHECK] Outer error: {type(e).__name__}")
            result['done'] = True
    
    thread = threading.Thread(target=_check)
    thread.daemon = True
    thread.start()
    thread.join(timeout=max_timeout)
    
    if not result['done']:
        log(f"[PLAYER-CHECK] TIMEOUT FORȚAT ({max_timeout}s) - SKIP")
        return False
    
    return result['valid']


def check_sooti_audio_only(url, headers=None, max_timeout=None):
    """Verifică dacă sursa Sooti este audio-only. Returnează True dacă e AUDIO (adică invalidă)."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT  # <-- Folosește constanta globală
    
    result = {'is_audio': False, 'done': False}
    
    def _check():
        try:
            clean_url = url.split('|')[0]
            custom_headers = headers if headers else {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            internal_timeout = max(1.5, max_timeout / 2)
            
            r = requests.get(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True)
            
            if r.status_code >= 400:
                result['is_audio'] = True
                result['done'] = True
                return
            
            content_str = r.text[:4096]
            content_lower = content_str.lower()
            
            if '#extm3u' not in content_lower:
                result['done'] = True
                return
            
            if 'type=audio' in content_lower and 'type=video' not in content_lower:
                log(f"[SOOTI-CHECK] Audio-only (type=audio)")
                result['is_audio'] = True
                result['done'] = True
                return
            
            if 'codecs=' in content_lower:
                has_video_codec = any(x in content_lower for x in ['avc', 'hvc', 'hevc', 'vp9', 'av01'])
                has_audio_only = 'mp4a' in content_lower and not has_video_codec
                
                if has_audio_only:
                    log(f"[SOOTI-CHECK] Audio-only (codec)")
                    result['is_audio'] = True
                    result['done'] = True
                    return
            
            if '#ext-x-stream-inf' in content_lower and 'resolution=' not in content_lower:
                log(f"[SOOTI-CHECK] Audio-only (no resolution)")
                result['is_audio'] = True
                result['done'] = True
                return
            
            result['done'] = True
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            log(f"[SOOTI-CHECK] Network error: {type(e).__name__}")
            result['is_audio'] = True
            result['done'] = True
        except Exception as e:
            log(f"[SOOTI-CHECK] Error: {type(e).__name__}")
            result['is_audio'] = True
            result['done'] = True
    
    thread = threading.Thread(target=_check)
    thread.daemon = True
    thread.start()
    thread.join(timeout=max_timeout)
    
    if not result['done']:
        log(f"[SOOTI-CHECK] TIMEOUT FORȚAT ({max_timeout}s) - SKIP")
        return True
    
    return result['is_audio']


# =============================================================================
# SISTEM CACHE RAM COMPLET
# =============================================================================
def get_window():
    return xbmcgui.Window(10000)


def get_search_id(tmdb_id, content_type, season=None, episode=None):
    if content_type == 'movie':
        return f"movie_{tmdb_id}"
    else:
        return f"tv_{tmdb_id}_s{season}_e{episode}"


def save_sources_to_ram(streams, tmdb_id, content_type, season=None, episode=None):
    try:
        window = get_window()
        search_id = get_search_id(tmdb_id, content_type, season, episode)
        window.setProperty('tmdbmovies.src_id', search_id)
        window.setProperty('tmdbmovies.src_data', json.dumps(streams))
        log(f"[RAM-SRC] Salvat {len(streams)} surse pentru: {search_id}")
    except Exception as e:
        log(f"[RAM-SRC] Eroare salvare: {e}", xbmc.LOGERROR)


def load_sources_from_ram(tmdb_id, content_type, season=None, episode=None):
    try:
        window = get_window()
        current_id = get_search_id(tmdb_id, content_type, season, episode)
        cached_id = window.getProperty('tmdbmovies.src_id')
        
        if current_id == cached_id:
            data = window.getProperty('tmdbmovies.src_data')
            if data:
                streams = json.loads(data)
                if streams and len(streams) > 0:
                    log(f"[RAM-SRC] Încărcat {len(streams)} surse din cache")
                    return streams
    except Exception as e:
        log(f"[RAM-SRC] Eroare citire: {e}", xbmc.LOGERROR)
    return None


def clear_sources_cache():
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.src_id')
        window.clearProperty('tmdbmovies.src_data')
        log("[RAM-SRC] Cache curățat complet")
    except Exception as e:
        log(f"[RAM-SRC] Eroare cleanup: {e}", xbmc.LOGERROR)


def save_return_path():
    try:
        window = get_window()
        window.setProperty('tmdbmovies.need_fast_return', 'true')
        log("[RAM-NAV] Marcat pentru întoarcere rapidă")
    except Exception as e:
        log(f"[RAM-NAV] Eroare: {e}", xbmc.LOGERROR)


def check_fast_return():
    try:
        window = get_window()
        need_return = window.getProperty('tmdbmovies.need_fast_return')
        if need_return == 'true':
            window.clearProperty('tmdbmovies.need_fast_return')
            return True
    except:
        pass
    return False


def clear_fast_return():
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.need_fast_return')
    except:
        pass


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def get_poster_url(tmdb_id, content_type, season=None):
    poster_url = "DefaultVideo.png"
    
    cached_poster = trakt_sync.get_poster_from_db(tmdb_id, content_type)
    if cached_poster and cached_poster.startswith('http'):
        return cached_poster

    try:
        found_poster = None
        
        if content_type == 'tv' and season:
            try:
                meta_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}"
                data = get_json(meta_url)
                if data and data.get('poster_path'):
                    found_poster = IMG_BASE + data.get('poster_path')
            except: 
                pass
            
        if not found_poster:
            endpoint = 'movie' if content_type == 'movie' else 'tv'
            meta_url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
            data = get_json(meta_url)
            if data and data.get('poster_path'):
                found_poster = IMG_BASE + data.get('poster_path')
        
        if found_poster:
            poster_url = found_poster
            trakt_sync.set_poster_to_db(tmdb_id, content_type, poster_url)

    except Exception as e:
        log(f"[PLAYER] Poster Error: {e}", xbmc.LOGWARNING)
    
    return poster_url


def build_display_items(streams, poster_url):
    from resources.lib.utils import extract_details, clean_text
    
    display_items = []
    for idx, s in enumerate(streams, 1):
        raw_n = s.get('name', '')
        raw_t = s.get('title', '')
        
        clean_n = clean_text(raw_n)
        clean_t = clean_text(raw_t)
        
        sz, prov, quality = extract_details(clean_t, clean_n)
        
        c_qual = "FF00BFFF"
        if quality == "4K": 
            c_qual = "FF00FFFF"
        elif quality == "1080p": 
            c_qual = "FF00FF7F"
        elif quality == "720p": 
            c_qual = "FFFFD700"

        full_info = (raw_n + raw_t).lower()
        tags = []
        if 'dolby vision' in full_info or '.dv.' in full_info: 
            tags.append("[COLOR FFDA70D6]DV[/COLOR]")
        if 'hdr' in full_info: 
            tags.append("[COLOR FFADFF2F]HDR[/COLOR]")
        if 'remux' in full_info: 
            tags.append("[B][COLOR FFFF0000]REMUX[/COLOR][/B]")
        
        tags_str = " ".join(tags)
        
        label = f"[B][COLOR FFFFFFFF]{idx:02d}.[/COLOR][/B]  [B][COLOR {c_qual}]{quality}[/COLOR][/B] • [COLOR FFFF69B4]{prov}[/COLOR] • [COLOR FFFFA500]{sz}[/COLOR] {tags_str}"
        
        li = xbmcgui.ListItem(label=label)
        li.setLabel2(clean_t if clean_t else clean_n)
        li.setArt({'icon': poster_url, 'thumb': poster_url})
        display_items.append(li)
    return display_items


def sort_streams_by_quality(streams):
    from resources.lib.utils import extract_details
    import re

    def get_sort_key(s):
        _, _, quality = extract_details(s.get('title', ''), s.get('name', ''))
        
        if quality == "4K": 
            q_score = 3
        elif quality == "1080p": 
            q_score = 2
        elif quality == "720p": 
            q_score = 1
        else: 
            q_score = 0
            
        size_mb = 0.0
        text = (s.get('name', '') + " " + s.get('title', '')).lower()
        match = re.search(r'(\d+(?:\.\d+)?)\s*(gb|gib|mb|mib)', text)
        if match:
            val = float(match.group(1))
            unit = match.group(2)
            size_mb = val * 1024 if 'g' in unit else val
        
        return (q_score, size_mb)

    streams.sort(key=get_sort_key, reverse=True)
    return streams


def is_link_playable(url):
    try:
        clean_url = url.split('|')[0]
        r = requests.head(clean_url, headers=get_headers(), timeout=3, allow_redirects=True, verify=False)
        
        if r.status_code in [200, 206]:
            return True
        elif r.status_code in [405, 403]: 
            r2 = requests.get(clean_url, headers=get_headers(), stream=True, timeout=3, verify=False)
            r2.close()
            if r2.status_code in [200, 206]:
                return True
                
        log(f"[PLAYER-CHECK] Link Dead ({r.status_code}): {clean_url}")
    except Exception as e:
        log(f"[PLAYER-CHECK] Error checking link: {e}")
        
    return False


def handle_resume_dialog(title):
    try:
        if len(sys.argv) > 3:
            resume_arg = sys.argv[3] if len(sys.argv) > 3 else ''
            if 'resume:false' in resume_arg:
                return False
            elif 'resume:true' in resume_arg:
                return True
    except:
        pass
    
    return False


# =============================================================================
# GET ENGLISH METADATA
# =============================================================================
def get_english_metadata(tmdb_id, content_type, season=None, episode=None):
    eng_title = ""
    eng_tvshowtitle = ""
    found_imdb_id = ""
    show_parent_imdb_id = ""
    
    try:
        if content_type == 'movie':
            url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data = get_json(url)
            eng_title = data.get('title', '')
            found_imdb_id = data.get('imdb_id') or data.get('external_ids', {}).get('imdb_id', '')
        else:
            url_show = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data_show = get_json(url_show)
            eng_tvshowtitle = data_show.get('name', '')
            show_parent_imdb_id = data_show.get('external_ids', {}).get('imdb_id', '')
            
            if season and episode:
                url_ep = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
                data_ep = get_json(url_ep)
                eng_title = data_ep.get('name', '')
                ep_imdb = data_ep.get('external_ids', {}).get('imdb_id')
                if ep_imdb:
                    found_imdb_id = ep_imdb
                else:
                    if not found_imdb_id: 
                        found_imdb_id = show_parent_imdb_id

    except Exception as e:
        log(f"[PLAYER] Error fetching metadata: {e}", xbmc.LOGERROR)
        
    return eng_title, eng_tvshowtitle, found_imdb_id, show_parent_imdb_id


def get_filename_from_url(url, stream_title=''):
    try:
        if stream_title and len(stream_title) > 5 and '.' in stream_title:
            return stream_title
        
        clean = url.split('|')[0].split('?')[0]
        filename = urllib.parse.unquote(clean.split('/')[-1])
        return filename
    except:
        return ""


# =============================================================================
# CLASA PLAYER + MONITOR THREAD
# =============================================================================
_active_player = None
_player_monitor = None

class TMDbPlayer(xbmc.Player):
    def __init__(self, tmdb_id, content_type, season=None, episode=None, title='', year=''):
        super().__init__()
        self.tmdb_id = str(tmdb_id)
        self.content_type = content_type
        
        try: 
            self.season = int(season) if season else None
        except: 
            self.season = None
            
        try: 
            self.episode = int(episode) if episode else None
        except: 
            self.episode = None
        
        self.title = title
        self.year = str(year)
        
        self.playback_started = False
        self.watched_marked = False
        self.playback_start_time = 0
        self.last_progress_sent = 0
        self.scrobble_threshold = 5.0
        
        # ============================================================
        # Variabile pentru a păstra ULTIMA poziție cunoscută
        # (actualizate în fiecare iterație a monitorului)
        # ============================================================
        self.last_known_position = 0
        self.last_known_total = 0

    def onAVStarted(self):
        log("[PLAYER-CLASS] onAVStarted: Stream is playing stable.")
        self.playback_started = True
        self.playback_start_time = time.time()
        
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        def close_error_dialogs():
            for _ in range(30):
                xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
                xbmc.sleep(100)
        threading.Thread(target=close_error_dialogs, daemon=True).start()
        
        self._send_trakt_scrobble('start', 0)

    def onPlayBackStopped(self):
        log(f"[PLAYER-CLASS] onPlayBackStopped called")
        # Nu facem nimic aici - monitorul se ocupă

    def onPlayBackEnded(self):
        log("[PLAYER-CLASS] onPlayBackEnded called")
        self.watched_marked = True
        # Nu facem nimic aici - monitorul se ocupă

    def _send_trakt_scrobble(self, action, progress):
        try:
            from resources.lib.trakt_api import send_trakt_scrobble
            send_trakt_scrobble(action, self.tmdb_id, self.content_type, self.season, self.episode, progress)
        except: 
            pass


def start_playback_monitor(player_instance):
    """Monitor thread care verifică periodic și salvează la oprire."""
    global _player_monitor
    
    if _player_monitor and _player_monitor.is_alive():
        return
    
    def monitor_loop():
        log("[PLAYER-MONITOR] Monitor thread started")
        
        # Așteptăm să pornească playerul
        for _ in range(30):
            if player_instance.isPlaying():
                break
            xbmc.sleep(500)
        else:
            log("[PLAYER-MONITOR] Player did not start, exiting monitor")
            return
        
        log("[PLAYER-MONITOR] Player is playing, monitoring...")
        player_instance.playback_start_time = time.time()
        
        # ============================================================
        # Salvăm PROCENTUL (nu poziția) - sincronizat cu Trakt
        # ============================================================
        last_known_progress = 0
        last_known_position = 0
        last_known_total = 0
        
        while player_instance.isPlaying():
            try:
                curr = player_instance.getTime()
                total = player_instance.getTotalTime()
                
                # ============================================================
                # Salvează PROCENTUL la fiecare iterație
                # ============================================================
                if curr > 0 and total > 0:
                    last_known_position = curr
                    last_known_total = total
                    last_known_progress = (curr / total) * 100
                # ============================================================
                
                # Scrobble periodic la Trakt
                if total > 0 and curr > 300:
                    progress = (curr / total) * 100
                    
                    if not player_instance.watched_marked and progress >= 85:
                        log(f"[PLAYER-MONITOR] 85% reached. Will mark on stop.")
                        player_instance.watched_marked = True
                    
                    if abs(progress - player_instance.last_progress_sent) >= player_instance.scrobble_threshold:
                        player_instance._send_trakt_scrobble('scrobble', progress)
                        player_instance.last_progress_sent = progress
                
                # ============================================================
                # ELIMINAT: Detecția stall-ului care oprea playerul în timpul buffering
                # Kodi are propria sa detecție pentru stream-uri moarte
                # ============================================================
                        
            except Exception as e:
                log(f"[PLAYER-MONITOR] Loop error: {e}")
            
            xbmc.sleep(250)
        
        # ============================================================
        # PLAYERUL S-A OPRIT - Salvăm PROCENTUL
        # ============================================================
        log("[PLAYER-MONITOR] Player stopped, saving progress...")
        
        if last_known_progress <= 0 or last_known_total <= 0:
            log(f"[PLAYER-MONITOR] No valid progress saved, skipping")
            return
        
        mins = int(last_known_position) // 60
        secs = int(last_known_position) % 60
        log(f"[PLAYER-MONITOR] ✓ Final: {mins}m {secs}s ({last_known_progress:.2f}%)")
        
        # ============================================================
        # SALVARE
        # ============================================================
        watched_duration = 0
        if player_instance.playback_start_time > 0:
            watched_duration = time.time() - player_instance.playback_start_time
        
        log(f"[PLAYER-MONITOR] Watched duration: {int(watched_duration)}s")
        
        try:
            if player_instance.watched_marked or last_known_progress >= 85:
                log(f"[PLAYER-MONITOR] Marking as WATCHED ({last_known_progress:.2f}%)")
                
                trakt_sync.mark_as_watched_internal(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    notify=True, sync_trakt=True
                )
                
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    100, player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('stop', 100)
                
            elif watched_duration > 180:  # 3 minute
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    last_known_progress,
                    player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('stop', last_known_progress)
                
                log(f"[PLAYER-MONITOR] ✓ Resume saved: {last_known_progress:.2f}%")
                
            else:
                log(f"[PLAYER-MONITOR] Watched <3min ({int(watched_duration)}s). Resume NOT saved.")
                
        except Exception as e:
            log(f"[PLAYER-MONITOR] Error saving progress: {e}", xbmc.LOGERROR)
        
        log("[PLAYER-MONITOR] Monitor thread finished")
    
    _player_monitor = threading.Thread(target=monitor_loop, daemon=True)
    _player_monitor.start()


def is_sd_or_720p(stream):
    """Verifică dacă sursa este SD sau 720p (sub 1080p)."""
    full_info = (stream.get('name', '') + stream.get('title', '')).lower()
    
    # Dacă are 1080p sau 4K, NU e SD/720p
    if '1080' in full_info or '2160' in full_info or '4k' in full_info:
        return False
    
    # Dacă are 720p sau rezoluție mai mică, E SD/720p
    if '720' in full_info or '480' in full_info or '360' in full_info:
        return True
    
    # Dacă nu are nicio rezoluție specificată, considerăm SD
    has_quality = any(x in full_info for x in ['1080', '720', '480', '360', '2160', '4k'])
    if not has_quality:
        return True  # Fără calitate = probabil SD
    
    return False

# =============================================================================
# PLAY WITH ROLLOVER - VERSIUNE FINALĂ (FĂRĂ BUFFERING DUPLICAT)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties, resume_time=0, from_resolve=False):
    
    log("[PLAYER] === PLAY_WITH_ROLLOVER START ===")
    
    xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
    xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()
    xbmc.executebuiltin('Playlist.Clear')
    
    if not from_resolve:
        try:
            current_handle = int(sys.argv[1])
            xbmcplugin.setResolvedUrl(current_handle, False, xbmcgui.ListItem())
        except:
            pass
    
    if xbmc.Player().isPlaying():
        xbmc.Player().stop()
        xbmc.sleep(300)

    total_streams = len(streams)
    log(f"[PLAYER] Total surse: {total_streams}")
    
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Initializare...")
    
    p_title = info_tag.get('title', 'Unknown')
    p_year = info_tag.get('year', '')

    from resources.lib.utils import clean_text
    
    bad_domains = [
        'googleusercontent.com',
        'googlevideo.com',
        'video-leech.pro',
        'video-seed.pro',
    ]
    
    valid_url = None
    valid_index = -1

    for i in range(start_index, total_streams):
        try:
            stream = streams[i]
            url = stream.get('url', '')
            
            if not url or url.startswith('plugin://') or not url.startswith(('http://', 'https://')):
                continue
            
            base_url_check = url.split('|')[0].lower()
            is_bad = False
            for bad in bad_domains:
                if bad in base_url_check:
                    log(f"[PLAYER] Sursa {i+1} - Bad domain ({bad}) SKIP")
                    is_bad = True
                    break
            if is_bad:
                continue
            
            log(f"[PLAYER] === SURSA {i+1}/{total_streams} ===")
            
            raw_name = stream.get('name', '').lower()
            provider_id = stream.get('provider_id', '').lower()
            url_lower = url.lower()
            
            is_sooti = 'sooti' in raw_name or 'sooti' in provider_id or 'sooti' in url_lower
            
            if is_sooti:
                log(f"[PLAYER] Provider: SOOTI")
            
            raw_n = stream.get('name', 'Unknown')
            raw_t = stream.get('title', '')
            full_info = (raw_n + raw_t).lower()
            clean_name_display = clean_text(raw_n).replace('\n', ' ')[:50]
            
            c_qual = "FF00BFFF"
            qual_txt = "SD"
            if '2160' in full_info or '4k' in full_info:
                qual_txt = "4K"
                c_qual = "FF00FFFF"
            elif '1080' in full_info:
                qual_txt = "1080p"
                c_qual = "FF00FF7F"
            elif '720' in full_info:
                qual_txt = "720p"
                c_qual = "FFFFD700"
                
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{clean_name_display}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            p_dialog.update(int(((i - start_index + 1) / max(1, total_streams - start_index)) * 100), message=msg)
            
            # Verificare validitate
            try:
                base_url = url.split('|')[0]
                
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try:
                        check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except:
                        pass
                
                is_valid = check_url_validity(base_url, headers=check_headers)
                
                # ============================================================
                # Verificare Sooti audio-only DOAR pentru SD/720p
                # ============================================================
                if is_valid and is_sooti:
                    if PLAYER_AUDIO_CHECK_ONLY_SD:
                        # Verifică DOAR dacă e SD/720p
                        if is_sd_or_720p(stream):
                            log(f"[PLAYER] Sooti SD/720p - verific audio-only")
                            if check_sooti_audio_only(base_url, headers=check_headers):
                                is_valid = False
                        else:
                            log(f"[PLAYER] Sooti 1080p+ - SKIP audio check")
                    else:
                        # Verifică toate (setare veche)
                        if check_sooti_audio_only(base_url, headers=check_headers):
                            is_valid = False
                # ============================================================
                
                log(f"[PLAYER] Verificare: {is_valid}")
                
            except Exception as e:
                log(f"[PLAYER] Eroare verificare: {e}")
                is_valid = False
            
            if is_valid:
                valid_url = url
                valid_index = i
                log(f"[PLAYER] ✓ SURSĂ VALIDĂ: {i+1}")
                break
            else:
                log(f"[PLAYER] ✗ Sursa {i+1} respinsă")
                continue
                
        except Exception as e:
            log(f"[PLAYER] Eroare sursa {i+1}: {e}", xbmc.LOGERROR)
            continue
    
    p_dialog.close()
    
    if valid_url:
        log(f"[PLAYER] === PORNIRE REDARE SURSA {valid_index + 1} ===")
        
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        # ============================================================
        # PĂSTRĂM REFERINȚA LA PLAYER GLOBAL (pentru callback-uri!)
        # ============================================================
        global _active_player
        # ============================================================
        
        # ============================================================
        # THREAD PERMANENT (Cât timp merge playerul)
        # ============================================================
        stop_cleaner = threading.Event()
        
        def playlist_cleaner():
            log("[PLAYER] Cleaner thread pornit")
            
            # Așteptăm să pornească playerul
            for _ in range(20):
                if xbmc.Player().isPlaying():
                    break
                xbmc.sleep(500)
                
            # Ciclăm cât timp playerul merge SAU până trec 30 secunde
            # Dacă playerul se oprește, oprim și cleaner-ul
            start_time = time.time()
            while not stop_cleaner.is_set():
                # Verificăm dacă playerul s-a oprit
                if not xbmc.Player().isPlaying() and (time.time() - start_time > 5):
                    log("[PLAYER] Player oprit, opresc cleaner")
                    break
                
                # Curățăm și închidem
                xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
                
                if xbmc.getCondVisibility('Window.IsVisible(okdialog)'):
                    xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                    
                if xbmc.getCondVisibility('Window.IsVisible(progressdialog)'):
                    xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                
                xbmc.sleep(500)
                
            log("[PLAYER] Cleaner thread oprit")
        
        cleaner_thread = threading.Thread(target=playlist_cleaner, daemon=True)
        cleaner_thread.start()
        # ============================================================
        
        # ============================================================
        # SALVĂM REFERINȚA GLOBAL (altfel se pierde și callback-urile nu merg!)
        # ============================================================
        global _active_player
        _active_player = TMDbPlayer(tmdb_id, c_type, season, episode, title=p_title, year=str(p_year))
        player = _active_player
        
        li = xbmcgui.ListItem(label=info_tag['title'], path=valid_url)
        li.setInfo('video', info_tag)
        if unique_ids:
            li.setUniqueIDs(unique_ids)
        if art:
            li.setArt(art)
        for k, v in properties.items():
            li.setProperty(k, str(v))
        
        player.play(valid_url, li)
        
        xbmc.executebuiltin('Dialog.Close(busydialog)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        log(f"[PLAYER] player.play() OK")
        
        # ============================================================
        # PORNEȘTE MONITORUL CARE SALVEAZĂ PROGRESUL
        # ============================================================
        start_playback_monitor(player)
        # ============================================================
        
        if resume_time > 0:
            def do_resume():
                log(f"[PLAYER] Resume requested: {resume_time} seconds")
                
                # 1. Așteptăm să pornească playerul
                for _ in range(30):
                    if player.isPlaying():
                        break
                    xbmc.sleep(500)
                else:
                    log("[PLAYER] Player did not start, cancelling resume")
                    return
                
                # 2. Așteptăm încă 3 secunde pentru HLS/stream-uri
                log("[PLAYER] Player started, waiting 3s for stream to stabilize...")
                xbmc.sleep(3000)
                
                # 3. Încercăm seek de 5 ori
                target_pos = float(resume_time)
                for attempt in range(5):
                    if not player.isPlaying():
                        log("[PLAYER] Player stopped, cancelling resume")
                        return
                    
                    try:
                        current_pos = player.getTime()
                        
                        # Dacă suntem deja aproape de target (±30s), e OK
                        if abs(current_pos - target_pos) < 30:
                            log(f"[PLAYER] Already at correct position: {int(current_pos)}s")
                            return
                        
                        log(f"[PLAYER] Seek attempt {attempt+1}: {int(current_pos)}s -> {int(target_pos)}s")
                        player.seekTime(target_pos)
                        
                        # Așteptăm 2 secunde pentru seek
                        xbmc.sleep(2000)
                        
                        # Verificăm dacă a funcționat
                        new_pos = player.getTime()
                        if abs(new_pos - target_pos) < 60:  # Toleranță 1 minut
                            log(f"[PLAYER] Seek SUCCESS! Position: {int(new_pos)}s")
                            return
                        else:
                            log(f"[PLAYER] Seek failed, got {int(new_pos)}s instead of {int(target_pos)}s")
                            
                    except Exception as e:
                        log(f"[PLAYER] Seek error: {e}")
                    
                    xbmc.sleep(1000)
                
                log("[PLAYER] All seek attempts failed")
                    
            threading.Thread(target=do_resume, daemon=True).start()
        
        if unique_ids.get('imdb'):
            threading.Thread(target=subtitles.run_wyzie_service, args=(unique_ids['imdb'], season, episode)).start()
            
        # Oprim manual cleaner-ul când funcția se termină (deși e daemon)
        # Dar el va rula în background cât timp playerul merge datorită logicii interne
            
    else:
        log(f"[PLAYER] FAIL - Nicio sursă validă din {total_streams}")
        xbmcgui.Dialog().notification("TMDb Movies", "Nicio sursă nu a putut fi redată", TMDbmovies_ICON)
    
    log("[PLAYER] === END ===")

# =============================================================================
# LIST SOURCES - VERSIUNE CORECTATĂ
# =============================================================================
def list_sources(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    
    ids = {}
    
    # ============================================================
    # CITIM PROCENTUL DIN DB și calculăm poziția din runtime
    # ============================================================
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
    
    resume_time = 0
    
    if progress_value > 0 and progress_value < 95:
        log(f"[LIST-SOURCES] Progress from DB: {progress_value:.2f}%")
        
        # Obținem runtime-ul pentru a calcula poziția
        duration_secs = 0
        try:
            if c_type == 'movie':
                url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                runtime = data.get('runtime', 0) if data else 0
                if runtime:
                    duration_secs = int(runtime) * 60
            else:
                url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                if data:
                    runtimes = data.get('episode_run_time', [])
                    if runtimes:
                        duration_secs = int(runtimes[0]) * 60
                    else:
                        duration_secs = 2700  # 45 min default pentru seriale
        except Exception as e:
            log(f"[LIST-SOURCES] Error getting runtime: {e}")
        
        if duration_secs <= 0:
            duration_secs = 7200  # 2 ore default
        
        resume_time = int((progress_value / 100.0) * duration_secs)
        log(f"[LIST-SOURCES] Calculated resume: {resume_time}s ({resume_time//60}m {resume_time%60}s) from {progress_value:.2f}% of {duration_secs}s")
    
    elif progress_value >= 1000000:
        # Format vechi cu marker (pentru backwards compatibility)
        resume_time = int(progress_value - 1000000)
        log(f"[LIST-SOURCES] Legacy position from DB: {resume_time}s")
    # ============================================================

    # Meniu resume
    if resume_time > 180:
        m, s = divmod(resume_time, 60)
        h, m = divmod(m, 60)
        if h > 0: 
            time_str = f"{h}h {m}m"
        else: 
            time_str = f"{m}m {s}s"
        
        log(f"[LIST-SOURCES] Showing resume dialog for {resume_time} seconds")
        
        choice = xbmcgui.Dialog().contextmenu([f"Resume from {time_str}", "Play from beginning"])
        if choice == 1: 
            resume_time = 0
        elif choice == -1:
            try:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except:
                pass
            return

    # --- 2. CAUTARE / CACHE ---
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: 
        cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: 
        cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': 
        search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: 
        scanned_providers_history = []
    if failed_providers_history is None: 
        failed_providers_history = []

    streams = []
    providers_to_scan = [] 
    
    if cached_streams is not None:
        log(f"[SMART-CACHE] Found {len(cached_streams)} cached streams.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: 
                    s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: 
                    s_pid = 'nuvio'
                elif 'vix' in raw_name: 
                    s_pid = 'vixsrc'
                elif 'sooti' in raw_name: 
                    s_pid = 'sooti'
                elif 'vega' in raw_name: 
                    s_pid = 'vega'
                elif 'vidzee' in raw_name: 
                    s_pid = 'vidzee'
                elif 'rogflix' in raw_name: 
                    s_pid = 'rogflix'
                elif 'streamvix' in raw_name: 
                    s_pid = 'streamvix'
            
            if s_pid and s_pid not in active_providers:
                continue 
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id')
        if not imdb_id: 
            imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if not p_dialog.iscanceled():
                msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
                p_dialog.update(percent, msg)

        target_list = providers_to_scan if cached_streams is not None else None
        
        # Filtrare finală: doar provideri activi
        if target_list:
            final_target = [p for p in target_list if p in active_providers]
        else:
            final_target = active_providers  # <-- CRUCIAL!

        new_streams, new_failed = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target  # <-- Folosește lista filtrată
        )
        
        p_dialog.close()
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
                
        final_failed = new_failed

        if cached_streams is not None:
            if PLAYER_KEEP_DUPLICATES:
                # Păstrează TOATE sursele (chiar dacă sunt duplicate)
                streams.extend(new_streams)
                log(f"[SMART-CACHE] Adăugate {len(new_streams)} surse noi (cu duplicate)")
            else:
                # Elimină duplicatele (comportament vechi)
                existing_urls = set(s['url'].split('|')[0] for s in streams)
                for ns in new_streams:
                    clean_url = ns['url'].split('|')[0]
                    if clean_url not in existing_urls:
                        streams.append(ns)
        else:
            streams = new_streams
            
        if streams or final_scanned: 
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)

    if not streams:
        xbmcgui.Dialog().notification("TMDb Movies", "Nu s-au găsit surse", TMDbmovies_ICON)
        try:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except:
            pass
        return

    # --- 4. AFIȘARE ---
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    dlg_title = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if cached_streams is not None: 
        dlg_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        # Preluare metadate
        eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
        
        if not ids: 
            try: 
                ids = get_external_ids(c_type, tmdb_id)
            except: 
                ids = {}

        final_imdb_id = None
        if c_type == 'tv':
            final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else ids.get('imdb_id')
        else:
            final_imdb_id = extra_imdb_id if extra_imdb_id else ids.get('imdb_id')

        final_title = eng_title if eng_title else title
        final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
        
        properties = {'tmdb_id': str(tmdb_id)}
        if final_imdb_id:
            if c_type == 'tv': 
                properties['tvshow.imdb_id'] = final_imdb_id
            properties['imdb_id'] = final_imdb_id
            properties['ImdbNumber'] = final_imdb_id

        info_tag = {
            'title': final_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0
        }
        if final_imdb_id: 
            info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: 
                info_tag['season'] = int(season)
            if episode: 
                info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id: 
            unique_ids['imdb'] = final_imdb_id
            
        # Pornește playerul - play_with_rollover se ocupă de setResolvedUrl
        play_with_rollover(
            streams, ret, tmdb_id, c_type, season, episode,
            info_tag, unique_ids, {'poster': poster_url}, properties, resume_time
        )
        
        if final_imdb_id:
            threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode)).start()
            
    else:
        # User cancelled dialog
        try:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except:
            pass


# =============================================================================
# RESOLVE DIALOG - VERSIUNE CORECTATĂ
# =============================================================================
def tmdb_resolve_dialog(params):
    """
    Funcție pentru TMDbHelper - rezolvă și redă direct.
    """
    
    log("[RESOLVE] === TMDB_RESOLVE_DIALOG START ===")
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title', '')
    year = params.get('year', '')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = params.get('imdb_id')
    
    log(f"[RESOLVE] TMDb ID: {tmdb_id}, Type: {c_type}, Title: {title}")
    
    # =========================================================================
    # DEFINIRE BAD DOMAINS
    # =========================================================================
    bad_domains = [
        'googleusercontent.com',
        'googlevideo.com',
        'video-leech.pro',
        'video-seed.pro',
    ]
    
    # =========================================================================
    # 1. VERIFICĂM SMART CACHE ÎNTÂI
    # =========================================================================
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid != "nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try:
        cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except:
        cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv':
        search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None:
        scanned_providers_history = []
    if failed_providers_history is None:
        failed_providers_history = []

    streams = []
    providers_to_scan = []
    from_cache = False
    
    if cached_streams is not None:
        log(f"[RESOLVE] [SMART-CACHE] Found {len(cached_streams)} cached streams.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name:
                    s_pid = 'webstreamr'
                elif 'nuvio' in raw_name:
                    s_pid = 'nuvio'
                elif 'vix' in raw_name:
                    s_pid = 'vixsrc'
                elif 'sooti' in raw_name:
                    s_pid = 'sooti'
                elif 'vega' in raw_name:
                    s_pid = 'vega'
                elif 'vidzee' in raw_name:
                    s_pid = 'vidzee'
                elif 'rogflix' in raw_name:
                    s_pid = 'rogflix'
                elif 'streamvix' in raw_name:
                    s_pid = 'streamvix'
            
            if s_pid and s_pid not in active_providers:
                continue
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        from_cache = True
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    # =========================================================================
    # 2. CĂUTARE NET
    # =========================================================================
    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")
        
        if not imdb_id:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        
        if not imdb_id:
            imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if not p_dialog.iscanceled():
                msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
                p_dialog.update(percent, msg)

        target_list = providers_to_scan if cached_streams is not None else None
        
        # Filtrare finală: doar provideri activi
        if target_list:
            final_target = [p for p in target_list if p in active_providers]
        else:
            final_target = active_providers  # <-- CRUCIAL!

        new_streams, new_failed = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target  # <-- Folosește lista filtrată
        )
        
        p_dialog.close()
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
        
        final_failed = new_failed

        if cached_streams is not None:
            if PLAYER_KEEP_DUPLICATES:
                # Păstrează TOATE sursele (chiar dacă sunt duplicate)
                streams.extend(new_streams)
                log(f"[SMART-CACHE] Adăugate {len(new_streams)} surse noi (cu duplicate)")
            else:
                # Elimină duplicatele (comportament vechi)
                existing_urls = set(s['url'].split('|')[0] for s in streams)
                for ns in new_streams:
                    clean_url = ns['url'].split('|')[0]
                    if clean_url not in existing_urls:
                        streams.append(ns)
        else:
            streams = new_streams
        
        if streams or final_scanned:
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)
    
    # =========================================================================
    # 3. VERIFICĂM DACĂ AVEM SURSE
    # =========================================================================
    if not streams:
        log("[RESOLVE] Nicio sursă găsită")
        xbmcgui.Dialog().notification("TMDb Movies", "Nu s-au găsit surse", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 4. AFIȘARE DIALOG CU SURSE
    # =========================================================================
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    dlg_title = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if from_cache:
        dlg_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret < 0:
        log("[RESOLVE] User cancelled")
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 5. GĂSEȘTE PRIMA SURSĂ VALIDĂ (cu verificare) - CU MESAJE FRUMOASE
    # =========================================================================
    from resources.lib.utils import clean_text
    
    selected_url = None
    total_streams = len(streams)
    
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Inițializare...")
    
    try:  # <-- IMPORTANT: Try-finally pentru a asigura închiderea dialogului
        for i in range(ret, total_streams):
            stream = streams[i]
            url = stream.get('url', '')
            
            if not url or not url.startswith(('http://', 'https://')):
                continue
            
            # Verificare domenii rele
            base_url_check = url.split('|')[0].lower()
            is_bad = False
            for bad in bad_domains:
                if bad in base_url_check:
                    is_bad = True
                    break
            if is_bad:
                continue
            
            # ============================================================
            # MESAJ FRUMOS CU CULORI
            # ============================================================
            raw_n = stream.get('name', 'Unknown')
            raw_t = stream.get('title', '')
            full_info = (raw_n + raw_t).lower()
            clean_name_display = clean_text(raw_n).replace('\n', ' ')[:50]
            
            c_qual = "FF00BFFF"
            qual_txt = "SD"
            if '2160' in full_info or '4k' in full_info:
                qual_txt = "4K"
                c_qual = "FF00FFFF"
            elif '1080' in full_info:
                qual_txt = "1080p"
                c_qual = "FF00FF7F"
            elif '720' in full_info:
                qual_txt = "720p"
                c_qual = "FFFFD700"
                
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{clean_name_display}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            p_dialog.update(int(((i - ret + 1) / max(1, total_streams - ret)) * 100), message=msg)
            # ============================================================
            
            # Verificare validitate
            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try:
                        check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except:
                        pass
                
                is_valid = check_url_validity(base_url, headers=check_headers)
                
                # Verificare Sooti audio-only DOAR pentru SD/720p
                raw_name = stream.get('name', '').lower()
                provider_id = stream.get('provider_id', '').lower()
                is_sooti = 'sooti' in raw_name or 'sooti' in provider_id or 'sooti' in url.lower()
                
                if is_valid and is_sooti:
                    if PLAYER_AUDIO_CHECK_ONLY_SD:
                        if is_sd_or_720p(stream):
                            log(f"[RESOLVE] Sooti SD/720p - verific audio-only")
                            if check_sooti_audio_only(base_url, headers=check_headers):
                                is_valid = False
                        else:
                            log(f"[RESOLVE] Sooti 1080p+ - SKIP audio check")
                    else:
                        if check_sooti_audio_only(base_url, headers=check_headers):
                            is_valid = False
                
                if is_valid:
                    selected_url = url
                    log(f"[RESOLVE] Sursă validă găsită: {i+1}/{total_streams}")
                    break
            except Exception as e:
                log(f"[RESOLVE] Eroare verificare sursa {i+1}: {e}")
                continue
    
    finally:  # <-- ASIGURĂ ÎNCHIDEREA DIALOGULUI ÎNTOTDEAUNA
        p_dialog.close()
    
    if not selected_url:
        log("[RESOLVE] Nicio sursă validă")
        xbmcgui.Dialog().notification("TMDb Movies", "Nicio sursă validă", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 6. CONSTRUIEȘTE LISTITEM ȘI RETURNEAZĂ PRIN setResolvedUrl
    # =========================================================================
    eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
    
    if not imdb_id:
        try:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        except:
            pass

    final_imdb_id = None
    if c_type == 'tv':
        final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else imdb_id
    else:
        final_imdb_id = extra_imdb_id if extra_imdb_id else imdb_id

    final_title = eng_title if eng_title else title
    final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
    
    properties = {'tmdb_id': str(tmdb_id)}
    if final_imdb_id:
        if c_type == 'tv':
            properties['tvshow.imdb_id'] = final_imdb_id
        properties['imdb_id'] = final_imdb_id
        properties['ImdbNumber'] = final_imdb_id

    info_tag = {
        'title': final_title,
        'mediatype': 'movie' if c_type == 'movie' else 'episode',
        'year': int(year) if year else 0
    }
    if final_imdb_id:
        info_tag['imdbnumber'] = final_imdb_id
    if c_type == 'tv':
        info_tag['tvshowtitle'] = final_show_title
        if season:
            info_tag['season'] = int(season)
        if episode:
            info_tag['episode'] = int(episode)

    unique_ids = {'tmdb': str(tmdb_id)}
    if final_imdb_id:
        unique_ids['imdb'] = final_imdb_id
    
    art = {'poster': poster_url, 'thumb': poster_url}
    
    # Construiește ListItem final
    li = xbmcgui.ListItem(label=final_title, path=selected_url)
    li.setInfo('video', info_tag)
    li.setUniqueIDs(unique_ids)
    li.setArt(art)
    for k, v in properties.items():
        li.setProperty(k, str(v))
    
    # =========================================================================
    # RETURNEAZĂ URL-UL REZOLVAT CĂTRE TMDb Helper
    # =========================================================================
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    log("[RESOLVE] setResolvedUrl(True) trimis cu succes")
    
    # Pornește subtitle service în background
    if final_imdb_id:
        threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode), daemon=True).start()
    
    log("[RESOLVE] === END ===")