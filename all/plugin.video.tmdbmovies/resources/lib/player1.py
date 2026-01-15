import os
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
from resources.lib import trakt_sync # Added import
from resources.lib.cache import MainCache
from resources.lib.subtitles import run_wyzie_service

LANG = get_language()

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

def check_url_validity(url, headers=None):
    try:
        clean_url = url.split('|')[0]
        custom_headers = headers if headers else get_headers()
        
        # Timeout foarte scurt (3 secunde) pentru verificare
        # Daca serverul nu raspunde in 3 secunde la un simplu HEAD/GET, nu are rost sa incercam redarea
        try:
            # Încercăm HEAD întâi (foarte rapid)
            r = requests.head(clean_url, headers=custom_headers, timeout=3, verify=False, allow_redirects=True)
            if r.status_code < 400:
                return True
        except:
            pass # Fallback la GET

        # Fallback la GET cu stream=True (doar primii bytes)
        with requests.get(clean_url, headers=custom_headers, stream=True, timeout=3, verify=False, allow_redirects=True) as r:
            
            # Respingem clar erorile
            if r.status_code >= 400: 
                log(f"[PLAYER-CHECK] Resping sursa moartă: {clean_url} ({r.status_code})")
                return False
            
            # Verificăm conținutul
            chunk = next(r.iter_content(chunk_size=512), b'')
            content_str = chunk.decode('utf-8', errors='ignore')
            ctype = r.headers.get('Content-Type', '').lower()
            
            # Validăm tipul
            if '#EXTM3U' in content_str: return True
            if 'video' in ctype or 'application/octet-stream' in ctype: return True
            
            # Respingem HTML/Text (pagini de eroare, captchas, "File not found")
            if 'text' in ctype or 'html' in ctype: 
                log(f"[PLAYER-CHECK] Resping sursa HTML (Fake video): {clean_url}")
                return False
            
            return True

    except Exception as e:
        log(f"[PLAYER-CHECK] Sursa inaccesibilă (Timeout/Eroare): {e}")
        return False

# =============================================================================
# SISTEM CACHE RAM COMPLET
# =============================================================================
def get_window():
    return xbmcgui.Window(10000)


# -----------------------------------------------------------------------------
# CACHE PENTRU SURSE
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# CACHE CLEANUP
# -----------------------------------------------------------------------------
def clear_sources_cache():
    """Curăță complet cache-ul de surse din RAM."""
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.src_id')
        window.clearProperty('tmdbmovies.src_data')
        log("[RAM-SRC] Cache curățat complet")
    except Exception as e:
        log(f"[RAM-SRC] Eroare cleanup: {e}", xbmc.LOGERROR)

# -----------------------------------------------------------------------------
# CACHE PENTRU LISTA ANTERIOARĂ (pentru întoarcere rapidă)
# -----------------------------------------------------------------------------
def save_return_path():
    """Salvează calea curentă pentru întoarcere rapidă."""
    try:
        window = get_window()
        # Marcăm că am intrat în surse și vrem întoarcere rapidă
        window.setProperty('tmdbmovies.need_fast_return', 'true')
        log("[RAM-NAV] Marcat pentru întoarcere rapidă")
    except Exception as e:
        log(f"[RAM-NAV] Eroare: {e}", xbmc.LOGERROR)


