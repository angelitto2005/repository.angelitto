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
    xbmc.log(f"[tmdbmovies-context] {msg}", xbmc.LOGINFO)

def clean_str(text):
    """Curatare titlu pentru comparatie (lowercase, fara spatii duble)"""
    if not text: return ""
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
    # 1. Avem deja ID
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

    # 4. Titlu (LOGICA INTELIGENTA - POPULARITATE)
    if title:
        search_type = 'movie' if media_type == 'movie' else 'tv'
        clean_search_title = title.split('(')[0].strip()
        search_query = clean_str(clean_search_title)
        
        log(f"Resolving by Title: '{clean_search_title}' | Year: {year}")

        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        if year and str(year).isdigit():
            if search_type == 'movie': url += f"&primary_release_year={year}"
            else: url += f"&first_air_date_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        # Fallback fara an
        if not results and year:
            log("Retrying without year...")
            url_no_year = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
            data = get_json(url_no_year)
            results = data.get('results', [])

        if not results: return None, None

        candidates = []
        for item in results:
            # Check An (+- 1 an)
            item_year_str = (item.get('release_date') or item.get('first_air_date') or '')[:4]
            if year and str(year).isdigit() and item_year_str.isdigit():
                if abs(int(item_year_str) - int(year)) > 1: continue

            # Check Titlu (Strict)
            item_title = clean_str(item.get('title') or item.get('name', ''))
            item_orig_title = clean_str(item.get('original_title') or item.get('original_name', ''))
            
            match = False
            if search_query == item_title: match = True
            elif search_query == item_orig_title: match = True
            
            # Partial match
            if not match:
                if search_query in item_title and len(item_title) < len(search_query) + 5: match = True
                elif search_query in item_orig_title and len(item_orig_title) < len(search_query) + 5: match = True
            
            if match:
                candidates.append(item)

        if candidates:
            # Sortare dupa Voturi (Popularitate)
            candidates.sort(key=lambda x: x.get('vote_count', 0), reverse=True)
            winner = candidates[0]
            log(f"Resolved ID: {winner['id']} ({winner.get('title') or winner.get('name')}) - Votes: {winner.get('vote_count')}")
            return str(winner['id']), search_type

    return None, None

def main():
    # 1. IDs
    tmdb_labels = ['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.Property(id)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId', 'ListItem.Property(uniqueid_tmdb)']
    tmdb_id = get_valid_id(tmdb_labels, 'digit')

    imdb_labels = ['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 'ListItem.Property(imdb)', 'VideoPlayer.IMDBNumber', 'ListItem.Property(uniqueid_imdb)']
    imdb_id = get_valid_id(imdb_labels, 'imdb')

    tvdb_labels = ['ListItem.Property(tvdb_id)', 'ListItem.Property(tvdb)', 'ListItem.Property(uniqueid_tvdb)']
    tvdb_id = get_valid_id(tvdb_labels, 'digit')

    # 2. Tip
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    season = xbmc.getInfoLabel('ListItem.Season') or xbmc.getInfoLabel('ListItem.Property(season)')
    episode = xbmc.getInfoLabel('ListItem.Episode') or xbmc.getInfoLabel('ListItem.Property(episode)')
    
    raw_season = season
    final_type = 'movie'
    final_season = season
    final_episode = episode

    if dbtype == 'season' or mediatype == 'season':
        final_type = 'tv' 
        final_episode = '' 
    elif dbtype == 'episode' or mediatype == 'episode':
        final_type = 'tv'
    elif dbtype == 'tvshow' or mediatype == 'tvshow':
        final_type = 'tv'
        final_season = ''
        final_episode = ''
    elif raw_season and raw_season != '0':
         final_type = 'tv'

    # 3. Titluri
    title = xbmc.getInfoLabel('ListItem.Title') or xbmc.getInfoLabel('ListItem.Label') or xbmc.getInfoLabel('ListItem.OriginalTitle')
    tv_show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Property(tvshowtitle)')
    year = xbmc.getInfoLabel('ListItem.Year') or xbmc.getInfoLabel('ListItem.Property(year)')

    search_title = tv_show_title if tv_show_title else title
    
    log(f"Item detected: '{search_title}' | FinalType: {final_type} | IDs: T:{tmdb_id} I:{imdb_id}")

    # 4. Rezolvare ID
    real_tmdb_id, real_type = resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, search_title, year, final_type)

    if real_tmdb_id:
        path = "plugin://plugin.video.tmdbmovies/"
        api_type = 'movie' if real_type == 'movie' else 'tv'
        
        # --- FIX TRAILERE: Trimitem limbile indiene in parametrii URL ---
        # Speram ca addon-ul stie sa preia acest parametru si sa il trimita la TMDB
        extra_langs = "en,null,hi,ta,te,ml,kn,bn,pa,es,fr,de,it"
        
        params = f"?mode=global_info&type={api_type}&tmdb_id={quote_plus(real_tmdb_id)}"
        params += f"&include_video_language={quote_plus(extra_langs)}"
        params += f"&append_to_response=videos,credits,images,external_ids,release_dates"
        
        if final_season and str(final_season).isdigit(): 
            params += f"&season={quote_plus(final_season)}"
        if final_episode and str(final_episode).isdigit(): 
            params += f"&episode={quote_plus(final_episode)}"

        log(f"Opening TMDB Info with ID: {real_tmdb_id} and Extra Languages")
        xbmc.executebuiltin(f"RunPlugin({path}{params})")

    else:
        xbmcgui.Dialog().notification("TMDb Info", "ID-ul nu a putut fi găsit.", xbmcgui.NOTIFICATION_WARNING)

if __name__ == '__main__':
    main()