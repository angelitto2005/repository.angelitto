import sys
import xbmc
import xbmcgui
import xbmcaddon
import re
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor

# --- CONFIG ---
try:
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"
except:
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"

_executor = ThreadPoolExecutor(max_workers=2)

def log(msg):
    xbmc.log(f"[TMDb Extended INFO] {msg}", xbmc.LOGINFO)

def clean_str(text):
    if not text: return ""
    text = str(text).lower().strip()
    for char in [':', '-', '.', ',', "'", '"', '!', '?', '&']:
        text = text.replace(char, ' ')
    return " ".join(text.split())

def normalize_date(date_str):
    if not date_str: return ""
    date_str = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str): return date_str
    match = re.match(r'^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$', date_str)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str

def get_first_valid(labels):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if val and val != label and val.lower() not in ['', 'none', 'null', '-1']:
            return str(val).strip()
    return ""

def get_int_value(val):
    if not val:
        return None
    try:
        num = int(str(val).strip())
        return num if num >= 0 else None
    except:
        return None

def get_json(url):
    try:
        import requests
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}


def find_tv_show_id(imdb_id, tvdb_id, title, year):
    """Găsește ID-ul TMDb pentru un SERIAL (nu episod)."""
    
    if imdb_id and imdb_id.startswith('tt'):
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if data.get('tv_results'): 
                return str(data['tv_results'][0]['id'])
            if data.get('tv_episode_results'):
                show_id = data['tv_episode_results'][0].get('show_id')
                if show_id:
                    return str(show_id)
    
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data:
            if data.get('tv_results'): 
                return str(data['tv_results'][0]['id'])
            if data.get('tv_episode_results'):
                show_id = data['tv_episode_results'][0].get('show_id')
                if show_id:
                    return str(show_id)
    
    if title:
        clean_title = title.split('(')[0].strip()
        clean_title = re.sub(r'\s*-?\s*[Ss]ezon(ul)?\s*\d+.*$', '', clean_title)
        clean_title = re.sub(r'\s*-?\s*[Ss]eason\s*\d+.*$', '', clean_title)
        clean_title = clean_title.strip()
        
        if clean_title:
            url = f"{BASE_URL}/search/tv?api_key={API_KEY}&query={quote_plus(clean_title)}"
            data = get_json(url)
            results = data.get('results', [])
            if results:
                return str(results[0]['id'])
    
    return None


def resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, title, year, premiered, media_type):
    if tmdb_id and str(tmdb_id).isdigit():
        return tmdb_id, media_type

    if imdb_id and imdb_id.startswith('tt'):
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if data.get('movie_results'): return str(data['movie_results'][0]['id']), 'movie'
            if data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'
            if data.get('tv_episode_results'): return str(data['tv_episode_results'][0]['show_id']), 'tv'
            
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data and data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'

    if title:
        search_type = 'movie' if media_type == 'movie' else 'tv'
        clean_search_title = title.split('(')[0].strip()
        clean_search_title = re.sub(r'\s*-?\s*[Ss]ezon(ul)?\s*\d+.*$', '', clean_search_title)
        clean_search_title = re.sub(r'\s*-?\s*[Ss]eason\s*\d+.*$', '', clean_search_title)
        clean_search_title = clean_search_title.strip()
        
        if not clean_search_title:
            return None, None
        
        norm_premiered = normalize_date(premiered)
        log(f"Searching: '{clean_search_title}' | Year: {year} | Date: {norm_premiered}")

        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        if year and str(year).isdigit() and search_type == 'movie':
            url += f"&primary_release_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        if not results and year:
            url_no_year = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
            data = get_json(url_no_year)
            results = data.get('results', [])

        if not results: 
            return None, None

        for item in results[:5]:
            item_date = item.get('release_date') or item.get('first_air_date') or ''
            if norm_premiered and item_date == norm_premiered:
                log(f"PERFECT DATE MATCH: {item['id']}")
                return str(item['id']), search_type

        return str(results[0]['id']), search_type

    return None, None


def run_extended_info_wrapper(real_tmdb_id, real_type, s_num, e_num, tv_name):
    try:
        from resources.lib.extended_info_mod import run_extended_info
        log(f"Launching Extended Info: ID={real_tmdb_id}, Type={real_type}, S={s_num}, E={e_num}")
        run_extended_info(real_tmdb_id, real_type, season=s_num, episode=e_num, tv_name=tv_name)
    except Exception as e:
        import traceback
        log(f"CRASH: {traceback.format_exc()}")
        xbmcgui.Dialog().notification("Extended Info", f"Eroare: {e}", xbmcgui.NOTIFICATION_ERROR)


def run_threaded_extended_search(tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, final_type, final_season, final_episode):
    try:
        real_tmdb_id, real_type = resolve_tmdb_id(
            tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, final_type
        )

        if real_tmdb_id:
            s_num = final_season
            e_num = final_episode
            
            if real_type == 'movie':
                s_num = None
                e_num = None

            run_extended_info_wrapper(real_tmdb_id, real_type, s_num, e_num, search_title)
        else:
            xbmcgui.Dialog().notification("Extended Info", f"Nu am găsit: {search_title}", xbmcgui.NOTIFICATION_WARNING)
            
    except Exception as e:
        log(f"Thread error: {str(e)}")