def check_fast_return():
    """Verifică dacă trebuie să facem întoarcere rapidă."""
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
    """Curăță flag-ul de întoarcere rapidă."""
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
    
    # 1. Verificăm cache local
    cached_poster = trakt_sync.get_poster_from_db(tmdb_id, content_type)
    if cached_poster and cached_poster.startswith('http'):
        return cached_poster

    try:
        # 2. Logică Fallback
        found_poster = None
        
        # Dacă e Sezon/Episod, încercăm întâi posterul de sezon
        if content_type == 'tv' and season:
            try:
                meta_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}"
                data = get_json(meta_url)
                if data and data.get('poster_path'):
                    found_poster = IMG_BASE + data.get('poster_path')
            except: pass
            
        # 3. Dacă nu am găsit (sau e film), luăm posterul principal (Film sau Serial)
        if not found_poster:
            endpoint = 'movie' if content_type == 'movie' else 'tv'
            meta_url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
            data = get_json(meta_url)
            if data and data.get('poster_path'):
                found_poster = IMG_BASE + data.get('poster_path')
        
        if found_poster:
            poster_url = found_poster
            # Salvăm în cache pentru data viitoare
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
        
        # Curățăm complet textele pentru afișare
        clean_n = clean_text(raw_n)
        clean_t = clean_text(raw_t)
        
        # Extragem detaliile tot din textul curat
        sz, prov, quality = extract_details(clean_t, clean_n)
        
        c_qual = "FF00BFFF"
        if quality == "4K": c_qual = "FF00FFFF"
        elif quality == "1080p": c_qual = "FF00FF7F"
        elif quality == "720p": c_qual = "FFFFD700"

        # Etichete extra (HDR, DV etc) - căutăm în textul original (lower)
        full_info = (raw_n + raw_t).lower()
        tags = []
        if 'dolby vision' in full_info or '.dv.' in full_info: tags.append("[COLOR FFDA70D6]DV[/COLOR]")
        if 'hdr' in full_info: tags.append("[COLOR FFADFF2F]HDR[/COLOR]")
        if 'remux' in full_info: tags.append("[B][COLOR FFFF0000]REMUX[/COLOR][/B]")
        
        tags_str = " ".join(tags)
        
        # Label principal (folosește 'prov' care e deja curățat de extract_details)
        label = f"[B][COLOR FFFFFFFF]{idx:02d}.[/COLOR][/B]  [B][COLOR {c_qual}]{quality}[/COLOR][/B] • [COLOR FFFF69B4]{prov}[/COLOR] • [COLOR FFFFA500]{sz}[/COLOR] {tags_str}"
        
        li = xbmcgui.ListItem(label=label)
        
        # AICI ERA PROBLEMA: Label2 afișa textul brut cu pătrățele
        # Acum afișăm textul curățat
        li.setLabel2(clean_t if clean_t else clean_n)
        
        li.setArt({'icon': poster_url, 'thumb': poster_url})
        display_items.append(li)
    return display_items


def sort_streams_by_quality(streams):
    from resources.lib.utils import extract_details
    import re

    def get_sort_key(s):
        # Folosim funcția centralizată pentru consistență
        _, _, quality = extract_details(s.get('title', ''), s.get('name', ''))
        
        # Scor Calitate
        if quality == "4K": q_score = 3
        elif quality == "1080p": q_score = 2
        elif quality == "720p": q_score = 1
        else: q_score = 0
            
        # Scor Mărime (MB)
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
    """
    Verifică rapid dacă link-ul răspunde cu 200 OK (HEAD request).
    Evită eroarea 'Playback failed' din Kodi.
    """
    try:
        # Extragem doar URL-ul curat, fără header-ele speciale Kodi (|User-Agent...)
        clean_url = url.split('|')[0]
        
        # Facem un request HEAD rapid (doar antetul, nu descarcă fișierul)
        # Timeout scurt (3 secunde)
        r = requests.head(clean_url, headers=get_headers(), timeout=3, allow_redirects=True, verify=False)
        
        # Dacă primim 200 (OK) sau 206 (Partial Content - specific streaming), e bun
        if r.status_code in [200, 206]:
            return True
        # Unele servere nu suportă HEAD, încercăm GET cu stream=True doar pentru primul byte
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
    """
    Verifică dacă există o poziție salvată și întreabă utilizatorul.
    Returnează True dacă vrea să continue, False dacă vrea de la început.
    Returnează None dacă nu există poziție salvată.
    """
    try:
        # Verificăm dacă parametrul resume:true/false a fost trimis
        if len(sys.argv) > 3:
            resume_arg = sys.argv[3] if len(sys.argv) > 3 else ''
            if 'resume:false' in resume_arg:
                return False  # Pornește de la început
            elif 'resume:true' in resume_arg:
                return True   # Continuă de unde a rămas
    except:
        pass
    
    # Dacă nu e specificat, întotdeauna de la început (pentru surse noi)
    return False

