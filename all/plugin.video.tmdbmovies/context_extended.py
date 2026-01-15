import sys
import xbmc
import xbmcgui
import xbmcaddon
import requests
import re
from urllib.parse import quote_plus

# --- CONFIG ---
try:
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"
except:
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"

def log(msg):
    xbmc.log(f"[Extended Context] {msg}", xbmc.LOGINFO)

def clean_str(text):
    """Curata titlul pentru comparatie (lowercase, fara spatii duble)"""
    if not text: return ""
    # Eliminam caracterele speciale, pastram doar litere si cifre si spatii
    # Convertim la lowercase
    text = str(text).lower().strip()
    return " ".join(text.split())

def get_valid_id(labels, validation_type='digit'):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if not val or val == label: continue
        val = str(val).strip()
        
        if validation_type == 'digit':
            if val.isdigit() and val != '0': return val
        elif validation_type == 'imdb':
            if val.startswith('tt'): return val
    return ''

def get_json(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}

def resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, title, year, media_type):
    # 1. Avem deja ID TMDB
    if tmdb_id:
        return tmdb_id, media_type

    # 2. IMDb
    if imdb_id:
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if data.get('movie_results'): return str(data['movie_results'][0]['id']), 'movie'
            if data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'
            if data.get('tv_episode_results'): return str(data['tv_episode_results'][0]['show_id']), 'tv'

    # 3. TVDb
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data and data.get('tv_results'): 
            return str(data['tv_results'][0]['id']), 'tv'

    # 4. Titlu (LOGICA COMPLEXA DE FILTRARE)
    if title:
        search_type = 'movie' if media_type == 'movie' else 'tv'
        # Curatam titlul cautat (fara an, fara paranteze)
        clean_search_title = title.split('(')[0].strip()
        search_query = clean_str(clean_search_title)
        
        log(f"Searching: '{clean_search_title}' (Normalized: '{search_query}') | Year: {year}")

        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        if year and str(year).isdigit():
            if search_type == 'movie': url += f"&primary_release_year={year}"
            else: url += f"&first_air_date_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        # Daca nu gasim cu an, incercam fara an (fallback)
        if not results and year:
            log("No results with Strict Year. Retrying without year...")
            url_no_year = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
            data = get_json(url_no_year)
            results = data.get('results', [])

        if not results:
            return None, None

        # --- LISTA CANDIDATI ---
        candidates = []
        
        for item in results:
            # 1. Verificare An (Relaxata +/- 1 an)
            item_year_str = (item.get('release_date') or item.get('first_air_date') or '')[:4]
            if year and str(year).isdigit() and item_year_str.isdigit():
                if abs(int(item_year_str) - int(year)) > 1:
                    continue # Sarim peste daca anul e prea diferit

            # 2. Verificare TITLU (STRICTA)
            # Comparam titlul cautat cu Titlul TMDB si Titlul Original TMDB
            item_title = clean_str(item.get('title') or item.get('name', ''))
            item_orig_title = clean_str(item.get('original_title') or item.get('original_name', ''))
            
            # Verificam egalitate exacta (ignora case si spatii)
            match = False
            if search_query == item_title: match = True
            elif search_query == item_orig_title: match = True
            
            # Fallback: Daca titlul cautat e continut complet in titlul gasit (ex: "Jai Ho" in "Jai Ho!")
            if not match:
                if search_query in item_title and len(item_title) < len(search_query) + 5: match = True
                elif search_query in item_orig_title and len(item_orig_title) < len(search_query) + 5: match = True
            
            if match:
                candidates.append(item)
            else:
                log(f"Ignored result due to title mismatch: '{item_title}' vs '{search_query}'")

        # --- SELECTIE FINALA ---
        if candidates:
            # Sortam candidatii care au trecut testul de nume dupa Popularitate (Voturi)
            candidates.sort(key=lambda x: x.get('vote_count', 0), reverse=True)
            
            winner = candidates[0]
            log(f"Winner (Matched Title & Most Popular): {winner.get('title') or winner.get('name')} (ID: {winner.get('id')})")
            return str(winner['id']), search_type
        
        else:
            log("No results matched the Title criteria exactly.")
            # Fallback extrem: daca nu avem niciun match pe titlu, dar avem rezultate, 
            # luam primul rezultat DOAR daca userul nu a dat an (riscant, dar mai bine decat nimic)
            # Dar aici, fiind Jai Ho, vrem strictete.

    return None, None

def main():
    tmdb_labels = ['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId', 'ListItem.Property(uniqueid_tmdb)']
    tmdb_id = get_valid_id(tmdb_labels, 'digit')

    imdb_labels = ['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 'ListItem.Property(uniqueid_imdb)']
    imdb_id = get_valid_id(imdb_labels, 'imdb')

    tvdb_labels = ['ListItem.Property(tvdb_id)', 'ListItem.Property(uniqueid_tvdb)']
    tvdb_id = get_valid_id(tvdb_labels, 'digit')

    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    season = xbmc.getInfoLabel('ListItem.Season') or xbmc.getInfoLabel('ListItem.Property(season)')
    episode = xbmc.getInfoLabel('ListItem.Episode') or xbmc.getInfoLabel('ListItem.Property(episode)')
    
    final_type = 'movie'
    if dbtype in ['tvshow', 'season', 'episode', 'tv'] or mediatype in ['tvshow', 'season', 'episode', 'tv']:
        final_type = 'tv'
    elif season: final_type = 'tv'

    title = xbmc.getInfoLabel('ListItem.Title') or xbmc.getInfoLabel('ListItem.Label')
    tv_show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Property(tvshowtitle)')
    year = xbmc.getInfoLabel('ListItem.Year') or xbmc.getInfoLabel('ListItem.Property(year)')

    search_title = tv_show_title if tv_show_title else title
    
    final_season = None
    final_episode = None

    if dbtype == 'season' or mediatype == 'season':
        final_type = 'tv'
        final_season = season
    elif dbtype == 'episode' or mediatype == 'episode':
        final_type = 'tv'
        final_season = season
        final_episode = episode
    elif dbtype == 'tvshow' or mediatype == 'tvshow':
        final_type = 'tv'
    elif dbtype == 'movie' or mediatype == 'movie':
        final_type = 'movie'

    log(f"Detected: SearchTitle='{search_title}', FinalType='{final_type}', IDs(T:{tmdb_id}/I:{imdb_id}), Year='{year}'")

    real_tmdb_id, real_type = resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, search_title, year, final_type)

    if real_tmdb_id:
        try:
            from resources.lib.extended_info_mod import run_extended_info
            
            s_num = int(final_season) if final_season and str(final_season).isdigit() else None
            e_num = int(final_episode) if final_episode and str(final_episode).isdigit() else None
            
            if real_type == 'movie':
                s_num = None
                e_num = None

            log(f"Launching: ID={real_tmdb_id}, Type={real_type}, S={s_num}, E={e_num}")
            run_extended_info(real_tmdb_id, real_type, season=s_num, episode=e_num, tv_name=search_title)
            
        except Exception as e:
            import traceback
            log(f"CRASH: {traceback.format_exc()}")
            xbmcgui.Dialog().notification("Extended Info", f"Eroare: {e}", xbmcgui.NOTIFICATION_ERROR)
    else:
        xbmcgui.Dialog().notification("Extended Info", "Nu am găsit ID-ul", xbmcgui.NOTIFICATION_WARNING)

if __name__ == '__main__':
    main()