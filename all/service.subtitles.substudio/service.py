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

robot = None; robot2 = None; robot3 = None; loader = None
try: import robot
except Exception: pass
try: import robot2
except Exception: pass
try: import robot3
except Exception: pass
try: import loader
except Exception: pass

try: import utils
except Exception: pass

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
    'dut':'nl','rum':'ro','ron':'ro','ro':'ro', # Adăugat ron și ro pentru siguranță
    'gre':'el','ell':'el','cze':'cs','pol':'pl',
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

# FIX CRITIC (Cloudflare Bypass): Adăugăm un "User-Agent" neutru de aplicație mobilă și, 
# EXTREM DE IMPORTANT, header-ul "Accept" setat doar pe "application/json".
# Când Cloudflare vede că ești o aplicație care vrea doar date JSON, 
# de obicei dezactivează provocarea JS/CAPTCHA care bloca Wyzie și SubHero!
HEADERS = {
    'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 10; SM-G975F Build/QP1A.190711.020)',
    'Accept': 'application/json, text/plain, */*',
    'Connection': 'keep-alive'
}

OS_REST_LANG = {
    'ro': 'rum', 'en': 'eng', 'es': 'spa', 'fr': 'fre', 'de': 'ger',
    'it': 'ita', 'hu': 'hun', 'pt': 'por', 'ru': 'rus', 'tr': 'tur',
    'bg': 'bul', 'el': 'gre', 'pl': 'pol', 'cs': 'cze', 'nl': 'dut'
}

# Variabilă globală pentru timeout-ul request-urilor (setată în search)
RACE_TIMEOUT = 10.0

def get_imdb_id_from_title(title, is_tv=False, kodi_year=None):
    """Găsește ID-ul IMDB folosind TMDB pe baza titlului și anului."""
    try:
        # Elimină informațiile de sezon/episod din nume
        clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', title, flags=re.IGNORECASE).strip()

        # Caută anul în text (ex: (2024), .2024., 2024)
        year_match = re.search(r'[\(\.\s](\d{4})[\)\.\s]?', clean_name)
        extracted_year = year_match.group(1) if year_match else None

        if extracted_year:
            clean_name = clean_name[:year_match.start()].strip(' .-_()')

        # Stabilim anul final (Kodi are prioritate dacă există și e valid)
        year = kodi_year if (kodi_year and str(kodi_year).isdigit() and int(kodi_year) > 1900) else extracted_year

        # Elimină sufixe de țară comune (AU, UK, US) ca TMDB să nu fie încurcat
        # dar salvăm sufixul pentru a alege corect rezultatul mai jos
        country_hint = None
        country_match = re.search(r'\b(AU|UK|US)\b', title, re.IGNORECASE)
        if country_match:
            country_hint = country_match.group(1).upper()
            clean_name = re.sub(r'\s+(AU|UK|US)$', '', clean_name, flags=re.IGNORECASE).strip()

        if not clean_name:
            return None

        media_type = "tv" if is_tv else "movie"
        search_url = f"{BASE_URL_TMDB}/search/{media_type}"

        def perform_tmdb_search(search_year):
            params = {"api_key": TMDB_API_KEY, "query": clean_name}
            if search_year:
                if is_tv: params["first_air_date_year"] = search_year
                else: params["primary_release_year"] = search_year
            try:
                r = requests.get(search_url, params=params, timeout=RACE_TIMEOUT).json()
                return r.get('results', [])
            except:
                return []

        # 1. Căutăm cu anul exact
        results = perform_tmdb_search(year)

        # 2. Fallback -1 an (Rezolvă problema "Fancy Dance 2024" care pe TMDB e 2023)
        if not results and year:
            _log_debug(f"Nu s-a găsit cu anul {year}, încercăm cu {int(year) - 1}")
            results = perform_tmdb_search(str(int(year) - 1))

        # 3. Fallback complet FĂRĂ an (pentru siguranță absolută)
        if not results and year:
            _log_debug("Nu s-a găsit cu an, facem fallback search complet fără an.")
            results = perform_tmdb_search(None)

        if results:
            best_result = results[0]

            # Dacă e serial și avem indiciu de țară (ex: Utopia AU), forțăm varianta corectă
            if is_tv and country_hint:
                for res in results:
                    if country_hint in res.get('origin_country', []):
                        best_result = res
                        break

            tmdb_id = best_result['id']
            ext_url = f"{BASE_URL_TMDB}/{media_type}/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": TMDB_API_KEY}, timeout=RACE_TIMEOUT).json()
            imdb_id = ext_r.get('imdb_id')

            _log_debug(f"Convertit '{clean_name}' (An: {year}) -> TMDB: {tmdb_id} -> IMDB: {imdb_id}")
            return imdb_id

    except Exception as e:
        if not RACE_STATE["finished"]: _log_error(f"TMDB Search Eroare: {str(e)}")
    return None