# =============================================================================
# FUNCȚIA PRINCIPALĂ - LIST_SOURCES
# =============================================================================
def get_english_metadata(tmdb_id, content_type, season=None, episode=None):
    """
    Funcție care aduce titlurile în ENGLEZĂ și ID-urile pentru Player.
    Returnează: (eng_title, eng_tvshowtitle, found_imdb_id, show_parent_imdb_id)
    """
    eng_title = ""
    eng_tvshowtitle = ""
    found_imdb_id = ""         # ID-ul itemului redat (film sau episod)
    show_parent_imdb_id = ""   # ID-ul serialului (doar pt TV)
    
    try:
        if content_type == 'movie':
            url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data = get_json(url)
            eng_title = data.get('title', '')
            found_imdb_id = data.get('imdb_id') or data.get('external_ids', {}).get('imdb_id', '')
        else:
            # 1. Numele Serialului și ID-ul Părinte
            url_show = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data_show = get_json(url_show)
            eng_tvshowtitle = data_show.get('name', '')
            show_parent_imdb_id = data_show.get('external_ids', {}).get('imdb_id', '')
            
            # 2. Numele Episodului și ID-ul Episodului
            if season and episode:
                url_ep = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
                data_ep = get_json(url_ep)
                eng_title = data_ep.get('name', '')
                ep_imdb = data_ep.get('external_ids', {}).get('imdb_id')
                if ep_imdb:
                    found_imdb_id = ep_imdb
                else:
                    # Dacă episodul nu are IMDb ID propriu, uneori se folosește cel al serialului
                    if not found_imdb_id: 
                        found_imdb_id = show_parent_imdb_id

    except Exception as e:
        log(f"[PLAYER] Error fetching metadata: {e}", xbmc.LOGERROR)
        
    return eng_title, eng_tvshowtitle, found_imdb_id, show_parent_imdb_id

def get_filename_from_url(url, stream_title=''):
    """
    Extrage numele fișierului pentru a ajuta addon-urile de subtitrări.
    Prioritizează titlul sursei (dacă există), apoi URL-ul.
    """
    try:
        # Dacă scraperul a dat un titlu bun (ex: Movie.Year.1080p.mkv), îl folosim pe ăla
        if stream_title and len(stream_title) > 5 and '.' in stream_title:
            return stream_title
        
        # Altfel, extragem din URL
        clean = url.split('|')[0].split('?')[0]
        filename = urllib.parse.unquote(clean.split('/')[-1])
        return filename
    except:
        return ""

