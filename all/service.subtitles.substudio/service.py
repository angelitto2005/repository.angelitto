# -*- coding: utf-8 -*-
import os, sys, re, json, unicodedata, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__    = __addon__.getAddonInfo('id')

# ── FUNCȚII PENTRU CONTROLUL LOGURILOR DIN SETĂRI ────────────────
# Variabilă globală pentru a muta logurile pierzătorilor
RACE_STATE = {"finished": False}

def _log_debug(msg):
    if RACE_STATE["finished"]: return
    try:
        if __addon__.getSettingBool('debug_logging'):
            xbmc.log(f"SUBSTUDIO: {msg}", xbmc.LOGINFO)
    except Exception:
        pass

def _log_warn(msg):
    if RACE_STATE["finished"]: return
    try:
        if __addon__.getSettingBool('debug_logging'):
            xbmc.log(f"SUBSTUDIO: {msg}", xbmc.LOGWARNING)
    except Exception:
        pass

def _log_error(msg):
    if RACE_STATE["finished"]: return
    try:
        xbmc.log(f"SUBSTUDIO EROARE: {msg}", xbmc.LOGERROR)
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────

ADDON_NAME = '[B][COLOR FFB048B5]Sub[/COLOR][COLOR FF00BFFF]Studio[/COLOR][/B]'
ADDON_ICON = os.path.join(__addon__.getAddonInfo('path'), 'icon.png')

