import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import json
import requests
import sys
import os
import html
import threading
from urllib.parse import urlencode, quote
from datetime import datetime, date
from resources.lib import trakt_sync

# --- FIX EROARE LOG: Fortam ID-ul daca nu este detectat ---
try:
    # Incercam sa luam instanta curenta
    ADDON = xbmcaddon.Addon()
    # Verificam daca are ID valid, altfel aruncam eroare pentru a intra in except
    _id = ADDON.getAddonInfo('id')
except:
    # Daca esueaza, fortam ID-ul cunoscut
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
# ----------------------------------------------------------

ADDON_PATH = ADDON.getAddonInfo('path')

try:
    from resources.lib.config import API_KEY, IMG_BASE, BACKDROP_BASE
except ImportError:
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    # IMG_BASE este w500 (bun pentru postere principale)
    IMG_BASE = "https://image.tmdb.org/t/p/w500" 
    # BACKDROP_BASE este w1280 (bun pentru fundal)
    BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

# --- OPTIMIZARE VITEZA ---
# In loc de 'original' (care blocheaza Android-ul), folosim w1280 (HD)
IMG_FULL = "https://image.tmdb.org/t/p/w1280" 

# Definim o marime mica pentru listele lungi (Cast, Recomandari)
# w185 sau w342 se incarca instant
IMG_THUMB_SMALL = "https://image.tmdb.org/t/p/w342"
# -------------------------

# --- LISTA CHEI YOUTUBE (ROTATIE) ---
YOUTUBE_KEYS = [
    'AIzaSyDtgCds1-7WAuajTIj2z9hXCMTCCFvJxGc',
    'AIzaSyC8OXml2Dz3KVOMbxW5LZj45Fr7Qf9APQY',
    'AIzaSyCXAUyE5nnzbkn3ItbOaAExPVCf4Cmqk-A',
    'AIzaSyA0LiS7G-KlrlfmREcCAXjyGqa_h_zfrSE',
    'AIzaSyBOXZVC-xzrdXSAmau5UM3rG7rc8eFIuFw',
    'AIzaSyDCJJcBtvDsTH5f-7xJWeV10ZnoRZB_E50'
]
# ------------------------------------

# Imagini full resolution pentru viewer
IMG_FULL = "https://image.tmdb.org/t/p/original"

XML_VIDEO_INFO = 'ext_DialogVideoInfo.xml'
XML_ACTOR_INFO = 'ext_DialogInfo.xml'

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_LEFT = 1
ACTION_RIGHT = 2
ACTION_UP = 3
ACTION_DOWN = 4
ACTION_SELECT = 7
ACTION_MOUSE_LEFT_CLICK = 100

NAVIGATION_STACK = []

def log(msg):
    xbmc.log(f"[TMDb Extended INFO] {msg}", level=xbmc.LOGINFO)

# --- FUNCTII NOI PENTRU BUTOANE (Play, Library, Settings) ---
def action_play_dialog(tmdb_id, media_type, season=None, episode=None, title=''):
    """
    Gestionează meniul de acțiuni (Play/Browse/Search).
    Fix: Culori personalizate și Text Bold.
    """
    s_id = str(tmdb_id)
    s_season = str(season) if season is not None else '1'
    s_episode = str(episode) if episode is not None else '1'
    s_title = str(title)
    
    # Determinăm tipul corect pentru Căutare
    search_type_real = 'tv' if media_type in ['tv', 'season', 'episode'] else 'movie'
    
    # --- DEFINIRE CULORI ---
    # TMDb Movies -> FFFDBD01 (Gold)
    # TMDb Helper -> FF00CED1 (Turquoise)
    # Search Title -> FF6AFB92 (Light Green)
    
    c_movies = "[COLOR FFFDBD01]TMDb Movies[/COLOR]"
    c_helper = "[COLOR FF00CED1]TMDb Helper[/COLOR]"
    c_title  = f"[COLOR FF6AFB92]'{s_title}'[/COLOR]"
    
    # 1. GENERARE ETICHETE (Toate cu [B]old)
    if media_type == 'tv':
        label_movies = f"[B]Browse Seasons ({c_movies})[/B]"
        label_helper = f"[B]Browse Seasons ({c_helper})[/B]"
    elif media_type == 'season':
        label_movies = f"[B]Browse Episodes ({c_movies})[/B]"
        label_helper = f"[B]Browse Episodes ({c_helper})[/B]"
    elif media_type == 'episode':
        label_movies = f"[B]Play Episode ({c_movies})[/B]"
        label_helper = f"[B]Play Episode ({c_helper})[/B]"
    else: 
        label_movies = f"[B]Play Movie ({c_movies})[/B]"
        label_helper = f"[B]Play Movie ({c_helper})[/B]"
        
    label_search = f"[B]Search {c_title} ({search_type_real.upper()})[/B]"
        
    options = [label_movies, label_helper, label_search]
    
    dialog = xbmcgui.Dialog()
    ret = dialog.contextmenu(options)
    
    if ret < 0: return # Cancel
    
    url = ""
    is_browsing = False
    
    # OPTIUNEA 0: TMDB MOVIES
    if ret == 0:
        base_url = "plugin://plugin.video.tmdbmovies/"
        if media_type == 'movie':
            url = f"{base_url}?mode=sources&tmdb_id={s_id}&type=movie&title={quote(s_title)}"
        elif media_type == 'episode':
            url = f"{base_url}?mode=sources&tmdb_id={s_id}&type=tv&season={s_season}&episode={s_episode}&title={quote(s_title)}"
        elif media_type == 'tv':
            url = f"{base_url}?mode=details&tmdb_id={s_id}&type=tv&title={quote(s_title)}"
            is_browsing = True
        elif media_type == 'season':
            url = f"{base_url}?mode=episodes&tmdb_id={s_id}&season={s_season}&tv_show_title={quote(s_title)}"
            is_browsing = True

    # OPTIUNEA 1: TMDB HELPER
    elif ret == 1:
        base_url = "plugin://plugin.video.themoviedb.helper/"
        if media_type == 'movie':
            url = f"{base_url}?info=play&type=movie&tmdb_id={s_id}"
        elif media_type == 'episode':
            url = f"{base_url}?info=play&type=episode&tmdb_id={s_id}&season={s_season}&episode={s_episode}"
        elif media_type == 'tv':
            url = f"{base_url}?info=details&type=tv&tmdb_id={s_id}"
            is_browsing = True
        elif media_type == 'season':
            url = f"{base_url}?info=episodes&type=tv&tmdb_id={s_id}&season={s_season}"
            is_browsing = True

    # OPTIUNEA 2: SEARCH
    elif ret == 2:
        import re
        clean_title = s_title
        # Curatam S01, S2024 etc
        match = re.search(r'\sS\d+', s_title)
        if match:
            clean_title = s_title[:match.start()]
            
        url = f"plugin://plugin.video.tmdbmovies/?mode=perform_search_query&query={quote(clean_title)}&type={search_type_real}"
        is_browsing = True

    # EXECUȚIE PRIN THREAD
    if url:
        xbmc.log(f"[ExtendedInfo] Executing via Thread: {url}", xbmc.LOGINFO)
        
        def run_command():
            import xbmc
            import time
            xbmc.executebuiltin("Dialog.Close(all,true)")
            time.sleep(0.4)
            
            if is_browsing:
                xbmc.executebuiltin(f'ActivateWindow(Videos,"{url}",return)')
            else:
                xbmc.executebuiltin(f"RunPlugin({url})")

        t = threading.Thread(target=run_command)
        t.start()

def action_open_settings():
    xbmcaddon.Addon('plugin.video.tmdbmovies').openSettings()

def action_refresh_trakt():
    xbmc.executebuiltin("RunPlugin(plugin://plugin.video.tmdbmovies/?mode=trakt_sync)")
# -----------------------------------------------------------

def get_tmdb_data(endpoint, params=None):
    if params is None: params = {}
    params['api_key'] = API_KEY
    params['language'] = 'en-US'
    params['include_image_language'] = 'en,null'
    
    # --- MODIFICARE: Adaugam limbile indiene (Hindi, Tamil, Telugu, Malayalam, Kannada) ---
    # Daca parametrul nu exista deja in apel, il setam noi extins
    if 'include_video_language' not in params:
        params['include_video_language'] = 'en,null,hi,ta,te,ml,kn,bn,pa'
    # --------------------------------------------------------------------------------------
    
    url = f"https://api.themoviedb.org/3/{endpoint}"
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}

def get_youtube_api_data(query):
    # --- CAUTARE YOUTUBE CU ROTATIE DE CHEI ---
    if not query: return []
    
    base_url = "https://www.googleapis.com/youtube/v3/search"
    
    # Incercam fiecare cheie din lista
    for api_key in YOUTUBE_KEYS:
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': 50,
            'key': api_key,
            'relevanceLanguage': 'en'
        }
        
        try:
            xbmc.log(f"[YOUTUBE_DEBUG] Trying key ending in ...{api_key[-4:]}", level=xbmc.LOGINFO)
            r = requests.get(base_url, params=params, timeout=5)
            
            if r.status_code == 200:
                data = r.json()
                items = data.get('items', [])
                xbmc.log(f"[YOUTUBE_DEBUG] Success! Found {len(items)} videos.", level=xbmc.LOGINFO)
                return items
            elif r.status_code == 403:
                xbmc.log(f"[YOUTUBE_DEBUG] Quota Exceeded for key ...{api_key[-4:]}. Trying next...", level=xbmc.LOGINFO)
                continue # Trecem la urmatoarea cheie
            else:
                xbmc.log(f"[YOUTUBE_DEBUG] API Error: {r.status_code}", level=xbmc.LOGINFO)
                
        except Exception as e:
            xbmc.log(f"[YOUTUBE_DEBUG] Request Failed: {e}", level=xbmc.LOGINFO)
            
    xbmc.log("[YOUTUBE_DEBUG] All keys failed!", level=xbmc.LOGINFO)
    return []

def format_money(val):
    if not val: return ''
    try:
        # Transformam in int pentru a elimina zecimalele, apoi punem virgula
        return f"{int(val):,}"
    except:
        return str(val)

def format_money_short(val):
    """Formateaza banii scurt: 1 Mil, 2 Bil (Fara zecimale)"""
    if not val: return ''
    try:
        val = float(val)
        if val >= 1000000000:
            # .0f inseamna 0 zecimale (rotunjit)
            return f"{val/1000000000:.0f} Bil"
        elif val >= 1000000:
            # .0f inseamna 0 zecimale
            return f"{val/1000000:.0f} Mil"
        else:
            # ,.0f pune virgula la mii si scoate zecimalele
            return f"{val:,.0f}"
    except:
        return str(val)

def format_date(date_str):
    if not date_str: return ''
    try:
        # Converteste din YYYY-MM-DD in DD.MM.YYYY (ex: 22.01.2025)
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%d.%m.%Y')
    except:
        return date_str

