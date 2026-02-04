import sys
import xbmc
import xbmcgui
import xbmcaddon
import re
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor

# NOTA: NU importam 'requests' aici. Il importam doar in functia get_json 
# pentru a face meniul sa apara INSTANT cand avem deja ID-ul (Lazy Loading).

# --- CONFIG ---
try:
    ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"
except:
    API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
    BASE_URL = "https://api.themoviedb.org/3"

def log(msg):
    xbmc.log(f"[TMDb INFO] {msg}", xbmc.LOGINFO)

def get_first_valid(labels):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if val and val != label:
            return str(val).strip()
    return ""

def get_json(url):
    # --- LAZY IMPORT ---
    # Importam requests DOAR daca ajungem aici (adica daca nu avem ID si trebuie sa cautam pe net)
    try:
        import requests
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}

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

def parse_duration(duration_str):
    if not duration_str: return 0
    s = str(duration_str).lower().strip()
    try:
        if 'h' in s:
            hours = 0; minutes = 0
            h_match = re.search(r'(\d+)\s*h', s)
            if h_match: hours = int(h_match.group(1))
            m_match = re.search(r'(\d+)\s*m', s)
            if m_match: minutes = int(m_match.group(1))
            total = (hours * 60) + minutes
            if total > 0: return total
        if ':' in s:
            parts = s.split(':')
            if len(parts) == 3: return (int(parts[0]) * 60) + int(parts[1])
            if len(parts) == 2: return int(parts[0])
        nums = re.findall(r'\d+', s)
        if nums:
            val = int(nums[0])
            if val > 300: return int(val / 60)
            return val
    except: pass
    return 0

def check_details_match(tmdb_id, media_type, kodi_duration_min, kodi_country):
    url = f"{BASE_URL}/{media_type}/{tmdb_id}?api_key={API_KEY}"
    data = get_json(url)
    if not data: return 0, 999
    
    tmdb_runtime = 0
    if media_type == 'movie': tmdb_runtime = data.get('runtime', 0)
    else: 
        runtimes = data.get('episode_run_time', [])
        if runtimes: tmdb_runtime = runtimes[0]
        
    is_runtime_ok = False
    diff = 999
    if kodi_duration_min > 0 and tmdb_runtime:
        diff = abs(tmdb_runtime - kodi_duration_min)
        if diff <= 15: is_runtime_ok = True
    elif kodi_duration_min == 0:
        is_runtime_ok = True 
        diff = 0

    is_country_ok = True
    if kodi_country:
        tmdb_countries = []
        if 'production_countries' in data:
            tmdb_countries = [c.get('name', '').lower() for c in data['production_countries']]
            tmdb_countries += [c.get('iso_3166_1', '').lower() for c in data['production_countries']]
        if 'origin_country' in data:
            tmdb_countries += [c.lower() for c in data['origin_country']]

        kodi_countries_list = [c.strip().lower() for c in re.split(r'[ /,\.]', kodi_country) if len(c) > 2]
        for kc in kodi_countries_list:
            for tc in tmdb_countries:
                if kc in tc or tc in kc:
                    is_country_ok = True
                    break
                    
    if is_runtime_ok and is_country_ok: return 2, diff
    if is_runtime_ok: return 1, diff
    return 0, diff

def resolve_tmdb_id(imdb_id, tvdb_id, title, year, premiered, duration_min, country, media_type):
    # Aceasta functie se apeleaza DOAR daca nu avem tmdb_id din prima (Slow Path)
    if imdb_id:
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if data.get('movie_results'): return str(data['movie_results'][0]['id']), 'movie'
            if data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'
            
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data and data.get('tv_results'): return str(data['tv_results'][0]['id']), 'tv'

    if title:
        search_type = 'movie' if media_type == 'movie' else 'tv'
        clean_search_title = title.split('(')[0].strip()
        
        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        if year and str(year).isdigit():
            if search_type == 'movie': url += f"&primary_release_year={year}"
            else: url += f"&first_air_date_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        if not results: return None, None

        candidates = []
        norm_premiered = normalize_date(premiered)
        
        # Logica simplificata de matching
        for item in results:
            item_id = item.get('id')
            item_date = item.get('release_date') or item.get('first_air_date') or ''
            
            if norm_premiered and item_date == norm_premiered:
                return str(item_id), search_type # Match perfect pe data

            candidates.append(item)

        if candidates:
            # Daca nu avem match pe data, luam primul (cel mai popular)
            # Sau putem face deep check daca avem durata
            if duration_min > 0:
                best_score = -1
                best_cand = candidates[0]
                for item in candidates[:3]: # Verificam doar top 3 pentru viteza
                    score, diff = check_details_match(item['id'], search_type, duration_min, country)
                    if score > best_score:
                        best_score = score
                        best_cand = item
                return str(best_cand['id']), search_type
            
            return str(candidates[0]['id']), search_type

    return None, None