# =============================================================================
# CLASA PLAYER (SAFEGUARDS: 5 MIN & RESUME PROTECTION)
# =============================================================================
class TMDbPlayer(xbmc.Player):
    def __init__(self, tmdb_id, content_type, season=None, episode=None, title='', year=''):
        super().__init__()
        self.tmdb_id = str(tmdb_id)
        self.content_type = content_type
        
        try: self.season = int(season) if season else None
        except: self.season = None
            
        try: self.episode = int(episode) if episode else None
        except: self.episode = None
        
        self.title = title
        self.year = str(year)
        
        self.playback_started = False
        self.watched_marked = False
        self.monitor_thread = None
        self.stop_monitor = False
        self.last_progress_sent = 0
        self.scrobble_threshold = 5.0

    def onAVStarted(self):
        log("[PLAYER-CLASS] onAVStarted: Stream is playing stable.")
        self.playback_started = True
        
        # Trimitem START doar ca să apărem în "Now Watching" pe Trakt.
        # Acest status expiră singur dacă nu trimitem STOP.
        self._send_trakt_scrobble('start', 0)
        
        self.stop_monitor = False
        self.monitor_thread = threading.Thread(target=self._progress_monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def onPlayBackStopped(self):
        self.stop_monitor = True
        log(f"[PLAYER-CLASS] Playback Stopped. ID: {self.tmdb_id}")
        
        if not self.watched_marked:
            try:
                curr = self.getTime()
                total = self.getTotalTime()
                
                # Safeguard 1: Durată video validă (> 5 min)
                if total > 300: 
                    progress = (curr / total) * 100
                    
                    # Safeguard 2: Condiția de 5 minute (300 secunde)
                    # Dacă ai văzut sub 5 minute (și nu ai terminat filmul), IGNORĂM TOT.
                    # Nu trimitem stop 0, nu ștergem resume local. Lăsăm totul așa cum era înainte de play.
                    if curr > 300 or progress >= 85:
                        
                        # A. Trimitem la Trakt
                        self._send_trakt_scrobble('stop', progress)
                        
                        # B. Salvăm LOCAL
                        log(f"[PLAYER-CLASS] Saving local progress: {progress:.2f}% (Watched > 5min)")
                        
                        # Dacă e >= 85%, salvăm 100% ca să dispară din In Progress
                        save_progress = progress if progress < 85 else 100
                        
                        trakt_sync.update_local_playback_progress(
                            self.tmdb_id, self.content_type, self.season, self.episode, 
                            save_progress, self.title, self.year
                        )
                        
                        xbmc.executebuiltin("Container.Refresh")
                    else:
                        # Dacă e vizionare scurtă (ex: testezi surse, te uiți 1 minut)
                        # NU facem nimic. Lăsăm resume-ul vechi (dacă există) neatins.
                        log(f"[PLAYER-CLASS] Short playback ({int(curr)}s < 5min). Ignoring save to protect history.")

            except Exception as e:
                log(f"[PLAYER-CLASS] Error saving progress: {e}", xbmc.LOGERROR)
        
        self._sync_trakt_watched()

    def onPlayBackEnded(self):
        self.stop_monitor = True
        
        # Protecție pentru EOF prematur (dacă stream-ul pică la 50%, nu îl marcăm vizionat)
        # Dar îl salvăm ca Resume Point dacă e peste 5 minute.
        try:
            curr = self.getTime()
            total = self.getTotalTime()
            if total > 300:
                progress = (curr / total) * 100
                if progress < 85:
                    log(f"[PLAYER] Stream died early at {progress:.1f}%. Treating as STOP.")
                    # Apelăm logica de stop manual ca să salveze resume point-ul
                    # (Refolosim logica din onPlayBackStopped manual)
                    if curr > 300:
                        self._send_trakt_scrobble('stop', progress)
                        trakt_sync.update_local_playback_progress(
                            self.tmdb_id, self.content_type, self.season, self.episode, 
                            progress, self.title, self.year
                        )
                    return
        except: pass

        # Dacă ajungem aici, e final real (credits)
        self.watched_marked = True 
        
        # Ștergem progresul local (punem 100%)
        try:
            trakt_sync.update_local_playback_progress(
                self.tmdb_id, self.content_type, self.season, self.episode, 
                100, self.title, self.year
            )
        except: pass

        self._send_trakt_scrobble('stop', 100)
        self._sync_trakt_watched()

    def _progress_monitor(self):
        last_time = -1
        stalled_count = 0
        time.sleep(15)
        
        while not self.stop_monitor and self.isPlaying():
            try:
                curr = self.getTime()
                total = self.getTotalTime()

                if total > 300: 
                    progress = (curr / total) * 100
                    
                    # 1. Marcare Automată VIZIONAT (85%)
                    if not self.watched_marked and progress >= 85:
                        trakt_sync.mark_as_watched_internal(self.tmdb_id, self.content_type, self.season, self.episode, notify=False, sync_trakt=False)
                        self.watched_marked = True
                        log(f"[PLAYER-CLASS] Progress {progress:.1f}% >= 85%. Marked watched locally.")

                    # 2. Scrobble la Trakt
                    # FIX: Trimitem scrobble DOAR dacă am depășit 5 minute.
                    # Altfel, Trakt înregistrează progresul de 1% sau 2% și ne strică istoricul.
                    if curr > 300:
                        if abs(progress - self.last_progress_sent) >= self.scrobble_threshold:
                            self._send_trakt_scrobble('scrobble', progress)
                            self.last_progress_sent = progress

                if curr > 0:
                    if abs(curr - last_time) < 0.1:
                        stalled_count += 1
                        if stalled_count >= 80: 
                            self.stop()
                            return
                    else:
                        stalled_count = 0 
                        last_time = curr
            except: pass
            time.sleep(0.5)

    def _sync_trakt_watched(self):
        if self.watched_marked:
            try:
                trakt_sync.sync_single_watched_to_trakt(self.tmdb_id, self.content_type, self.season, self.episode)
            except: pass

    def _send_trakt_scrobble(self, action, progress):
        try:
            from resources.lib.trakt_api import send_trakt_scrobble
            send_trakt_scrobble(action, self.tmdb_id, self.content_type, self.season, self.episode, progress)
        except: pass

# =============================================================================
# FUNCȚIE NOUĂ: PLAY LOOP (AUTO-ROLLOVER) - V2 (Fixed IDs)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties, resume_time=0):
    
    # 1. Resetare Brutală la Start (Logică Stabilă)
    if xbmc.Player().isPlaying():
        xbmc.Player().stop()
    xbmc.executebuiltin('Playlist.Clear') # Curăță playlist-ul intern Kodi
    xbmc.sleep(1000)

    total_streams = len(streams)
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Initializare...")
    
    p_title = info_tag.get('title', 'Unknown')
    p_year = info_tag.get('year', '')

    try:
        for i in range(start_index, total_streams):
            stream = streams[i]
            url = stream['url']
            
            # 1. Preluare și Curățare Nume (O singură dată)
            raw_n = stream.get('name', 'Unknown')
            raw_t = stream.get('title', '')
            # Folosim clean_text pentru a scoate caracterele ciudate, apoi înlocuim newline cu spațiu
            clean_name_display = clean_text(raw_n).replace('\n', ' ')
            
            # 2. Determinare Calitate și Culori (pentru UI)
            full_info = (raw_n + raw_t).lower()
            
            c_qual = "FF00BFFF" # SD (Default - Albastru)
            qual_txt = "SD"
            
            if '2160' in full_info or '4k' in full_info:
                qual_txt = "4K UHD"
                c_qual = "FF00FFFF" # Cyan
            elif '1080' in full_info:
                qual_txt = "1080p"
                c_qual = "FF00FF7F" # SpringGreen
            elif '720' in full_info:
                qual_txt = "720p"
                c_qual = "FFFFD700" # Gold
                
            # 3. Construire Mesaj Dialog (Exact cu formatarea ta)
            # Format: Verific sursa 1/10
            #         NumeSursa (Pink) • Quality (Colorat)
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{clean_name_display}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            
            # Update UI
            p_dialog.update(int((i / total_streams) * 100), message=msg)
            
            # --- LOGICĂ TEHNICĂ ---
            
            # Verificare URL (Rapidă - 3s)
            base_url = url.split('|')[0]
            check_headers = {}
            if '|' in url:
                try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                except: pass
            else:
                from resources.lib.config import get_stream_headers
                check_headers = get_stream_headers(url)

            if not check_url_validity(base_url, headers=check_headers):
                log(f"[PLAYER] Sursa {i+1} respinsa (403/404/Fake).")
                continue

            # --- PLAY ---
            # Instanțiem playerul
            player = TMDbPlayer(tmdb_id, c_type, season, episode, title=p_title, year=p_year)
            
            # ListItem
            li = xbmcgui.ListItem(info_tag['title'])
            li.setPath(url)
            li.setInfo('video', info_tag)
            if unique_ids: li.setUniqueIDs(unique_ids)
            if art: li.setArt(art)
            for k, v in properties.items(): li.setProperty(k, str(v))
            li.setProperty('IsPlayable', 'true')
            
            # LOGICĂ NOUĂ: Așteptare eliberare resurse înainte de Play
            retry_count = 0
            while xbmc.getCondVisibility("Player.HasVideo") and retry_count < 10:
                xbmc.sleep(500)
                retry_count += 1

            log(f"[PLAYER] Pornire sursa {i+1}...")
            player.play(url, li)
            
            # --- MONITORIZARE START (90 secunde pt buffering lent) ---
            success = False
            for _ in range(180): # 180 * 0.5s = 90s
                xbmc.sleep(500)
                
                # Dacă a început redarea (onAVStarted)
                if player.playback_started:
                    success = True
                    break
                
                # Dacă playerul s-a oprit singur (eroare Kodi)
                if not player.isPlaying():
                    # Verificăm dacă e doar o pauză de buffering sau stop real
                    if not xbmc.getCondVisibility("Player.Caching"):
                        break
            
            if success:
                log(f"[PLAYER] ✓ Playback STABLE on source {i+1}")
                p_dialog.close()
                
                if resume_time > 0:
                    xbmc.sleep(2000) # Pauză mai mare pentru buffer
                    if player.isPlaying():
                         player.seekTime(float(resume_time))
                
                # Subtitrări
                if unique_ids.get('imdb'):
                    threading.Thread(target=subtitles.run_wyzie_service, args=(unique_ids['imdb'], season, episode)).start()
                
                return
            else:
                log(f"[PLAYER] Source {i+1} failed/timeout. Force Stop & Wait.")
                
                if player.isPlaying():
                    player.stop()
                
                # Așteptare critică pentru eliberarea CURL/DXVA
                wait_stop = 0
                while xbmc.Player().isPlaying() and wait_stop < 50:
                    xbmc.sleep(100)
                    wait_stop += 1
                
                # Resetăm playlistul din nou pentru a forța curățarea stivei
                xbmc.executebuiltin('Playlist.Clear')
                xbmc.sleep(1000) 
                
    except Exception as e:
        log(f"[PLAYER] Eroare critica rollover: {e}", xbmc.LOGERROR)
        
    p_dialog.close()
    xbmcgui.Dialog().notification("TMDb Movies", "Nicio sursă nu a putut fi redată", TMDbmovies_ICON)


# =============================================================================
# LIST SOURCES MODIFICAT (Fix Serial ID)
# =============================================================================
def list_sources(params):
    try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    except: pass
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    
    resume_time = int(params.get('resume_time', 0))
    
    # --- FIX RESUME: Dacă nu vine din URL, verificăm DB local ---
    if resume_time == 0:
        progress_pct = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
        
        if progress_pct > 0:
            # Avem un procent (ex: 60.5%), dar ne trebuie secundele.
            # Trebuie să aflăm durata filmului/episodului.
            from resources.lib.tmdb_api import get_tmdb_item_details
            
            meta = get_tmdb_item_details(tmdb_id, c_type)
            duration_secs = 0
            
            if meta:
                if c_type == 'movie':
                    runtime = meta.get('runtime', 0)
                    if runtime: duration_secs = int(runtime) * 60
                else:
                    # Pentru episoade e mai complicat, luăm media sau runtime-ul episodului specific dacă am avea detalii season
                    # Fallback la runtime-ul serialului
                    runtimes = meta.get('episode_run_time', [])
                    if runtimes: duration_secs = int(runtimes[0]) * 60
            
            # Dacă am găsit durata, calculăm secundele
            if duration_secs > 0:
                resume_time = int((progress_pct / 100.0) * duration_secs)
                log(f"[PLAYER] Resume point found in DB: {progress_pct}% -> {resume_time} seconds")

    # Afișăm dialogul dacă avem un timp valid (din URL sau DB)
    if resume_time > 0:
        # Formatare timp frumos (HH:MM:SS)
        m, s = divmod(resume_time, 60)
        h, m = divmod(m, 60)
        if h > 0: time_str = f"{h}h {m}m"
        else: time_str = f"{m}m {s}s"
        
        choice = xbmcgui.Dialog().contextmenu([f"Resume from {time_str}", "Play from beginning"])
        if choice == 1: resume_time = 0
        elif choice == -1: return


    # --- 1. DETERMINĂM PROVIDERII ACTIVI ACUM ---
    # Lista hardcodată a tuturor ID-urilor posibile (trebuie să coincidă cu scraper.py)
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    # --- SMART CACHE LOGIC ---
    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    
    # Variabile init
    cached_streams = None
    failed_providers_history = []
    scanned_providers_history = []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    # --- FIX CRITIC: SANITIZARE VARIABILE DIN CACHE ---
    # Dacă nu există cache, funcția returnează None. Asigurăm că sunt liste goale.
    if scanned_providers_history is None: scanned_providers_history = []
    if failed_providers_history is None: failed_providers_history = []
    # -------------------------------------------------

    streams = []
    providers_to_scan = [] 
    
    # Scenariul 1: Avem Cache Valid
    if cached_streams is not None:
        log(f"[SMART-CACHE] Found {len(cached_streams)} cached streams.")
        
# A. FILTRARE RIGUROASĂ (pentru a elimina providerii dezactivați)
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            
            # FALLBACK: Dacă e cache vechi (fără ID), încercăm să ghicim din nume
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: s_pid = 'nuvio'
                elif 'vix' in raw_name: s_pid = 'vixsrc'
                elif 'sooti' in raw_name: s_pid = 'sooti'
                elif 'vega' in raw_name: s_pid = 'vega'
                elif 'vidzee' in raw_name: s_pid = 'vidzee'
                elif 'rogflix' in raw_name: s_pid = 'rogflix'
                elif 'streamvix' in raw_name: s_pid = 'streamvix'
            
            # Păstrăm doar dacă providerul e activ
            # Dacă s_pid tot nu a putut fi dedus (e.g. nume generic), îl păstrăm.
            if s_pid and s_pid not in active_providers:
                continue # SKIP (Eliminat pentru ca e dezactivat)
                
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        
        # B. DETECTARE LIPSURI (Provideri noi sau eșuați)
        
        # 1. Provideri care au eșuat data trecută și sunt încă activi (Retry)
        retry_list = [p for p in failed_providers_history if p in active_providers]
        
        # 2. Provideri care sunt activi ACUM, dar NU au fost scanați data trecută (New/Activated)
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        
        # Lista finală de scanat
        providers_to_scan = list(set(retry_list + missing_list))
        
        if not providers_to_scan:
            log("[SMART-CACHE] Cache is complete and consistent with settings. Skipping scan.")
        else:
            log(f"[SMART-CACHE] Rescanning: {providers_to_scan} (Retry/New)")

    # Scenariul 2: Nu avem Cache SAU trebuie să completăm
    if cached_streams is None or providers_to_scan:
        
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id')
        if not imdb_id: imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if not p_dialog.iscanceled():
                p_dialog.update(percent, f"Caut: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]")

        # Dacă nu avem cache deloc, providers_to_scan e None (scan all). 
        # Dacă avem cache, providers_to_scan e lista calculată mai sus.
        target_list = providers_to_scan if cached_streams is not None else None
        
        new_streams, new_failed = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=target_list
        )
        
        p_dialog.close()
        
        # COMBINARE REZULTATE
        
        # Calculăm lista finală de provideri care au fost scanați cu succes (istoric + curent)
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        
        for p in providers_attempted_now:
            # Dacă providerul rulat acum nu e în lista de eșecuri și nici în lista finală de scanați
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
                
        # Calculăm lista finală de failed (doar cei care au eșuat ACUM)
        final_failed = new_failed

        # Merge Streams
        if cached_streams is not None:
            existing_urls = set(s['url'].split('|')[0] for s in streams)
            for ns in new_streams:
                clean_url = ns['url'].split('|')[0]
                if clean_url not in existing_urls:
                    streams.append(ns)
        else:
            streams = new_streams
            
        # Sortare si Salvare Cache
        # Salvăm chiar dacă sunt 0 surse, atâta timp cât am scanat provideri (ca să nu repete scanarea degeaba)
        if streams or final_scanned: 
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)
                log(f"[SMART-CACHE] Updated. Streams: {len(streams)}, Scanned: {final_scanned}, Failed: {final_failed}")

    if not streams:
        xbmcgui.Dialog().notification("TMDb Movies", "Nu s-au găsit surse", TMDbmovies_ICON)
        return

    # Afișare
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    dlg_title = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if cached_streams is not None: dlg_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
        
        final_imdb_id = None
        if c_type == 'tv':
            final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else ids.get('imdb_id')
        else:
            final_imdb_id = extra_imdb_id if extra_imdb_id else ids.get('imdb_id')

        final_title = eng_title if eng_title else title
        final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
        
        properties = {'tmdb_id': str(tmdb_id)}
        if final_imdb_id:
            if c_type == 'tv': properties['tvshow.imdb_id'] = final_imdb_id
            properties['imdb_id'] = final_imdb_id
            properties['ImdbNumber'] = final_imdb_id

        info_tag = {
            'title': final_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0
        }
        if final_imdb_id: info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: info_tag['season'] = int(season)
            if episode: info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id: unique_ids['imdb'] = final_imdb_id
            
        play_with_rollover(
            streams, ret, tmdb_id, c_type, season, episode,
            info_tag, unique_ids, {'poster': poster_url}, properties, resume_time
        )
        
        if final_imdb_id:
            threading.Thread(target=run_wyzie_service, args=(final_imdb_id, season, episode)).start()