def format_date_short(date_str):
    if not date_str: return ''
    try:
        # Folosim acelasi format scurt si clar: DD.MM.YYYY
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%d.%m.%Y')
    except:
        return date_str

def calculate_age(birthday_str, deathday_str=None):
    if not birthday_str:
        return ''
    
    import time
    import xbmc

    try:
        # 1. Parsare manuala a datei nasterii (YYYY-MM-DD)
        # Ocolim complet datetime.strptime care da eroare
        parts = str(birthday_str).strip().split('-')
        if len(parts) != 3:
            return ''
        
        b_year = int(parts[0])
        b_month = int(parts[1])
        b_day = int(parts[2])
        
        # 2. Determinam data curenta (sau data decesului)
        if deathday_str and str(deathday_str).strip():
            d_parts = str(deathday_str).strip().split('-')
            if len(d_parts) == 3:
                now_year = int(d_parts[0])
                now_month = int(d_parts[1])
                now_day = int(d_parts[2])
            else:
                # Fallback la azi daca data decesului e gresita
                t = time.localtime()
                now_year, now_month, now_day = t.tm_year, t.tm_mon, t.tm_mday
        else:
            # Folosim time.localtime() care este low-level si sigur
            t = time.localtime()
            now_year, now_month, now_day = t.tm_year, t.tm_mon, t.tm_mday
            
        # 3. Calcul matematic pur (Scadem 1 daca ziua nasterii nu a trecut inca anul acesta)
        age = now_year - b_year
        if (now_month, now_day) < (b_month, b_day):
            age -= 1
            
        return str(age)
        
    except Exception as e:
        xbmc.log(f"[TMDb Extended INFO] Manual Age Calc Error: {e}", level=xbmc.LOGINFO)
        return ''

def get_kodi_library_movies():
    try:
        query = {
            "jsonrpc": "2.0",
            "method": "VideoLibrary.GetMovies",
            "params": {"properties": ["uniqueid", "year", "title", "playcount"]},
            "id": 1
        }
        response = xbmc.executeJSONRPC(json.dumps(query))
        data = json.loads(response)
        
        library_movies = {}
        if 'result' in data and 'movies' in data['result']:
            for movie in data['result']['movies']:
                unique_ids = movie.get('uniqueid', {})
                tmdb_id = unique_ids.get('tmdb', '')
                if tmdb_id:
                    library_movies[str(tmdb_id)] = {
                        'dbid': movie['movieid'],
                        'playcount': movie.get('playcount', 0)
                    }
        return library_movies
    except Exception as e:
        log(f"Error getting Kodi library: {e}")
        return {}

def get_kodi_library_tvshows():
    try:
        query = {
            "jsonrpc": "2.0",
            "method": "VideoLibrary.GetTVShows",
            "params": {"properties": ["uniqueid", "year", "title", "watchedepisodes", "episode"]},
            "id": 1
        }
        response = xbmc.executeJSONRPC(json.dumps(query))
        data = json.loads(response)
        
        library_shows = {}
        if 'result' in data and 'tvshows' in data['result']:
            for show in data['result']['tvshows']:
                unique_ids = show.get('uniqueid', {})
                tmdb_id = unique_ids.get('tmdb', '')
                if tmdb_id:
                    total_eps = show.get('episode', 0)
                    watched_eps = show.get('watchedepisodes', 0)
                    library_shows[str(tmdb_id)] = {
                        'dbid': show['tvshowid'],
                        'watched': watched_eps,
                        'unwatched': total_eps - watched_eps,
                        'playcount': 1 if watched_eps == total_eps and total_eps > 0 else 0
                    }
        return library_shows
    except Exception as e:
        log(f"Error getting Kodi TV library: {e}")
        return {}

def show_text_dialog(heading, text):
    dialog = xbmcgui.Dialog()
    dialog.textviewer(heading, text)

def control_exists(window, control_id):
    try:
        window.getControl(control_id)
        return True
    except:
        return False

def create_list_item_with_year(label, year_str, icon, media_type='video'):
    # --- 1. TITLU BOLD ---
    li = xbmcgui.ListItem(f"[B]{label}[/B]")
    
    li.setArt({'thumb': icon, 'poster': icon, 'icon': icon})
    
    if year_str:
        # --- 2. AN BOLD (Setam Proprietatea Year, nu doar InfoTag-ul) ---
        li.setProperty('Year', f"[B]{year_str}[/B]")
        li.setProperty('year', f"[B]{year_str}[/B]") # Dublura pentru siguranta
        
        # Setam si Label2 pentru skin-urile care il folosesc
        li.setLabel2(f"[B]{year_str}[/B]")
        
        try:
            # Setam si anul numeric pentru sortare interna
            year_int = int(year_str)
            video_info = li.getVideoInfoTag()
            video_info.setYear(year_int)
        except:
            pass
    
    return li

# --- CLASA SLIDESHOW BAZATA PE XML ---
class SlideShow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(SlideShow, self).__init__(*args)
        self.images = kwargs.get('images', [])
        self.index = kwargs.get('index', 0)
        self.list_id = 10001 # ID-ul listei din XML-ul tau

    def onInit(self):
        try:
            # Populam lista din XML cu imagini
            ctl = self.getControl(self.list_id)
            items = []
            for img_url in self.images:
                # Creem item-ul. Proprietatea 'Original' este folosita in XML la texture
                li = xbmcgui.ListItem(path=img_url)
                li.setProperty('Original', img_url)
                items.append(li)
            
            ctl.addItems(items)
            
            # Selectam imaginea pe care s-a dat click
            ctl.selectItem(self.index)
            # Dam focus listei pentru a putea naviga
            self.setFocusId(self.list_id)
            
        except Exception as e:
            log(f"SlideShow Init Error: {e}")
            self.close()

    def onAction(self, action):
        # Inchidem la BACK sau ESC
        if action.getId() in [ACTION_PREVIOUS_MENU, ACTION_NAV_BACK]:
            self.close()

# --- FUNCTIE APELARE (Modificata sa foloseasca XML-ul) ---
def show_full_image(window, list_id):
    try:
        ctl = window.getControl(list_id)
        size = ctl.size()
        if size == 0: return
        
        # Colectam URL-urile
        images = []
        for i in range(size):
            # In ExtendedInfo am folosit 'image_url' ca proprietate
            url = ctl.getListItem(i).getProperty('image_url')
            if url: images.append(url)
            
        if not images: return
        
        idx = ctl.getSelectedPosition()
        if idx < 0: idx = 0
        
        # Lansam fereastra folosind XML-ul tau
        # Asigura-te ca numele fisierului XML este corect!
        ss = SlideShow('ext_SlideShow.xml', ADDON_PATH, 
                       images=images, index=idx)
        ss.doModal()
        del ss
        
    except Exception as e:
        log(f"ShowImage Error: {e}")
# ---------------------------------------------------------

