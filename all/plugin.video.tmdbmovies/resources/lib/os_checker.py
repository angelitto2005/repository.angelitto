# resources/lib/os_checker.py
# -*- coding: utf-8 -*-

import xbmcgui
import requests
import threading
from resources.lib.utils import log

def check_ro_subs_bg(imdb_id=None, tmdb_id=None, season=None, episode=None):
    """
    Rulează în fundal pentru a nu bloca interfața Kodi.
    Interoghează OpenSubtitles V3 și setează o proprietate a ferestrei dacă găsește RO.
    """
    # Curățăm proprietatea veche ca să nu apară din greșeală de la filmul anterior
    xbmcgui.Window(10000).clearProperty('tmdbmovies.has_ro_sub')

    def _worker():
        try:
            # 1. Ne asigurăm că avem IMDB ID (OS Stremio API folosește exclusiv IMDB)
            final_imdb = imdb_id
            if not final_imdb and tmdb_id:
                # Fallback pentru a obține IMDb ID prin API-ul TMDbMovies
                from resources.lib.tmdb_api import get_tmdb_item_details
                media_type = 'tv' if season else 'movie'
                details = get_tmdb_item_details(str(tmdb_id), media_type)
                if details:
                    final_imdb = details.get('external_ids', {}).get('imdb_id', '')

            if not final_imdb:
                log("[OS-CHECKER] Fara IMDB ID. Verificarea anulata.")
                return

            # Normalizare ID (eliminam 'tt' daca exista deja de 2 ori sau il adaugam)
            numeric_id = str(final_imdb).replace('tt', '')
            clean_imdb_id = f"tt{numeric_id}"

            # 2. Construire URL
            if season and episode:
                url = f"https://opensubtitles-v3.strem.io/subtitles/series/{clean_imdb_id}:{int(season)}:{int(episode)}.json"
            else:
                url = f"https://opensubtitles-v3.strem.io/subtitles/movie/{clean_imdb_id}.json"

            # 3. Cerere catre API
            log(f"[OS-CHECKER] Verific subtitrari RO la: {url}")
            r = requests.get(url, timeout=4.0)
            
            if r.status_code == 200:
                data = r.json()
                subs = data.get('subtitles', [])
                
                # 4. Cautam limba Romana ('rum', 'ro', 'ron')
                for sub in subs:
                    lang = str(sub.get('lang', '')).lower()
                    if lang in ['rum', 'ro', 'ron', 'romanian']:
                        log("[OS-CHECKER] SUCCES! Subtitrare RO gasita.")
                        # Setam proprietatea care face vizibil butonul in results.xml
                        xbmcgui.Window(10000).setProperty('tmdbmovies.has_ro_sub', 'true')
                        break
            else:
                log(f"[OS-CHECKER] Eroare API: Status {r.status_code}")

        except Exception as e:
            log(f"[OS-CHECKER] Eroare interna: {str(e)}")

    # Pornim thread-ul (demon = se închide automat dacă ieși din Kodi)
    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()