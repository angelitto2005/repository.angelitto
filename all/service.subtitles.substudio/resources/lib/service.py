# -*- coding: utf-8 -*-
import os, sys, re, json, unicodedata, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__    = __addon__.getAddonInfo('id')

# ── FUNCTIONS FOR LOG CONTROL FROM SETTINGS ────────────────
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
        xbmc.log(f"SUBSTUDIO ERROR: {msg}", xbmc.LOGERROR)
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

# ── HANDLE — protected against RunScript ───────────────────────────
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
    'dut':'nl','rum':'ro','ron':'ro','ro':'ro',
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

# ── Special OS REST mapping ────────────────────────────────────────
ISO_MAP_OS = {
    "ro": "rum", "en": "eng", "es": "spa", "fr": "fre", "de": "ger",
    "it": "ita", "hu": "hun", "pt": "por", "ru": "rus", "tr": "tur",
    "bg": "bul", "el": "ell", "pl": "pol", "cs": "cze", "nl": "dut",
    "ar": "ara", "zh": "chi", "ja": "jpn", "ko": "kor", "sv": "swe",
    "da": "dan", "fi": "fin", "no": "nor", "hr": "hrv", "sr": "srp",
    "sk": "slo", "sl": "slv", "uk": "ukr", "he": "heb", "th": "tha",
    "vi": "vie", "id": "ind", "ms": "may", "hi": "hin", "fa": "per",
    "ca": "cat", "eu": "baq", "gl": "glg", "et": "est", "lv": "lav",
    "lt": "lit", "mk": "mac", "sq": "alb", "bs": "bos", "is": "ice"
}

# ════════════════════════════════════════════════════════════════════
#  OPENSUBTITLES & TMDB CONFIGURATIONS
# ════════════════════════════════════════════════════════════════════
TMDB_API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL_TMDB = "https://api.themoviedb.org/3"

HEADERS = {
    'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 10; SM-G975F Build/QP1A.190711.020)',
    'Accept': 'application/json, text/plain, */*',
    'Connection': 'keep-alive'
}

RACE_TIMEOUT = 10.0

def get_imdb_id_from_title(title, is_tv=False, kodi_year=None):
    try:
        clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', title, flags=re.IGNORECASE).strip()
        year_match = re.search(r'[\(\.\s](\d{4})[\)\.\s]?', clean_name)
        extracted_year = year_match.group(1) if year_match else None

        if extracted_year:
            clean_name = clean_name[:year_match.start()].strip(' .-_()')

        year = kodi_year if (kodi_year and str(kodi_year).isdigit() and int(kodi_year) > 1900) else extracted_year

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

        results = perform_tmdb_search(year)

        if not results and year:
            _log_debug(f"Did not find with year {year}, trying with {int(year) - 1}")
            results = perform_tmdb_search(str(int(year) - 1))

        if not results and year:
            _log_debug("Did not find with year, doing full fallback search without year.")
            results = perform_tmdb_search(None)

        if results:
            best_result = results[0]

            if is_tv and country_hint:
                for res in results:
                    if country_hint in res.get('origin_country', []):
                        best_result = res
                        break

            tmdb_id = best_result['id']
            ext_url = f"{BASE_URL_TMDB}/{media_type}/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": TMDB_API_KEY}, timeout=RACE_TIMEOUT).json()
            imdb_id = ext_r.get('imdb_id')

            _log_debug(f"Converted '{clean_name}' (Year: {year}) -> TMDB: {tmdb_id} -> IMDB: {imdb_id}")
            return imdb_id

    except Exception as e:
        if not RACE_STATE["finished"]: _log_error(f"TMDB Search Error: {str(e)}")
    return None

def _get_lang_name(code):
    if not code:
        return 'Unknown'
    return LANG_MAP.get(code, LANG_MAP.get(code.lower(), code.upper()))