class SeasonInfo(xbmcgui.WindowXMLDialog):
    """Pagină pentru informații despre un sezon"""
    
    def __init__(self, *args, **kwargs):
        super(SeasonInfo, self).__init__(*args)
        self.tv_id = kwargs.get('tv_id')
        self.season_num = kwargs.get('season_num')
        self.tv_name = kwargs.get('tv_name', '')
        self.title_text = self.tv_name
        self.meta = {}
        self.episodes = []
        self.go_back = False
        self.next_info = None
        self.poster_urls = []
        self.still_urls = []
        self.showing_text_dialog = False
        self.plot_text = ''
        
        # --- MODIFICARE: Setam fundalul default ---
        bg_fallback = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
        self.setProperty('fanart', bg_fallback)
        self.setProperty('movie.ImageFilter', bg_fallback)
        self.setProperty('ImageFilter', bg_fallback)
        
    def onInit(self):
        self.setProperty('type', 'Season')
        
        # Cerem datele sezonului
        self.meta = get_tmdb_data(
            f"tv/{self.tv_id}/season/{self.season_num}",
            {'append_to_response': 'credits,images,videos', 'include_video_language': 'en,null'}
        )
        
        # FALLBACK: Dacă sezonul nu există, deschidem info de SERIAL
        if not self.meta or self.meta.get('success') == False:
            log(f"[SeasonInfo] Season {self.season_num} not found, falling back to TV show")
            self.close()
            
            try:
                from resources.lib.extended_info_mod import run_extended_info
                xbmc.sleep(100)
                run_extended_info(self.tv_id, 'tv', season=None, episode=None, tv_name=self.tv_name)
            except Exception as e:
                log(f"[SeasonInfo] Fallback error: {e}")
            return
        
        # --- FIX RATING SEZON ---
        tv_meta = get_tmdb_data(f"tv/{self.tv_id}/content_ratings")
        self.tv_mpaa = ""
        if tv_meta and 'results' in tv_meta:
            for r in tv_meta['results']:
                if r['iso_3166_1'] == 'US':
                    self.tv_mpaa = r['rating']
                    break
        
        self.episodes = self.meta.get('episodes', [])
        self.update_ui()

    def load_youtube_async(self):
        # 1. PLAN A: Google YouTube API
        # -----------------------------------------------------------------------------
        date_str = self.meta.get('release_date') or self.meta.get('first_air_date') or ''
        year = date_str[:4]
        search_query = f"{self.title_text} {year} trailer"
        
        yt_results = get_youtube_api_data(search_query)
        
        primary_list = []   # Sus (Trailere)
        secondary_list = [] # Jos (Clipuri)
        
        # =========================================================================
        # PLAN B: FALLBACK TMDb (Dacă Google API a picat)
        # =========================================================================
        if not yt_results:
            log(f"[ExtendedInfo] Google API failed. Starting TMDb Fallback for {self.title_text}.")
            
            # Pasul 1: Datele deja existente (din fetch_data)
            tmdb_videos = self.meta.get('videos', {}).get('results', [])
            
            # Verificăm rapid dacă avem trailer în datele standard
            has_trailer = any(v.get('type') in ['Trailer', 'Teaser'] for v in tmdb_videos)
            
            # Pasul 2: DEEP SCAN REGIONAL (Dacă nu avem trailer)
            if not tmdb_videos or not has_trailer:
                log("[ExtendedInfo] Missing trailer. Initiating Regional Deep Scan (Manual URL)...")
                
                # Lista de regiuni (Prioritate: Tamil pentru 'Kiss', apoi restul)
                target_locales = ['ta-IN', 'te-IN', 'kn-IN', 'ml-IN', 'hi-IN', 'pa-IN', 'en-US']
                
                # Lista de limbi (string fix, necodat) - exact ca în browser
                safe_langs = "en,null,xx,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ro"
                
                # Definim BASE_URL local
                base_api = "https://api.themoviedb.org/3"
                
                backup_videos = []
                
                for locale in target_locales:
                    try:
                        # --- MODIFICARE CRITICĂ: CONSTRUIRE URL MANUALĂ (FĂRĂ params={}) ---
                        # Asta previne codarea virgulei în %2C care strică request-ul la TMDb
                        deep_url = (f"{base_api}/{self.media_type}/{self.tmdb_id}/videos"
                                    f"?api_key={API_KEY}"
                                    f"&language={locale}"
                                    f"&include_video_language={safe_langs}")
                        
                        # Request simplu, fără params
                        r = requests.get(deep_url, timeout=2)
                        
                        if r.status_code == 200:
                            data_vid = r.json()
                            found = data_vid.get('results', [])
                            
                            if found:
                                # Căutăm AURUL (Trailer/Teaser)
                                found_trailer_here = False
                                for v in found:
                                    if v.get('type') in ['Trailer', 'Teaser']:
                                        found_trailer_here = True
                                        break
                                
                                if found_trailer_here:
                                    log(f"[ExtendedInfo] FOUND TRAILER in locale: {locale}")
                                    tmdb_videos = found
                                    break # GATA! Am găsit trailer valid.
                                else:
                                    # Am găsit doar clipuri, le păstrăm de rezervă
                                    if not backup_videos:
                                        backup_videos = found
                                        
                    except Exception as e:
                        log(f"[ExtendedInfo] Deep scan error on {locale}: {e}")
                
                # Dacă nu am găsit trailer, folosim clipurile de rezervă
                has_new_trailer = any(v.get('type') in ['Trailer', 'Teaser'] for v in tmdb_videos)
                if not has_new_trailer and backup_videos:
                    log("[ExtendedInfo] No trailer found in Deep Scan. Using backup clips.")
                    tmdb_videos = backup_videos

            # Procesare finală a listei (Conversie format TMDb -> Format ExtendedInfo)
            for v in tmdb_videos:
                if v.get('site') != 'YouTube':
                    continue
                    
                v_key = v.get('key')
                v_type = v.get('type', 'Video')
                v_name = v.get('name', 'Unknown')
                v_iso = v.get('iso_639_1', 'en')
                
                # Adăugăm eticheta de limbă la titlu
                if v_iso not in ['en', 'xx', 'null']:
                    v_name = f"[{v_iso.upper()}] {v_name}"
                
                is_trailer = v_type in ['Trailer', 'Teaser']
                
                video_obj = {
                    'name': v_name,
                    'key': v_key,
                    'type': v_type,
                    'official': True,
                    'thumb': f"https://img.youtube.com/vi/{v_key}/mqdefault.jpg",
                    'published_at': v.get('published_at', ''),
                    'lang': v_iso
                }
                
                if is_trailer:
                    primary_list.append(video_obj)
                else:
                    secondary_list.append(video_obj)
            
            # Sortare: Limba originală sus
            orig_lang = self.meta.get('original_language', 'en')
            def smart_sort(x):
                l = x['lang']
                if l == orig_lang: return 0
                if l == 'ro': return 1
                if l == 'en': return 2
                return 3
            primary_list.sort(key=smart_sort)

        # =========================================================================
        # 3. ZONA STANDARD (Google API a reușit)
        # =========================================================================
        else:
            for item in yt_results:
                snippet = item.get('snippet', {})
                video_id = item.get('id', {}).get('videoId')
                if not video_id: continue
                
                raw_title = html.unescape(snippet.get('title', ''))
                title = ""
                for char in raw_title:
                    if ord(char) < 60000: title += char
                
                title_lower = title.lower()
                is_trailer = 'trailer' in title_lower or 'teaser' in title_lower
                
                video_obj = {
                    'name': title,
                    'key': video_id,
                    'type': 'Trailer' if is_trailer else 'Clip',
                    'official': is_trailer,
                    'thumb': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'published_at': snippet.get('publishedAt', '')
                }
                
                if is_trailer: primary_list.append(video_obj)
                else: secondary_list.append(video_obj)
        
        # Trimitem listele la interfață
        if not primary_list and not secondary_list:
             log("[ExtendedInfo] No videos found via API or Fallback.")
             
        self.fill_video_list(1150, primary_list)
        self.fill_video_list(350, secondary_list)

    def update_ui(self):
        season_name = self.meta.get('name', f'Season {self.season_num}')
        self.plot_text = self.meta.get('overview', '') or f"Season {self.season_num} of {self.tv_name}"
        air_date = self.meta.get('air_date', '')
        # Data formatata frumos
        air_date_formatted = format_date_short(air_date)
        # Data simpla (anul)
        year = air_date[:4] if air_date else ''
        
        poster = IMG_BASE + self.meta.get('poster_path', '') if self.meta.get('poster_path') else ''
        ep_count = len(self.episodes)
        
        # --- NOU: TITLU COMPLET ---
        # Format: "Fallout - Season 2"
        if self.tv_name:
            full_title = f"{self.tv_name} - {season_name}"
        else:
            full_title = season_name
        
        # Actualizam title_text pentru YouTube trailer search
        self.title_text = self.tv_name if self.tv_name else season_name
        # --------------------------
        
        # --- TITLURI ---
        self.setProperty('movie.title', full_title)      # ERA: season_name
        self.setProperty('movie.Title', full_title)      # ERA: season_name
        self.setProperty('title', full_title)            # ERA: season_name
        self.setProperty('movie.originaltitle', season_name)  # ERA: self.tv_name
        
        # --- DATA (SOLUTIE AGRESIVA) ---
        # 1. Setam data formatata in toate proprietatile de data
        self.setProperty('movie.Premiered', air_date_formatted)
        self.setProperty('movie.release_date', air_date_formatted)
        self.setProperty('movie.ReleaseDate', air_date_formatted)
        self.setProperty('Premiered', air_date_formatted)
        self.setProperty('ReleaseDate', air_date_formatted)
        self.setProperty('Date', air_date_formatted) # Uneori XML-ul cauta 'Date'
        
        # 2. Setam ANUL (uneori e folosit ca fallback)
        self.setProperty('movie.year', year)
        self.setProperty('movie.Year', year)
        self.setProperty('year', year)
        
        # 3. TRUC: Setam Status-ul cu DATA -> MODIFICAT
        # Lasam gol pentru ca XML-ul sa foloseasca fallback-ul si sa scrie "Release Date"
        self.setProperty('Status', "")
        self.setProperty('movie.Status', "")
        
        # Setam Rating-ul Serialului la Sezon (ca sa nu mai apara NR)
        if hasattr(self, 'tv_mpaa') and self.tv_mpaa:
            self.setProperty('movie.mpaa', self.tv_mpaa)
        
        # 4. TRUC: Setam Studio cu DATA (daca studio e gol)
        self.setProperty('movie.Studio', air_date_formatted)
        self.setProperty('Studio', air_date_formatted)

        # --- EPISOADE SI DURATION ---
        self.setProperty('TotalEpisodes', str(ep_count))
        self.setProperty('episode_count', str(ep_count))
        
        # Ascundem duration (setam gol pentru a dezactiva grupul "Duration" din XML)
        self.setProperty('movie.duration', "")
        self.setProperty('duration', "")
        
        # --- TAGLINE ---
        # Punem "8 Episodes" in tagline daca nu apare altundeva
        self.setProperty('Tagline', f"{ep_count} Episodes")
        self.setProperty('movie.Tagline', f"{ep_count} Episodes")

        # --- RESTUL ---
        self.setProperty('movie.plot', self.plot_text)
        self.setProperty('movie.Plot', self.plot_text)
        self.setProperty('plot', self.plot_text)
        self.setProperty('movie.poster', poster)
        self.setProperty('poster', poster)
        
        if self.episodes and self.episodes[0].get('still_path'):
            fanart = BACKDROP_BASE + self.episodes[0]['still_path']
            self.setProperty('movie.fanart', fanart)
            self.setProperty('fanart', fanart)
            # COMENTAM linia veche ca sa nu puna imaginea episodului ca fundal
            # self.setProperty('ImageFilter', fanart)

        # --- MODIFICARE BACKGROUND SEZON ---
        texture_path = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
        self.setProperty('movie.ImageFilter', texture_path)
        self.setProperty('ImageFilter', texture_path)
        # -----------------------------------
        
        if self.episodes:
            avg_rating = sum(e.get('vote_average', 0) for e in self.episodes) / len(self.episodes)
            self.setProperty('movie.rating', f"{avg_rating:.1f}")
            self.setProperty('movie.Rating', f"{avg_rating:.1f}")
        
        self.setProperty('PlayButtonLabel', "Browse Episodes")
        
        # --- LISTE (neschimbate) ---
        self.fill_episode_list(2000, self.episodes)
        
        # LANSARE YOUTUBE IN FUNDAL
        t = threading.Thread(target=self.load_youtube_async)
        t.daemon = True  # <--- LINIE NOUA: Opreste thread-ul la iesire
        t.start()
        
        cast = self.meta.get('credits', {}).get('cast', [])[:20]
        self.fill_cast_list(1000, cast)
        posters = self.meta.get('images', {}).get('posters', [])
        self.poster_urls = [IMG_FULL + p['file_path'] for p in posters if p.get('file_path')]
        self.fill_image_list(1250, posters, 'poster')
        stills = []
        for ep in self.episodes:
            if ep.get('still_path'):
                stills.append({'file_path': ep['still_path']})
        self.still_urls = [BACKDROP_BASE + s['file_path'] for s in stills]
        self.fill_image_list(1350, stills, 'backdrop')
        
        # --- MODIFICARE FOCUS: Setam focus pe butonul PLAY (8) ---
        try: self.setFocusId(8)
        except: pass
        
    
    def fill_episode_list(self, list_id, episodes):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            items = []
            
            for idx, ep in enumerate(episodes):
                ep_num = ep.get('episode_number', 0)
                ep_name = ep.get('name', f'Episode {ep_num}')
                still = f"https://image.tmdb.org/t/p/w500{ep['still_path']}" if ep.get('still_path') else 'DefaultVideo.png'
                air_date = format_date_short(ep.get('air_date', ''))
                
                # --- MODIFICARE: Titlu BOLD ---
                # XML-ul pune punctul automat, noi doar ingrosam textul
                li = xbmcgui.ListItem(f"[B]{ep_name}[/B]")
                # ------------------------------
                
                v_tag = li.getVideoInfoTag()
                try: v_tag.setEpisode(int(ep_num))
                except: pass
                v_tag.setTitle(ep_name)
                v_tag.setMediaType('episode')
                
                # --- MODIFICARE: Data BOLD ---
                if air_date:
                    li.setProperty('release_date', f"[B]{air_date}[/B]")
                # -----------------------------
                
                li.setArt({'thumb': still, 'icon': still, 'poster': still})
                li.setProperty('episode_number', str(ep_num))
                li.setProperty('media_type', 'episode')
                li.setProperty('DBTYPE', 'episode')
                li.setProperty('overview', ep.get('overview', ''))
                li.setProperty('rating', str(ep.get('vote_average', 0)))
                li.setProperty('Premiered', air_date)
                
                if trakt_sync.is_episode_watched(self.tv_id, self.season_num, ep_num):
                    li.setProperty('PlayCount', '1')
                    li.setProperty('Overlay', 'Watched')
                    v_tag.setPlaycount(1)
                else:
                    li.setProperty('PlayCount', '0')
                
                items.append(li)
            
            ctl.addItems(items)
        except Exception as e:
            log(f"Error filling episode list: {e}")

    def fill_video_list(self, list_id, videos):
        # --- FUNCȚIE VIDEO SEZON (MODIFICATĂ PENTRU GOOGLE API) ---
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            
            list_items = []
            
            for v in videos:
                label = v.get('name', 'Video')
                # Tipul (Trailer, Recap, Clip) determinat in update_ui
                v_type = v.get('type', 'Video')
                
                is_off = v.get('official', False)
                official_str = "Official" if is_off else "Standard"
                
                date_str = v.get('published_at', '')[:4]
                
                label2 = f"{official_str} {v_type}"
                if date_str:
                    label2 += f" • {date_str}"
                
                key = v.get('key')
                if not key: continue
                
                # Thumbnail
                icon = v.get('thumb')
                if not icon:
                    icon = f"https://img.youtube.com/vi/{key}/mqdefault.jpg"
                
                li = xbmcgui.ListItem(label)
                li.setLabel2(label2)
                li.setArt({'thumb': icon, 'icon': icon})
                li.setProperty('youtube_id', key)
                
                list_items.append(li)
            
            ctl.addItems(list_items)
        except Exception as e:
            pass # Ignoram erorile minore de UI
    
    def fill_cast_list(self, list_id, cast):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            items = []
            for c in cast:
                name = c.get('name', '')
                character = c.get('character', '')
                
                # Numele actorului (Bold)
                li = xbmcgui.ListItem(f"[B]{name}[/B]")
                
                # --- MODIFICARE: Alias PINK BOLD ---
                if character:
                    formatted_char = f"[B][COLOR FFFF69B4]{character}[/COLOR][/B]"
                    li.setLabel2(formatted_char)
                    li.setProperty('character', formatted_char)
                    li.setProperty('role', formatted_char)
                # -----------------------------------
                
                # MODIFICARE: Folosim IMG_THUMB_SMALL pentru viteza
                icon = IMG_THUMB_SMALL + c['profile_path'] if c.get('profile_path') else 'DefaultActor.png'
                li.setArt({'thumb': icon, 'icon': icon})
                li.setProperty('id', str(c.get('id', '')))
                items.append(li)
            ctl.addItems(items)
        except Exception as e: pass
    
    def fill_image_list(self, list_id, images, img_type):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            items = []
            base = IMG_FULL if img_type == 'poster' else BACKDROP_BASE
            for idx, img in enumerate(images):
                path = img.get('file_path', '')
                if not path: continue
                url = base + path
                li = xbmcgui.ListItem()
                li.setArt({'thumb': url, 'icon': url})
                li.setProperty('image_url', url)
                items.append(li)
            ctl.addItems(items)
        except Exception as e: pass
    
    def onAction(self, action):
        if action.getId() in [ACTION_PREVIOUS_MENU, ACTION_NAV_BACK]:
            self.go_back = True
            self.close()
    
    def onClick(self, controlId):
        # PLAY -> Sezon
        if controlId == 8:
            # --- MODIFICARE: AM SCOS self.close() ---
            action_play_dialog(
                self.tv_id, 
                'season', 
                season=self.season_num, 
                title=self.tv_name
            )

        elif controlId == 445: action_open_settings()
        elif controlId == 447: action_refresh_trakt()
        elif controlId == 446: self.close()

        # --- RESTUL ---
        elif controlId == 132: # Plot
            if self.plot_text and not self.showing_text_dialog:
                self.showing_text_dialog = True
                show_text_dialog(f"Season {self.season_num}", self.plot_text)
                self.showing_text_dialog = False

        elif controlId == 2000: # Episodes List
            item = self.getControl(2000).getSelectedItem()
            if item:
                ep_num = item.getProperty('episode_number')
                self.next_info = ('episode', ep_num)
                self.close()
        
        elif controlId == 1150: # Videos
            item = self.getControl(1150).getSelectedItem()
            yt_id = item.getProperty('youtube_id')
            if yt_id:
                self.next_info = ('youtube_play', yt_id)
                self.close()
        
        elif controlId == 1000: # Cast
            item = self.getControl(1000).getSelectedItem()
            if item and item.getProperty('id'):
                self.next_info = ('actor', item.getProperty('id'))
                self.close()
        
        elif controlId == 1250: show_full_image(self, 1250)
        elif controlId == 1350: show_full_image(self, 1350)


