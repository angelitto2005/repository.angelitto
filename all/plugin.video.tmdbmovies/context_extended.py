import sys
import xbmc
import xbmcgui
import xbmcaddon
import requests
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
        # Am marit timeout-ul la 10 secunde pentru siguranta
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}

def resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, title, year, media_type):
    # 1. Avem deja ID
    if tmdb_id:
        return tmdb_id, media_type

    # 2. IMDb
    if imdb_id:
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data.get('movie_results'): return str(data['movie_results'][0]['id']), 'movie'
        if data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'
        if data.get('tv_episode_results'): return str(data['tv_episode_results'][0]['show_id']), 'tv'

    # 3. TVDb
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'

    # 4. Titlu (Căutare Avansată)
    if title:
        search_type = 'movie' if media_type == 'movie' else 'tv'
        clean_title = title.split('(')[0].strip() # Eliminam anul din titlu daca exista ex: "Movie (2024)"
        
        # Tentativa A: Căutare STRICTĂ (Cu An)
        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_title)}"
        url_with_year = url
        if year and str(year).isdigit():
            if search_type == 'movie': url_with_year += f"&primary_release_year={year}"
            else: url_with_year += f"&first_air_date_year={year}"
            
        log(f"Searching Title: {clean_title} | Year: {year}")
        
        # Încercăm întâi cu an
        if year:
            data = get_json(url_with_year)
            if data.get('results'):
                found = data['results'][0]
                log(f"Found with Year: {found.get('name') or found.get('title')} ({found.get('id')})")
                return str(found['id']), search_type

        # Tentativa B: Căutare RELAXATĂ (Fără An) - Asta rezolvă SEZOANELE
        # Dacă sezonul e din 2017 dar serialul din 2015, căutarea cu an eșuează.
        # Acum încercăm fără an.
        if year: # Doar daca am incercat deja cu an si nu a mers
            log("Search with year failed (likely Season year vs Show year mismatch). Retrying without year...")
            data = get_json(url) # Url-ul simplu fara an
            if data.get('results'):
                found = data['results'][0]
                log(f"Found without Year: {found.get('name') or found.get('title')} ({found.get('id')})")
                return str(found['id']), search_type
            
        # Daca nici asa nu a mers si nu aveam an de la inceput
        if not year:
             data = get_json(url)
             if data.get('results'):
                return str(data['results'][0]['id']), search_type

    return None, None

def main():
    # 1. ID-uri
    tmdb_id = get_valid_id(['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId'])
    imdb_id = get_valid_id(['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)'], 'imdb')
    tvdb_id = get_valid_id(['ListItem.Property(tvdb_id)'], 'digit')

    # 2. Tip
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    # 3. Sezon si Episod
    season = xbmc.getInfoLabel('ListItem.Season') or xbmc.getInfoLabel('ListItem.Property(season)')
    episode = xbmc.getInfoLabel('ListItem.Episode') or xbmc.getInfoLabel('ListItem.Property(episode)')
    
    final_type = 'movie'
    if dbtype in ['tvshow', 'season', 'episode', 'tv'] or mediatype in ['tvshow', 'season', 'episode', 'tv']:
        final_type = 'tv'
    elif season: 
        final_type = 'tv'

    # 4. Titluri
    title = xbmc.getInfoLabel('ListItem.Title') or xbmc.getInfoLabel('ListItem.Label')
    tv_show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Property(tvshowtitle)')
    year = xbmc.getInfoLabel('ListItem.Year') or xbmc.getInfoLabel('ListItem.Property(year)')

    # IMPORTANT: Pentru sezoane/episoade, cautam dupa TVShowTitle daca exista
    search_title = tv_show_title if tv_show_title else title

    # LOGICA SPECIALA PENTRU SEZOANE/EPISOADE
    final_season = None
    final_episode = None

    if dbtype == 'season' or mediatype == 'season':
        final_type = 'tv'
        final_season = season
        final_episode = None # Ignoram episodul pt folder sezon
        # Daca suntem pe sezon, titlul curent e "Season X", deci ne bazam pe TVShowTitle
        if not tv_show_title: 
            # Fallback periculos: Uneori label e "Serial - Season X"
            # Incercam sa curatam daca nu avem tvshowtitle
            pass 

    elif dbtype == 'episode' or mediatype == 'episode':
        final_type = 'tv'
        final_season = season
        final_episode = episode

    elif dbtype == 'tvshow' or mediatype == 'tvshow':
        final_type = 'tv'
        # Resetam season/episode ca sa deschidem pagina principala
        final_season = None
        final_episode = None

    elif dbtype == 'movie' or mediatype == 'movie':
        final_type = 'movie'
        final_season = None
        final_episode = None

    log(f"Detected: SearchTitle='{search_title}', FinalType='{final_type}', S='{final_season}', E='{final_episode}', Year='{year}'")

    # 5. Rezolvare ID
    real_tmdb_id, real_type = resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, search_title, year, final_type)

    if real_tmdb_id:
        try:
            from resources.lib.extended_info_mod import run_extended_info
            
            s_num = int(final_season) if final_season and str(final_season).isdigit() else None
            e_num = int(final_episode) if final_episode and str(final_episode).isdigit() else None
            
            # Siguranta pt filme
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