import sys
import xbmc
import xbmcgui
import xbmcaddon
import re
from urllib.parse import quote_plus, urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIG ---
try:
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"
except:
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"

_executor = ThreadPoolExecutor(max_workers=3)

def log(msg):
    xbmc.log(f"[TMDb INFO] {msg}", xbmc.LOGINFO)

def get_first_valid(labels):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if val and val != label and val.lower() not in ['', 'none', 'null', '-1']:
            return str(val).strip()
    return ""

def get_int_value(val):
    if not val:
        return -1
    try:
        num = int(str(val).strip())
        return num if num >= 0 else -1
    except:
        return -1

def get_json(url):
    try:
        import requests
        response = requests.get(url, timeout=5)  # Timeout redus
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}

def normalize_date(date_str):
    if not date_str: return ""
    date_str = str(date_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str): return date_str
    match = re.match(r'^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$', date_str)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str


def find_tv_show_id_fast(imdb_id, tvdb_id, title):
    """Găsește ID-ul TMDb pentru un SERIAL - versiune RAPIDĂ cu request-uri paralele."""
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results = {}
    
    def fetch_imdb():
        if imdb_id and imdb_id.startswith('tt'):
            try:
                r = requests.get(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id", timeout=3)
                if r.status_code == 200:
                    return ('imdb', r.json())
            except: pass
        return ('imdb', None)
    
    def fetch_tvdb():
        if tvdb_id:
            try:
                r = requests.get(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id", timeout=3)
                if r.status_code == 200:
                    return ('tvdb', r.json())
            except: pass
        return ('tvdb', None)
    
    def fetch_search():
        if title:
            clean_title = title.split('(')[0].strip()
            clean_title = re.sub(r'\s*-?\s*[Ss]ezon(ul)?\s*\d+.*$', '', clean_title)
            clean_title = re.sub(r'\s*-?\s*[Ss]eason\s*\d+.*$', '', clean_title).strip()
            if clean_title:
                try:
                    r = requests.get(f"{BASE_URL}/search/tv?api_key={API_KEY}&query={quote_plus(clean_title)}", timeout=3)
                    if r.status_code == 200:
                        return ('search', r.json())
                except: pass
        return ('search', None)
    
    # Lansăm toate request-urile în paralel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(fetch_imdb),
            executor.submit(fetch_tvdb),
            executor.submit(fetch_search)
        ]
        
        # Procesăm rezultatele pe măsură ce vin
        for future in as_completed(futures, timeout=4):
            try:
                key, data = future.result()
                if data:
                    # IMDB result - prioritate maximă
                    if key == 'imdb':
                        if data.get('tv_results'):
                            return str(data['tv_results'][0]['id'])
                        if data.get('tv_episode_results'):
                            show_id = data['tv_episode_results'][0].get('show_id')
                            if show_id:
                                return str(show_id)
                    
                    # TVDB result
                    elif key == 'tvdb':
                        if data.get('tv_results'):
                            return str(data['tv_results'][0]['id'])
                        if data.get('tv_episode_results'):
                            show_id = data['tv_episode_results'][0].get('show_id')
                            if show_id:
                                return str(show_id)
                    
                    # Search result - salvăm pentru fallback
                    elif key == 'search':
                        results['search'] = data
            except:
                pass
    
    # Fallback la search dacă IMDB/TVDB nu au dat rezultat
    if 'search' in results and results['search'].get('results'):
        return str(results['search']['results'][0]['id'])
    
    return None


def resolve_tmdb_id(imdb_id, tvdb_id, title, year, premiered, media_type):
    if imdb_id and imdb_id.startswith('tt'):
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if media_type == 'tv':
                if data.get('tv_results'): 
                    return str(data['tv_results'][0]['id']), 'tv'
                if data.get('tv_episode_results'):
                    show_id = data['tv_episode_results'][0].get('show_id')
                    if show_id:
                        return str(show_id), 'tv'
            else:
                if data.get('movie_results'): 
                    return str(data['movie_results'][0]['id']), 'movie'
                if data.get('tv_results'): 
                    return str(data['tv_results'][0]['id']), 'tv'
            
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data:
            if data.get('tv_results'): 
                return str(data['tv_results'][0]['id']), 'tv'
            if data.get('tv_episode_results'):
                show_id = data['tv_episode_results'][0].get('show_id')
                if show_id:
                    return str(show_id), 'tv'

    if title:
        clean_search_title = title.split('(')[0].strip()
        clean_search_title = re.sub(r'\s*-?\s*[Ss]ezon(ul)?\s*\d+.*$', '', clean_search_title)
        clean_search_title = re.sub(r'\s*-?\s*[Ss]eason\s*\d+.*$', '', clean_search_title).strip()
        
        if not clean_search_title:
            return None, None
        
        search_type = media_type
        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        
        if year and str(year).isdigit() and search_type == 'movie':
            url += f"&primary_release_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        if results:
            norm_premiered = normalize_date(premiered)
            for item in results[:5]:
                item_date = item.get('release_date') or item.get('first_air_date') or ''
                if norm_premiered and item_date == norm_premiered:
                    return str(item['id']), search_type
            
            return str(results[0]['id']), search_type

    return None, None


def get_source_info():
    """Detectează sursa apelului (addon sau bibliotecă)."""
    container_path = xbmc.getInfoLabel('Container.FolderPath')
    plugin_name = xbmc.getInfoLabel('Container.PluginName')
    
    # Dacă suntem într-un plugin
    if plugin_name or 'plugin://' in container_path:
        return 'addon', container_path
    
    # Dacă suntem în bibliotecă
    if 'videodb://' in container_path or 'library://' in container_path:
        return 'library', container_path
    
    return 'unknown', container_path


def launch_addon(tmdb_id, media_type, season=None, episode=None, source='addon', source_path=''):
    path = "plugin://plugin.video.tmdbmovies/"
    extra_langs = "en,null,xx-XX,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ro,ru,pt,zh,ja,ko"
    
    if media_type == 'movie':
        actual_type = 'movie'
    elif episode is not None and episode > 0:
        actual_type = 'episode'
    elif season is not None and season >= 0:
        actual_type = 'season'
    else:
        actual_type = 'tv'
    
    params_dict = {
        'mode': 'global_info',
        'type': actual_type,
        'tmdb_id': str(tmdb_id),
        'source': source  # Adăugăm sursa
    }
    
    if source_path:
        params_dict['source_path'] = source_path
    
    if season is not None and season >= 0:
        params_dict['season'] = str(season)
    if episode is not None and episode > 0:
        params_dict['episode'] = str(episode)
    
    params_dict['include_video_language'] = extra_langs
    params_dict['append_to_response'] = 'videos,credits,images,external_ids'
    
    full_url = f"{path}?{urlencode(params_dict)}"
    xbmc.executebuiltin(f"RunPlugin({full_url})")


def run_threaded_search(imdb_id, tvdb_id, search_title, year, premiered, final_type, season, episode, source, source_path):
    try:
        real_tmdb_id, real_type = resolve_tmdb_id(
            imdb_id, tvdb_id, search_title, year, premiered, final_type
        )

        if real_tmdb_id:
            launch_addon(real_tmdb_id, real_type, season, episode, source, source_path)
        else:
            xbmcgui.Dialog().notification(
                "TMDb Info", 
                f"Nu am găsit: {search_title}", 
                xbmcgui.NOTIFICATION_WARNING,
                3000
            )
    except Exception as e:
        log(f"Error: {str(e)}")


def main():
    # Detectăm sursa ÎNAINTE de orice
    source, source_path = get_source_info()
    
    # --- IDs ---
    tmdb_id = get_first_valid([
        'ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 
        'ListItem.Property(TmdbId)', 'ListItem.TMDBId', 
        'VideoPlayer.TMDBId', 'ListItem.UniqueID(tmdb)'
    ])
    
    imdb_id = get_first_valid([
        'ListItem.IMDBNumber', 'ListItem.Property(imdb_id)',
        'ListItem.Property(imdbid)', 'ListItem.UniqueID(imdb)',
        'VideoPlayer.IMDBNumber'
    ])
    
    tvdb_id = get_first_valid([
        'ListItem.Property(tvdb_id)', 'ListItem.Property(tvdbid)',
        'ListItem.Property(uniqueid_tvdb)', 'ListItem.UniqueID(tvdb)'
    ])
    
    # --- TIPUL CONTINUTULUI ---
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE').lower().strip()
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)').lower().strip()
    
    final_type = 'movie'
    season_num = None
    episode_num = None
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
        season_num = get_int_value(season_raw)
        if season_num < 0:
            season_num = None
        
    elif dbtype == 'episode':
        final_type = 'tv'
        use_tmdb_id = False
        
        season_raw = get_first_valid([
            'ListItem.Season', 'ListItem.Property(season)',
            'ListItem.Property(Season)', 'VideoPlayer.Season'
        ])
        episode_raw = get_first_valid([
            'ListItem.Episode', 'ListItem.Property(episode)',
            'ListItem.Property(Episode)', 'VideoPlayer.Episode'
        ])
        season_num = get_int_value(season_raw)
        episode_num = get_int_value(episode_raw)
        
        if episode_num > 50:
            episode_num = None
        if season_num < 0:
            season_num = None
        if episode_num is not None and episode_num < 1:
            episode_num = None
            
    else:
        if mediatype in ['tvshow', 'season', 'episode', 'tv']:
            final_type = 'tv'
        elif tvdb_id:
            final_type = 'tv'
        
        season_raw = get_first_valid([
            'ListItem.Season', 'ListItem.Property(season)',
            'ListItem.Property(Season)', 'VideoPlayer.Season'
        ])
        episode_raw = get_first_valid([
            'ListItem.Episode', 'ListItem.Property(episode)',
            'ListItem.Property(Episode)', 'VideoPlayer.Episode'
        ])
        season_num = get_int_value(season_raw)
        episode_num = get_int_value(episode_raw)
        
        if season_num is not None and season_num >= 0:
            final_type = 'tv'
        else:
            season_num = None
            
        if episode_num is not None and episode_num > 0 and episode_num <= 50:
            final_type = 'tv'
        else:
            episode_num = None
    
    # --- TITLURI ---
    title = get_first_valid(['ListItem.Title', 'ListItem.Label', 'ListItem.OriginalTitle'])
    tv_show_title = get_first_valid([
        'ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)',
        'ListItem.Property(TVShowTitle)', 'ListItem.Property(showtitle)',
        'VideoPlayer.TVShowTitle'
    ])
    
    if final_type == 'tv' and tv_show_title:
        search_title = tv_show_title
    else:
        search_title = title
    
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    premiered = get_first_valid(['ListItem.Premiered', 'ListItem.Date', 'ListItem.Aired'])
    
    # --- SPECIAL HANDLING PENTRU EPISOADE ---
    if dbtype == 'episode':
        # Căutare RAPIDĂ și paralelă
        show_tmdb_id = find_tv_show_id_fast(imdb_id, tvdb_id, tv_show_title or search_title)
        
        if show_tmdb_id:
            launch_addon(show_tmdb_id, final_type, season_num, episode_num, source, source_path)
            return
        else:
            _executor.submit(
                run_threaded_search, 
                imdb_id, tvdb_id, search_title, year, premiered, 
                final_type, season_num, episode_num, source, source_path
            )
            return
    
    # --- FAST PATH pentru alte tipuri ---
    if tmdb_id and str(tmdb_id).isdigit() and use_tmdb_id:
        launch_addon(tmdb_id, final_type, season_num, episode_num, source, source_path)
        return

    # --- SLOW PATH ---
    if not search_title:
        xbmcgui.Dialog().notification("TMDb Info", "Nu am găsit titlul", xbmcgui.NOTIFICATION_WARNING)
        return
    
    _executor.submit(
        run_threaded_search, 
        imdb_id, tvdb_id, search_title, year, premiered, 
        final_type, season_num, episode_num, source, source_path
    )


if __name__ == '__main__':
    main()