def get_detailed_subtitle_names(imdb_id, target_lang=None, season=None, episode=None):
    """Interoghează API-ul REST OpenSubtitles separat pt fiecare limbă necesară."""
    mapping = {}
    if not imdb_id:
        return mapping
    try:
        numeric_id = imdb_id.replace('tt', '')
        
        parts_base = []
        if season and str(season) != '0' and episode and str(episode) != '0':
            parts_base.append(f"episode-{episode}")
        parts_base.append(f"imdbid-{numeric_id}")
        if season and str(season) != '0':
            parts_base.append(f"season-{season}")
            
        langs_to_fetch = []
        if target_lang:
            for l in target_lang.split(','):
                langs_to_fetch.append(OS_REST_LANG.get(l.strip(), 'eng'))
        else:
            langs_to_fetch = [None] # Pentru modul "Arată Toate"
            
        # FIX CRITIC: Facem o cerere curată pentru fiecare limbă în parte ca OS să nu dea eroare!
        for lang in set(langs_to_fetch):
            parts = list(parts_base)
            if lang:
                parts.append(f"sublanguageid-{lang}")
            
            rest_url = "https://rest.opensubtitles.org/search/" + "/".join(parts)
            _log_debug(f"REST URL: {rest_url}")
            
            response = requests.get(rest_url, headers=HEADERS, timeout=RACE_TIMEOUT)
            if response.ok:
                data = response.json()
                if isinstance(data, list):
                    for item in data:
                        file_name = item.get('SubFileName')
                        if not file_name:
                            continue
                        
                        extra_info = {
                            'filename': file_name,
                            'hi': str(item.get('SubHearingImpaired', '0')) == '1',
                            'rating': str(item.get('SubRating', '0.0')),
                            'uploader': item.get('UserNickName') or 'Unknown',
                            'rank': item.get('UserRank') or ''
                        }

                        for key in ('IDSubtitleFile', 'IDSubtitle'):
                            val = str(item.get(key, ''))
                            if val:
                                mapping[val] = extra_info
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

def _find_saved_subtitle(imdb_id, tmdb_id, video_title, season, episode):
    saved_dir = _get_saved_folder()

    try:
        _, files = xbmcvfs.listdir(saved_dir)
    except Exception:
        return []

    srt_files = [f for f in files if f.lower().endswith('.srt')]
    if not srt_files:
        return []

    matches = []
    matched_filenames = set() # Folosim un set pentru a preveni duplicatele

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
                incomplete_path = os.path.join(saved_dir, filename)
                if xbmcvfs.exists(incomplete_path):
                    xbmcvfs.delete(incomplete_path)
                continue

            full_path = os.path.join(saved_dir, filename)
            if not xbmcvfs.exists(full_path):
                continue

            is_match = False
            if imdb_id and info.get('imdb') and imdb_id.lower().strip() == info['imdb'].lower().strip():
                is_match = True
            elif tmdb_id and info.get('tmdb') and str(tmdb_id).strip() == str(info['tmdb']).strip():
                is_match = True
            elif video_title and info.get('title'):
                n_idx = _normalize(info['title'])
                n_vid = _normalize(video_title)
                if n_idx and n_vid and (n_idx == n_vid or n_idx.startswith(n_vid) or n_vid.startswith(n_idx)):
                    is_match = True

            if is_match:
                # FIX S/E: Dacă e serial, asigură-te că nu dă S01E01 în loc de S01E15
                if season and episode and str(season) != '0':
                    info_s = str(info.get('season', ''))
                    info_e = str(info.get('episode', ''))
                    # Dacă în index avem sezon/episod salvat, le comparăm strict
                    if info_s and info_e:
                        if str(season) != info_s or str(episode) != info_e:
                            is_match = False

            if is_match:
                matches.append((full_path, filename))
                matched_filenames.add(filename)

    # ── METODA 2: Fallback filename ──────────────────────────────
    current_key = _normalize(video_title) if video_title else ""

    for f in srt_files:
        if f in matched_filenames:
            continue

        saved_key = _normalize(_extract_title_key(f)) if current_key else ""
        is_match = False

        if imdb_id and imdb_id.lower() in f.lower():
            is_match = True
        elif current_key and saved_key:
            ck_words = current_key.split()[:3]
            sk_words = saved_key.split()[:3]

            if len(ck_words) >= 1 and ck_words == sk_words:
                is_match = True
            elif len(current_key) >= 3 and (current_key in saved_key or saved_key in current_key):
                is_match = True

        # Dacă e serial, verificăm ca numele fișierului să aibă formatul S01E15 sau 1x15
        if is_match and season and episode and str(season) != '0':
            ep_pattern1 = f"s{int(season):02d}e{int(episode):02d}"
            ep_pattern2 = f"{int(season)}x{int(episode):02d}"
            if ep_pattern1 not in f.lower() and ep_pattern2 not in f.lower():
                is_match = False

        if is_match:
            matches.append((os.path.join(saved_dir, f), f))
            matched_filenames.add(f)

    _log_debug(f"{len(matches)} potriviri locale.")
    return matches

