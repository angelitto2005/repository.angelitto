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
                matches.append((full_path, filename))
                matched_filenames.add(filename) # Salvăm numele ca să nu-l dublăm mai jos

    # ── METODA 2: Fallback filename (ACUM RULEAZĂ MEREU) ─────────
    current_key = _normalize(video_title) if video_title else ""

    for f in srt_files:
        if f in matched_filenames:
            continue # Dacă a fost deja găsit via index.json, sărim peste

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
    base_url = 'https://sub.wyzie.ru/search'

    try: source_opt = __addon__.getSettingInt('subtitle_source')
    except Exception: source_opt = 3

    if source_opt == 3: 
        RACE_TIMEOUT = 2.5   # Racing mode (foarte agresiv)
    else: 
        RACE_TIMEOUT = 25.0  # Mod dedicat (oferim timp agregatoarelor)

    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    
    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")
    video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
    
    junk_ids = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')
    if str(tmdb_id) in junk_ids: tmdb_id = None
    if str(imdb_id) in junk_ids: imdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt') and str(imdb_id).isdigit(): imdb_id = f"tt{imdb_id}"

    v_id = imdb_id or tmdb_id
    if not v_id and video_title:
        fetched = get_imdb_id_from_title(video_title, is_tv=bool(s and s != "0"))
        if fetched: v_id = imdb_id = fetched

    if not v_id and not video_title:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try: l_code = LANGS[__addon__.getSettingInt('subs_languages')]
    except Exception: l_code = "ro"

    # Metode sigure de citire bool pentru orice versiune de Kodi
    try: robot_activat = __addon__.getSettingBool('robot_activat')
    except Exception: robot_activat = str(__addon__.getSetting('robot_activat')).lower() == 'true'
    
    try: show_all = __addon__.getSettingBool('show_all_langs')
    except Exception: show_all = str(__addon__.getSetting('show_all_langs')).lower() == 'true'
    
    try: filter_sdh = __addon__.getSettingBool('filter_sdh')
    except Exception: filter_sdh = str(__addon__.getSetting('filter_sdh')).lower() == 'true'

    wyzie_api_key = __addon__.getSetting('wyzie_api_key').strip()

    # --- NOU: PROTECȚIE WYZIE LIPSĂ ---
    if source_opt == 0 and not wyzie_api_key:
        xbmcgui.Dialog().notification(ADDON_NAME, 'Cheie Wyzie lipsă! Adaugă în setări.', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    # ----------------------------------

    all_results = []
    saved_matches = _find_saved_subtitle(imdb_id, tmdb_id, video_title)
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

    def fetch_wyzie(search_params, allowed_langs=None):
        results = []
        try:
            # Asigurăm interogarea tuturor surselor dinamice
            search_params['source'] = 'all'
            r = requests.get(base_url, params=search_params, timeout=RACE_TIMEOUT)
            if not r.ok: return results
            
            for sub in r.json():
                t_code = sub.get('language', 'en')
                t_code_norm = NORM.get(t_code, t_code)
                
                if allowed_langs is not None and t_code_norm not in allowed_langs: 
                    continue
                
                url = sub.get('url', '')
                if not url: continue
                
                # --- EXTRAGEREA NUMELUI CURAT ---
                raw_fname = sub.get('release') or sub.get('fileName') or 'sub.srt'
                clean_release = re.split(r'<br\s*/?>|\n', raw_fname, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                
                if not clean_release.lower().endswith('.srt'):
                    clean_release += '.srt'
                
                # --- AFIȘARE DINAMICĂ A SURSEI ([WZ] + sursa originală colorată) ---
                source_dynamic = sub.get('source', 'api')
                fname_display = f"{clean_release} [B][COLOR FFB048B5][WZ][/COLOR][/B] [COLOR FF00BFFF]{source_dynamic}[/COLOR]"
                
                # --- VERIFICARE HI/SDH/CC (Tot JSON-ul) ---
                check_str = f"{raw_fname} {sub.get('url','')} {sub.get('id','')}".lower()
                is_sdh = sub.get('hearing_impaired', False) or bool(sdh_pattern.search(check_str))

                is_chosen = (t_code_norm == NORM.get(l_code, l_code))

                results.append({
                    'language_name': _get_lang_name(t_code),
                    'filename': fname_display,
                    'url': url,
                    'l_code': t_code,
                    'api_filename': clean_release,
                    'is_chosen': is_chosen,
                    'is_local': False,
                    'is_sdh': is_sdh
                })
        except Exception: pass
        return results

    def wyzie_worker():
        worker_results = []
        seen = set()
        lock = threading.Lock()

        def fetch_and_add(lang_code):
            params = dict(bp)
            if lang_code: params['language'] = lang_code
            for r in fetch_wyzie(params, None):
                with lock:
                    hash_key = f"{r['url']}_{r['filename']}"
                    if hash_key not in seen:
                        seen.add(hash_key)
                        worker_results.append(r)

        bp = {}
        if wyzie_api_key: bp['key'] = wyzie_api_key
        if v_id: bp['id'] = v_id
        elif video_title: bp['title'] = video_title
        if s and s != "0": bp['season'] = s; bp['episode'] = e

        if show_all:
            fetch_and_add(None)
        else:
            threads = []
            t1 = threading.Thread(target=fetch_and_add, args=(l_code,))
            threads.append(t1)
            t1.start()
            
            if l_code != 'en': # CERE MEREU EN CA FALLBACK!
                t2 = threading.Thread(target=fetch_and_add, args=('en',))
                threads.append(t2)
                t2.start()
                
            for t in threads:
                t.join()

        # Filtru local
        final_results = []
        for r in worker_results:
            short_lang = NORM.get(r['l_code'], r['l_code'])
            is_target = (short_lang == NORM.get(l_code, l_code))
            is_fallback = (short_lang == 'en' and l_code != 'en')
            
            if show_all or is_target or is_fallback:
                r['is_chosen'] = is_target
                final_results.append(r)
                
        return final_results

    def os_worker():
        results = []
        try:
            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)
            if not current_imdb_id: return results

            if s and e and s != '0': media_type, query_id = 'series', f"{current_imdb_id}:{s}:{e}"
            else: media_type, query_id = 'movie', current_imdb_id

            api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
            r = requests.get(api_url, headers=HEADERS, timeout=RACE_TIMEOUT)
            if not r.ok: return results

            subtitles = r.json().get('subtitles',[])
            fallback_en = (l_code != 'en') # CERE MEREU EN CA FALLBACK!

            # CERE DETALIILE EXACT CUM ERA ÎN ORIGINAL (Fără erori de API)
            if show_all:
                detailed_names = get_detailed_subtitle_names(current_imdb_id, season=s, episode=e)
            else:
                detailed_names = get_detailed_subtitle_names(current_imdb_id, target_lang=l_code, season=s, episode=e)
                if fallback_en: 
                    detailed_names.update(get_detailed_subtitle_names(current_imdb_id, target_lang='en', season=s, episode=e))

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
                raw_fname = detailed_names.get(sub_id, f"OpenSubtitles_{sub_id}.srt")
                fname_display = f"{raw_fname} [B][COLOR FFB048B5][OS][/COLOR][/B]"
                
                check_str = f"{raw_fname} {sub.get('url','')} {sub_id}".lower()
                is_sdh = sub.get('hearing_impaired', False) or bool(sdh_pattern.search(check_str))

                results.append({
                    'language_name': _get_lang_name(sub_l_code),
                    'filename': fname_display,
                    'url': url,
                    'l_code': sub_l_code,
                    'api_filename': raw_fname,
                    'is_chosen': is_target,
                    'is_local': False,
                    'is_sdh': is_sdh
                })
        except Exception: pass
        return results

    def subhero_worker():
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
                    r = requests.get(url, timeout=RACE_TIMEOUT)
                    if r.ok: return r.json().get('subtitles', [])
                except Exception: pass
                return []

            if show_all:
                subs = fetch_sh("ro,en,es,fr,de,it,hu,pt,ru,tr,bg,el,pl,cs,nl,ar")
            else:
                search_langs = [NORM.get(l_code, l_code)]
                if l_code != 'en': search_langs.append('en') # CERE MEREU EN CA FALLBACK!
                subs = fetch_sh(",".join(search_langs))
            
            seen = set()
            for sub in subs or []:
                s_lang = sub.get('lang', 'eng').lower()
                short_lang = NORM.get(s_lang, s_lang[:2])
                
                is_target = (short_lang == NORM.get(l_code, l_code))
                is_fallback = (short_lang == 'en' and l_code != 'en')
                
                if not (show_all or is_target or is_fallback): continue

                url = sub.get('url', '')
                if not url or url in seen: continue
                seen.add(url)
                
                raw_release = sub.get('release') or sub.get('description') or 'Subtitle'
                clean_release = re.split(r'<br\s*/?>|\n', raw_release, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                if not clean_release.lower().endswith('.srt'): clean_release += '.srt'

                fname_display = f"{clean_release} [B][COLOR FFB048B5][SH][/COLOR][/B]"
                
                check_str = f"{raw_release} {sub.get('description','')} {sub.get('url','')} {sub.get('id','')}".lower()
                is_sdh = sub.get('hearing_impaired', False) or bool(sdh_pattern.search(check_str))

                results.append({
                    'language_name': _get_lang_name(short_lang),
                    'filename': fname_display,
                    'url': url,
                    'l_code': short_lang,
                    'api_filename': clean_release,
                    'is_chosen': is_target,
                    'is_local': False,
                    'is_sdh': is_sdh
                })
        except Exception: pass
        return results

    online_results = []
    if source_opt == 0: online_results = wyzie_worker()
    elif source_opt == 1: online_results = os_worker()
    elif source_opt == 2: online_results = subhero_worker()
    else:
        fast_results = []
        fast_lock = threading.Lock()
        fast_event = threading.Event()
        finished_count = [0]
        
        def run_worker_thread(worker_func):
            res = worker_func()
            with fast_lock:
                if res:
                    # Acum adună rezultatele de la TOȚI providerii
                    fast_results.extend(res)
                
                finished_count[0] += 1
                # Abia când toți 3 au terminat, deblocăm așteptarea
                if finished_count[0] == 3: 
                    fast_event.set()

        t1 = threading.Thread(target=run_worker_thread, args=(wyzie_worker,), daemon=True)
        t2 = threading.Thread(target=run_worker_thread, args=(os_worker,), daemon=True)
        t3 = threading.Thread(target=run_worker_thread, args=(subhero_worker,), daemon=True)
        t1.start(); t2.start(); t3.start()
        
        fast_event.wait(timeout=3.5)
        RACE_STATE["finished"] = True
        online_results = fast_results

    all_results.extend(online_results)

    if filter_sdh:
        normal_subs = [r for r in all_results if not r.get('is_sdh', False)]
        if normal_subs:
            all_results = normal_subs

    all_results.sort(key=lambda x: (not x.get('is_local', False), not x['is_chosen'], x['language_name']))

    for res in all_results:
        # Arătăm vizual tag-ul [SDH] ca să știi exact cum a acționat filtrul
        display_name = res['filename']
        if res.get('is_sdh'):
            display_name += " [B][COLOR yellow][SDH][/COLOR][/B]"

        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(display_name)
        flag_code = l_code[:2] if res.get('is_local', False) else (res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code'])
        li.setArt({'thumb': flag_code, 'icon': flag_code})

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
            if robot_idx == 0: # Gemini
                keys = [__addon__.getSetting(f'api_key_{i}').strip() for i in range(1, 6)]
                if not any(keys):
                    xbmcgui.Dialog().notification(ADDON_NAME, 'Chei Gemini lipsă! Adaugă în setări.', xbmcgui.NOTIFICATION_ERROR, 5000)
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                    return
            elif robot_idx == 2: # Google Translate
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
            try: 
                # Verificăm STRICT dacă playerul încă există pe ecran
                if xbmc.getCondVisibility('Player.HasVideo'):
                    xbmc.Player().setSubtitles(path)
            except Exception: pass

        threading.Thread(target=force_activate, args=(temp_path,), daemon=True).start()

        # --- NOTIFICĂRI ȘI DECLANȘARE ---
        if is_local:
            xbmcgui.Dialog().notification(ADDON_NAME, f'Subtitrare locală [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] activată!', ADDON_ICON, 3000)
        elif needs_translation:
            if robot_on:
                xbmcgui.Dialog().notification(ADDON_NAME, f'Traducere [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] pornită...', ADDON_ICON, 3000)
                
                # Selectarea robotului corect
                if robot_idx == 1 and robot2 is not None:
                    threading.Thread(target=robot2.run_translation, args=(__id__,), daemon=True).start()
                elif robot_idx == 2 and robot3 is not None:
                    threading.Thread(target=robot3.run_translation, args=(__id__,), daemon=True).start()
                else:
                    threading.Thread(target=robot.run_translation, args=(__id__,), daemon=True).start()
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