lib_path = xbmcvfs.translatePath(
    os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

robot  = None
loader = None
try:
    import robot
except Exception as e:
    _log_error(f"robot import failed: {e}")
try:
    import loader
except Exception as e:
    _log_error(f"loader import failed: {e}")

# ── HANDLE — protejat contra RunScript ───────────────────────────
try:
    HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
except (ValueError, IndexError):
    HANDLE = 0

LANGS =["ro","en","es","fr","de","it","hu","pt","ru","tr",
         "bg","el","pl","cs","nl"]

LANG_MAP = {
    'ro':'Romanian','en':'English','es':'Spanish','fr':'French',
    'de':'German','it':'Italian','hu':'Hungarian','pt':'Portuguese',
    'ru':'Russian','tr':'Turkish','bg':'Bulgarian','el':'Greek',
    'pl':'Polish','cs':'Czech','nl':'Dutch','ar':'Arabic',
    'zh':'Chinese','ja':'Japanese','ko':'Korean','sv':'Swedish',
    'da':'Danish','fi':'Finnish','no':'Norwegian','hr':'Croatian',
    'sr':'Serbian','sk':'Slovak','sl':'Slovenian','uk':'Ukrainian',
    'he':'Hebrew','th':'Thai','vi':'Vietnamese','id':'Indonesian',
    'ms':'Malay','hi':'Hindi','fa':'Persian','ca':'Catalan',
    'eu':'Basque','gl':'Galician','et':'Estonian','lv':'Latvian',
    'lt':'Lithuanian','mk':'Macedonian','sq':'Albanian',
    'bs':'Bosnian','is':'Icelandic','mt':'Maltese','cy':'Welsh',
    'ga':'Irish','ka':'Georgian','af':'Afrikaans','sw':'Swahili',
    'ta':'Tamil','te':'Telugu','ur':'Urdu','bn':'Bengali',
    'ml':'Malayalam','kn':'Kannada','si':'Sinhala','my':'Burmese',
    'km':'Khmer','lo':'Lao','mn':'Mongolian','ne':'Nepali',
    'am':'Amharic','zu':'Zulu','tl':'Filipino',
    'rum':'Romanian','eng':'English','spa':'Spanish','fre':'French',
    'ger':'German','ita':'Italian','hun':'Hungarian','por':'Portuguese',
    'rus':'Russian','tur':'Turkish','bul':'Bulgarian','gre':'Greek',
    'pol':'Polish','cze':'Czech','dut':'Dutch','ara':'Arabic',
    'chi':'Chinese','jpn':'Japanese','kor':'Korean','swe':'Swedish',
    'dan':'Danish','fin':'Finnish','nor':'Norwegian','hrv':'Croatian',
    'srp':'Serbian','slv':'Slovenian','slo':'Slovak','ukr':'Ukrainian',
    'heb':'Hebrew','tha':'Thai','vie':'Vietnamese','per':'Persian',
    'cat':'Catalan','baq':'Basque','glg':'Galician','est':'Estonian',
    'lav':'Latvian','lit':'Lithuanian','mac':'Macedonian',
    'alb':'Albanian','bos':'Bosnian','ice':'Icelandic',
    'ind':'Indonesian','may':'Malay','hin':'Hindi',
    'pb':'Portuguese-BR','pob':'Portuguese-BR',
    'spa_la':'Spanish-LatAm','zht':'Chinese-Trad',
    'zhe':'Chinese-Simp',
}

NORM = {
    'eng':'en','spa':'es','fre':'fr','fra':'fr','ger':'de','ita':'it',
    'dut':'nl','rum':'ro','ron':'ro','gre':'el','cze':'cs','pol':'pl',
    'hun':'hu','tur':'tr','bul':'bg','rus':'ru','por':'pt',
    'spa_la':'es','pb':'pt','pob':'pt','cat':'ca',
    'hrv':'hr','srp':'sr','slv':'sl','slo':'sk','ukr':'uk',
    'ara':'ar','heb':'he','tha':'th','vie':'vi',
    'jpn':'ja','kor':'ko','chi':'zh','swe':'sv',
    'dan':'da','fin':'fi','nor':'no','ind':'id',
    'may':'ms','hin':'hi','per':'fa','alb':'sq',
    'bos':'bs','ice':'is','mac':'mk','baq':'eu',
    'glg':'gl','est':'et','lav':'lv','lit':'lt',
}

# ════════════════════════════════════════════════════════════════════
#  CONFTIGURAȚII OPENSUBTITLES & TMDB
# ════════════════════════════════════════════════════════════════════
TMDB_API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL_TMDB = "https://api.themoviedb.org/3"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

OS_REST_LANG = {
    'ro': 'rum', 'en': 'eng', 'es': 'spa', 'fr': 'fre', 'de': 'ger',
    'it': 'ita', 'hu': 'hun', 'pt': 'por', 'ru': 'rus', 'tr': 'tur',
    'bg': 'bul', 'el': 'gre', 'pl': 'pol', 'cs': 'cze', 'nl': 'dut'
}

# Variabilă globală pentru timeout-ul request-urilor (setată în search)
RACE_TIMEOUT = 10.0

def get_imdb_id_from_title(title, is_tv=False):
    """Găsește ID-ul IMDB folosind TMDB pe baza titlului și anului."""
    try:
        clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', title, flags=re.IGNORECASE).strip()
        
        year_match = re.search(r'\((\d{4})\)', clean_name)
        year = year_match.group(1) if year_match else None
        
        if year_match:
            clean_name = clean_name[:year_match.start()].strip()

        if not clean_name:
            return None

        media_type = "tv" if is_tv else "movie"
        search_url = f"{BASE_URL_TMDB}/search/{media_type}"
        params = {"api_key": TMDB_API_KEY, "query": clean_name}
        
        if year:
            if is_tv: params["first_air_date_year"] = year
            else: params["primary_release_year"] = year

        r = requests.get(search_url, params=params, timeout=RACE_TIMEOUT).json()
        
        if r.get('results'):
            tmdb_id = r['results'][0]['id']
            ext_url = f"{BASE_URL_TMDB}/{media_type}/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": TMDB_API_KEY}, timeout=RACE_TIMEOUT).json()
            imdb_id = ext_r.get('imdb_id')
            
            _log_debug(f"Convertit {clean_name} ({year}) -> TMDB: {tmdb_id} -> IMDB: {imdb_id}")
            return imdb_id
    except Exception as e:
        if not RACE_STATE["finished"]: _log_error(f"TMDB Search Eroare: {str(e)}")
    return None

def get_detailed_subtitle_names(imdb_id, target_lang=None, season=None, episode=None):
    """Interoghează API-ul REST OpenSubtitles pentru a obține SubFileName."""
    mapping = {}
    if not imdb_id:
        return mapping
    try:
        numeric_id = imdb_id.replace('tt', '')
        
        # Ordinea ALFABETICĂ obligatorie: episode → imdbid → season → sublanguageid
        parts = []
        if season and str(season) != '0' and episode and str(episode) != '0':
            parts.append(f"episode-{episode}")
        parts.append(f"imdbid-{numeric_id}")
        if season and str(season) != '0':
            parts.append(f"season-{season}")
        if target_lang:
            rest_lang = OS_REST_LANG.get(target_lang, 'eng')
            parts.append(f"sublanguageid-{rest_lang}")
        
        rest_url = "https://rest.opensubtitles.org/search/" + "/".join(parts)
        
        _log_debug(f"REST URL: {rest_url}")
        
        response = requests.get(rest_url, headers=HEADERS, timeout=RACE_TIMEOUT)
        if response.ok:
            data = response.json()
            if isinstance(data, list):
                _log_debug(f"REST a returnat {len(data)} subtitrări")
                for item in data:
                    file_name = item.get('SubFileName')
                    if not file_name:
                        continue
                    for key in ('IDSubtitleFile', 'IDSubtitle'):
                        val = str(item.get(key, ''))
                        if val:
                            mapping[val] = file_name
    except Exception as e:
        if not RACE_STATE["finished"]: _log_error(f"OS REST Eroare: {str(e)}")
    return mapping