# ════════════════════════════════════════════════════════════════════
#  SEARCH
# ════════════════════════════════════════════════════════════════════
def search():
    global RACE_STATE, RACE_TIMEOUT
    RACE_STATE["finished"] = False
    base_url = 'https://sub.wyzie.io/search'

    try: source_opt = __addon__.getSettingInt('subtitle_source')
    except Exception: source_opt = 3

    if source_opt == 3: 
        RACE_TIMEOUT = 15.0   # Relaxat de la 2.5s la 6s pentru a da timp alternativelor Wyzie/SubHero
    else: 
        RACE_TIMEOUT = 25.0  # Mod dedicat (oferim timp agregatoarelor)

    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    
    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")
    video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
    
    # 1. Extragere agresivă a anului din etichetele Kodi
    kodi_year = xbmc.getInfoLabel("VideoPlayer.Year") or \
                xbmc.getInfoLabel("ListItem.Year") or \
                xbmc.getInfoLabel("ListItem.Premiered")
                
    if not kodi_year or len(str(kodi_year)) < 4:
        kodi_year = xbmcgui.Window(10000).getProperty("ListItem.Year")
        
    if kodi_year and len(str(kodi_year)) >= 4:
        kodi_year = str(kodi_year)[:4]
    else:
        kodi_year = None

    # 2. Extragere de rezervă (An și Țară) direct din numele fișierului/link-ului
    try:
        file_path = unquote(xbmc.Player().getPlayingFile())
        _log_debug(f"Verific link fisier pentru indicii: {file_path}")
        
        # Căutăm anul în formatul .2014. sau (2014) din link
        if not kodi_year:
            match_y = re.search(r'[\(\.\s](\d{4})[\)\.\s]', file_path)
            if match_y:
                kodi_year = match_y.group(1)
                _log_debug(f"Anul {kodi_year} a fost extras din numele fișierului.")
                
        # Căutăm 'AU' (Australia) în nume dacă lipsește din titlul Kodi
        if "au" in file_path.lower() and "au" not in video_title.lower():
            # Ne asigurăm că e AU izolat (ex: Utopia.AU.S03), nu un cuvânt ca "audio"
            if re.search(r'[\.\s_]au[\.\s_]', file_path, re.IGNORECASE):
                video_title += " AU"
                _log_debug("S-a adăugat automat sufixul 'AU' din denumirea fișierului.")
    except Exception as e:
        _log_debug(f"Eroare procesare nume fisier: {e}")
    
    junk_ids = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')
    if str(tmdb_id) in junk_ids: tmdb_id = None
    if str(imdb_id) in junk_ids: imdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt') and str(imdb_id).isdigit(): imdb_id = f"tt{imdb_id}"

    v_id = imdb_id or tmdb_id
    if not v_id and video_title:
        fetched = get_imdb_id_from_title(video_title, is_tv=bool(s and s != "0"), kodi_year=kodi_year)
        if fetched: v_id = imdb_id = fetched

    if not v_id and not video_title:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try: l_code = LANGS[__addon__.getSettingInt('subs_languages')]
    except Exception: l_code = "ro"

    robot_activat = __addon__.getSettingBool('robot_activat')
    show_all = __addon__.getSettingBool('show_all_langs')
    filter_sdh = __addon__.getSettingBool('filter_sdh')
    wyzie_api_key = __addon__.getSetting('wyzie_api_key').strip()

    # --- NOU: PROTECȚIE WYZIE LIPSĂ ---
    if source_opt == 0 and not wyzie_api_key:
        xbmcgui.Dialog().notification(ADDON_NAME, 'Cheie Wyzie lipsă! Adaugă în setări.', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    # ----------------------------------

    all_results = []
    # Acum trimitem și sezonul (s) și episodul (e) pentru potrivire exactă
    saved_matches = _find_saved_subtitle(imdb_id, tmdb_id, video_title, s, e)
    local_seen = set()
    for saved_path, saved_name in saved_matches:
        if saved_path in local_seen: continue
        local_seen.add(saved_path)
        all_results.append({
            'language_name': f'[B][COLOR yellow]LOCAL[/COLOR][/B]',
            'filename': saved_name,
            'url': saved_path,
            'l_code': l_code,
            'api_filename': saved_name,
            'is_chosen': True,
            'is_local': True,
            'is_sdh': False
        })

    # Regex blindat pentru SDH/HI care ocolește problema cu underscore-ul din Python!
    sdh_pattern = re.compile(r'(?:^|[^a-z0-9])(sdh|cc|hi|hearing[\s_]*impaired)(?:[^a-z0-9]|$)', re.IGNORECASE)

    def fetch_wyzie(search_params):
        results = []
        try:
            # ELIMINĂM source=all pentru că blochează rezultatele RO
            if 'source' in search_params: del search_params['source']
            if 'language' in search_params: del search_params['language']
            
            _log_debug(f"[WYZIE] Apel API Curat: {base_url}?{urlencode(search_params)}")
            
            r = requests.get(base_url, params=search_params, headers=HEADERS, timeout=RACE_TIMEOUT)
            if not r.ok: return results
            
            for sub in r.json():
                t_code = sub.get('language', 'en')
                t_code_norm = NORM.get(t_code.lower(), t_code.lower())
                
                url = sub.get('url', '')
                if not url: continue
                
                raw_fname = sub.get('release') or sub.get('fileName') or 'sub.srt'
                clean_release = re.split(r'<br\s*/?>|\n', raw_fname, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                if not clean_release.lower().endswith('.srt'): clean_release += '.srt'
                
                is_sdh = sub.get('isHearingImpaired', False) or sub.get('hearing_impaired', False) or bool(sdh_pattern.search(f"{raw_fname} {url}".lower()))

                try: dl_count = int(sub.get('downloadCount') or 0)
                except: dl_count = 0
                
                w_rating = 6.0 
                if dl_count >= 50000: w_rating = 10.0
                elif dl_count >= 10000: w_rating = 8.0
                
                results.append({
                    'language_name': _get_lang_name(t_code_norm),
                    'filename': f"{clean_release} [B][COLOR FFB048B5][WZ][/COLOR][/B]",
                    'url': url,
                    'l_code': t_code,
                    'l_code_norm': t_code_norm,
                    'api_filename': clean_release,
                    'is_local': False,
                    'is_sdh': is_sdh,
                    'rating': w_rating
                })
        except Exception as e:
            _log_debug(f"[WYZIE] Eroare API: {e}")
        return results


    def wyzie_worker():
        worker_results = []
        bp = {'key': wyzie_api_key}
        if v_id: bp['id'] = v_id
        elif video_title: bp['title'] = video_title
        if s and s != "0": bp['season'] = s; bp['episode'] = e

        # Facem UN SINGUR apel care aduce toate limbile
        raw_list = fetch_wyzie(bp)
        
        target_norm = NORM.get(l_code, l_code)
        
        final_results = []
        for r in raw_list:
            r_lang = r['l_code_norm']
            
            is_target = (r_lang == target_norm)
            is_fallback = (r_lang == 'en' and l_code != 'en')

            # Dacă "Arată toate" e oprit, filtrăm doar RO și EN
            if show_all or is_target or is_fallback:
                r['is_chosen'] = is_target # Prioritate la sortare pentru limba din setări
                final_results.append(r)
                
        _log_debug(f"[WYZIE] S-au filtrat {len(final_results)} rezultate din {len(raw_list)} totale.")
        return final_results

    def os_worker():
        nonlocal s, e, video_title, imdb_id
        results = []
        try:
            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)
            if not current_imdb_id: return results

            if s and e and s != '0': media_type, query_id = 'series', f"{current_imdb_id}:{s}:{e}"
            else: media_type, query_id = 'movie', current_imdb_id

            api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
            _log_debug(f"[OS] Face cerere API către: {api_url}")
            r = requests.get(api_url, headers=HEADERS, timeout=RACE_TIMEOUT)
            if not r.ok: 
                return results

            subtitles = r.json().get('subtitles',[])
            fallback_en = (l_code != 'en')

            if show_all:
                detailed_names = get_detailed_subtitle_names(current_imdb_id, target_lang=None, season=s, episode=e)
            else:
                lang_query = f"{l_code},en" if fallback_en else l_code
                detailed_names = get_detailed_subtitle_names(current_imdb_id, target_lang=lang_query, season=s, episode=e)

            seen = set()
            for sub in subtitles:
                sub_lang_raw = sub.get('lang', '')
                sub_l_code = NORM.get(sub_lang_raw, sub_lang_raw)
                is_target = (sub_l_code == NORM.get(l_code, l_code))
                is_fallback = (sub_l_code == 'en' and fallback_en)

                if not (show_all or is_target or is_fallback): continue

                url = sub.get('url', '')
                if not url or url in seen: continue
                seen.add(url)

                sub_id = str(sub.get('id', ''))
                detailed_info = detailed_names.get(sub_id)
                
                if detailed_info:
                    raw_fname = detailed_info['filename']
                    hi_flag = detailed_info['hi']
                    rating = detailed_info['rating']
                    uploader = detailed_info['uploader']
                    rank = detailed_info['rank']
                else:
                    raw_fname = f"OpenSubtitles_{sub_id}.srt"
                    hi_flag = False
                    rating = "0.0"
                    uploader = ""
                    rank = ""

                fname_display = f"{raw_fname} [B][COLOR FFB048B5][OS][/COLOR][/B]"
                
                check_str = f"{raw_fname} {sub.get('url','')} {sub_id}".lower()
                is_sdh = sub.get('hearing_impaired', False) or hi_flag or bool(sdh_pattern.search(check_str))

                # Adăugăm doar numele de uploader în text, FĂRĂ steluțe grafice!
                if uploader and uploader != "Unknown":
                    rank_display = f" ({rank})" if rank else ""
                    # fname_display += f" [COLOR gray]- {uploader}{rank_display}[/COLOR]"
                    fname_display += f" [COLOR gray]- by [B][COLOR FF00BFFF]{uploader}[COLOR orange]{rank_display}[/COLOR][/B]"

                results.append({
                    'language_name': _get_lang_name(sub_l_code),
                    'filename': fname_display,
                    'url': url,
                    'l_code': sub_l_code,
                    'api_filename': raw_fname,
                    'is_chosen': is_target,
                    'is_local': False,
                    'is_sdh': is_sdh,
                    'rating': rating  # O păstrăm ascunsă pentru a o da lui Kodi
                })
        except Exception as e: 
            pass
        return results

    def subhero_worker():
        nonlocal s, e, video_title, imdb_id
        results = []
        try:
            from urllib.parse import quote
            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)
            if not current_imdb_id: return results

            v_type = "series" if (s and str(s) != "0") else "movie"
            v_id_sh = f"{current_imdb_id}:{s}:{e}" if v_type == "series" else current_imdb_id

            def fetch_sh(langs_str):
                config_dict = {"language": langs_str, "onlyReturnMatching": False}
                config_encoded = quote(json.dumps(config_dict, separators=(',', ':')))
                url = f"https://subhero.chromeknight.dev/{config_encoded}/subtitles/{v_type}/{v_id_sh}/manifest.json"
                try:
                    r = requests.get(url, headers=HEADERS, timeout=RACE_TIMEOUT)
                    if r.ok: return r.json().get('subtitles', [])
                except: pass
                return []

            subs = fetch_sh("ro,en,es,fr,de,it,hu,pt,ru,tr,bg,el,pl,cs,nl,ar") if show_all else fetch_sh(",".join([NORM.get(l_code, l_code), 'en']))
            
            try: v_path = xbmc.Player().getPlayingFile().lower()
            except: v_path = ""

            seen = set()
            for sub in subs or []:
                url = sub.get('url', '')
                if not url or url in seen: continue
                seen.add(url)
                
                s_lang = sub.get('lang', 'eng').lower()
                short_lang = NORM.get(s_lang, s_lang[:2])
                
                raw_release = sub.get('release') or sub.get('description') or 'Subtitle'
                clean_release = re.split(r'<br\s*/?>|\n', raw_release, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                if not clean_release.lower().endswith('.srt'): clean_release += '.srt'

                # --- LOGICĂ RATING INTELIGENTĂ PT SUBHERO ---
                # Plecăm de la o notă de bază (4.0 = 2 stele)
                sh_rating = 4.0
                rel_low = clean_release.lower()
                sync_tags = ['web-dl', 'webrip', 'bluray', 'brrip', 'x264', 'x265', 'hevc', '1080p', '720p', '2160p', 'hdtv']
                
                # Calculăm câte tag-uri coincid cu fișierul video curent
                matches = sum(1 for tag in sync_tags if tag in rel_low and tag in v_path)
                if matches >= 3: sh_rating = 10.0  # 5 stele
                elif matches >= 1: sh_rating = 8.0 # 4 stele
                
                is_sdh = sub.get('hearing_impaired', False) or bool(sdh_pattern.search(f"{raw_release} {url}".lower()))

                results.append({
                    'language_name': _get_lang_name(short_lang),
                    'filename': f"{clean_release} [B][COLOR FFB048B5][SH][/COLOR][/B]",
                    'url': url,
                    'l_code': short_lang,
                    'api_filename': clean_release,
                    'is_chosen': (short_lang == NORM.get(l_code, l_code)),
                    'is_local': False,
                    'is_sdh': is_sdh,
                    'rating': sh_rating # Trimitem rating-ul calculat
                })
        except Exception: pass
        return results

    online_results = []
    if source_opt == 0: online_results = wyzie_worker()
    elif source_opt == 1: online_results = os_worker()
    elif source_opt == 2: online_results = subhero_worker()
    else:
        # ── MODUL RACING ADEVĂRAT ("FIRST TO FIND WINS") ──
        fast_results = []
        fast_lock = threading.Lock()
        
        # Un Event special care se declanșează DOAR când un provider găsește măcar 1 subtitrare
        fast_event = threading.Event()
        
        # Variabilă comună pentru a număra câți provideri și-au terminat cursa
        finished_count = [0]
        
        def run_worker_thread(worker_func, name):
            try:
                res = worker_func()
                with fast_lock:
                    _log_debug(f"[RACING] {name} a terminat cursa și a adus {len(res) if res else 0} rezultate.")
                    
                    finished_count[0] += 1
                    
                    # 1. Dacă providerul A GĂSIT rezultate și cursa nu s-a oprit deja:
                    if res and not fast_event.is_set():
                        fast_results.extend(res)
                        _log_debug(f"[RACING] WINNER! {name} a câștigat cursa! Oprim cronometrul!")
                        fast_event.set() # Declansăm finalul cursei!
                        
                    # 2. Dacă e ULTIMUL provider și nimeni n-a găsit nimic:
                    elif finished_count[0] == 3 and not fast_event.is_set():
                        _log_debug("[RACING] Toți au terminat și toți au 0 rezultate...")
                        fast_event.set() # Eliberăm blocajul
                        
            except Exception as e:
                _log_debug(f"[RACING] Eroare critică în firul {name}: {e}")
                with fast_lock:
                    finished_count[0] += 1
                    if finished_count[0] == 3 and not fast_event.is_set():
                        fast_event.set()

        t1 = threading.Thread(target=run_worker_thread, args=(wyzie_worker, "WYZIE"), daemon=True)
        t2 = threading.Thread(target=run_worker_thread, args=(os_worker, "OS"), daemon=True)
        t3 = threading.Thread(target=run_worker_thread, args=(subhero_worker, "SUBHERO"), daemon=True)
        t1.start(); t2.start(); t3.start()
        
        # Așteptăm maxim 12.5 secunde SAU până când Primul câștigător aduce rezultate valide.
        fast_event.wait(timeout=15)
        
        with fast_lock:
            _log_debug(f"[RACING] Finish cursă. S-au preluat în total {len(fast_results)} rezultate.")
            RACE_STATE["finished"] = True
            online_results = fast_results

    all_results.extend(online_results)

    if filter_sdh:
        normal_subs = [r for r in all_results if not r.get('is_sdh', False)]
        if normal_subs:
            all_results = normal_subs

    try:
        video_path = xbmc.Player().getPlayingFile().lower()
    except:
        video_path = ""

    all_results.sort(key=lambda x: (not x.get('is_local', False), not x['is_chosen'], x['language_name']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])
        
        # --- LOGICĂ STELUȚE (Mapare 1-5 ca în sistemul Kodi) ---
        try:
            # Transformăm orice rating (string sau float) în float
            val = float(res.get('rating', 0.0) or 0.0)
            
            # Mapare manuală pe 5 stele pentru a evita rotunjirile greșite
            if val <= 0.0: stars = "0"
            elif val <= 2.0: stars = "1"
            elif val <= 4.0: stars = "2"
            elif val <= 6.0: stars = "3"
            elif val <= 8.5: stars = "4"
            else: stars = "5"
        except:
            stars = "0"
            
        # FIX: Folosim formatul exact din RegieLive (Nota la icon, steagul la thumb)
        flag_code = l_code[:2] if res.get('is_local', False) else (res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code'])
        li.setArt({'thumb': flag_code, 'icon': stars})
        
        # Proprietăți extra pentru skin-uri
        li.setProperty('rating', stars)
        li.setProperty('hearing_imp', "true" if res.get('is_sdh', False) else "false")
        
        # Calcul Sync
        sub_name_lower = res.get('api_filename', '').lower()
        sync_tags = ['amzn', 'web-dl', 'webrip', 'bluray', 'brrip', 'x264', 'x265', 'hevc', '1080p', '720p', '2160p']
        m_score = sum(1 for tag in sync_tags if tag in sub_name_lower and tag in video_path)
        li.setProperty('sync', "true" if (res.get('is_local', False) or m_score > 0) else "false")

        d_params = {'action': 'download', 'url': res['url'], 'l_code': res['l_code'], 'api_filename': res['api_filename'], 'is_local': '1' if res.get('is_local', False) else '0'}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)


# ════════════════════════════════════════════════════════════════════
#  DOWNLOAD
# ════════════════════════════════════════════════════════════════════
def download(params):
    import time
    import re
    try:
        url       = unquote(params.get('url', ''))
        l_code    = params.get('l_code', 'unknown')
        is_local  = params.get('is_local', '0') == '1'

        try:
            chosen_lang = LANGS[__addon__.getSettingInt('subs_languages')]
        except Exception:
            chosen_lang = "ro"

        normalized_lcode = NORM.get(l_code, l_code)
        needs_translation = False if is_local else (normalized_lcode != chosen_lang)

        robot_on = False
        robot_idx = 0
        if robot is not None:
            try: 
                robot_on = __addon__.getSettingBool('robot_activat')
                robot_idx = __addon__.getSettingInt('robot_selectat')
            except Exception: pass

        # --- NOU: VERIFICARE LIPSĂ CHEI ROBOT ÎNAINTE DE DOWNLOAD ---
        if needs_translation and robot_on:
            if robot_idx in [0, 1]: # Gemini Fast sau Slow
                keys = [__addon__.getSetting(f'api_key_{i}').strip() for i in range(1, 6)]
                if not any(keys):
                    xbmcgui.Dialog().notification(ADDON_NAME, 'Chei Gemini lipsă! Adaugă în setări.', xbmcgui.NOTIFICATION_ERROR, 5000)
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                    return
            elif robot_idx == 3: # Google Translate
                keys = [__addon__.getSetting(f'api_key_r1_{i}').strip() for i in range(1, 6)]
                if not any(keys):
                    xbmcgui.Dialog().notification(ADDON_NAME, 'Chei Google lipsă! Adaugă în setări.', xbmcgui.NOTIFICATION_ERROR, 5000)
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                    return
        # -----------------------------------------------------------

        # --- FIX 1: Nume corect și original ---
        api_filename = params.get('api_filename') or 'subtitle'
        if api_filename.lower().endswith('.srt'):
            api_filename = api_filename[:-4]
        
        # Eliminăm orice cod de limbă agățat la final (ex: Film.en -> Film)
        api_filename = re.sub(r'\.[a-z]{2,3}$', '', api_filename, flags=re.IGNORECASE)

        # Salvăm fișierul inițial cu limba LUI REALĂ descărcată (ex: .en.srt)
        # Robotul se va ocupa să-l transforme în .ro.srt la final.
        safe_name = _safe_filename(f"{api_filename}.{normalized_lcode}.srt")

        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir):
            xbmcvfs.mkdirs(dest_dir)

        try:
            _, old_files = xbmcvfs.listdir(dest_dir)
            for f in old_files:
                if f.lower().endswith('.srt'):
                    try: xbmcvfs.delete(os.path.join(dest_dir, f))
                    except Exception: pass
        except Exception:
            pass

        # --- FIX 2: Folder TEMP dedicat si autocurățare ---
        base_temp = xbmcvfs.translatePath('special://temp/substudio_subs/')
        if not xbmcvfs.exists(base_temp):
            xbmcvfs.mkdirs(base_temp)

        # Ștergem absolut tot din folderul dedicat la fiecare rulare
        try:
            dirs, files = xbmcvfs.listdir(base_temp)
            for d in dirs:
                folder_to_delete = os.path.join(base_temp, d)
                try:
                    _, subfiles = xbmcvfs.listdir(folder_to_delete)
                    for sf in subfiles: xbmcvfs.delete(os.path.join(folder_to_delete, sf))
                    xbmcvfs.rmdir(folder_to_delete)
                except Exception: pass
            for f in files:
                try: xbmcvfs.delete(os.path.join(base_temp, f))
                except Exception: pass
        except Exception:
            pass

        dest_path = os.path.join(dest_dir, safe_name)

        # ── DESCĂRCARE ───────────────────────────────────────────
        if is_local:
            xbmcvfs.copy(url, dest_path)
        else:
            r = requests.get(url, timeout=20, headers=HEADERS)
            if not r.ok or b'<html' in r.content.lower():
                _log_error("Fișier descărcat invalid sau HTML")
                xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                return

            try: text = r.content.decode('utf-8')
            except UnicodeDecodeError:
                try: text = r.content.decode('cp1250')
                except UnicodeDecodeError:
                    try: text = r.content.decode('iso-8859-2')
                    except UnicodeDecodeError: text = r.content.decode('utf-8', errors='replace')

            text = text.lstrip('\ufeff')
            utf8_content = b'\xef\xbb\xbf' + text.encode('utf-8')

            try:
                fh = xbmcvfs.File(dest_path, 'wb')
                fh.write(utf8_content)
                fh.close()
            except Exception:
                with open(dest_path, 'wb') as f:
                    f.write(utf8_content)

        timestamp = int(time.time())
        # Creăm folderul în subdirectorul nostru curat!
        unique_temp_folder = os.path.join(base_temp, f"sub_{timestamp}")
        xbmcvfs.mkdirs(unique_temp_folder)
        temp_path = os.path.join(unique_temp_folder, safe_name)
        
        try: xbmcvfs.copy(dest_path, temp_path)
        except Exception: temp_path = dest_path

        # Predăm ștafeta oficială către Kodi
        li = xbmcgui.ListItem(label=safe_name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=temp_path, listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True)

        def force_activate(path):
            xbmc.sleep(800)
            try: xbmc.Player().setSubtitles(path)
            except Exception: pass

        threading.Thread(target=force_activate, args=(temp_path,), daemon=True).start()

        # --- NOTIFICĂRI ȘI DECLANȘARE ---
        if is_local:
            xbmcgui.Dialog().notification(ADDON_NAME, f'Subtitrare locală [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] activată!', ADDON_ICON, 3000)
        elif needs_translation:
            if robot_on:
                xbmcgui.Dialog().notification(ADDON_NAME, f'Traducere [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] pornită...', ADDON_ICON, 3000)
                
                # Selectarea robotului corect (Cu mod Fast / Slow)
                if robot_idx == 0 and robot is not None:
                    threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'fast'}, daemon=True).start()
                elif robot_idx == 1 and robot is not None:
                    threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'slow'}, daemon=True).start()
                elif robot_idx == 2 and robot2 is not None:
                    threading.Thread(target=robot2.run_translation, args=(__id__,), daemon=True).start()
                elif robot_idx == 3 and robot3 is not None:
                    threading.Thread(target=robot3.run_translation, args=(__id__,), daemon=True).start()
                else:
                    threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'fast'}, daemon=True).start()
            else:
                # Dacă e OPRIT robotul, o lăsăm să ruleze normal în player și notificăm:
                xbmcgui.Dialog().notification(
                    ADDON_NAME, 
                    f'Subtitrare [B][COLOR orange]{normalized_lcode.upper()}[/COLOR][/B] activată. Robot oprit!', 
                    ADDON_ICON, 4000
                )
        else:
            _log_debug(f"Limba este deja OK ({l_code}), nu necesită traducere.")
            
    except Exception as e:
        _log_error(f"Eroare procesare descărcare: {e}")
        try: xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception: pass

