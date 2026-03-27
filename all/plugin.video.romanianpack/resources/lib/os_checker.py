# Dummy file to make this directory a package.
# -*- coding: utf-8 -*-
import xbmcgui
import requests
import threading
from resources.functions import convert_tmdb_to_imdb, log

def check_ro_subs_bg(imdb_id=None, tmdb_id=None, season=None, episode=None):
    """
    Rulează în fundal pentru a nu bloca interfața Kodi.
    Interoghează OpenSubtitles și setează o proprietate a ferestrei dacă găsește RO.
    """
    # Curățăm proprietatea veche ca să nu apară din greșeală de la filmul anterior
    xbmcgui.Window(10000).clearProperty('mrsp.has_ro_sub')

    def _worker():
        try:
            # 1. Ne asigurăm că avem IMDB ID (OS Stremio API folosește exclusiv IMDB)
            final_imdb = imdb_id
            if not final_imdb and tmdb_id:
                media_type = 'tv' if season else 'movie'
                final_imdb = convert_tmdb_to_imdb(tmdb_id, media_type)

            if not final_imdb:
                log("[MRSP-OS-CHECKER] Fara IMDB ID. Verificarea anulata.")
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
            log(f"[MRSP-OS-CHECKER] Verific subtitrari RO la: {url}")
            r = requests.get(url, timeout=3.5)
            
            if r.ok:
                data = r.json()
                subs = data.get('subtitles', [])
                
                # 4. Cautam limba Romana ('rum', 'ro', 'ron')
                for sub in subs:
                    lang = str(sub.get('lang', '')).lower()
                    if lang in ['rum', 'ro', 'ron']:
                        log("[MRSP-OS-CHECKER] SUCCES! Subtitrare RO gasita.")
                        # Setam proprietatea care face vizibil butonul in results.xml
                        xbmcgui.Window(10000).setProperty('mrsp.has_ro_sub', 'true')
                        break
            else:
                log(f"[MRSP-OS-CHECKER] Eroare API: Status {r.status_code}")

        except Exception as e:
            log(f"[MRSP-OS-CHECKER] Eroare interna: {str(e)}")

    # Pornim thread-ul (demon = se închide automat dacă ieși din Kodi)
    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()