def launch_addon(tmdb_id, media_type, season=None, episode=None):
    path = "plugin://plugin.video.tmdbmovies/"
    api_type = 'movie' if media_type == 'movie' else 'tv'
    
    # Parametrii optimizati
    extra_langs = "en,null,xx-XX,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ro,ru,pt,zh,ja,ko"
    
    params = f"?mode=global_info&type={api_type}&tmdb_id={quote_plus(str(tmdb_id))}"
    params += f"&include_video_language={quote_plus(extra_langs)}"
    
    # Aici cerem VIDEOS pentru a le avea pregatite pentru ExtendedInfo fallback
    params += f"&append_to_response=videos,credits,images,external_ids"
    
    if season: params += f"&season={quote_plus(str(season))}"
    if episode: params += f"&episode={quote_plus(str(episode))}"

    xbmc.executebuiltin(f"RunPlugin({path}{params})")


# --- ADAUGA ACEASTA FUNCTIE NOUA PENTRU PROCESARE IN FUNDAL ---
def run_threaded_search(imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type, season, episode):
    real_tmdb_id, real_type = resolve_tmdb_id(imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type)

    if real_tmdb_id:
        launch_addon(real_tmdb_id, real_type, season, episode)
    else:
        xbmcgui.Dialog().notification("TMDb Info", "ID-ul nu a putut fi găsit.", xbmcgui.NOTIFICATION_WARNING)


def main():
    # =========================================================================
    # 1. FAST PATH: Citim ID-ul direct din proprietatile ferestrei/listei
    # =========================================================================
    tmdb_id = get_first_valid(['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId'])
    
    # Determinăm tipul (movie/tv/season/episode)
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    final_type = 'movie'
    if dbtype in ['season', 'episode', 'tvshow'] or mediatype in ['season', 'episode', 'tvshow']:
        final_type = 'tv'
        
    season = xbmc.getInfoLabel('ListItem.Season')
    episode = xbmc.getInfoLabel('ListItem.Episode')
    
    # Cazul special: Daca e sezon sau episod, dar tipul principal e 'tv'
    if dbtype == 'season' or mediatype == 'season':
        # TMDb API pentru 'season' se face tot prin endpoint-ul 'tv'
        pass 
        
    # --- CHECKPOINT INSTANT ---
    if tmdb_id:
        log(f"FAST PATH: ID found {tmdb_id} type {final_type}")
        launch_addon(tmdb_id, final_type, season, episode)
        return

    # =========================================================================
    # 2. SLOW PATH: Fallback - Doar daca nu avem ID
    # (Aici se incarca 'requests' si dureaza mai mult)
    # =========================================================================
    log("SLOW PATH: ID missing, initiating scraper...")
    
    imdb_id = get_first_valid(['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)'])
    tvdb_id = get_first_valid(['ListItem.Property(tvdb_id)', 'ListItem.Property(uniqueid_tvdb)'])
    
    title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    tv_show_title = get_first_valid(['ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)'])
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    premiered = get_first_valid(['ListItem.Premiered', 'ListItem.Date'])
    
    # Parse Duration/Country doar la nevoie
    duration_str = get_first_valid(['ListItem.Duration', 'ListItem.Runtime'])
    duration_min = parse_duration(duration_str)
    country = get_first_valid(['ListItem.Country', 'ListItem.Property(country)'])
    
    search_title = tv_show_title if tv_show_title else title
    
    # INLOCUIESTE BLOCUL VECHI (SLOW PATH) CU ACESTA:
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(run_threaded_search, imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type, season, episode)

if __name__ == '__main__':
    main()