# =============================================================================
# RESOLVE DIALOG MODIFICAT PENTRU ROLLOVER
# =============================================================================
def tmdb_resolve_dialog(params):
    # 1. ELIMINAT "setResolvedUrl(False)" care cauza eroarea "Playback Failed".
    # Nu semnalăm nimic încă. Lăsăm Kodi să aștepte puțin până găsim sursele.
    
    # 2. Preluare parametri
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = params.get('imdb_id')
    
    # --- 3. LOGICA RESUME (Reparată pentru TMDb Helper) ---
    resume_time = 0
    try:
        # Verificăm în baza de date locală
        progress_pct = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
        
        if progress_pct > 0:
            from resources.lib.tmdb_api import get_tmdb_item_details
            
            # Trebuie să aflăm durata totală pentru a transforma % în secunde
            meta = get_tmdb_item_details(tmdb_id, c_type)
            duration_secs = 0
            
            if meta:
                if c_type == 'movie':
                    runtime = meta.get('runtime', 0)
                    if runtime: duration_secs = int(runtime) * 60
                else:
                    # Pentru episoade, încercăm runtime-ul din meta sau un default
                    runtimes = meta.get('episode_run_time', [])
                    if runtimes: duration_secs = int(runtimes[0]) * 60
                    else: duration_secs = 2700 # 45 min fallback
            
            if duration_secs > 0:
                resume_time = int((progress_pct / 100.0) * duration_secs)
                log(f"[RESOLVE] Resume point found: {progress_pct}% -> {resume_time}s")
    except Exception as e:
        log(f"[RESOLVE] Resume check failed: {e}", xbmc.LOGWARNING)

    # Dacă avem un timp de resume, întrebăm utilizatorul
    if resume_time > 0:
        # Formatare timp frumos (HH:MM:SS)
        m, s = divmod(resume_time, 60)
        h, m = divmod(m, 60)
        if h > 0: time_str = f"{h}h {m}m"
        else: time_str = f"{m}m {s}s"
        
        # Dialog Resume
        dialog = xbmcgui.Dialog()
        choice = dialog.contextmenu([f"Resume from {time_str}", "Play from beginning"])
        
        if choice == 0:
            pass # Păstrăm resume_time calculat
        elif choice == 1:
            resume_time = 0 # Reset la 0
        else:
            return # Cancel (ESC)

    # --- 4. SMART CACHE LOGIC (Identic cu list_sources) ---
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    
    cached_streams = None
    failed_providers_history = []
    scanned_providers_history = []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: scanned_providers_history = []
    if failed_providers_history is None: failed_providers_history = []

    streams = []
    providers_to_scan = [] 
    
    if cached_streams is not None:
        log(f"[RESOLVE] Found {len(cached_streams)} cached streams.")
        
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid: # Fallback nume
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: s_pid = 'nuvio'
                elif 'vix' in raw_name: s_pid = 'vixsrc'
                elif 'sooti' in raw_name: s_pid = 'sooti'
                elif 'vega' in raw_name: s_pid = 'vega'
                elif 'vidzee' in raw_name: s_pid = 'vidzee'
                elif 'rogflix' in raw_name: s_pid = 'rogflix'
                elif 'streamvix' in raw_name: s_pid = 'streamvix'
            
            if s_pid and s_pid not in active_providers:
                continue 
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Căutare surse (Resolve)...")
        
        if not imdb_id:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        if not imdb_id: imdb_id = f"tmdb:{tmdb_id}"

        def update_prog(percent, provider_name):
            if not p_dialog.iscanceled():
                p_dialog.update(percent, f"Caut: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]")

        target_list = providers_to_scan if cached_streams is not None else None

        new_streams, new_failed = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_prog,
            target_providers=target_list
        )
        p_dialog.close()
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
        final_failed = new_failed

        if cached_streams is not None:
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
        # Trimitem resolved False doar la final, dacă chiar nu am găsit nimic
        try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except: pass
        return

    # 5. METADATE SI ARTWORK
    eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
    
    if c_type == 'tv':
        final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else imdb_id
    else:
        final_imdb_id = extra_imdb_id if extra_imdb_id else imdb_id
    
    if not final_imdb_id:
        try:
            forced_ids = get_external_ids(c_type, tmdb_id)
            final_imdb_id = forced_ids.get('imdb_id')
        except: pass

    primary_imdb = final_imdb_id
    final_title = eng_title if eng_title else title
    final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
    
    properties = {'tmdb_id': str(tmdb_id)}
    if final_imdb_id:
        if c_type == 'tv': properties['tvshow.imdb_id'] = final_imdb_id
        properties['imdb_id'] = final_imdb_id
        properties['ImdbNumber'] = final_imdb_id

    info_tag = {
        'title': final_title,
        'mediatype': 'movie' if c_type == 'movie' else 'episode',
        'year': int(year) if year else 0
    }
    if primary_imdb:
        info_tag['imdbnumber'] = primary_imdb
        info_tag['code'] = primary_imdb
    if c_type == 'tv':
        info_tag['tvshowtitle'] = final_show_title
        if season: info_tag['season'] = int(season)
        if episode: info_tag['episode'] = int(episode)

    unique_ids = {'tmdb': str(tmdb_id)}
    if primary_imdb: unique_ids['imdb'] = primary_imdb

    poster_url = get_poster_url(tmdb_id, c_type, season)
    art = {'poster': poster_url, 'thumb': poster_url}

    # 6. SELECTIE SURSA
    display_items = build_display_items(streams, poster_url)
    
    dialog = xbmcgui.Dialog()
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    title_dlg = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if cached_streams is not None: title_dlg += " [COLOR lime][CACHE][/COLOR]"
        
    ret = dialog.select(title_dlg, display_items, useDetails=True)
    
    if ret >= 0:
        # AICI E SCHIMBAREA: Trimitem Resolved IMEDIAT ce userul a ales o sursă.
        # Îi dăm un URL fals dar valid sintactic ("http://localhost/dummy") ca să creadă că a reușit.
        # Asta ar trebui să închidă dialogul de așteptare al TMDb Helper instant.
        try:
            dummy_item = xbmcgui.ListItem(path="http://localhost/dummy")
            xbmcplugin.setResolvedUrl(HANDLE, True, dummy_item)
        except: pass
        
        # Așteptăm puțin să se propage starea
        xbmc.sleep(500)

        # Pornim player-ul nostru "peste" cel fals
        play_with_rollover(
            streams, 
            ret, 
            tmdb_id, 
            c_type, 
            season, 
            episode, 
            info_tag, 
            unique_ids, 
            art, 
            properties,
            resume_time=resume_time
        )
        
        if final_imdb_id:
            threading.Thread(target=run_wyzie_service, args=(final_imdb_id, season, episode)).start()
            
    else:
        # User cancelled - Anunțăm Kodi că am renunțat
        try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except: pass