def main():
    # --- IDs ---
    tmdb_id = get_first_valid([
        'ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 
        'ListItem.TMDBId', 'VideoPlayer.TMDBId', 
        'ListItem.Property(uniqueid_tmdb)', 'ListItem.UniqueID(tmdb)'
    ])
    imdb_id = get_first_valid([
        'ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 
        'ListItem.Property(uniqueid_imdb)', 'ListItem.UniqueID(imdb)'
    ])
    tvdb_id = get_first_valid([
        'ListItem.Property(tvdb_id)', 'ListItem.Property(uniqueid_tvdb)',
        'ListItem.UniqueID(tvdb)'
    ])

    # --- TIPUL CONTINUTULUI ---
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE').lower().strip()
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)').lower().strip()
    
    # --- DETERMINAM TIPUL FINAL BAZAT PE DBTYPE ---
    final_type = 'movie'
    final_season = None
    final_episode = None
    use_tmdb_id = True
    
    if dbtype == 'movie':
        final_type = 'movie'
        
    elif dbtype == 'tvshow':
        final_type = 'tv'
        
    elif dbtype == 'season':
        final_type = 'tv'
        season_raw = get_first_valid([
            'ListItem.Season', 'ListItem.Property(season)',
            'ListItem.Property(Season)', 'VideoPlayer.Season'
        ])
        s = get_int_value(season_raw)
        if s is not None and s >= 0:
            final_season = s
        
    elif dbtype == 'episode':
        final_type = 'tv'
        use_tmdb_id = False  # NU folosim tmdb_id pentru episoade - poate fi ID de episod!
        
        season_raw = get_first_valid([
            'ListItem.Season', 'ListItem.Property(season)',
            'ListItem.Property(Season)', 'VideoPlayer.Season'
        ])
        episode_raw = get_first_valid([
            'ListItem.Episode', 'ListItem.Property(episode)',
            'ListItem.Property(Episode)', 'VideoPlayer.Episode'
        ])
        s = get_int_value(season_raw)
        e = get_int_value(episode_raw)
        
        if s is not None and s >= 0:
            final_season = s
        if e is not None and e > 0 and e <= 50:
            final_episode = e
        else:
            log(f"Episode {e} seems invalid/cumulative, ignoring")
            
    else:
        if mediatype in ['tvshow', 'season', 'episode', 'tv']:
            final_type = 'tv'
        elif tvdb_id:
            final_type = 'tv'
        
        if mediatype == 'season':
            season_raw = get_first_valid(['ListItem.Season', 'ListItem.Property(season)'])
            s = get_int_value(season_raw)
            if s is not None and s >= 0:
                final_season = s
                
        elif mediatype == 'episode':
            use_tmdb_id = False
            season_raw = get_first_valid(['ListItem.Season', 'ListItem.Property(season)'])
            episode_raw = get_first_valid(['ListItem.Episode', 'ListItem.Property(episode)'])
            s = get_int_value(season_raw)
            e = get_int_value(episode_raw)
            if s is not None and s >= 0:
                final_season = s
            if e is not None and e > 0 and e <= 50:
                final_episode = e

    # --- TITLURI ---
    title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    tv_show_title = get_first_valid([
        'ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)',
        'ListItem.Property(TVShowTitle)', 'ListItem.Property(showtitle)',
        'VideoPlayer.TVShowTitle'
    ])
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    premiered = get_first_valid(['ListItem.Premiered', 'ListItem.Date', 'ListItem.Property(premiered)'])

    search_title = tv_show_title if (final_type == 'tv' and tv_show_title) else title
    
    if not search_title:
        xbmcgui.Dialog().notification("Extended Info", "Nu am găsit titlul", xbmcgui.NOTIFICATION_WARNING)
        return

    log(f"Detected: Title='{search_title}', DBTYPE='{dbtype}', Type='{final_type}', S={final_season}, E={final_episode}, UseTMDbID={use_tmdb_id}")

    # --- SPECIAL HANDLING PENTRU EPISOADE ---
    if dbtype == 'episode' or (mediatype == 'episode' and not use_tmdb_id):
        show_tmdb_id = find_tv_show_id(imdb_id, tvdb_id, tv_show_title or search_title, year)
        
        if show_tmdb_id:
            log(f"Found TV Show ID: {show_tmdb_id} for episode")
            try:
                from resources.lib.extended_info_mod import run_extended_info
                run_extended_info(show_tmdb_id, 'tv', season=final_season, episode=final_episode, tv_name=search_title)
            except Exception as e:
                log(f"Error: {str(e)}")
            return
        else:
            log("Could not find TV Show ID for episode, searching...")
            _executor.submit(
                run_threaded_extended_search, 
                None, imdb_id, tvdb_id, 
                search_title, year, premiered, 
                final_type, final_season, final_episode
            )
            return

    # --- FAST PATH pentru alte tipuri ---
    if tmdb_id and str(tmdb_id).isdigit() and use_tmdb_id:
        s_num = final_season
        e_num = final_episode
        real_type = final_type
        
        if real_type == 'movie':
            s_num = None
            e_num = None
        
        try:
            from resources.lib.extended_info_mod import run_extended_info
            log(f"FAST PATH: ID={tmdb_id}, Type={real_type}, S={s_num}, E={e_num}")
            run_extended_info(tmdb_id, real_type, season=s_num, episode=e_num, tv_name=search_title)
        except Exception as e:
            log(f"Error: {str(e)}")
        return

    # --- SLOW PATH ---
    log("SLOW PATH: Searching for TMDb ID...")
    _executor.submit(
        run_threaded_extended_search, 
        tmdb_id, imdb_id, tvdb_id, 
        search_title, year, premiered, 
        final_type, final_season, final_episode
    )


if __name__ == '__main__':
    main()