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
from resources.lib.utils import log, get_json, extract_size_provider, get_language
from resources.lib.scraper import get_external_ids, get_stream_data
from resources.lib.tmdb_api import set_metadata
from resources.lib.trakt_api import mark_as_watched_internal
from resources.lib import subtitles
from resources.lib import trakt_sync # Added import

LANG = get_language()

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

def check_url_validity(url):
    """
    Verificare HIBRIDĂ:
    1. Respinge erorile clare (403, 404).
    2. Acceptă Video (mp4, mkv).
    3. Acceptă Playlist HLS (#EXTM3U) chiar dacă e declarat ca text.
    4. Respinge HTML/Text care nu e playlist (paginile de eroare Sooti).
    """
    try:
        clean_url = url
        custom_headers = get_headers()

        # 1. Extragem headerele custom (pentru Rogflix/Vidzee)
        if '|' in url:
            clean_url, qs = url.split('|', 1)
            parsed = urllib.parse.parse_qsl(qs)
            custom_headers.update(dict(parsed))
        
        # 2. Request cu stream=True (doar headerul și puțin conținut)
        # Timeout scurt, verify=False obligatoriu
        with requests.get(clean_url, headers=custom_headers, stream=True, timeout=6, verify=False, allow_redirects=True) as r:
            
            # --- FILTRU 1: Status Code ---
            # Dacă serverul zice 403 (Forbidden) sau 404 (Not Found), e MORT.
            if r.status_code >= 400:
                log(f"[PLAYER-CHECK] Link Error code ({r.status_code}): {clean_url}")
                return False

            # --- FILTRU 2: Conținut ---
            # Citim primii 512 bytes pentru a vedea ce e înăuntru
            chunk = next(r.iter_content(chunk_size=512), b'')
            content_str = ""
            try:
                content_str = chunk.decode('utf-8', errors='ignore')
            except:
                pass

            # A. E Playlist HLS? (Rogflix) -> ADMIS
            if '#EXTM3U' in content_str:
                return True
                
            # B. E fișier video binar? (MKV, MP4) -> ADMIS
            # Verificăm Content-Type
            ctype = r.headers.get('Content-Type', '').lower()
            if 'video' in ctype or 'application/octet-stream' in ctype or 'mpegurl' in ctype:
                return True

            # C. E HTML/Text simplu? (Sooti Error Page) -> RESPINS
            if 'text' in ctype or 'html' in ctype or '<html' in content_str.lower():
                log(f"[PLAYER-CHECK] Link is HTML/Text (Fake video): {clean_url}")
                return False
            
            # D. Implicit -> ADMIS (pentru cazuri rare)
            return True
                
    except Exception as e:
        log(f"[PLAYER-CHECK] Connection Error: {e}")
        # Dacă dă eroare de conexiune, îl respingem ca să treacă la următorul
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
# MONITORIZARE VIZIONARE
# =============================================================================
def start_watched_tracking(tmdb_id, content_type, season=None, episode=None):
    def monitor():
        player = xbmc.Player()
        marked = False
        time.sleep(5)
        while not marked:
            time.sleep(10)
            if not player.isPlaying():
                break
            try:
                total_time = player.getTotalTime()
                current_time = player.getTime()
                if total_time > 0:
                    progress = (current_time / total_time) * 100
                    if progress >= 85:
                        mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=True, sync_trakt=True)
                        marked = True
                        break
            except:
                pass
    
    thread = threading.Thread(target=monitor)
    thread.daemon = True
    thread.start()


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
    display_items = []
    
    # Folosim enumerate(streams, 1) pentru a genera automat numerele (1, 2, 3...)
    for idx, s in enumerate(streams, 1):
        raw_t = s.get('title', '')
        raw_n = s.get('name', '')
        full_info = (raw_n + raw_t).lower()
        sz, prov = extract_size_provider(raw_t, raw_n)
        
        # --- Determinare Culori Calitate ---
        c_qual = "FF00BFFF"
        qual_txt = "SD"
        if '2160' in full_info or '4k' in full_info:
            qual_txt = "4K UHD"
            c_qual = "FF00FFFF"
        elif '1080' in full_info:
            qual_txt = "1080p"
            c_qual = "FF00FF7F"
        elif '720' in full_info:
            qual_txt = "720p"
            c_qual = "FFFFD700"

        c_size = "FFFFA500"
        c_prov = "FFFF69B4"
        c_sep = "FF777777"
        sep = f"[COLOR {c_sep}] • [/COLOR]"

        # --- Tag-uri Audio/Video ---
        tags = []
        if 'dolby vision' in full_info or '.dv.' in full_info:
            tags.append("[COLOR FFDA70D6]DV[/COLOR]")
        if 'hdr' in full_info:
            tags.append("[COLOR FFADFF2F]HDR[/COLOR]")
        if 'hybrid' in full_info:
            tags.append("[COLOR FFA0522D]HYBRID[/COLOR]")
        if 'remux' in full_info:
            tags.append("[B][COLOR FFFF0000]REMUX[/COLOR][/B]")
        if 'atmos' in full_info:
            tags.append("[COLOR FF87CEEB]ATMOS[/COLOR]")
        elif 'dd+' in full_info or 'ddp' in full_info:
            tags.append("[COLOR FFB0C4DE]DD+[/COLOR]")
        
        tags_str = (" " + sep + " ").join(tags)
        if tags_str:
            tags_str = sep + tags_str

        # --- CONSTRUCȚIE LABEL CU NUMĂR ---
        # {idx:02d} formatează numerele sub 10 cu zero în față (ex: 01, 02... 10, 11)
        # Am pus numărul în ALB [COLOR FFFFFFFF]
        number_str = f"[B][COLOR FFFFFFFF]{idx:02d}.[/COLOR][/B]"

        label_main = (
            f"{number_str}  "  # <--- Aici e numărul adăugat + spațiu
            f"[B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]{sep}"
            f"[B][COLOR {c_size}]{sz}[/COLOR][/B]{sep}"
            f"[COLOR {c_prov}]{prov}[/COLOR]{tags_str}"
        )
        
        li = xbmcgui.ListItem(label=label_main)
        li.setLabel2(raw_t if raw_t else raw_n)
        li.setArt({'icon': poster_url, 'thumb': poster_url})
        display_items.append(li)
    
    return display_items