def _get_lang_name(code):
    if not code:
        return 'Unknown'
    return LANG_MAP.get(code, LANG_MAP.get(code.lower(), code.upper()))

def _safe_filename(name):
    name = re.sub(r'[<>:"|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def _normalize(s):
    """Elimină diacritice și caractere speciale pentru comparare."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', '', s.lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ════════════════════════════════════════════════════════════════════
#  FOLDER SUBTITRĂRI SALVATE
# ════════════════════════════════════════════════════════════════════
def _get_saved_folder():
    profile = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
    saved_dir = os.path.join(profile, 'Subtitrari traduse')
    if not xbmcvfs.exists(saved_dir + os.sep):
        xbmcvfs.mkdirs(saved_dir + os.sep)
    return saved_dir


def _clean_saved_folder():
    saved_dir = _get_saved_folder()
    try:
        _, files = xbmcvfs.listdir(saved_dir)
        count = 0
        for f in files:
            try:
                xbmcvfs.delete(os.path.join(saved_dir, f))
                count += 1
            except Exception:
                pass

        if count > 0:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                f'[B][COLOR lime]{count}[/COLOR][/B] fișiere șterse!',
                ADDON_ICON, 4000)
        else:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                'Folderul era deja gol.',
                ADDON_ICON, 3000)
        _log_debug(f"Șterse {count} fișiere (inclusiv index).")
    except Exception as e:
        _log_error(f"Eroare ștergere: {e}")


# ════════════════════════════════════════════════════════════════════
#  POTRIVIRE FILM
# ════════════════════════════════════════════════════════════════════
def _extract_title_key(filename):
    name = os.path.splitext(filename)[0]
    for lang in LANGS:
        if name.lower().endswith(f'.{lang}'):
            name = name[:-len(lang)-1]
            break

    name = re.sub(r'[._\-]', ' ', name)

    stop_words =['1080p','720p','2160p','4k','web','webrip','webdl',
                  'web-dl','bluray','brrip','hdrip','dvdrip','hdtv',
                  'x264','x265','h264','h265','hevc','aac','dts',
                  'ddp','dd5','atmos','amzn','nf','hulu','dsnp',
                  'hmax','atvp','pcok','mp4','mkv','avi']

    words = name.split()
    title_words =[]
    for w in words:
        if w.lower() in stop_words:
            break
        title_words.append(w)

    key = ' '.join(title_words).strip().lower()
    return key if key else filename.lower()


def _find_saved_subtitle(imdb_id, tmdb_id, video_title):
    saved_dir = _get_saved_folder()

    try:
        _, files = xbmcvfs.listdir(saved_dir)
    except Exception:
        return[]

    srt_files =[f for f in files if f.lower().endswith('.srt')]
    if not srt_files:
        return []

    matches =[]

    # ── METODA 1: index.json ─────────────────────────────────────
    index_path = os.path.join(saved_dir, 'index.json')
    index = {}

    if xbmcvfs.exists(index_path):
        try:
            fh = xbmcvfs.File(index_path)
            raw = fh.read()
            fh.close()
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8', errors='replace')
                index = json.loads(raw)
        except Exception as e:
            _log_error(f"Eroare citire index: {e}")

    if index:
        _log_debug(f"Index: {len(index)} intrări.")

        for filename, info in index.items():
            if not info.get('complete', False):
                _log_debug(f"Skip incomplet: {filename}")
                incomplete_path = os.path.join(saved_dir, filename)
                if xbmcvfs.exists(incomplete_path):
                    xbmcvfs.delete(incomplete_path)
                    _log_debug(f"Șters incomplet: {filename}")
                continue

            full_path = os.path.join(saved_dir, filename)
            if not xbmcvfs.exists(full_path):
                continue

            if imdb_id and info.get('imdb'):
                if imdb_id.lower().strip() == info['imdb'].lower().strip():
                    matches.append((full_path, filename))
                    _log_debug(f"Match IMDB: {filename}")
                    continue

            if tmdb_id and info.get('tmdb'):
                if str(tmdb_id).strip() == str(info['tmdb']).strip():
                    matches.append((full_path, filename))
                    _log_debug(f"Match TMDB: {filename}")
                    continue

            if video_title and info.get('title'):
                n_idx = _normalize(info['title'])
                n_vid = _normalize(video_title)

                if n_idx and n_vid and (n_idx == n_vid or
                    n_idx.startswith(n_vid) or n_vid.startswith(n_idx)):
                    matches.append((full_path, filename))
                    _log_debug(f"Match TITLE: '{info['title']}' ≈ '{video_title}'")
                    continue

    # ── METODA 2: Fallback filename ──────────────────────────────
    if not matches:
        current_key = _normalize(video_title) if video_title else ""

        for f in srt_files:
            saved_key = _normalize(_extract_title_key(f)) if current_key else ""

            if imdb_id and imdb_id.lower() in f.lower():
                matches.append((os.path.join(saved_dir, f), f))
                continue

            if current_key and saved_key:
                ck_words = current_key.split()[:3]
                sk_words = saved_key.split()[:3]

                if len(ck_words) >= 1 and ck_words == sk_words:
                    matches.append((os.path.join(saved_dir, f), f))
                    continue

                if len(current_key) >= 3 and (current_key in saved_key
                                               or saved_key in current_key):
                    matches.append((os.path.join(saved_dir, f), f))
                    continue

    _log_debug(f"{len(matches)} potriviri locale.")
    return matches

# ════════════════════════════════════════════════════════════════════
#  SEARCH
# ════════════════════════════════════════════════════════════════════
def search():
    global RACE_STATE
    global RACE_TIMEOUT
    
    RACE_STATE["finished"] = False
    base_url = 'https://sub.wyzie.ru/search'

    try:
        source_opt = __addon__.getSettingInt('subtitle_source')
    except Exception:
        source_opt = 2  # Default: 0=Wyzie, 1=OpenSubtitles, 2=Fast (Ambele)

    # MAGIC TRICK: Timeout agresiv dacă e modul Fast!
    # Wyzie e tăiat automat de Python după 2.5 secunde dacă nu răspunde. 
    # Asta previne complet ca motorul Kodi să agațe scriptul.
    if source_opt == 2:
        RACE_TIMEOUT = 2.5
    else:
        RACE_TIMEOUT = 10.0

    # --- ASPIRATOR DE METADATE PENTRU SUPORT UNIVERSAL ---
    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or \
              xbmc.getInfoLabel("VideoPlayer.TMDbId") or \
              xbmc.getInfoLabel("ListItem.Property(tmdb)") or \
              xbmc.getInfoLabel("VideoPlayer.TMDb")

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or \
              xbmc.getInfoLabel("ListItem.Property(imdb_id)") or \
              xbmc.getInfoLabel("ListItem.IMDBNumber") or \
              xbmc.getInfoLabel("ListItem.Property(imdb)")
    
    # 1. Fallback: Window Properties (Fen, Seren, TMDBHelper, MRSP, Umbrella, Elementum)
    try:
        home_window = xbmcgui.Window(10000)
        
        if not tmdb_id:
            tmdb_props =['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb', 'tmdbmovies.id', 'tmdbshows.id', 'trakt.tmdb_id']
            for prop in tmdb_props:
                cand = home_window.getProperty(prop)
                if cand and cand != 'None' and cand.strip():
                    tmdb_id = cand.strip()
                    break
                    
        if not imdb_id:
            imdb_props =['IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber', 'trakt.imdb_id']
            for prop in imdb_props:
                cand = home_window.getProperty(prop)
                if cand and cand != 'None' and cand.strip():
                    imdb_id = cand.strip()
                    break
    except Exception:
        pass

    # 2. Fallback: Path / Elementum Magnet links
    candidate_paths =[]
    try: candidate_paths.append(xbmc.Player().getPlayingFile())
    except: pass
    candidate_paths.append(xbmc.getInfoLabel("ListItem.Path"))
    candidate_paths.append(xbmc.getInfoLabel("ListItem.FolderPath"))
    candidate_paths.append(xbmc.getInfoLabel("Player.Filenameandpath"))
    candidate_paths.append(xbmc.getInfoLabel("Container.ListItem.FileNameAndPath"))
    
    file_original_path = ""
    for p in candidate_paths:
        p_str = str(p)
        if 'plugin://' in p_str and ('tmdb' in p_str or 'imdb' in p_str or 'season' in p_str or 'title' in p_str or 'magnet' in p_str or 'dn=' in p_str):
            file_original_path = p_str
            break
            
    if not file_original_path and candidate_paths and candidate_paths[0]:
        file_original_path = str(candidate_paths[0])

    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")

    # Extragem detalii suplimentare din link daca exista
    if file_original_path:
        if not tmdb_id:
            match_tmdb = re.search(r'[?&](?:tmdb_id|tmdb)=(\d+)', file_original_path)
            if match_tmdb: tmdb_id = match_tmdb.group(1)
        if not imdb_id:
            match_imdb = re.search(r'[?&](?:imdb_id|imdb)=(tt\d+|\d+)', file_original_path)
            if match_imdb: imdb_id = match_imdb.group(1)
        if not s or s == "0" or s == "":
            match_s = re.search(r'[?&]season=(\d+)', file_original_path)
            if match_s: s = match_s.group(1)
        if not e or e == "0" or e == "":
            match_e = re.search(r'[?&]episode=(\d+)', file_original_path)
            if match_e: e = match_e.group(1)

    # Curățăm și normalizăm IMDb ID-ul
    junk_ids = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')
    if str(tmdb_id) in junk_ids: tmdb_id = None
    if str(imdb_id) in junk_ids: imdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt') and str(imdb_id).isdigit():
        imdb_id = f"tt{imdb_id}"

    # 3. Extragerea inteligentă a titlului 
    video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
    
    if not video_title or video_title.lower() in ["play", "episodul", ""]:
        if file_original_path:
            match_title_url = re.search(r'[?&]title=([^&]+)', file_original_path)
            if match_title_url:
                decoded_t = unquote(match_title_url.group(1)).replace('+', ' ')
                if len(decoded_t) > 2: video_title = decoded_t
            else:
                match_dn = re.search(r'[?&]dn=([^&]+)', file_original_path)
                if match_dn:
                    decoded_dn = unquote(match_dn.group(1)).replace('+', ' ')
                    video_title = decoded_dn
                    
    video_file = xbmc.getInfoLabel("Player.Filename")
    if (not video_title or video_title.lower() == "play") and video_file:
        video_title = os.path.splitext(video_file)[0]

    v_id = imdb_id or tmdb_id

    # 4. Solutia Finală: TMDB Fallback pt Titlu
    if not v_id and video_title:
        is_tv = bool(s and s != "0")
        _log_debug(f"Nu avem ID, dar avem Titlu: '{video_title}'. Incercam TMDB API...")
        fetched_imdb_id = get_imdb_id_from_title(video_title, is_tv=is_tv)
        if fetched_imdb_id:
            imdb_id = fetched_imdb_id
            v_id = imdb_id

    _log_debug(f"METADATA FINALE -> TMDb:{tmdb_id} | IMDb:{imdb_id} | V_ID:{v_id} | S:{s} | E:{e} | Titlu: {video_title}")

    if not v_id and not video_title:
        _log_warn("No video ID or Title found! Nu se poate efectua cautarea.")
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # --- INIȚIALIZARE SETĂRI UTILIZATOR ---
    try:
        l_code = LANGS[__addon__.getSettingInt('subs_languages')]
    except Exception:
        l_code = "ro"

    robot_activat = False
    try:
        robot_activat = __addon__.getSettingBool('robot_activat')
    except Exception:
        pass

    show_all = False
    try:
        show_all = __addon__.getSettingBool('show_all_langs')
    except Exception:
        pass

    all_results =[]
    
    # ── 1. SUBTITRĂRI LOCALE ─────────────────────────────────────
    try:
        l_code_name = _get_lang_name(l_code)
    except Exception:
        l_code_name = l_code.upper()

    saved_matches = _find_saved_subtitle(imdb_id, tmdb_id, video_title)
    local_seen = set()
    for saved_path, saved_name in saved_matches:
        if saved_path in local_seen:
            continue
        local_seen.add(saved_path)

        all_results.append({
            'language_name': f'[B][COLOR yellow]LOCAL[/COLOR][/B]',
            'filename':      saved_name,
            'url':           saved_path,
            'l_code':        l_code,
            'api_filename':  saved_name,
            'is_chosen':     True,
            'is_local':      True,
        })

    # ── 2. WORKERS ONLINE ─────────────────────────────────────────

    def fetch_wyzie(search_params, mark_chosen=False, allowed_langs=None):
        results =[]
        try:
            r = requests.get(base_url, params=search_params, timeout=RACE_TIMEOUT)
            if not r.ok:
                return results
            for sub in r.json():
                t_code = sub.get('language', '') or 'unknown'
                t_code_norm = NORM.get(t_code, t_code)
                
                if allowed_langs is not None and t_code_norm not in allowed_langs:
                    continue

                url = sub.get('url', '')
                if not url:
                    continue

                full_lang = _get_lang_name(t_code)
                fname     = sub.get('fileName', 'sub.srt') or 'sub.srt'
                chosen    = mark_chosen and (t_code_norm == NORM.get(l_code, l_code))

                results.append({
                    'language_name': full_lang,
                    'filename':      fname,
                    'url':           url,
                    'l_code':        t_code,
                    'api_filename':  fname,
                    'is_chosen':     chosen,
                    'is_local':      False
                })
        except Exception as ex:
            if not RACE_STATE["finished"]: _log_error(f"WYZIE API Eroare: {ex}")
        return results

    def wyzie_worker():
        _log_debug("[Worker WYZIE] A inceput cautarea...")
        worker_results =[]
        seen = set()
        
        def add_res(params, chosen, allowed):
            res_list = fetch_wyzie(params, mark_chosen=chosen, allowed_langs=allowed)
            for r in res_list:
                if r['url'] not in seen:
                    seen.add(r['url'])
                    worker_results.append(r)

        bp = {}
        if v_id:
            bp['id'] = v_id
        elif video_title:
            bp['title'] = video_title

        if s and s != "0":
            bp['season'] = s
            bp['episode'] = e

        if show_all:
            add_res(bp, True, None)
        else:
            allowed =[NORM.get(l_code, l_code)]
            if l_code != 'en' and robot_activat:
                allowed.append('en')

            p1 = dict(bp); p1['language'] = l_code
            add_res(p1, True,[NORM.get(l_code, l_code)])

            if l_code != 'en' and robot_activat:
                p2 = dict(bp); p2['language'] = 'en'
                add_res(p2, False,['en'])

            if len(worker_results) <= len(saved_matches) and robot_activat:
                add_res(bp, False, allowed)

        _log_debug(f"[Worker WYZIE] S-a terminat. A gasit {len(worker_results)} rezultate.")
        return worker_results

    def os_worker():
        _log_debug("[Worker OS] A inceput cautarea...")
        results =[]
        try:
            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)

            if not current_imdb_id:
                _log_debug("[Worker OS] Nu s-a gasit IMDB ID necesar pt API, anulat.")
                return results

            if s and e and s != '0':
                media_type = 'series'
                query_id = f"{current_imdb_id}:{s}:{e}"
            else:
                media_type = 'movie'
                query_id = current_imdb_id

            api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
            r = requests.get(api_url, headers=HEADERS, timeout=RACE_TIMEOUT)
            if not r.ok:
                _log_debug(f"[Worker OS] Request esuat (Status {r.status_code}).")
                return results

            data = r.json()
            subtitles = data.get('subtitles',[])

            # ── FIX: Dacă 0 rezultate, IMDB-ul poate fi greșit → retry cu TMDB search ──
            if not subtitles and video_title:
                _log_debug(f"[Worker OS] 0 rezultate cu {current_imdb_id}, retry via TMDB search...")
                fetched_id = get_imdb_id_from_title(video_title, is_tv=bool(s and s != '0'))
                if fetched_id and fetched_id != current_imdb_id:
                    current_imdb_id = fetched_id
                    if s and e and s != '0':
                        query_id = f"{current_imdb_id}:{s}:{e}"
                    else:
                        query_id = current_imdb_id
                    api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
                    _log_debug(f"[Worker OS] Retry URL: {api_url}")
                    r = requests.get(api_url, headers=HEADERS, timeout=RACE_TIMEOUT)
                    if r.ok:
                        data = r.json()
                        subtitles = data.get('subtitles',[])

            if not subtitles:
                _log_debug("[Worker OS] API-ul a intors 0 rezultate.")
                return results

            fallback_en = (l_code != 'en' and robot_activat)

            if show_all:
                detailed_names = get_detailed_subtitle_names(current_imdb_id, season=s, episode=e)
            else:
                detailed_names = get_detailed_subtitle_names(current_imdb_id, l_code, season=s, episode=e)
                if fallback_en:
                    detailed_names.update(get_detailed_subtitle_names(current_imdb_id, 'en', season=s, episode=e))

            seen = set()
            for sub in subtitles:
                sub_lang_raw = sub.get('lang', '')
                sub_l_code = NORM.get(sub_lang_raw, sub_lang_raw)

                is_target = (sub_l_code == l_code)
                is_fallback = (sub_l_code == 'en' and fallback_en)

                if not (show_all or is_target or is_fallback):
                    continue

                url = sub.get('url', '')
                if not url or url in seen:
                    continue
                seen.add(url)

                sub_id = str(sub.get('id', ''))
                fname = detailed_names.get(sub_id, f"OpenSubtitles_{sub_id}.srt")
                full_lang = _get_lang_name(sub_l_code)
                chosen = is_target

                results.append({
                    'language_name': full_lang,
                    'filename':      fname,
                    'url':           url,
                    'l_code':        sub_l_code,
                    'api_filename':  fname,
                    'is_chosen':     chosen,
                    'is_local':      False
                })
        except Exception as ex:
            if not RACE_STATE["finished"]: _log_error(f"OpenSubtitles Eroare Cautare: {ex}")
            
        _log_debug(f"[Worker OS] S-a terminat. A gasit {len(results)} rezultate.")
        return results

    # ── 3. EXECUȚIE SURSE ─────────────────────────────────────────
    online_results =[]

    if source_opt == 0:
        _log_debug("Sursa selectata: Doar Wyzie")
        online_results = wyzie_worker()
    elif source_opt == 1:
        _log_debug("Sursa selectata: Doar OpenSubtitles")
        online_results = os_worker()
    else:
        _log_debug(f"Mod Fast (Concurent) initiat! Timeout agresiv setat la: {RACE_TIMEOUT}s")
        fast_results =[]
        fast_lock = threading.Lock()
        fast_event = threading.Event()
        finished_count = [0]
        
        def run_worker_thread(worker_func, name):
            try:
                res = worker_func()
            except Exception as e:
                if not RACE_STATE["finished"]: _log_error(f"Eroare in thread {name}: {e}")
                res =[]
                
            with fast_lock:
                if res and not fast_results:
                    fast_results.extend(res)
                    _log_debug(f"Fast Mode - {name} a castigat cursa cu {len(res)} rezultate!")
                    fast_event.set()
                finished_count[0] += 1
                if finished_count[0] == 2:
                    fast_event.set() 

        t1 = threading.Thread(target=run_worker_thread, args=(wyzie_worker, "WYZIE"), daemon=True)
        t2 = threading.Thread(target=run_worker_thread, args=(os_worker, "OpenSubtitles"), daemon=True)
        t1.start()
        t2.start()
        
        # Așteptăm maxim 2.6s (puțin peste timeout-ul tăios al request-ului)
        fast_event.wait(timeout=2.6)
        
        RACE_STATE["finished"] = True
        online_results = fast_results

    # Combinăm local cu online
    all_results.extend(online_results)

    # Sortare: LOCAL → limba preferată → restul
    all_results.sort(key=lambda x: (
        not x.get('is_local', False),
        not x['is_chosen'],
        x['language_name']
    ))

    # Construire UI listă
    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])

        if res.get('is_local', False):
            flag_code = l_code[:2]
        else:
            flag_code = res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code']

        li.setArt({'thumb': flag_code, 'icon': flag_code})

        d_params = {
            'action':       'download',
            'url':          res['url'],
            'l_code':       res['l_code'],
            'api_filename': res['api_filename'],
            'is_local':     '1' if res.get('is_local', False) else '0',
        }
        xbmcplugin.addDirectoryItem(
            handle=HANDLE,
            url=f"{sys.argv[0]}?{urlencode(d_params)}",
            listitem=li,
        )

    xbmcplugin.endOfDirectory(HANDLE)


# ════════════════════════════════════════════════════════════════════
#  DOWNLOAD
# ════════════════════════════════════════════════════════════════════
def download(params):
    try:
        url       = unquote(params.get('url', ''))
        l_code    = params.get('l_code', 'unknown')
        is_local  = params.get('is_local', '0') == '1'

        api_filename = params.get('api_filename') or 'subtitle.srt'
        if not api_filename.lower().endswith('.srt'):
            api_filename += '.srt'

        safe_name = _safe_filename(api_filename)

        try:
            chosen_lang = LANGS[__addon__.getSettingInt('subs_languages')]
        except Exception:
            chosen_lang = "ro"

        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir):
            xbmcvfs.mkdirs(dest_dir)

        # Șterge SRT-uri vechi (NU din Subtitrari traduse!)
        try:
            _, old_files = xbmcvfs.listdir(dest_dir)
            for f in old_files:
                if f.lower().endswith('.srt'):
                    try:
                        xbmcvfs.delete(os.path.join(dest_dir, f))
                    except Exception:
                        pass
        except Exception:
            pass

        # Șterge TempSubtitle vechi
        try:
            temp_dir = xbmcvfs.translatePath('special://temp/')
            _, temp_files = xbmcvfs.listdir(temp_dir)
            for f in temp_files:
                if f.lower().startswith('tempsubtitle') and f.lower().endswith('.srt'):
                    try:
                        xbmcvfs.delete(os.path.join(temp_dir, f))
                    except Exception:
                        pass
        except Exception:
            pass

        dest_path = os.path.join(dest_dir, safe_name)

        # ── DESCĂRCARE ───────────────────────────────────────────
        if is_local:
            xbmcvfs.copy(url, dest_path)
            _log_debug(f"Local descărcat → {dest_path}")
        else:
            r = requests.get(url, timeout=20, headers=HEADERS)
            if not r.ok:
                _log_error(f"HTTP {r.status_code} la descărcare")
                xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                return
            try:
                fh = xbmcvfs.File(dest_path, 'w')
                fh.write(r.content)
                fh.close()
            except Exception:
                with open(dest_path, 'wb') as f:
                    f.write(r.content)

        _log_debug(f"Salvat → {dest_path} (local={is_local})")

        normalized_lcode = NORM.get(l_code, l_code)

        if is_local:
            needs_translation = False
        else:
            needs_translation = (normalized_lcode != chosen_lang)

        robot_on = False
        if robot is not None:
            try:
                robot_on = __addon__.getSettingBool('robot_activat')
            except Exception:
                pass

        # ── Copiază în temp ──────────────────────────────────────
        try:
            temp_dir = xbmcvfs.translatePath('special://temp/')
            if needs_translation and robot_on:
                temp_lang = chosen_lang
            else:
                temp_lang = NORM.get(l_code, l_code)
            temp_name = f"TempSubtitle.{temp_lang}.srt"
            temp_path = os.path.join(temp_dir, temp_name)
            xbmcvfs.copy(dest_path, temp_path)
        except Exception:
            temp_path = dest_path

        li = xbmcgui.ListItem(label=safe_name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=temp_path, listitem=li)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True)

        if is_local:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                f'Subtitrare locală [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] activată!',
                ADDON_ICON, 3000)
        elif needs_translation:
            if robot_on:
                _log_debug(f"Pornește traducerea din {l_code} → {chosen_lang}")
                xbmcgui.Dialog().notification(
                    ADDON_NAME,
                    f'Traducere [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] pornită...',
                    ADDON_ICON, 3000)
                threading.Thread(
                    target=robot.run_translation,
                    args=(__id__,),
                    daemon=True,
                ).start()
            elif robot is None:
                xbmcgui.Dialog().notification(
                    ADDON_NAME, 'Robotul nu e disponibil!',
                    ADDON_ICON, 4000)
            else:
                xbmcgui.Dialog().notification(
                    ADDON_NAME, 'Robot dezactivat',
                    ADDON_ICON, 4000)
        else:
            _log_debug(f"Limba este deja OK ({l_code}), nu necesită traducere.")

    except Exception as e:
        _log_error(f"Eroare procesare descărcare: {e}")
        try:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # ── Verifică dacă e RunScript (clean_saved) ──────────────────
    # RunScript trimite parametrii ca sys.argv[1], sys.argv[2], etc.
    # NU ca query string
    for arg in sys.argv:
        if 'clean_saved' in str(arg):
            _clean_saved_folder()
            sys.exit(0)

    # ── Flow normal (subtitle module) ────────────────────────────
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()