def _safe_filename(name):
    name = re.sub(r'[<>:"|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def _normalize(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', '', s.lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return s

# ════════════════════════════════════════════════════════════════════
#  SAVED SUBTITLES FOLDER
# ════════════════════════════════════════════════════════════════════
def _get_saved_folder():
    profile = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
    saved_dir = os.path.join(profile, 'Translated Subtitles')
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
            xbmcgui.Dialog().notification(ADDON_NAME, f'[B][COLOR lime]{count}[/COLOR][/B] files deleted!', ADDON_ICON, 4000)
        else:
            xbmcgui.Dialog().notification(ADDON_NAME, 'The folder was already empty.', ADDON_ICON, 3000)
        _log_debug(f"Deleted {count} files (including index).")
    except Exception as e:
        _log_error(f"Delete error: {e}")

# ════════════════════════════════════════════════════════════════════
#  MOVIE MATCHING
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
    try: _, files = xbmcvfs.listdir(saved_dir)
    except Exception: return []

    srt_files = [f for f in files if f.lower().endswith('.srt')]
    if not srt_files: return []

    matches = []
    matched_filenames = set()
    index_path = os.path.join(saved_dir, 'index.json')
    index = {}

    if xbmcvfs.exists(index_path):
        try:
            fh = xbmcvfs.File(index_path)
            raw = fh.read()
            fh.close()
            if raw:
                if isinstance(raw, bytes): raw = raw.decode('utf-8', errors='replace')
                index = json.loads(raw)
        except Exception as e:
            _log_error(f"Index read error: {e}")

    if index:
        _log_debug(f"Index: {len(index)} entries.")
        for filename, info in index.items():
            if not info.get('complete', False):
                incomplete_path = os.path.join(saved_dir, filename)
                if xbmcvfs.exists(incomplete_path): xbmcvfs.delete(incomplete_path)
                continue

            full_path = os.path.join(saved_dir, filename)
            if not xbmcvfs.exists(full_path): continue

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
                if season and episode and str(season) != '0':
                    info_s = str(info.get('season', ''))
                    info_e = str(info.get('episode', ''))
                    if info_s and info_e:
                        if str(season) != info_s or str(episode) != info_e: is_match = False

            if is_match:
                matches.append((full_path, filename))
                matched_filenames.add(filename)

    current_key = _normalize(video_title) if video_title else ""

    for f in srt_files:
        if f in matched_filenames: continue
        saved_key = _normalize(_extract_title_key(f)) if current_key else ""
        is_match = False

        if imdb_id and imdb_id.lower() in f.lower(): is_match = True
        elif current_key and saved_key:
            ck_words = current_key.split()[:3]
            sk_words = saved_key.split()[:3]
            if len(ck_words) >= 1 and ck_words == sk_words: is_match = True
            elif len(current_key) >= 3 and (current_key in saved_key or saved_key in current_key): is_match = True

        if is_match and season and episode and str(season) != '0':
            ep_pattern1 = f"s{int(season):02d}e{int(episode):02d}"
            ep_pattern2 = f"{int(season)}x{int(episode):02d}"
            if ep_pattern1 not in f.lower() and ep_pattern2 not in f.lower(): is_match = False

        if is_match:
            matches.append((os.path.join(saved_dir, f), f))
            matched_filenames.add(f)

    _log_debug(f"{len(matches)} local matches.")
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
        RACE_TIMEOUT = 15.0
    else: 
        RACE_TIMEOUT = 25.0

    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}

    junk_ids = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')

    # ── MANUAL SEARCH MODE (user types in Kodi's built-in search field) ──
    if p.get('searchstring'):
        dialog = xbmcgui.Dialog()
        search_query = p.get('searchstring').strip()
        if not search_query:
            xbmcplugin.endOfDirectory(HANDLE)
            return

        media_idx = dialog.select(f'Search "{search_query}" as:', ['Movie', 'TV Series'])
        if media_idx < 0:
            xbmcplugin.endOfDirectory(HANDLE)
            return
        is_tv = (media_idx == 1)

        s = None
        e = None
        if is_tv:
            s_inp = dialog.input('Season (default 1):', type=xbmcgui.INPUT_ALPHANUM)
            s = s_inp.strip() if (s_inp and s_inp.strip().isdigit()) else '1'
            e_inp = dialog.input('Episode (default 1):', type=xbmcgui.INPUT_ALPHANUM)
            e = e_inp.strip() if (e_inp and e_inp.strip().isdigit()) else '1'

        video_title = search_query
        kodi_year = None
        imdb_id = None
        tmdb_id = None

        tmdb_type = "tv" if is_tv else "movie"
        try:
            r = requests.get(f"{BASE_URL_TMDB}/search/{tmdb_type}", params={"api_key": TMDB_API_KEY, "query": search_query}, timeout=RACE_TIMEOUT)
            tmdb_results = r.json().get('results', [])
        except:
            tmdb_results = []

        if tmdb_results:
            choices = []
            for res in tmdb_results:
                name = res.get('title') or res.get('name', 'Unknown')
                year = (res.get('release_date') or res.get('first_air_date') or '')[:4]
                lang = res.get('original_language', '').upper()
                choices.append(f"{name} ({year}) [{lang}]")
            sel = dialog.select('Select the correct match:', choices)
            if sel >= 0:
                best = tmdb_results[sel]
                tmdb_id = best['id']
                video_title = best.get('title') or best.get('name', search_query)
                try:
                    ext_r = requests.get(f"{BASE_URL_TMDB}/{tmdb_type}/{tmdb_id}/external_ids", params={"api_key": TMDB_API_KEY}, timeout=RACE_TIMEOUT).json()
                    imdb_id = ext_r.get('imdb_id')
                except:
                    pass

        v_id = imdb_id or str(tmdb_id) if tmdb_id else None
        if not v_id:
            dialog.ok('No results', 'Could not find an ID for subtitle search.')
            xbmcplugin.endOfDirectory(HANDLE)
            return

    else:
        # ── Auto-detection from player ──
        tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
        imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")

        home_window = xbmcgui.Window(10000)
        if not imdb_id or str(imdb_id) in junk_ids:
            imdb_id = home_window.getProperty("IMDb") or home_window.getProperty("imdb_id")
        if not tmdb_id or str(tmdb_id) in junk_ids:
            tmdb_id = home_window.getProperty("TMDb") or home_window.getProperty("tmdb_id")

        s = xbmc.getInfoLabel("VideoPlayer.Season")
        e = xbmc.getInfoLabel("VideoPlayer.Episode")
        video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")

        kodi_year = xbmc.getInfoLabel("VideoPlayer.Year") or \
                    xbmc.getInfoLabel("ListItem.Year") or \
                    xbmc.getInfoLabel("ListItem.Premiered")

        if not kodi_year or len(str(kodi_year)) < 4: kodi_year = home_window.getProperty("ListItem.Year")
        if kodi_year and len(str(kodi_year)) >= 4: kodi_year = str(kodi_year)[:4]
        else: kodi_year = None

        try:
            file_path = unquote(xbmc.Player().getPlayingFile())
            _log_debug(f"Checking file link for clues: {file_path}")

            if not imdb_id or str(imdb_id) in junk_ids:
                match_imdb = re.search(r'(?:media_id|imdb|imdb_id|title)=([^&]+)', file_path, re.IGNORECASE)
                if match_imdb and match_imdb.group(1).startswith('tt'):
                    imdb_id = match_imdb.group(1)
                    _log_debug(f"IMDb ID extracted instantly directly from video link: {imdb_id}")

            if not kodi_year:
                match_y = re.search(r'[\(\.\s](\d{4})[\)\.\s]', file_path)
                if match_y:
                    kodi_year = match_y.group(1)
                    _log_debug(f"The year {kodi_year} was extracted from the filename.")

            if "au" in file_path.lower() and "au" not in video_title.lower():
                if re.search(r'[\.\s_]au[\.\s_]', file_path, re.IGNORECASE):
                    video_title += " AU"
                    _log_debug("Automatically added 'AU' suffix from the filename.")
        except Exception as ex:
            _log_debug(f"Filename processing error: {ex}")

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

    if source_opt == 0 and not wyzie_api_key:
        xbmcgui.Dialog().notification(ADDON_NAME, 'Missing Wyzie key! Add it in settings.', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    all_results = []
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

    sdh_pattern = re.compile(r'(?:^|[^a-z0-9])(sdh|cc|hi|hearing[\s_]*impaired)(?:[^a-z0-9]|$)', re.IGNORECASE)

    def fetch_wyzie(search_params):
        results = []
        try:
            search_params['source'] = 'all'
            if 'language' in search_params: del search_params['language']
            
            _log_debug(f"[WYZIE] Single API call: {base_url}?{urlencode(search_params)}")
            r = requests.get(base_url, params=search_params, headers=HEADERS, timeout=RACE_TIMEOUT)
            
            if not r.ok: 
                _log_debug(f"[WYZIE] API returned error code: {r.status_code}")
                return results
            
            for sub in r.json():
                t_code = sub.get('language', 'en')
                t_code_norm = NORM.get(t_code.lower(), t_code.lower())
                
                url = sub.get('url', '')
                if not url: continue
                
                raw_fname = sub.get('release') or sub.get('fileName') or 'sub.srt'
                clean_release = re.split(r'<br\s*/?>|\n', raw_fname, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                if not clean_release.lower().endswith('.srt'): clean_release += '.srt'
                
                source_dynamic = sub.get('source', 'api').upper()
                fname_display = f"{clean_release} [B][COLOR FFB048B5][WZ][/COLOR][/B] [B][COLOR FF00BFFF][{source_dynamic}][/COLOR][/B]"
                
                check_str = f"{raw_fname} {url} {sub.get('id','')}".lower()
                is_sdh = sub.get('isHearingImpaired', False) or sub.get('hearing_impaired', False) or bool(sdh_pattern.search(check_str))

                try: dl_count = int(sub.get('downloadCount') or 0)
                except: dl_count = 0
                    
                w_rating = 0.0
                if dl_count >= 50000: w_rating = 10.0
                elif dl_count >= 10000: w_rating = 8.0
                elif dl_count >= 2000: w_rating = 6.0
                elif dl_count >= 500: w_rating = 4.0
                elif dl_count >= 50: w_rating = 2.0
                
                results.append({
                    'language_name': _get_lang_name(t_code_norm),
                    'filename': fname_display,
                    'url': url,
                    'l_code': t_code,
                    'l_code_norm': t_code_norm,
                    'api_filename': clean_release,
                    'is_local': False,
                    'is_sdh': is_sdh,
                    'rating': w_rating
                })
        except Exception as e:
            _log_debug(f"[WYZIE] NETWORK OR JSON PARSE ERROR: {e}")
        return results

    def wyzie_worker():
        bp = {'key': wyzie_api_key}
        if v_id: bp['id'] = v_id
        elif video_title: bp['title'] = video_title
        if s and s != "0": bp['season'] = s; bp['episode'] = e

        raw_list = fetch_wyzie(bp)
        target_norm = NORM.get(l_code, l_code)
        
        final_results = []
        for r in raw_list:
            r_lang = r['l_code_norm']
            is_target = (r_lang == target_norm)
            is_fallback = (r_lang == 'en' and l_code != 'en')

            if show_all or is_target or is_fallback:
                r['is_chosen'] = is_target
                final_results.append(r)
                
        _log_debug(f"[WYZIE] Filtered {len(final_results)} local results out of {len(raw_list)} total.")
        return final_results

    def os_worker():
        nonlocal s, e, video_title, imdb_id, l_code, show_all
        results = []
        try:
            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)
            if not current_imdb_id: return results

            imdb_clean = current_imdb_id.replace('tt', '')
            if s and e and str(s) != '0':
                query_path = f"episode-{e}/imdbid-{imdb_clean}/season-{s}"
            else:
                query_path = f"imdbid-{imdb_clean}"

            seen_urls = set()
            os_headers = {'User-Agent': 'HotSubtitlesV1'}

            # --- A SINGLE DIRECT GLOBAL QUERY ---
            os_url = f"https://rest.opensubtitles.org/search/{query_path}"
            _log_debug(f"[OS REST] Single global API query: {os_url}")
            
            try:
                r = requests.get(os_url, headers=os_headers, timeout=RACE_TIMEOUT)
                if r.ok:
                    data = r.json()
                    if isinstance(data, list):
                        for item in data:
                            file_id = item.get('IDSubtitleFile')
                            if not file_id: continue
                            
                            url = f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{file_id}"
                            if url in seen_urls: continue
                            seen_urls.add(url)

                            sub_lang_raw = item.get('ISO639', 'en')
                            sub_l_code = NORM.get(sub_lang_raw, sub_lang_raw)
                            
                            is_target = (sub_l_code == NORM.get(l_code, l_code))
                            is_fallback = (sub_l_code == 'en' and l_code != 'en')

                            # Instant filtering according to XML setting (Only target/EN or All)
                            if not (show_all or is_target or is_fallback): 
                                continue

                            raw_fname = item.get('SubFileName', 'subtitle.srt')
                            hi_flag = str(item.get('SubHearingImpaired', '0')) == '1'
                            rating = str(item.get('SubRating', '0.0'))
                            
                            nick = item.get('UserNickName') or ""
                            trans = item.get('SubTranslator') or ""
                            rank = item.get('UserRank') or ""
                            dl_count = item.get('SubDownloadsCnt', '0')

                            author_parts = []
                            if nick: author_parts.append(nick)
                            if trans: author_parts.append(trans)
                            uploader = " / ".join(author_parts) if author_parts else ""

                            fname_display = f"{raw_fname} [B][COLOR FFB048B5][OS][/COLOR][/B]"
                            is_sdh = hi_flag or bool(sdh_pattern.search(f"{raw_fname} {url} {file_id}".lower()))

                            if uploader:
                                rank_low = rank.lower()
                                r_color = "orange" if "trusted" in rank_low or "platinum" in rank_low else "lime" if "admin" in rank_low or "gold" in rank_low or "vip" in rank_low else "orange"
                                rank_str = f" [COLOR {r_color}]({rank})[/COLOR]" if rank else ""
                                fname_display += f" [COLOR gray] - by [B][COLOR FF00BFFF]{uploader}[/COLOR]{rank_str}[/B][/COLOR]"

                            if dl_count and dl_count != '0':
                                fname_display += f" [COLOR yellow]({dl_count} dls)[/COLOR]"

                            results.append({
                                'language_name': _get_lang_name(sub_l_code),
                                'filename': fname_display,
                                'url': url,
                                'l_code': sub_l_code,
                                'api_filename': raw_fname,
                                'is_chosen': is_target,
                                'is_local': False,
                                'is_sdh': is_sdh,
                                'rating': rating,
                                'dl_count': dl_count
                            })
            except Exception as ex:
                _log_debug(f"[OS REST] Single query parse error: {ex}")
            
            _log_debug(f"[OS REST] Finished with {len(results)} processed results (after filtering {'All languages' if show_all else 'only Target/EN'}).")
        except Exception as e:
            _log_error(f"[OS REST] General worker error: {e}")
            
        return results

    def stremio_worker():
        nonlocal s, e, video_title, imdb_id
        results = []
        try:
            manifest_url = __addon__.getSetting('custom_stremio_manifest').strip()
            if not manifest_url:
                _log_debug("[STREMIO] No manifest URL configured, skipping.")
                return results

            current_imdb_id = imdb_id
            if s and s != '0' and not current_imdb_id and video_title:
                current_imdb_id = get_imdb_id_from_title(video_title, is_tv=True)
            if not current_imdb_id: return results

            v_type = "series" if (s and str(s) != "0") else "movie"
            v_id_sh = f"{current_imdb_id}:{s}:{e}" if v_type == "series" else current_imdb_id
            params = f"subtitles/{v_type}/{v_id_sh}"

            url = manifest_url.replace('manifest', params)
            _log_debug(f"[STREMIO] API call: {url}")

            try:
                r = requests.get(url, headers=HEADERS, timeout=RACE_TIMEOUT)
                if not r.ok:
                    _log_debug(f"[STREMIO] API returned {r.status_code}")
                    return results
                subs = r.json().get('subtitles', [])
            except Exception as req_e:
                _log_debug(f"[STREMIO] Network/JSON error: {req_e}")
                return results

            try: v_path = xbmc.Player().getPlayingFile().lower()
            except: v_path = ""

            seen = set()
            for sub in subs or []:
                sub_url = sub.get('url', '')
                if not sub_url or sub_url in seen: continue
                seen.add(sub_url)

                s_lang = sub.get('lang_code', sub.get('lang', 'eng')).lower()
                if '-' in s_lang: s_lang = s_lang.split('-')[0]
                short_lang = NORM.get(s_lang, s_lang[:2])

                is_target = (short_lang == NORM.get(l_code, l_code))
                is_fallback = (short_lang == 'en' and l_code != 'en')
                if not (show_all or is_target or is_fallback): continue

                raw_release = sub.get('title') or sub.get('release') or sub.get('description') or 'Subtitle'
                clean_release = re.split(r'<br\s*/?>|\n', raw_release, flags=re.IGNORECASE)[0]
                clean_release = re.sub(r'[\\/*?:"<>|]', '', clean_release).strip()
                if not clean_release.lower().endswith('.srt'): clean_release += '.srt'

                sh_rating = 4.0
                rel_low = clean_release.lower()
                sync_tags = ['web-dl', 'webrip', 'bluray', 'brrip', 'x264', 'x265', 'hevc', '1080p', '720p', '2160p', 'hdtv']

                matches = sum(1 for tag in sync_tags if tag in rel_low and tag in v_path)
                if matches >= 3: sh_rating = 10.0
                elif matches >= 1: sh_rating = 8.0

                is_sdh = sub.get('hearing_impaired', False) or bool(sdh_pattern.search(f"{raw_release} {sub_url}".lower()))

                results.append({
                    'language_name': _get_lang_name(short_lang),
                    'filename': f"{clean_release} [B][COLOR FFB048B5][ST][/COLOR][/B]",
                    'url': sub_url,
                    'l_code': short_lang,
                    'api_filename': clean_release,
                    'is_chosen': is_target,
                    'is_local': False,
                    'is_sdh': is_sdh,
                    'rating': sh_rating
                })

            _log_debug(f"[STREMIO] Finished with {len(results)} processed results.")
        except Exception as e:
            _log_error(f"[STREMIO] General worker error: {e}")
        return results

    online_results = []
    if source_opt == 0: online_results = wyzie_worker()
    elif source_opt == 1: online_results = os_worker()
    elif source_opt == 2: online_results = stremio_worker()
    else:
        # ── RACING MODE ("FIRST TO FIND WINS") ──
        fast_results = []
        fast_lock = threading.Lock()
        fast_event = threading.Event()
        finished_count = [0]
        
        def run_worker_thread(worker_func, name):
            try:
                res = worker_func()
                with fast_lock:
                    _log_debug(f"[RACING] {name} finished the race and brought {len(res) if res else 0} results.")
                    finished_count[0] += 1
                    
                    if res and not fast_event.is_set():
                        fast_results.extend(res)
                        _log_debug(f"[RACING] WINNER! {name} won the race! Stopping timer!")
                        fast_event.set()
                        
                    elif finished_count[0] == 3 and not fast_event.is_set():
                        _log_debug("[RACING] Everyone finished and all have 0 results...")
                        fast_event.set()
                        
            except Exception as e:
                _log_debug(f"[RACING] Critical error in thread {name}: {e}")
                with fast_lock:
                    finished_count[0] += 1
                    if finished_count[0] == 3 and not fast_event.is_set():
                        fast_event.set()

        t1 = threading.Thread(target=run_worker_thread, args=(wyzie_worker, "WYZIE"), daemon=True)
        t2 = threading.Thread(target=run_worker_thread, args=(os_worker, "OS"), daemon=True)
        t3 = threading.Thread(target=run_worker_thread, args=(stremio_worker, "STREMIO"), daemon=True)
        
        t1.start(); t2.start(); t3.start()
        fast_event.wait(timeout=15)
        
        with fast_lock:
            _log_debug(f"[RACING] Race finish. Fetched a total of {len(fast_results)} online results.")
            RACE_STATE["finished"] = True
            online_results = fast_results

    all_results.extend(online_results)

    if filter_sdh:
        normal_subs = [r for r in all_results if not r.get('is_sdh', False)]
        if normal_subs:
            all_results = normal_subs

    try: video_path = xbmc.Player().getPlayingFile().lower()
    except: video_path = ""

    all_results.sort(key=lambda x: (not x.get('is_local', False), not x['is_chosen'], x['language_name']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])
        
        try:
            val = float(res.get('rating', 0.0) or 0.0)
            if val <= 0.0: stars = "0"
            elif val <= 2.0: stars = "1"
            elif val <= 4.0: stars = "2"
            elif val <= 6.0: stars = "3"
            elif val <= 8.5: stars = "4"
            else: stars = "5"
        except:
            stars = "0"
            
        flag_code = l_code[:2] if res.get('is_local', False) else (res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code'])
        li.setArt({'thumb': flag_code, 'icon': stars})
        
        li.setProperty('rating', stars)
        li.setProperty('hearing_imp', "true" if res.get('is_sdh', False) else "false")
        
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

        try: chosen_lang = LANGS[__addon__.getSettingInt('subs_languages')]
        except Exception: chosen_lang = "ro"

        normalized_lcode = NORM.get(l_code, l_code)
        needs_translation = False if is_local else (normalized_lcode != chosen_lang)

        robot_on = False
        robot_idx = 0
        if robot is not None:
            try: 
                robot_on = __addon__.getSettingBool('robot_activat')
                robot_idx = __addon__.getSettingInt('robot_selectat')
            except Exception: pass

        if needs_translation and robot_on:
            # Index 0 = Gemini Fast, Index 1 = Gemini Slow 3.0, Index 2 = Gemini Slow 3.5
            if robot_idx in [0, 1, 2]: 
                keys = [__addon__.getSetting(f'api_key_{i}').strip() for i in range(1, 6)]
                if not any(keys):
                    xbmcgui.Dialog().notification(ADDON_NAME, 'Missing Gemini keys! Add them in settings.', xbmcgui.NOTIFICATION_ERROR, 5000)
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                    return
                
                # --- SPECIAL LOG ADDED AT YOUR REQUEST FOR GEMINI THINKING ---
                try:
                    t_idx = __addon__.getSettingInt('gemini_thinking_level')
                    t_map = {0: "Minimal", 1: "Low", 2: "Medium", 3: "High"}
                    
                    b_idx = __addon__.getSettingInt('gemini_slow_batch')
                    b_map = {0: "300", 1: "400", 2: "500"}
                    
                    _log_debug(f"[TRANSLATION INFO] Translation with Gemini Robot starting (Index: {robot_idx}).")
                    if robot_idx in [1, 2]: # Only Gemini Slow uses this logic from settings
                        _log_debug(f"[TRANSLATION INFO] Thinking Level: {t_map.get(t_idx, 'Unknown')} | Batches: {b_map.get(b_idx, 'Unknown')} lines")
                except Exception as ex_log:
                    _log_debug(f"[TRANSLATION INFO] Error displaying Gemini settings log: {ex_log}")
                # ------------------------------------------------------------------

            # Index 3 = Lingva (No API) -> Passes without verification
            # Index 4 = Google Translate
            elif robot_idx == 4: 
                keys = [__addon__.getSetting(f'api_key_r1_{i}').strip() for i in range(1, 6)]
                if not any(keys):
                    xbmcgui.Dialog().notification(ADDON_NAME, 'Missing Google keys! Add them in settings.', xbmcgui.NOTIFICATION_ERROR, 5000)
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                    return

        api_filename = params.get('api_filename') or 'subtitle'
        if api_filename.lower().endswith('.srt'):
            api_filename = api_filename[:-4]
        
        api_filename = re.sub(r'\.[a-z]{2,3}$', '', api_filename, flags=re.IGNORECASE)
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

        base_temp = xbmcvfs.translatePath('special://temp/substudio_subs/')
        if not xbmcvfs.exists(base_temp):
            xbmcvfs.mkdirs(base_temp)

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

        if is_local:
            xbmcvfs.copy(url, dest_path)
        else:
            r = requests.get(url, timeout=20, headers=HEADERS)
            if not r.ok or b'<html' in r.content.lower():
                _log_error("Invalid or HTML downloaded file")
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
        unique_temp_folder = os.path.join(base_temp, f"sub_{timestamp}")
        xbmcvfs.mkdirs(unique_temp_folder)
        temp_path = os.path.join(unique_temp_folder, safe_name)
        
        try: xbmcvfs.copy(dest_path, temp_path)
        except Exception: temp_path = dest_path

        li = xbmcgui.ListItem(label=safe_name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=temp_path, listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True)

        def force_activate(path):
            xbmc.sleep(800)
            try: xbmc.Player().setSubtitles(path)
            except Exception: pass

        threading.Thread(target=force_activate, args=(temp_path,), daemon=True).start()

        if is_local:
            xbmcgui.Dialog().notification(ADDON_NAME, f'Local subtitle [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] activated!', ADDON_ICON, 3000)
        elif needs_translation:
            if robot_on:
                xbmcgui.Dialog().notification(ADDON_NAME, f'Translation [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] started...', ADDON_ICON, 3000)
                
                # IMPORTANT: Calls to robots strictly in XML order!
                if robot_idx == 0 and robot is not None: # Gemini Fast
                    threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'fast'}, daemon=True).start()
                elif robot_idx in [1, 2] and robot is not None: # Gemini Slow 3.0 and 3.5
                    threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'slow'}, daemon=True).start()
                elif robot_idx == 3 and robot2 is not None: # Lingva
                    threading.Thread(target=robot2.run_translation, args=(__id__,), daemon=True).start()
                elif robot_idx == 4 and robot3 is not None: # Google Translate
                    threading.Thread(target=robot3.run_translation, args=(__id__,), daemon=True).start()
                else:
                    # Safety fallback to Gemini
                    if robot is not None:
                        threading.Thread(target=robot.run_translation, kwargs={'sub_addon_id': __id__, 'mode': 'fast'}, daemon=True).start()
            else:
                xbmcgui.Dialog().notification(ADDON_NAME, f'Subtitle [B][COLOR orange]{normalized_lcode.upper()}[/COLOR][/B] activated. Robot stopped!', ADDON_ICON, 4000)
                _log_debug(f"Language is OK ({l_code}), but robot setting is off, so no translation.")
        else:
            _log_debug(f"Language is already OK ({l_code}), no translation needed.")
            
    except Exception as e:
        _log_error(f"Download processing error: {e}")
        try: xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception: pass