def sort_streams_by_quality(streams):
    """
    Sortează sursele după:
    1. Calitate (4K > 1080p > 720p > SD)
    2. Mărime (Descrescător - cele mai mari primele)
    """
    import re # Ne asigurăm că avem regex

    def get_sort_key(s):
        # Combinăm titlul și numele pentru a căuta detaliile
        text = (s.get('name', '') + " " + s.get('title', '')).lower()
        
        # --- 1. SCOR CALITATE ---
        if '2160' in text or '4k' in text:
            quality_score = 3
        elif '1080' in text:
            quality_score = 2
        elif '720' in text:
            quality_score = 1
        else:
            quality_score = 0
            
        # --- 2. SCOR MĂRIME (Convertim totul în MB) ---
        size_mb = 0.0
        # Căutăm tipare de genul: 10.5 GB, 500 MB, 2GB, etc.
        match = re.search(r'(\d+(?:\.\d+)?)\s*(gb|gib|mb|mib)', text)
        if match:
            val = float(match.group(1))
            unit = match.group(2)
            
            if 'g' in unit: # GB sau GiB
                size_mb = val * 1024
            else:           # MB sau MiB
                size_mb = val
        
        # Returnăm o tuplă. Python compară element cu element.
        # (Calitate, Mărime)
        return (quality_score, size_mb)

    # Sortăm lista folosind cheia de mai sus.
    # reverse=True înseamnă Descrescător (Cel mai mare scor primul)
    try:
        streams.sort(key=get_sort_key, reverse=True)
    except Exception as e:
        log(f"[SORT] Eroare la sortare: {e}")
        
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
# FUNCȚIE NOUĂ: PLAY LOOP (AUTO-ROLLOVER) - V2 (Fixed IDs)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties):
    # Asigurăm curățarea oricărui player anterior
    if xbmc.Player().isPlaying():
        xbmc.Player().stop()
        xbmc.sleep(1000)

    player = xbmc.Player()
    total_streams = len(streams)
    
    # Dialog Progres (Background)
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Inițializare player...")

    try:
        for i in range(start_index, total_streams):
            stream = streams[i]
            url = stream['url']
            
            # --- DETERMINARE CALITATE ȘI CULORI PENTRU UI ---
            raw_n = stream.get('name', 'Unknown')
            raw_t = stream.get('title', '')
            full_info = (raw_n + raw_t).lower()
            
            # 1. Culori Calitate (Sincronizate cu lista de surse)
            c_qual = "FF00BFFF" # SD (Default) - DeepSkyBlue
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
                
            # 2. Formatare Contor (Galben / Verde)
            # Exemplu: 1 (Galben) / 10 (Verde)
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            
            # 3. Formatare Nume Provider (Pink)
            clean_name = raw_n.replace('\n', ' ')
            
            # Actualizare UI
            # Linia 1: Verific sursa X/Y
            # Linia 2: Provider • Calitate (Colorate)
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{clean_name}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            
            p_dialog.update(int((i / total_streams) * 100), message=msg)
            # 1. VERIFICARE PRE-PLAY (Doar filtrare grosieră: HTML/Fake)
            if not check_url_validity(url):
                log(f"[PLAYER] Source {i} rejected by validity check. Next.")
                continue 

            # 2. PREGĂTIRE URL (Headers)
            if '|' in url:
                full_url = url
            else:
                from resources.lib.config import get_stream_headers
                req_headers = get_stream_headers(url)
                headers_str = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in req_headers.items()])
                full_url = f"{url}|{headers_str}"
            
            # 3. CREARE LISTITEM
            li = xbmcgui.ListItem(info_tag['title'])
            li.setPath(full_url)
            
            # --- Properties Identificare (subs.ro etc) ---
            li.setProperty('tmdb_id', str(tmdb_id))
            if unique_ids.get('imdb'):
                imdb_clean = unique_ids['imdb'].replace('tt', '')
                li.setProperty('imdb_id', imdb_clean)
                li.setProperty('imdbnumber', unique_ids['imdb'])
                li.setProperty('ImdbNumber', unique_ids['imdb'])
            
            if c_type == 'tv':
                if season:
                    li.setProperty('season', str(season))
                    li.setProperty('Season', str(season))
                if episode:
                    li.setProperty('episode', str(episode))
                    li.setProperty('Episode', str(episode))
                if info_tag.get('tvshowtitle'):
                    li.setProperty('TVShowTitle', info_tag['tvshowtitle'])
            
            if info_tag.get('year'):
                li.setProperty('year', str(info_tag['year']))
                li.setProperty('Year', str(info_tag['year']))
            
            li.setProperty('IsPlayable', 'true')
            for k, v in properties.items():
                li.setProperty(k, str(v))
            
            # InfoTag
            tag = li.getVideoInfoTag()
            tag.setMediaType(info_tag.get('mediatype', 'video'))
            tag.setTitle(info_tag.get('title'))
            if 'year' in info_tag: tag.setYear(info_tag['year'])
            if 'season' in info_tag: tag.setSeason(info_tag['season'])
            if 'episode' in info_tag: tag.setEpisode(info_tag['episode'])
            if 'tvshowtitle' in info_tag: tag.setTvShowTitle(info_tag['tvshowtitle'])
            if 'imdbnumber' in info_tag: tag.setIMDBNumber(info_tag['imdbnumber'])
            if unique_ids: tag.setUniqueIDs(unique_ids)
            if art: li.setArt(art)
            
            # 4. LANSARE REDARE
            log(f"[PLAYER] Attempting source {i}: {full_url[:100]}...")
            player.play(full_url, li)
            
            # 5. MONITORIZARE START (Critic pentru Sooti 403)
            # Așteptăm să vedem dacă pornește și dacă RĂMÂNE pornit
            playback_started = False
            
            # Loop de verificare (max 10 secunde)
            for wait_step in range(20): 
                xbmc.sleep(500)
                
                # Verificăm dacă rulează
                if player.isPlaying():
                    # Dacă a pornit, așteptăm încă 1.5 secunde să fim siguri că nu crapă (eroare 403 întârziată)
                    xbmc.sleep(1500) 
                    
                    if player.isPlaying():
                        log(f"[PLAYER] ✓ Playback STABLE on source {i}")
                        playback_started = True
                        p_dialog.close() # Închidem dialogul DOAR la succes
                        
                        try:
                            # Opțional: Resetare la început dacă e nevoie
                            # player.seekTime(0)
                            pass
                        except: pass
                        
                        # Monitorizare vizionare (Trakt)
                        start_watched_tracking(tmdb_id, c_type, season, episode)
                        return # IEȘIRE (SUCCES)
                    else:
                        log(f"[PLAYER] Source {i} crashed immediately (403/Forbidden).")
                        break # Ieșim din loop-ul de așteptare, trecem la următoarea sursă
            
            if not playback_started:
                log(f"[PLAYER] Source {i} failed to start (Timeout/Error). Next...")
                # Dacă a rămas agățat cumva, stop
                if player.isPlaying():
                    player.stop()
                    
    except Exception as e:
        log(f"[PLAYER] Fatal Loop Error: {e}", xbmc.LOGERROR)

    # FINAL
    p_dialog.close()
    xbmcgui.Dialog().notification("[B]TMDb Movies[/B]", "Nicio sursă funcțională", xbmcgui.NOTIFICATION_ERROR)


