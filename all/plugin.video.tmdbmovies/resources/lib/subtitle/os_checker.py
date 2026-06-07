# resources/lib/subtitle/os_checker.py
# -*- coding: utf-8 -*-

import xbmcgui
import requests
import threading
from resources.lib.utils import log
from resources.lib.config import get_plot_language_code

OS_REST_HEADERS = {'User-Agent': 'HotSubtitlesV1'}

NORM_LANG = {
    'rum': 'ro', 'ron': 'ro', 'ro': 'ro',
    'eng': 'en', 'en': 'en',
    'spa': 'es', 'es': 'es', 'spa_la': 'es',
    'fre': 'fr', 'fra': 'fr', 'fr': 'fr',
    'ger': 'de', 'de': 'de',
    'ita': 'it', 'it': 'it',
    'hun': 'hu', 'hu': 'hu',
    'por': 'pt', 'pt': 'pt',
    'rus': 'ru', 'ru': 'ru',
    'tur': 'tr', 'tr': 'tr',
    'bul': 'bg', 'bg': 'bg',
    'ell': 'el', 'gre': 'el', 'el': 'el',
    'pol': 'pl', 'pl': 'pl',
    'cze': 'cs', 'cs': 'cs',
    'dut': 'nl', 'nl': 'nl',
    'ara': 'ar', 'ar': 'ar',
    'chi': 'zh', 'zh': 'zh',
    'jpn': 'ja', 'ja': 'ja',
    'kor': 'ko', 'ko': 'ko',
    'swe': 'sv', 'sv': 'sv',
    'dan': 'da', 'da': 'da',
    'fin': 'fi', 'fi': 'fi',
    'nor': 'no', 'no': 'no',
    'hrv': 'hr', 'hr': 'hr',
    'srp': 'sr', 'sr': 'sr',
    'slv': 'sl', 'sl': 'sl',
    'slo': 'sk', 'sk': 'sk',
    'ukr': 'uk', 'uk': 'uk',
    'heb': 'he', 'he': 'he',
    'tha': 'th', 'th': 'th',
    'vie': 'vi', 'vi': 'vi',
    'ind': 'id', 'id': 'id',
    'may': 'ms', 'ms': 'ms',
    'all': 'en',
    'hin': 'hi', 'hi': 'hi',
    'per': 'fa', 'fa': 'fa',
    'cat': 'ca', 'ca': 'ca',
    'baq': 'eu', 'eu': 'eu',
    'glg': 'gl', 'gl': 'gl',
    'est': 'et', 'et': 'et',
    'lav': 'lv', 'lv': 'lv',
    'lit': 'lt', 'lt': 'lt',
    'mac': 'mk', 'mk': 'mk',
    'alb': 'sq', 'sq': 'sq',
    'bos': 'bs', 'bs': 'bs',
    'ice': 'is', 'is': 'is'
}

def check_ro_subs_bg(imdb_id=None, tmdb_id=None, season=None, episode=None):
    """
    Runs in background to avoid blocking the Kodi UI.
    Queries OpenSubtitles REST API and sets a window property if target language is found.
    """
    # Clear old properties so they don't show from the previous movie
    xbmcgui.Window(10000).clearProperty('tmdbmovies.has_ro_sub')
    xbmcgui.Window(10000).clearProperty('tmdbmovies.sub_text_label')

    def _worker():
        try:
            # 1. Ne asigurăm că avem IMDB ID
            final_imdb = imdb_id
            if not final_imdb and tmdb_id:
                # Fallback to get IMDb ID via TMDbMovies API
                from resources.lib.tmdb_api import get_tmdb_item_details
                media_type = 'tv' if season else 'movie'
                details = get_tmdb_item_details(str(tmdb_id), media_type)
                if details:
                    final_imdb = details.get('external_ids', {}).get('imdb_id', '')

            if not final_imdb:
                log("[OS-CHECKER] No IMDB ID. Check cancelled.")
                return

            # Normalize ID (remove 'tt' if already duplicated or add it)
            numeric_id = str(final_imdb).replace('tt', '')

            # Get target language from plot_language setting
            from resources.lib.config import get_plot_language_code, ADDON
            check_lang = get_plot_language_code()
            raw_setting = ADDON.getSetting('plot_language').strip().lower()
            if raw_setting == 'enro':
                check_lang = 'ro'

            # 2. Construire URL REST API
            is_tv = season and episode and str(season) != '0' and str(episode) != '0'
            if is_tv:
                query_path = f"episode-{episode}/imdbid-{numeric_id}/season-{season}"
            else:
                query_path = f"imdbid-{numeric_id}"

            url = f"https://rest.opensubtitles.org/search/{query_path}"

            # 3. API request
            log(f"[OS-CHECKER] Checking {check_lang.upper()} subtitles at: {url}")
            r = requests.get(url, headers=OS_REST_HEADERS, timeout=5.0)
            
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    # 4. Look for target language subtitle
                    for item in data:
                        sub_lang_raw = item.get('ISO639', 'en')
                        sub_lang = NORM_LANG.get(sub_lang_raw, sub_lang_raw[:2])
                        
                        if sub_lang == check_lang:
                            log(f"[OS-CHECKER] SUCCESS! {check_lang.upper()} subtitle found.")
                            # Setam proprietatile pentru butonul si textul din results.xml
                            xbmcgui.Window(10000).setProperty('tmdbmovies.has_ro_sub', 'true')
                            xbmcgui.Window(10000).setProperty('tmdbmovies.sub_text_label', f"{check_lang.upper()} subtitles available")
                            break
            else:
                log(f"[OS-CHECKER] API Error: Status {r.status_code}")

        except Exception as e:
            log(f"[OS-CHECKER] Internal error: {str(e)}")

    # Start thread (daemon = closes automatically if you exit Kodi)
    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()