def _cleanup_orphaned_settings():
    import xml.etree.ElementTree as ET
    try:
        current_version = __addon__.getAddonInfo('version')
        last_version = __addon__.getSetting('last_run_version')
        
        # If the version is the same, stop execution (NOT an update)
        if current_version == last_version: 
            return 
            
        # ─── THIS IS WHERE THE UPDATE TASKS HAPPEN (runs only once) ───
        
        # 1. Migrate the old folder
        if utils is not None:
            utils.migrate_saved_folder()
            
        # 2. Clean up orphaned settings (xml)
        addon_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
        addon_settings_path = os.path.join(addon_dir, 'resources', 'settings.xml')
        if not xbmcvfs.exists(addon_settings_path):
            addon_settings_path = os.path.join(addon_dir, 'settings.xml')
            
        user_data_dir = xbmcvfs.translatePath(f"special://profile/addon_data/{__id__}/")
        user_settings_path = os.path.join(user_data_dir, 'settings.xml')
        
        if not xbmcvfs.exists(addon_settings_path) or not xbmcvfs.exists(user_settings_path):
            __addon__.setSetting('last_run_version', current_version)
            return
            
        valid_ids = set()
        tree_base = ET.parse(addon_settings_path)
        for elem in tree_base.iter('setting'):
            if 'id' in elem.attrib: valid_ids.add(elem.attrib['id'])
                
        tree_user = ET.parse(user_settings_path)
        root_user = tree_user.getroot()
        
        changed = False
        for elem in root_user.findall('setting'):
            s_id = elem.attrib.get('id')
            if s_id and s_id not in valid_ids:
                root_user.remove(elem)
                changed = True
                _log_debug(f"Old setting deleted (garbage): {s_id}")
                
        if changed: 
            tree_user.write(user_settings_path, encoding='utf-8', xml_declaration=True)
            _log_debug("Settings.xml in addon_data successfully cleaned of orphaned settings!")
            
        # Save the new version so it doesn't run again until the next update
        __addon__.setSetting('last_run_version', current_version)
        
    except Exception as e:
        _log_debug(f"Non-critical error on update tasks: {e}")


if __name__ == '__main__':
    # Update check (cleanup + migration)
    _cleanup_orphaned_settings()
    
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

    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download': download(p)
    else: search()