# =============================================================================
# LIST SOURCES MODIFICAT (Fix Serial ID)
# =============================================================================
def list_sources(params):
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    tv_show_title = params.get('tv_show_title', '')

    streams = None
    from_cache = False
    scraped_imdb_id = None

    # 1. VERIFICĂ CACHE RAM
    cached_streams = load_sources_from_ram(tmdb_id, c_type, season, episode)
    
    if cached_streams:
        streams = cached_streams
        from_cache = True
        log(f"[RAM-SRC] Folosim cache pentru: {title}")
    else:
        # 2. CĂUTARE NET CU PROGRESS REAL-TIME
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")

        p_dialog.update(5, "Se verifică ID-urile externe...")
        ids = get_external_ids(c_type, tmdb_id)
        scraped_imdb_id = ids.get('imdb_id')

        if not scraped_imdb_id:
            log(f"[PLAYER] Lipsa IMDb ID pentru {tmdb_id}, cautam doar cu TMDb", xbmc.LOGWARNING)

        def update_progress(percent, provider_name):
            if not p_dialog.iscanceled():
                msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
                p_dialog.update(percent, msg)

        try:
            search_id = scraped_imdb_id if scraped_imdb_id else f"tmdb:{tmdb_id}"
            streams = get_stream_data(search_id, c_type, season, episode, progress_callback=update_progress)
        except Exception as e:
            p_dialog.close()
            log(f"Search Error: {e}", xbmc.LOGERROR)
            return

        if p_dialog.iscanceled():
            p_dialog.close()
            return

        p_dialog.update(95, "Se sortează rezultatele...")
        p_dialog.close()
        
        if not streams:
            xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Nu s-au găsit surse", TMDbmovies_ICON, 3000, False)
            return

        streams = sort_streams_by_quality(streams)
        save_sources_to_ram(streams, tmdb_id, c_type, season, episode)

    # 3. AFIȘARE
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)

    dialog = xbmcgui.Dialog()
    
    # --- MODIFICARE: Afișăm anul doar dacă e film ---
    if c_type == 'movie' and year:
        header_title = f"{title} ({year})"
    else:
        header_title = title  # Doar titlul episodului, fără an
        
    dialog_title = f"[B][COLOR FFFDBD01]{header_title} - [COLOR FF6AFB92]{len(streams)} [COLOR FFFDBD01]Surse[/COLOR][/B]"
    # ------------------------------------------------
    if from_cache:
        dialog_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = dialog.select(dialog_title, display_items, useDetails=True)

    # 4. PREGĂTIRE DATE ȘI APELARE ROLLOVER
    if ret >= 0:
        # --- PREPARARE METADATE ---
        eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
        
        # ✅ FIX: Pentru episoade, folosim IMDb-ul SERIALULUI (nu al episodului)
        if c_type == 'tv':
            # IMDb-ul serialului (principal) - ăsta se folosește pentru subtitrări
            final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else scraped_imdb_id
            
            # Salvăm și IMDb-ul episodului (opțional, pentru metadata)
            episode_imdb_id = extra_imdb_id if extra_imdb_id else None
        else:
            # Pentru filme, folosim IMDb-ul filmului
            final_imdb_id = extra_imdb_id if extra_imdb_id else scraped_imdb_id
            episode_imdb_id = None
        
        if not final_imdb_id:
            try:
                forced_ids = get_external_ids(c_type, tmdb_id)
                final_imdb_id = forced_ids.get('imdb_id')
            except:
                pass
        
        # Log pentru debugging
        if c_type == 'tv':
            log(f"[PLAYER] TV: Serial IMDb={final_imdb_id}, Episode IMDb={episode_imdb_id}")
        else:
            log(f"[PLAYER] Movie IMDb={final_imdb_id}")
        
        # Stabilim Titlurile
        final_title = eng_title if eng_title else title
        final_show_title = eng_tvshowtitle if eng_tvshowtitle else tv_show_title
        
        # Construim Properties
        properties = {'tmdb_id': str(tmdb_id)}
        
        # ✅ Pentru TV: Setăm IMDb-ul serialului (nu al episodului!)
        if c_type == 'tv':
            if final_imdb_id:
                properties['tvshow.imdb_id'] = final_imdb_id
                properties['tvshow.ImdbNumber'] = final_imdb_id
                # IMDb-ul principal e al serialului
                properties['imdb_id'] = final_imdb_id
                properties['ImdbNumber'] = final_imdb_id
            
            # Opțional: IMDb-ul episodului (dacă există)
            if episode_imdb_id:
                properties['episode.imdb_id'] = episode_imdb_id
        else:
            # Pentru filme
            if final_imdb_id:
                properties['imdb_id'] = final_imdb_id
                properties['ImdbNumber'] = final_imdb_id

        # Construim Info Tag
        info_tag = {
            'title': final_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0
        }
        if final_imdb_id:
            info_tag['imdbnumber'] = final_imdb_id
            info_tag['code'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: info_tag['season'] = int(season)
            if episode: info_tag['episode'] = int(episode)

        # Construim Unique IDs (OBLIGATORIU TMDb, Optional IMDb)
        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id:
            unique_ids['imdb'] = final_imdb_id
            
        art = {'poster': poster_url, 'thumb': poster_url}

        # APELĂM FUNCȚIA DE REDARE CU ROLLOVER
        play_with_rollover(
            streams, ret, tmdb_id, c_type, season, episode,
            info_tag, unique_ids, art, properties
        )
        
        # ✅ Pornire serviciu subtitrări DUPĂ ce rollover a pornit redarea
        # Folosim IMDb-ul corect (serial pentru TV, film pentru movie)
        if final_imdb_id:
            threading.Thread(
                target=subtitles.run_wyzie_service, 
                args=(final_imdb_id, season, episode) 
            ).start()


# =============================================================================
# RESOLVE DIALOG MODIFICAT PENTRU ROLLOVER
# =============================================================================
def tmdb_resolve_dialog(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = params.get('imdb_id')

    streams = None
    from_cache = False

    # VERIFICARE CACHE
    current_search_id = get_search_id(tmdb_id, c_type, season, episode)
    window = get_window()
    cached_id = window.getProperty('tmdbmovies.src_id')
    
    if cached_id and cached_id != current_search_id:
        log(f"[RAM-SRC] Resolve - Titlu nou! Curăț cache ({cached_id} -> {current_search_id})")
        clear_sources_cache()

    cached_streams = load_sources_from_ram(tmdb_id, c_type, season, episode)
    
    if cached_streams:
        streams = cached_streams
        from_cache = True
        log(f"[RAM-SRC] Resolve - folosim cache pentru: {title}")
    else:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")

        if not imdb_id:
            p_dialog.update(10, "Se verifică ID-urile externe...")
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        
        if not imdb_id:
            p_dialog.close()
            xbmcgui.Dialog().notification("Eroare", "Lipsă IMDb ID", xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return

        def update_progress(percent, provider_name):
            if not p_dialog.iscanceled():
                msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
                p_dialog.update(percent, msg)

        streams = get_stream_data(imdb_id, c_type, season, episode, progress_callback=update_progress)
        
        if p_dialog.iscanceled():
            p_dialog.close()
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return

        p_dialog.update(90, "Se sortează...")
        p_dialog.close()
        
        if not streams:
            xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Nu s-au găsit surse", xbmcgui.NOTIFICATION_INFO)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return

        streams = sort_streams_by_quality(streams)
        save_sources_to_ram(streams, tmdb_id, c_type, season, episode)

    # AFIȘARE DIALOG CU SURSE
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)

    dialog = xbmcgui.Dialog()
    dialog_title = f"{title} ({year}) - {len(streams)} Surse"
    if from_cache:
        dialog_title += " [COLOR lime][CACHE][/COLOR]"
        
    ret = dialog.select(dialog_title, display_items, useDetails=True)

    # REDARE
    if ret >= 0:
        # --- PREPARARE METADATE ---
        eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
        
        # ✅ FIX: Pentru episoade, folosim IMDb-ul SERIALULUI
        if c_type == 'tv':
            final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else imdb_id
        else:
            final_imdb_id = extra_imdb_id if extra_imdb_id else imdb_id
        
        if not final_imdb_id:
            try:
                forced_ids = get_external_ids(c_type, tmdb_id)
                final_imdb_id = forced_ids.get('imdb_id')
            except:
                pass

        primary_imdb = final_imdb_id
        
        # Log
        if c_type == 'tv':
            log(f"[PLAYER-RESOLVE] TV: Using show IMDb={primary_imdb}")
        else:
            log(f"[PLAYER-RESOLVE] Movie IMDb={primary_imdb}")

        final_title = eng_title if eng_title else title
        final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
        
        properties = {'tmdb_id': str(tmdb_id)}
        
        # ✅ Pentru TV: IMDb-ul serialului
        if c_type == 'tv':
            if primary_imdb:
                properties['tvshow.imdb_id'] = primary_imdb
                properties['tvshow.ImdbNumber'] = primary_imdb
                properties['imdb_id'] = primary_imdb
                properties['ImdbNumber'] = primary_imdb
        else:
            if primary_imdb:
                properties['imdb_id'] = primary_imdb
                properties['ImdbNumber'] = primary_imdb

        info_tag = {
            'title': final_title, 
            'mediatype': 'movie' if c_type == 'movie' else 'episode'
        }
        if primary_imdb:
            info_tag['imdbnumber'] = primary_imdb
            info_tag['code'] = primary_imdb
        if year: 
            info_tag['year'] = int(year)
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: 
                info_tag['season'] = int(season)
            if episode: 
                info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if primary_imdb:
            unique_ids['imdb'] = primary_imdb
            
        art = {'poster': poster_url, 'thumb': poster_url}

        # GĂSEȘTE PRIMA SURSĂ VALIDĂ
        valid_url = None
        valid_index = ret
        
        p_dialog_bg = xbmcgui.DialogProgressBG()
        p_dialog_bg.create("[B]TMDb Movies[/B]", "Verific sursele...")
        
        try:
            total_streams = len(streams)
            for i in range(ret, total_streams):
                stream = streams[i]
                url = stream['url']
                
                p_dialog_bg.update(int((i / total_streams) * 100), message=f"Verific sursa {i+1}/{total_streams}...")
                
                if check_url_validity(url):
                    valid_url = url
                    valid_index = i
                    log(f"[PLAYER-RESOLVE] Found valid source at index {i}")
                    break
                else:
                    log(f"[PLAYER-RESOLVE] Source {i} failed validity check. Skipping.")
        finally:
            p_dialog_bg.close()
        
        if not valid_url:
            xbmcgui.Dialog().notification("[B]TMDb Movies[/B]", "Nicio sursă nu funcționează", xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        
        # CONSTRUIEȘTE LISTITEM
        from resources.lib.config import get_stream_headers
        req_headers = get_stream_headers(valid_url)
        headers_str = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in req_headers.items()])
        full_url = f"{valid_url}|{headers_str}"
        
        li = xbmcgui.ListItem(final_title)
        li.setPath(full_url)
        
        # ✅ Properties pentru subs.ro
        li.setProperty('tmdb_id', str(tmdb_id))
        if primary_imdb:
            imdb_clean = primary_imdb.replace('tt', '')
            li.setProperty('imdb_id', imdb_clean)
            li.setProperty('imdbnumber', primary_imdb)
            li.setProperty('ImdbNumber', primary_imdb)
        
        if c_type == 'tv':
            if season:
                li.setProperty('season', str(season))
                li.setProperty('Season', str(season))
            if episode:
                li.setProperty('episode', str(episode))
                li.setProperty('Episode', str(episode))
            if final_show_title:
                li.setProperty('TVShowTitle', final_show_title)
        
        if year:
            li.setProperty('year', str(year))
            li.setProperty('Year', str(year))
        
        li.setProperty('IsPlayable', 'true')
        li.setProperty('StartOffset', '0')
        li.setProperty('ResumeTime', '0')
        li.setProperty('TotalTime', '0')
        
        for k, v in properties.items():
            li.setProperty(k, str(v))

        if unique_ids:
            li.setUniqueIDs(unique_ids)

        set_metadata(li, info_tag, unique_ids=unique_ids)
        
        # REZOLVĂ
        log(f"[PLAYER-RESOLVE] Resolving with valid URL from source {valid_index}")
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
        
        # Pornește serviciul de subtitrări
        if primary_imdb:
            threading.Thread(
                target=subtitles.run_wyzie_service, 
                args=(primary_imdb, season, episode)
            ).start()
        
        start_watched_tracking(tmdb_id, c_type, season, episode)
        
    else:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())