# ════════════════════════════════════════════════════════════════════
#  CURĂȚARE GUNOAIELOR DIN SETĂRI (Janitor)
# ════════════════════════════════════════════════════════════════════
def _cleanup_orphaned_settings():
    """Curăță settings.xml din addon_data de setările vechi, eliminate din script."""
    import xml.etree.ElementTree as ET
    try:
        current_version = __addon__.getAddonInfo('version')
        last_version = __addon__.getSetting('last_run_version')
        
        # Dacă versiunile sunt la fel, înseamnă că am curățat deja, ieșim rapid!
        if current_version == last_version:
            return 
            
        addon_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
        # Verificăm unde ține addon-ul fișierul de bază (în root sau în resources)
        addon_settings_path = os.path.join(addon_dir, 'resources', 'settings.xml')
        if not xbmcvfs.exists(addon_settings_path):
            addon_settings_path = os.path.join(addon_dir, 'settings.xml')
            
        user_data_dir = xbmcvfs.translatePath(f"special://profile/addon_data/{__id__}/")
        user_settings_path = os.path.join(user_data_dir, 'settings.xml')
        
        if not xbmcvfs.exists(addon_settings_path) or not xbmcvfs.exists(user_settings_path):
            __addon__.setSetting('last_run_version', current_version)
            return
            
        # 1. COLECTĂM TOATE ID-urile VALIDE (Chei API, limbi, etc.)
        valid_ids = set()
        tree_base = ET.parse(addon_settings_path)
        for elem in tree_base.iter('setting'):
            if 'id' in elem.attrib:
                valid_ids.add(elem.attrib['id'])
                
        # 2. CURĂȚĂM FIȘIERUL UTILIZATORULUI DE GUNOAIЕ
        tree_user = ET.parse(user_settings_path)
        root_user = tree_user.getroot()
        
        changed = False
        # Căutăm toate setările salvate de Kodi
        for elem in root_user.findall('setting'):
            s_id = elem.attrib.get('id')
            # Dacă id-ul există în addon_data dar NU mai există în addon, îl tăiem!
            if s_id and s_id not in valid_ids:
                root_user.remove(elem)
                changed = True
                _log_debug(f"Setare veche ștearsă (gunoi): {s_id}")
                
        # Salvăm fișierul curat înapoi
        if changed:
            tree_user.write(user_settings_path, encoding='utf-8', xml_declaration=True)
            _log_debug("Settings.xml din addon_data a fost curățat cu succes de setările orfane!")
            
        # Salvăm noua versiune ca să nu mai rulăm până la următorul update
        __addon__.setSetting('last_run_version', current_version)
        
    except Exception as e:
        _log_debug(f"Eroare non-critică la curățarea setărilor: {e}")


# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Rulăm curățenia în fundal rapid
    _cleanup_orphaned_settings()

    # ── Verifică dacă e RunScript (clean_saved, suport, log) ─────────
    for arg in sys.argv:
        if 'clean_saved' in str(arg):
            _clean_saved_folder()
            sys.exit(0)
        elif 'upload_log' in str(arg):
            if utils is not None: utils.upload_logfile()
            sys.exit(0)
        elif 'show_donate' in str(arg):
            if utils is not None: utils.show_donate_link()
            sys.exit(0)

    # ── Flow normal (subtitle module) ────────────────────────────
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()