class EpisodeInfo(xbmcgui.WindowXMLDialog):
    """Pagină pentru informații despre un episod"""
    
    def __init__(self, *args, **kwargs):
        super(EpisodeInfo, self).__init__(*args)
        self.tv_id = kwargs.get('tv_id')
        self.season_num = kwargs.get('season_num')
        self.episode_num = kwargs.get('episode_num')
        self.tv_name = kwargs.get('tv_name', '')
        self.meta = {}
        self.go_back = False
        self.next_info = None
        self.plot_text = ''
        self.showing_text_dialog = False
        self.still_urls = []
        
    def onInit(self):
        log(f"[EpisodeInfo] Opening S{self.season_num}E{self.episode_num} for TV ID {self.tv_id}")
        self.setProperty('type', 'Episode') 
        
        try:
            self.meta = get_tmdb_data(
                f"tv/{self.tv_id}/season/{self.season_num}/episode/{self.episode_num}",
                {'append_to_response': 'credits,images,videos', 'include_video_language': 'en,null'}
            )
            
            # FALLBACK: Dacă episodul nu există, deschidem info de SERIAL
            if not self.meta or self.meta.get('success') == False:
                log(f"[EpisodeInfo] Episode S{self.season_num}E{self.episode_num} not found, falling back to TV show")
                self.close()
                
                # Lansăm dialogul pentru serial în loc de episod
                try:
                    # Închidem acest dialog și deschidem TVShowInfo
                    from resources.lib.extended_info_mod import run_extended_info
                    xbmc.sleep(100)  # Mică pauză pentru a permite închiderea
                    run_extended_info(self.tv_id, 'tv', season=None, episode=None, tv_name=self.tv_name)
                except Exception as e:
                    log(f"[EpisodeInfo] Fallback error: {e}")
                return
            
            self.update_ui()
        except Exception as e:
            log(f"[EpisodeInfo] Error in onInit: {e}")
            self.close()
    def update_ui(self):
        try:
            ep_name = self.meta.get('name', f'Episode {self.episode_num}')
            self.plot_text = self.meta.get('overview', 'No overview available.')
            
            air_date = self.meta.get('air_date', '')
            # Format: January 01, 2024
            air_date_formatted = format_date_short(air_date) 
            
            # Daca nu avem data formatata, punem anul sau string gol
            if not air_date_formatted:
                air_date_formatted = air_date[:4] if air_date else ''

            rating = self.meta.get('vote_average', 0)
            still = BACKDROP_BASE + self.meta.get('still_path', '') if self.meta.get('still_path') else ''
            
            # NOU: Titlu complet
            season_str = f"S{int(self.season_num):02d}"
            episode_str = f"E{int(self.episode_num):02d}"

            # Format: "Fallout - S02E08 - The Strip"
            if self.tv_name:
                title = f"{self.tv_name} - {season_str}{episode_str} - {ep_name}"
            else:
                title = f"{season_str}{episode_str} - {ep_name}"

            full_title = title

            # --- TITLE & SUBTITLE ---
            self.setProperty('movie.title', title)
            self.setProperty('movie.Title', title)
            self.setProperty('title', title)
            self.setProperty('movie.originaltitle', ep_name)  # Numele original al episodului
            
            # --- RATING ---
            if rating:
                self.setProperty('movie.rating', f"{rating:.1f}")
                self.setProperty('movie.Rating', f"{rating:.1f}")
            
            # --- DATE (SOLUTIA PENTRU AFISARE SUS) ---
            # 1. Setam proprietatea 'release_date' (lowercase) exact cum ai facut la lista
            self.setProperty('release_date', air_date_formatted)
            self.setProperty('movie.release_date', air_date_formatted)
            
            # 2. Setam si variantele clasice
            self.setProperty('movie.Premiered', air_date_formatted)
            self.setProperty('Premiered', air_date_formatted)
            
            # 3. TRUC: Unele skin-uri afiseaza sus doar 'Year'. 
            # Fortam data completa in campul Year ca sa fim siguri ca apare ceva.
            self.setProperty('year', air_date_formatted)
            self.setProperty('movie.year', air_date_formatted)
            self.setProperty('movie.Year', air_date_formatted)
            
            # --- PLOT ---
            self.setProperty('movie.plot', self.plot_text)
            self.setProperty('movie.Plot', self.plot_text)
            self.setProperty('plot', self.plot_text)
            
            # --- ARTWORK ---
            if still:
                self.setProperty('movie.poster', still)
                self.setProperty('movie.fanart', still)
                self.setProperty('fanart', still)
                # COMENTAM linia veche
                # self.setProperty('ImageFilter', still)
            
            # --- MODIFICARE BACKGROUND EPISOD ---
            texture_path = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
            self.setProperty('movie.ImageFilter', texture_path)
            self.setProperty('ImageFilter', texture_path)
            # ------------------------------------
            self.setProperty('PlayButtonLabel', "Play")
            
            # --- LISTE ---
            guest_stars = self.meta.get('guest_stars', [])
            regular_cast = self.meta.get('credits', {}).get('cast', [])
            all_cast = guest_stars + regular_cast
            self.fill_cast_list(1000, all_cast[:30])
            
            stills = self.meta.get('images', {}).get('stills', [])
            self.still_urls = [IMG_FULL + s['file_path'] for s in stills if s.get('file_path')]
            self.fill_image_list(1350, stills)
            
            # --- MODIFICARE FOCUS: Setam focus pe butonul PLAY (8) ---
            try: self.setFocusId(8)
            except: pass
            # ---------------------------------------------------------

        except Exception as e:
            log(f"[EpisodeInfo] Error in update_ui: {e}")
    
    def fill_cast_list(self, list_id, cast):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            items = []
            for c in cast:
                name = c.get('name', '')
                character = c.get('character', '')
                
                # --- FIX: Numele actorului BOLD ---
                li = xbmcgui.ListItem(f"[B]{name}[/B]")
                
                # --- FIX: Alias PINK BOLD (ca la Sezoane/Filme) ---
                if character:
                    formatted_char = f"[B][COLOR FFFF69B4]{character}[/COLOR][/B]"
                    li.setLabel2(formatted_char)
                    li.setProperty('character', formatted_char)
                    li.setProperty('role', formatted_char)
                
                icon = IMG_THUMB_SMALL + c['profile_path'] if c.get('profile_path') else 'DefaultActor.png'
                li.setArt({'thumb': icon, 'icon': icon})
                li.setProperty('id', str(c.get('id', '')))
                items.append(li)
            ctl.addItems(items)
        except: pass
    
    def fill_image_list(self, list_id, images):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            items = []
            for idx, img in enumerate(images):
                path = img.get('file_path', '')
                if not path: continue
                url = BACKDROP_BASE + path
                li = xbmcgui.ListItem()
                li.setArt({'thumb': url, 'icon': url})
                li.setProperty('image_url', url)
                items.append(li)
            ctl.addItems(items)
        except: pass
    
    def onAction(self, action):
        if action.getId() in [ACTION_PREVIOUS_MENU, ACTION_NAV_BACK]:
            self.go_back = True
            self.close()
    
    def onClick(self, controlId):
        # PLAY -> Episod
        if controlId == 8:
            # --- MODIFICARE: AM SCOS self.close() ---
            display_title = f"{self.tv_name} S{int(self.season_num):02d}E{int(self.episode_num):02d}"
            
            action_play_dialog(
                self.tv_id, 
                'episode', 
                season=self.season_num, 
                episode=self.episode_num,
                title=display_title 
            )

        elif controlId == 445: action_open_settings()
        elif controlId == 447: action_refresh_trakt()
        elif controlId == 446: self.close()

        # --- RESTUL ---
        elif controlId == 132: # Plot
            if self.plot_text and not self.showing_text_dialog:
                self.showing_text_dialog = True
                show_text_dialog("Overview", self.plot_text)
                self.showing_text_dialog = False
        
        elif controlId == 1000: # Actor
            item = self.getControl(1000).getSelectedItem()
            if item and item.getProperty('id'):
                self.next_info = ('actor', item.getProperty('id'))
                self.close()
        
        elif controlId == 1350: show_full_image(self, 1350)


class ExtendedInfo(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(ExtendedInfo, self).__init__(*args)
        self.tmdb_id = kwargs.get('tmdb_id')
        self.media_type = kwargs.get('media_type', 'movie')
        self.meta = {}
        self.plot_text = ''
        self.title_text = ''
        self.showing_text_dialog = False
        self.go_back = False
        self.next_info = None
        
        self.kodi_movies = {}
        self.kodi_tvshows = {}
        
        # --- MODIFICARE: Folosim direct texture.png ---
        bg_fallback = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
            
        self.setProperty('movie.fanart', bg_fallback)
        self.setProperty('fanart', bg_fallback)
        self.setProperty('ImageColor', 'FF000000')
        self.setProperty('ImageFilter', bg_fallback)
        self.setProperty('WindowColor', 'FF000000')
        self.setProperty('script.extendedinfo_running', 'True')

    def onInit(self):
        self.kodi_movies = get_kodi_library_movies()
        self.kodi_tvshows = get_kodi_library_tvshows()
        self.fetch_data()
        
    def fetch_data(self):
        # 1. Cerem metadate + VIDEOS + Limbi Indiene
        # Adaugam 'videos' si toate limbile regionale in apelul principal
        append = "credits,recommendations,similar,images,external_ids,release_dates,content_ratings,videos"
        
        endpoint = f"{self.media_type}/{self.tmdb_id}"
        
        # LISTA COMPLETĂ DE CODURI (Copiaz-o exact așa)
        # hi=Hindi, ta=Tamil, te=Telugu, ml=Malayalam, kn=Kannada, bn=Bengali, pa=Punjabi
        all_langs = "en,null,xx,ro,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ru,pt,zh,ja,ko"
        
        params = {
            'append_to_response': append,
            'include_video_language': all_langs
        }
        
        data = get_tmdb_data(endpoint, params)
        
        if not data:
            self.close()
            return

        self.meta = data
        self.plot_text = self.meta.get('overview', '')
        self.title_text = self.meta.get('title') or self.meta.get('name', '')
        
        # --- LOGICA COLECȚIEI ---
        self.collection_items = []
        if self.media_type == 'movie' and self.meta.get('belongs_to_collection'):
            coll_id = self.meta['belongs_to_collection']['id']
            coll_data = get_tmdb_data(f"collection/{coll_id}")
            if coll_data:
                self.collection_items = coll_data.get('parts', [])
                self.collection_items.sort(key=lambda x: x.get('release_date', ''), reverse=False)
                
                coll_name = coll_data.get('name', '')
                coll_poster = IMG_BASE + coll_data.get('poster_path', '') if coll_data.get('poster_path') else ''
                coll_backdrop = BACKDROP_BASE + coll_data.get('backdrop_path', '') if coll_data.get('backdrop_path') else ''
                coll_overview = coll_data.get('overview', '')
                
                self.setProperty('movie.set.label', coll_name)
                self.setProperty('movie.set.id', str(coll_id))
                self.setProperty('movie.set.poster', coll_poster)
                self.setProperty('movie.set.thumb', coll_poster)
                self.setProperty('movie.set.fanart', coll_backdrop)
                self.setProperty('movie.set.overview', coll_overview)
                
        # Seasons
        self.seasons_items = []
        if self.media_type == 'tv':
            seasons = self.meta.get('seasons', [])
            self.seasons_items = [s for s in seasons if s.get('season_number', 0) > 0]
            self.setProperty('TotalSeasons', str(self.meta.get('number_of_seasons', len(self.seasons_items))))
            self.setProperty('TotalEpisodes', str(self.meta.get('number_of_episodes', 0)))

        self.update_ui()
        
        try: self.setFocusId(8)
        except: pass

    def load_youtube_async(self):
        # 1. PLAN A: Google YouTube API
        date_str = self.meta.get('release_date') or self.meta.get('first_air_date') or ''
        year = date_str[:4]
        search_query = f"{self.title_text} {year} trailer"
        
        yt_results = get_youtube_api_data(search_query)
        
        primary_list = []
        secondary_list = []
        
        # =========================================================================
        # PLAN B: FALLBACK TMDb
        # =========================================================================
        if not yt_results:
            log(f"[ExtendedInfo] Google API failed. Starting TMDb Fallback for {self.title_text}.")
            
            # Pasul 1: Verificăm datele deja descărcate prin fetch_data
            tmdb_videos = self.meta.get('videos', {}).get('results', [])
            
            # Verificăm dacă avem trailer valid
            has_trailer = any(v.get('type') in ['Trailer', 'Teaser'] for v in tmdb_videos)
            
            # Pasul 2: DEEP SCAN REGIONAL (doar dacă nu avem trailer)
            if not tmdb_videos or not has_trailer:
                log("[ExtendedInfo] Missing trailer. Initiating Regional Deep Scan...")
                
                # Lista de regiuni - AICI TREBUIE SĂ FIE LISTA COMPLETĂ
                target_locales = ['ta-IN', 'te-IN', 'kn-IN', 'ml-IN', 'hi-IN', 'pa-IN', 'en-US']
                
                # Limbile acceptate
                safe_langs = "en,null,xx,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ro"
                
                base_api = "https://api.themoviedb.org/3"
                backup_videos = []
                
                for locale in target_locales:
                    try:
                        # Construim URL-ul manual
                        deep_url = (f"{base_api}/{self.media_type}/{self.tmdb_id}/videos"
                                    f"?api_key={API_KEY}"
                                    f"&language={locale}"
                                    f"&include_video_language={safe_langs}")
                        
                        r = requests.get(deep_url, timeout=3) # Timeout mai mare (3s)
                        
                        if r.status_code == 200:
                            data_vid = r.json()
                            found = data_vid.get('results', [])
                            
                            if found:
                                # Cautam Trailer
                                found_trailer_here = False
                                for v in found:
                                    if v.get('type') in ['Trailer', 'Teaser']:
                                        found_trailer_here = True
                                        break
                                
                                if found_trailer_here:
                                    log(f"[ExtendedInfo] FOUND TRAILER in locale: {locale}")
                                    tmdb_videos = found
                                    break 
                                else:
                                    if not backup_videos: backup_videos = found
                        else:
                            log(f"[ExtendedInfo] API Error {r.status_code} for locale {locale}")
                                        
                    except Exception as e:
                        log(f"[ExtendedInfo] Deep scan error on {locale}: {e}")
                
                if not tmdb_videos and backup_videos:
                    log("[ExtendedInfo] Using backup clips from Deep Scan.")
                    tmdb_videos = backup_videos

            # Procesare finală
            for v in tmdb_videos:
                if v.get('site') != 'YouTube': continue
                    
                v_key = v.get('key')
                v_type = v.get('type', 'Video')
                v_name = v.get('name', 'Unknown')
                v_iso = v.get('iso_639_1', 'en')
                
                if v_iso not in ['en', 'xx', 'null']:
                    v_name = f"[{v_iso.upper()}] {v_name}"
                
                is_trailer = v_type in ['Trailer', 'Teaser']
                
                video_obj = {
                    'name': v_name,
                    'key': v_key,
                    'type': v_type,
                    'official': True,
                    'thumb': f"https://img.youtube.com/vi/{v_key}/mqdefault.jpg",
                    'published_at': v.get('published_at', ''),
                    'lang': v_iso
                }
                
                if is_trailer: primary_list.append(video_obj)
                else: secondary_list.append(video_obj)
            
            # Sortare
            orig_lang = self.meta.get('original_language', 'en')
            def smart_sort(x):
                l = x['lang']
                if l == orig_lang: return 0
                if l == 'ro': return 1
                if l == 'en': return 2
                return 3
            primary_list.sort(key=smart_sort)

        # =========================================================================
        # ZONA STANDARD (Google API)
        # =========================================================================
        else:
            for item in yt_results:
                snippet = item.get('snippet', {})
                video_id = item.get('id', {}).get('videoId')
                if not video_id: continue
                
                raw_title = html.unescape(snippet.get('title', ''))
                title = ""
                for char in raw_title:
                    if ord(char) < 60000: title += char
                
                title_lower = title.lower()
                is_trailer = 'trailer' in title_lower or 'teaser' in title_lower
                
                video_obj = {
                    'name': title,
                    'key': video_id,
                    'type': 'Trailer' if is_trailer else 'Clip',
                    'official': is_trailer,
                    'thumb': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'published_at': snippet.get('publishedAt', '')
                }
                
                if is_trailer: primary_list.append(video_obj)
                else: secondary_list.append(video_obj)
        
        self.fill_video_list(1150, primary_list)
        self.fill_video_list(350, secondary_list)

    def update_ui(self):
        title = self.meta.get('title') or self.meta.get('name')
        plot = self.meta.get('overview', '')
        rating = str(round(self.meta.get('vote_average', 0), 1))
        votes = f"{self.meta.get('vote_count', 0):,}"
        
        # --- DATA & STATUS FIX ---
        raw_date = self.meta.get('release_date') or self.meta.get('first_air_date') or ''
        year = raw_date[:4]
        
        # 1. AICI FORMATAM DATA (DD.MM.YYYY)
        formatted_date = format_date(raw_date)
        # ------------------------------------
        
        raw_status = self.meta.get('status', '')
        status = raw_status 
        status_map = {
            'released': 'Released', 'post production': 'Post production',
            'in production': 'In production', 'ended': 'Ended',
            'returning series': 'Continuing', 'planned': 'Planned', 'canceled': 'Canceled'
        }
        if raw_status.lower() in status_map:
            status = status_map[raw_status.lower()]

        # Durata
        duration = ""
        if self.media_type == 'movie':
            r = self.meta.get('runtime', 0)
            if r: duration = f"{r // 60}h {r % 60}m"
        else:
            r = self.meta.get('episode_run_time', [])
            if r: duration = f"{r[0]} min"

        studio = ""
        if self.media_type == 'movie':
            if self.meta.get('production_companies'): studio = self.meta['production_companies'][0]['name']
        else:
            if self.meta.get('networks'): studio = self.meta['networks'][0]['name']

        mpaa = ""
        if self.media_type == 'movie':
            rels = self.meta.get('release_dates', {}).get('results', [])
            for r in rels:
                if r['iso_3166_1'] == 'US':
                    for c in r['release_dates']:
                        if c['certification']: mpaa = c['certification']; break
        else:
            rels = self.meta.get('content_ratings', {}).get('results', [])
            for r in rels:
                if r['iso_3166_1'] == 'US': mpaa = r['rating']; break

        poster = IMG_BASE + self.meta.get('poster_path', '') if self.meta.get('poster_path') else ''
        
        fanart = ""
        if self.meta.get('backdrop_path'):
            fanart = BACKDROP_BASE + self.meta.get('backdrop_path')
        
        logo = ""
        logos = [x['file_path'] for x in self.meta.get('images', {}).get('logos', []) if x.get('iso_639_1') == 'en']
        if logos: logo = IMG_BASE + logos[0]

        budget = format_money_short(self.meta.get('budget', 0))
        revenue = format_money_short(self.meta.get('revenue', 0))

        # --- PROPRIETĂȚI COMPLETE DIAMOND INFO ---
        props = {
            'title': title, 'Title': title,
            'originaltitle': self.meta.get('original_title') or self.meta.get('original_name', title), 
            'plot': plot, 'Plot': plot,
            'rating': rating, 'Rating': rating,
            'votes': votes, 'Votes': votes,
            'year': year, 'Year': year,
            'duration': duration, 'Duration': duration,
            'studio': studio, 'Studio': studio,
            'mpaa': mpaa, 'MPAA': mpaa,
            'poster': poster, 'Poster': poster,
            'clearlogo': logo, 'logo': logo,
            'Budget': budget, 'Revenue': revenue,
            'Status': status,
            
            # 2. FOLOSIM DATA FORMATA PESTE TOT
            'Premiered': formatted_date,    # Era raw_date
            'Release_Date': formatted_date, # Era raw_date
            'ReleaseDate': formatted_date,  # Era release_date_formatted (neformatat inainte)
            
            'dbid': '0', 'imdbnumber': self.meta.get('external_ids', {}).get('imdb_id', '')
        }
        
        # --- MODIFICARE BACKGROUND (TEXTURE.PNG) ---
        texture_path = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')

        if fanart:
            props['fanart'] = fanart
            props['Fanart'] = fanart

        self.setProperty('movie.ImageFilter', texture_path)
        self.setProperty('ImageFilter', texture_path)
        # -------------------------------------------
        
        # Eticheta dinamica pentru buton
        btn_label = "Play" if self.media_type == 'movie' else "Browse"
        self.setProperty('PlayButtonLabel', btn_label)

        for k, v in props.items():
            self.setProperty(f'movie.{k}', str(v))
            self.setProperty(k, str(v))
            
        # Log DEBUG
        log(f"UPDATE_UI: Title={title}, Status={status}, Background={texture_path}")
            
        # Log DEBUG pentru a verifica daca Status se seteaza
        log(f"UPDATE_UI: Title={title}, Status={status}, Budget={budget}")

        # --- OPTIMIZARE: POPULARE LISTE IN FUNDAL (THREADING) ---
        # Asta face ca fereastra sa apara INSTANT, iar listele se incarca imediat dupa.
        def populate_lists_worker():
            # 1. Colectie / Sezoane
            if self.media_type == 'movie' and self.collection_items:
                self.fill_media_list(250, self.collection_items, 'movie')
            elif self.media_type == 'tv' and self.seasons_items:
                self.fill_season_list(250, self.seasons_items)
                    
            # 2. Actori
            cast = self.meta.get('credits', {}).get('cast', [])
            if self.media_type == 'tv': cast = cast[:20]
            self.fill_actor_list(1000, cast)
            
            # 3. Recomandari
            recommendations = self.meta.get('recommendations', {}).get('results', [])
            if not recommendations:
                recommendations = self.meta.get('similar', {}).get('results', [])
            if recommendations:
                recommendations = self.sort_by_library_and_year(recommendations, self.media_type)
                self.fill_media_list(150, recommendations, self.media_type)

            # 4. Imagini (Posters & Backdrops)
            posters = self.meta.get('images', {}).get('posters', [])
            self.fill_image_list(1250, posters, 'poster')
            
            backdrops = self.meta.get('images', {}).get('backdrops', [])
            self.fill_image_list(1350, backdrops, 'backdrop')

            # 5. YouTube (Ultimul pas)
            self.load_youtube_async()

        # Lansam worker-ul
        t = threading.Thread(target=populate_lists_worker)
        t.daemon = True  # <--- LINIE NOUA: Permite iesirea rapida fara buffering
        t.start()
        # --------------------------------------------------------

    def sort_by_library_and_year(self, items, media_type):
        in_library = []
        not_in_library = []
        library = self.kodi_movies if media_type == 'movie' else self.kodi_tvshows
        
        for item in items:
            tmdb_id_str = str(item.get('id', ''))
            year_str = (item.get('release_date') or item.get('first_air_date') or '')[:4]
            try: year_int = int(year_str) if year_str else 0
            except: year_int = 0
            item['_year_int'] = year_int
            if tmdb_id_str in library: in_library.append(item)
            else: not_in_library.append(item)
        
        in_library.sort(key=lambda x: x['_year_int'], reverse=True)
        not_in_library.sort(key=lambda x: x['_year_int'], reverse=True)
        return in_library + not_in_library

    def fill_media_list(self, list_id, items, media_type):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            list_items = []
            library = self.kodi_movies if media_type == 'movie' else self.kodi_tvshows
            
            media_type_tag = 'movie' if media_type == 'movie' else 'tvshow'

            for i in items:
                label = i.get('title') or i.get('name', '')
                icon = IMG_THUMB_SMALL + i['poster_path'] if i.get('poster_path') else 'DefaultVideo.png'
                year_str = (i.get('release_date') or i.get('first_air_date') or '')[:4]
                
                li = create_list_item_with_year(label, year_str, icon, media_type)
                
                # --- SETARE INFOTAG ---
                tag = li.getVideoInfoTag()
                tag.setMediaType(media_type_tag)
                tag.setTitle(label)
                # ----------------------

                li.setProperty('id', str(i['id']))
                li.setProperty('media_type', media_type)
                
                tmdb_id_str = str(i['id'])
                
                # --- LOGICA BIFA ---
                playcount = 0
                if media_type == 'movie':
                    if trakt_sync.is_movie_watched(tmdb_id_str):
                        playcount = 1
                elif media_type == 'tv':
                    if trakt_sync.get_episode_watched_count(tmdb_id_str) > 0:
                        playcount = 1
                
                # Fallback Library
                if tmdb_id_str in library:
                    info = library[tmdb_id_str]
                    li.setProperty('DBID', str(info['dbid']))
                    if info.get('playcount', 0) > 0:
                        playcount = info['playcount']

                if playcount > 0:
                    li.setProperty('PlayCount', str(playcount))
                    li.setProperty('Overlay', 'Watched')
                    tag.setPlaycount(playcount) # Activare bifa
                # -------------------

                list_items.append(li)
            ctl.addItems(list_items)
        except Exception as e:
            log(f"Error filling list {list_id}: {e}")

    def fill_season_list(self, list_id, seasons):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            list_items = []

            for s in seasons:
                season_num = s.get('season_number', 0)
                ep_count = s.get('episode_count', 0)
                
                # --- MODIFICARE: Titlu BOLD ---
                raw_label = s.get('name', f"Season {season_num}")
                label = f"[B]{raw_label}[/B]"
                # ------------------------------
                
                icon = IMG_THUMB_SMALL + s['poster_path'] if s.get('poster_path') else 'DefaultVideo.png'
                
                li = xbmcgui.ListItem(label)
                
                # --- MODIFICARE: Episoade BOLD ---
                li.setLabel2(f"[B]{ep_count} Episodes[/B]")
                # ---------------------------------
                
                li.setArt({'thumb': icon, 'poster': icon})
                li.setProperty('season_number', str(season_num))
                li.setProperty('id', str(self.tmdb_id))
                li.setProperty('media_type', 'season')
                
                # Tag
                tag = li.getVideoInfoTag()
                tag.setMediaType('season')
                tag.setTitle(raw_label)
                li.setProperty('DBTYPE', 'season')
                
                # Logica Bifa Sezon (Ramane la fel)
                watched_eps = trakt_sync.get_episode_watched_count(self.tmdb_id, season_num)
                unwatched = max(0, ep_count - watched_eps)
                
                li.setProperty('WatchedEpisodes', str(watched_eps))
                li.setProperty('UnWatchedEpisodes', str(unwatched))
                li.setProperty('TotalEpisodes', str(ep_count))
                
                if ep_count > 0 and watched_eps >= ep_count:
                    li.setProperty('PlayCount', '1')
                    li.setProperty('Overlay', 'Watched')
                    tag.setPlaycount(1)
                else:
                    li.setProperty('PlayCount', '0')
                    tag.setPlaycount(0)
                
                list_items.append(li)
            ctl.addItems(list_items)
        except Exception as e: 
            log(f"Error filling season list: {e}")

    def fill_actor_list(self, list_id, actors):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            list_items = []
            for a in actors:
                name = a.get('name', '')
                character = a.get('character', '')
                
                # Nume Actor Bold
                li = xbmcgui.ListItem(f"[B]{name}[/B]")
                
                # --- MODIFICARE: Alias PINK BOLD ---
                if character:
                    formatted_char = f"[B][COLOR FFFF69B4]{character}[/COLOR][/B]"
                    li.setLabel2(formatted_char)
                    li.setProperty('Character', formatted_char)
                    li.setProperty('character', formatted_char)
                # -----------------------------------

                icon = IMG_THUMB_SMALL + a['profile_path'] if a.get('profile_path') else 'DefaultActor.png'
                li.setArt({'thumb': icon, 'icon': icon, 'poster': icon})
                li.setProperty('id', str(a['id']))
                list_items.append(li)
            ctl.addItems(list_items)
        except: pass

    # --- MODIFICARE: Lista Videoclipuri plina ---
    def fill_video_list(self, list_id, videos):
        try:
            if not control_exists(self, list_id): return
            ctl = self.getControl(list_id)
            ctl.reset()
            
            list_items = []
            
            for v in videos:
                label = v.get('name', 'Video')
                # Aici preluam ce am setat noi manual mai sus (Trailer/Clip)
                v_type = v.get('type', 'Video')
                
                # Daca am setat noi official=True, scriem Official, altfel Unofficial
                is_off = v.get('official', False)
                official_str = "Official" if is_off else "Unofficial"
                
                # Data (Anul)
                date_str = v.get('published_at', '')[:4]
                
                label2 = f"{official_str} {v_type}"
                if date_str:
                    label2 += f" • {date_str}"
                
                key = v.get('key')
                if not key: continue
                
                # Thumbnail
                icon = v.get('thumb')
                if not icon:
                    icon = f"https://img.youtube.com/vi/{key}/mqdefault.jpg"
                
                li = xbmcgui.ListItem(label)
                li.setLabel2(label2)
                li.setArt({'thumb': icon, 'icon': icon})
                li.setProperty('youtube_id', key)
                
                list_items.append(li)
            
            ctl.addItems(list_items)
            
        except Exception as e:
            log(f"Error filling video list {list_id}: {e}")
    # ----------------------------------------------------------

    def fill_image_list(self, list_id, images, img_type):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            list_items = []
            base = IMG_FULL if img_type == 'poster' else BACKDROP_BASE
            for idx, img in enumerate(images):
                path = img.get('file_path', '')
                if not path: continue
                full_url = base + path
                li = xbmcgui.ListItem()
                li.setArt({'thumb': full_url, 'icon': full_url})
                li.setProperty('image_url', full_url)
                list_items.append(li)
            ctl.addItems(list_items)
        except: pass

    def get_selected_image_url(self, list_id):
        try:
            item = self.getControl(list_id).getSelectedItem()
            if item: return item.getProperty('image_url')
        except: pass
        return None

    def onAction(self, action):
        if action.getId() in [ACTION_PREVIOUS_MENU, ACTION_NAV_BACK]:
            self.go_back = True
            self.close()

    def onClick(self, controlId):
        # PLAY
        if controlId == 8:
            # --- MODIFICARE: AM SCOS self.close() ---
            # Fereastra ramane deschisa in spate. 
            # Se va inchide automat DOAR daca alegi o optiune din meniu (via action_play_dialog)
            action_play_dialog(self.tmdb_id, self.media_type, title=self.title_text)
            
        # SETTINGS
        elif controlId == 445: action_open_settings()
        # REFRESH
        elif controlId == 447: action_refresh_trakt()
        # RETURN
        elif controlId == 446: self.close()

        # --- RESTUL BUTOANELOR VECHI ---
        elif controlId == 132: # Plot
            if self.plot_text and not self.showing_text_dialog:
                self.showing_text_dialog = True
                show_text_dialog(self.title_text, self.plot_text)
                self.showing_text_dialog = False
        
        elif controlId == 1000: # Actor
            item = self.getControl(1000).getSelectedItem()
            if item and item.getProperty('id'):
                self.next_info = ('actor', item.getProperty('id'))
                self.close()
            
        elif controlId in [150, 250]: # Recommendations/Collection
            item = self.getControl(controlId).getSelectedItem()
            if item:
                media_type = item.getProperty('media_type')
                item_id = item.getProperty('id')
                if media_type == 'season':
                    season_num = item.getProperty('season_number')
                    self.next_info = ('season', {'tv_id': self.tmdb_id, 'season_num': season_num, 'tv_name': self.title_text})
                    self.close()
                elif item_id:
                    self.next_info = ('media', {'id': item_id, 'type': media_type or 'movie'})
                    self.close()
            
        elif controlId == 1150: # Videos
            item = self.getControl(controlId).getSelectedItem()
            if item and item.getProperty('youtube_id'):
                self.next_info = ('youtube_play', item.getProperty('youtube_id'))
                self.close()
        
        elif controlId == 1250: show_full_image(self, 1250) # Posters
        elif controlId == 1350: show_full_image(self, 1350) # Backdrops


class ActorInfo(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(ActorInfo, self).__init__(*args)
        self.actor_id = kwargs.get('actor_id')
        self.meta = {}
        self.actor_name = ''
        self.biography_text = ''
        self.showing_text_dialog = False
        self.go_back = False
        self.next_info = None
        
        self.kodi_movies = {}
        self.kodi_tvshows = {}
        
        # --- MODIFICARE: Folosim direct texture.png ---
        bg_fallback = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
        
        self.setProperty('fanart', bg_fallback)
        self.setProperty('actor.ImageFilter', bg_fallback)
        self.setProperty('ImageFilter', bg_fallback)

    def onInit(self):
        self.kodi_movies = get_kodi_library_movies()
        self.kodi_tvshows = get_kodi_library_tvshows()
        
        append = 'movie_credits,tv_credits,images,tagged_images,external_ids'
        data = get_tmdb_data(f"person/{self.actor_id}", {'append_to_response': append})
        if not data:
            self.close()
            return
        self.meta = data
        
        # --- PRELUARE DATE ---
        self.actor_name = self.meta.get('name', '')
        self.biography_text = self.meta.get('biography', '')
        birthday = self.meta.get('birthday', '')
        deathday = self.meta.get('deathday', '')
        place_of_birth = self.meta.get('place_of_birth', '')
        
        # --- FILTRARE CARACTERE CIUDATE (PATRATELE) ---
        raw_aka = self.meta.get('also_known_as', [])
        clean_aka = []
        for name in raw_aka:
            is_readable = True
            for char in name:
                if ord(char) > 1000: 
                    is_readable = False
                    break
            if is_readable:
                clean_aka.append(name)
        also_known_as_str = ", ".join(clean_aka[:5]) if clean_aka else ''
        
        thumb = IMG_BASE + self.meta.get('profile_path', '') if self.meta.get('profile_path') else ''

        # --- CALCUL VARSTA SI DATA ---
        age = calculate_age(birthday, deathday)
        birthday_formatted = format_date(birthday) if birthday else ''
        deathday_formatted = format_date(deathday) if deathday else ''
        
        final_birthday_str = birthday_formatted
        if final_birthday_str and age:
            if deathday:
                final_birthday_str = f"[B]{final_birthday_str}[/B]   [COLOR gray]Died at: [B][COLOR FFFDBD01]{age}[/COLOR][/B]"
            else:
                final_birthday_str = f"[B]{final_birthday_str}[/B]   [COLOR gray]Age: [B][COLOR FFFDBD01]{age}[/COLOR][/B]"

        # --- FORMATARE BOLD ---
        if also_known_as_str: also_known_as_str = f"[B]{also_known_as_str}[/B]"
        if place_of_birth: place_of_birth = f"[B]{place_of_birth}[/B]"
        if final_birthday_str: final_birthday_str = f"{final_birthday_str}"
        if deathday_formatted: deathday_formatted = f"[B]{deathday_formatted}[/B]"

        # --- LISTE CREDITE ---
        movies = self.meta.get('movie_credits', {}).get('cast', [])
        tvshows = self.meta.get('tv_credits', {}).get('cast', [])
        
        total_movies_str = f"[B]{len(movies)}[/B]"

        # --- SETARE PROPRIETATI XML ---
        self.setProperty('actor.title', self.actor_name)
        self.setProperty('actor.name', self.actor_name)
        self.setProperty('actor.AlsoKnownAs', also_known_as_str)
        self.setProperty('actor.Birthday', final_birthday_str)
        self.setProperty('actor.Age', "") 
        self.setProperty('actor.PlaceOfBirth', place_of_birth)
        self.setProperty('actor.Deathday', deathday_formatted)
        self.setProperty('actor.Biography', self.biography_text)
        self.setProperty('actor.TotalMovies', total_movies_str)
        self.setProperty('actor.thumb', thumb)
        
        texture_path = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'texture.png')
        self.setProperty('actor.ImageFilter', texture_path)
        self.setProperty('ImageFilter', texture_path)

        # --- UMPLERE LISTE ---
        movies = self.sort_credits_by_library_and_year(movies, 'movie')
        tvshows = self.sort_credits_by_library_and_year(tvshows, 'tv')

        self.fill_credits(150, movies, 'movie')
        self.fill_credits(250, tvshows, 'tv')
        
        # --- MODIFICARE: LANSARE YOUTUBE IN FUNDAL (THREAD) ---
        if control_exists(self, 350):
            t = threading.Thread(target=self.fill_actor_youtube_videos, args=(350, self.actor_name, movies[:15]))
            t.daemon = True  # <--- LINIE NOUA: Previne eroarea "waiting on thread"
            t.start()
        # -----------------------------------------------------
        
        actor_images = self.meta.get('images', {}).get('profiles', [])
        if control_exists(self, 450):
            self.fill_image_list(450, actor_images, 'profile')
        
        tagged_images = self.meta.get('tagged_images', {}).get('results', [])
        if control_exists(self, 750):
            self.fill_tagged_images(750, tagged_images)

    def sort_credits_by_library_and_year(self, items, media_type):
        in_library = []
        not_in_library = []
        library = self.kodi_movies if media_type == 'movie' else self.kodi_tvshows
        for item in items:
            tmdb_id_str = str(item.get('id', ''))
            year_str = (item.get('release_date') or item.get('first_air_date') or '')[:4]
            try: year_int = int(year_str) if year_str else 0
            except: year_int = 0
            item['_year_int'] = year_int
            if tmdb_id_str in library: in_library.append(item)
            else: not_in_library.append(item)
        in_library.sort(key=lambda x: x['_year_int'], reverse=True)
        not_in_library.sort(key=lambda x: x['_year_int'], reverse=True)
        return in_library + not_in_library

    def fill_credits(self, list_id, items, m_type):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            l_items = []
            library = self.kodi_movies if m_type == 'movie' else self.kodi_tvshows
            db_type_str = 'movie' if m_type == 'movie' else 'tvshow'
            
            for i in items:
                label = i.get('title') or i.get('name', '')
                # --- VITEZA: ICONITE MICI ---
                icon = IMG_THUMB_SMALL + i['poster_path'] if i.get('poster_path') else 'DefaultVideo.png'
                
                character = i.get('character', '')
                year_str = (i.get('release_date') or i.get('first_air_date') or '')[:4]
                
                li = create_list_item_with_year(label, year_str, icon, m_type)
                
                if character:
                    formatted_char = f"[B][COLOR FFFF69B4]{character}[/COLOR][/B]"
                    li.setProperty('Character', formatted_char)
                    li.setProperty('character', formatted_char)
                    li.setLabel2(formatted_char)

                tag = li.getVideoInfoTag()
                tag.setMediaType(db_type_str)
                tag.setTitle(label)

                li.setProperty('id', str(i['id']))
                li.setProperty('media_type', m_type)
                li.setProperty('DBTYPE', db_type_str)
                
                tmdb_id_str = str(i['id'])
                playcount = 0
                
                if m_type == 'movie':
                    if trakt_sync.is_movie_watched(tmdb_id_str): playcount = 1
                else:
                    if trakt_sync.get_episode_watched_count(tmdb_id_str) > 0: playcount = 1
                
                if tmdb_id_str in library:
                    info = library[tmdb_id_str]
                    li.setProperty('DBID', str(info['dbid']))
                    if m_type == 'tv':
                        if info.get('watched', 0) > 0: playcount = 1
                    else:
                        if info.get('playcount', 0) > 0: playcount = 1

                if playcount > 0:
                    li.setProperty('PlayCount', '1')
                    li.setProperty('Overlay', 'Watched')
                    tag.setPlaycount(1)
                else:
                    li.setProperty('PlayCount', '0')
                    tag.setPlaycount(0)

                l_items.append(li)
            ctl.addItems(l_items)
        except Exception as e:
            log(f"Error filling credits: {e}")

    def fill_actor_youtube_videos(self, list_id, actor_name, popular_movies):
        # --- LOGICA VIDEO ACTOR: INTERVIURI & BEST OF (GOOGLE API) ---
        try:
            # IMPORTANT: Verificarea controlului trebuie facuta pe thread-ul principal
            # Dar cum suntem in thread secundar, riscam sa nu il gaseasca.
            # Totusi, in Kodi Python, getControl merge si din thread de obicei.
            
            search_query = f"{actor_name} interview best moments"
            results = get_youtube_api_data(search_query)
            
            list_items = []
            if results:
                for item in results:
                    snippet = item.get('snippet', {})
                    video_id = item.get('id', {}).get('videoId')
                    if not video_id: continue
                    
                    raw_title = html.unescape(snippet.get('title', ''))
                    title = ""
                    for char in raw_title:
                        if ord(char) < 60000: title += char
                    
                    title_lower = title.lower()
                    v_type = "Video"
                    if 'interview' in title_lower or 'talk' in title_lower: v_type = "Interview"
                    elif 'funny' in title_lower or 'moments' in title_lower or 'compilation' in title_lower: v_type = "Best Moments"
                    elif 'trailer' in title_lower: v_type = "Trailer"
                    
                    date_str = snippet.get('publishedAt', '')[:4]
                    label2 = f"{v_type}"
                    if date_str: label2 += f" • {date_str}"
                    
                    icon = snippet.get('thumbnails', {}).get('high', {}).get('url', '')
                    if not icon: icon = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                    
                    li = xbmcgui.ListItem(title)
                    li.setLabel2(label2)
                    li.setArt({'thumb': icon, 'icon': icon})
                    li.setProperty('youtube_id', video_id)
                    list_items.append(li)
            
            # Adaugarea itemelor in lista trebuie facuta cu grija.
            # Daca fereastra s-a inchis intre timp, va da eroare, asa ca folosim try-except
            if control_exists(self, list_id):
                ctl = self.getControl(list_id)
                ctl.addItems(list_items)
            
        except Exception as e:
            pass

    def fill_image_list(self, list_id, images, img_type):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            l_items = []
            base = IMG_FULL
            for idx, img in enumerate(images):
                path = img.get('file_path', '')
                if not path: continue
                full_url = base + path
                
                # --- VITEZA: THUMB MIC ---
                thumb_url = IMG_THUMB_SMALL + path
                # -------------------------
                
                li = xbmcgui.ListItem()
                li.setArt({'thumb': thumb_url, 'icon': thumb_url})
                li.setProperty('image_url', full_url)
                l_items.append(li)
            ctl.addItems(l_items)
        except: pass

    def fill_tagged_images(self, list_id, images):
        try:
            ctl = self.getControl(list_id)
            ctl.reset()
            l_items = []
            for idx, img in enumerate(images[:30]):
                path = img.get('file_path', '')
                if not path: continue
                full_url = BACKDROP_BASE + path
                
                # --- VITEZA: THUMB MIC ---
                thumb_url = IMG_THUMB_SMALL + path
                # -------------------------
                
                li = xbmcgui.ListItem()
                li.setArt({'thumb': thumb_url, 'icon': thumb_url})
                li.setProperty('image_url', full_url)
                l_items.append(li)
            ctl.addItems(l_items)
        except: pass

    def get_selected_image_url(self, list_id):
        try:
            item = self.getControl(list_id).getSelectedItem()
            if item: return item.getProperty('image_url')
        except: pass
        return None

    def onAction(self, action):
        if action.getId() in [ACTION_PREVIOUS_MENU, ACTION_NAV_BACK]:
            self.go_back = True
            self.close()

    def onClick(self, controlId):
        if controlId == 132:
            if self.biography_text and not self.showing_text_dialog:
                self.showing_text_dialog = True
                show_text_dialog(self.actor_name, self.biography_text)
                self.showing_text_dialog = False
            return
        
        if controlId == 150:
            item = self.getControl(150).getSelectedItem()
            if item and item.getProperty('id'):
                self.next_info = ('media', {'id': item.getProperty('id'), 'type': 'movie'})
                self.close()
        elif controlId == 250:
            item = self.getControl(250).getSelectedItem()
            if item and item.getProperty('id'):
                self.next_info = ('media', {'id': item.getProperty('id'), 'type': 'tv'})
                self.close()
        
        elif controlId == 350:
            item = self.getControl(350).getSelectedItem()
            if item:
                yt_id = item.getProperty('youtube_id')
                if yt_id:
                    self.next_info = ('youtube_play', yt_id)
                    self.close()
        
        elif controlId == 450:
            show_full_image(self, 450)
        
        elif controlId == 750:
            show_full_image(self, 750)


def run_extended_info(tmdb_id, media_type='movie', clear_stack=True, season=None, episode=None, tv_name=''):
    if clear_stack:
        NAVIGATION_STACK.clear()
    
    # --- LOGICA DE RUTARE (ROUTING) ---
    # Decidem ce fereastra punem prima in stiva
    
    if media_type == 'tv' and season is not None and episode is not None:
        # 1. E EPISOD -> Deschidem direct EpisodeInfo
        log(f"[RunLoop] Direct Launch: EPISODE S{season}E{episode}")
        NAVIGATION_STACK.append({
            'type': 'episode', 
            'tv_id': tmdb_id, 
            'season_num': season, 
            'episode_num': episode, 
            'tv_name': tv_name
        })
        
    elif media_type == 'tv' and season is not None:
        # 2. E SEZON -> Deschidem direct SeasonInfo
        log(f"[RunLoop] Direct Launch: SEASON {season}")
        NAVIGATION_STACK.append({
            'type': 'season', 
            'tv_id': tmdb_id, 
            'season_num': season, 
            'tv_name': tv_name
        })
        
    else:
        # 3. E FILM sau SERIAL (ROOT) -> Deschidem ExtendedInfo standard
        log(f"[RunLoop] Direct Launch: MAIN MEDIA ({media_type})")
        NAVIGATION_STACK.append({
            'type': 'media', 
            'tmdb_id': tmdb_id, 
            'media_type': media_type
        })
    # ----------------------------------
    
    while NAVIGATION_STACK:
        current = NAVIGATION_STACK[-1]
        log(f"[RunLoop] Processing Stack Item: {current['type']}")
        
        if current['type'] == 'media':
            wd = ExtendedInfo(XML_VIDEO_INFO, ADDON_PATH, 
                            tmdb_id=current['tmdb_id'], 
                            media_type=current['media_type'])
            wd.doModal()
            
            if wd.go_back:
                NAVIGATION_STACK.pop()
            elif wd.next_info:
                next_type, next_data = wd.next_info
                if next_type == 'youtube_play':
                    del wd
                    play_youtube_and_return(next_data)
                    continue
                else:
                    handle_next_info(wd.next_info)
            else:
                del wd
                break
            del wd
            
        elif current['type'] == 'actor':
            wd = ActorInfo(XML_ACTOR_INFO, ADDON_PATH, actor_id=current['actor_id'])
            wd.doModal()
            
            if wd.go_back:
                NAVIGATION_STACK.pop()
            elif wd.next_info:
                next_type, next_data = wd.next_info
                if next_type == 'youtube_play':
                    del wd
                    play_youtube_and_return(next_data)
                    continue
                else:
                    handle_next_info(wd.next_info)
            else:
                del wd
                break
            del wd
            
        elif current['type'] == 'season':
            wd = SeasonInfo(XML_VIDEO_INFO, ADDON_PATH,
                          tv_id=current['tv_id'],
                          season_num=current['season_num'],
                          tv_name=current.get('tv_name', ''))
            wd.doModal()
            
            if wd.go_back:
                NAVIGATION_STACK.pop()
            elif wd.next_info:
                next_type, next_data = wd.next_info
                if next_type == 'youtube_play':
                    del wd
                    play_youtube_and_return(next_data)
                    continue
                log(f"[RunLoop] Season Next Info: {wd.next_info}")
                handle_next_info_season(wd.next_info, current)
            else:
                del wd
                break
            del wd
            
        elif current['type'] == 'episode':
            wd = EpisodeInfo(XML_VIDEO_INFO, ADDON_PATH,
                           tv_id=current['tv_id'],
                           season_num=current['season_num'],
                           episode_num=current['episode_num'],
                           tv_name=current.get('tv_name', ''))
            wd.doModal()
            
            if wd.go_back:
                NAVIGATION_STACK.pop()
            elif wd.next_info:
                handle_next_info_episode(wd.next_info)
            else:
                del wd
                break
            del wd
        else:
            break
    
    NAVIGATION_STACK.clear()

def play_youtube_and_return(yt_id):
    xbmc.Player().play(f"plugin://plugin.video.youtube/play/?video_id={yt_id}")
    monitor = xbmc.Monitor()
    for _ in range(30):
        if xbmc.Player().isPlaying(): break
        if monitor.abortRequested(): return
        monitor.waitForAbort(0.5)
    while xbmc.Player().isPlaying() and not monitor.abortRequested():
        monitor.waitForAbort(1)

def handle_next_info(next_info):
    info_type, data = next_info
    if info_type == 'actor':
        NAVIGATION_STACK.append({'type': 'actor', 'actor_id': data})
    elif info_type == 'media':
        NAVIGATION_STACK.append({'type': 'media', 'tmdb_id': data['id'], 'media_type': data['type']})
    elif info_type == 'season':
        NAVIGATION_STACK.append({
            'type': 'season',
            'tv_id': data['tv_id'],
            'season_num': data['season_num'],
            'tv_name': data['tv_name']
        })

def handle_next_info_season(next_info, current_season):
    info_type, data = next_info
    
    if info_type == 'actor':
        NAVIGATION_STACK.append({'type': 'actor', 'actor_id': data})
        
    elif info_type == 'episode':
        # VERIFICA LINIA ASTA: Trebuie sa fie 'type': 'episode' !!!
        NAVIGATION_STACK.append({
            'type': 'episode',  # <--- Aici e cheia. Daca scrie 'season' din greseala, redeschide sezonul!
            'tv_id': current_season['tv_id'],
            'season_num': current_season['season_num'],
            'episode_num': data,
            'tv_name': current_season['tv_name']
        })

def handle_next_info_episode(next_info):
    info_type, data = next_info
    if info_type == 'actor':
        NAVIGATION_STACK.append({'type': 'actor', 'actor_id': data})