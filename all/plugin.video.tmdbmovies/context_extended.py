import sys
import xbmc
import xbmcgui
import xbmcaddon
import requests
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

def parse_duration(duration_str):
    """Converteste orice format de durata in minute (int)"""
    if not duration_str: return 0
    s = str(duration_str).lower().strip()
    try:
        if 'h' in s:
            hours = 0
            minutes = 0
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

def get_first_valid(labels):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if val and val != label:
            return str(val).strip()
    return ""

def get_json(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return {}

def check_details_match(tmdb_id, media_type, kodi_duration_min, kodi_country):
    url = f"{BASE_URL}/{media_type}/{tmdb_id}?api_key={API_KEY}"
    data = get_json(url)
    if not data: return 0, 999
    
    # 1. Durata
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

    # 2. Tara
    is_country_ok = False
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
    else:
        is_country_ok = True 

    log(f"Deep Check ID {tmdb_id}: RuntimeMatch={is_runtime_ok} (Diff:{diff}), CountryMatch={is_country_ok} (Kodi:{kodi_country})")

    if is_runtime_ok and is_country_ok: return 2, diff
    if is_runtime_ok: return 1, diff
    return 0, diff

def resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, title, year, premiered, duration_min, country, media_type):
    if tmdb_id: return tmdb_id, media_type

    if imdb_id:
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
        search_query = clean_str(clean_search_title)
        norm_premiered = normalize_date(premiered)
        
        log(f"Searching: '{clean_search_title}' | Year: {year} | Date: {norm_premiered} | Time: {duration_min}m | Country: {country}")

        url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
        if year and str(year).isdigit():
            if search_type == 'movie': url += f"&primary_release_year={year}"
            else: url += f"&first_air_date_year={year}"
            
        data = get_json(url)
        results = data.get('results', [])
        
        if not results and year:
            url_no_year = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_search_title)}"
            data = get_json(url_no_year)
            results = data.get('results', [])

        if not results: return None, None

        candidates = []
        for item in results:
            item_id = item.get('id')
            item_date = item.get('release_date') or item.get('first_air_date') or ''
            
            if norm_premiered and item_date == norm_premiered:
                log(f"PERFECT DATE MATCH: {item_id}")
                return str(item_id), search_type

            item_title = clean_str(item.get('title') or item.get('name', ''))
            item_orig = clean_str(item.get('original_title') or item.get('original_name', ''))
            
            if search_query == item_title or search_query == item_orig:
                candidates.append(item)

        if candidates:
            best_candidate = None
            best_score = -1
            best_diff = 999
            for item in candidates:
                score, diff = check_details_match(item['id'], search_type, duration_min, country)
                if score > best_score:
                    best_score = score
                    best_diff = diff
                    best_candidate = item
                elif score == best_score:
                    if diff < best_diff:
                        best_diff = diff
                        best_candidate = item
            
            if best_candidate and best_score > 0:
                log(f"Resolved via DEEP CHECK (Score {best_score}): {best_candidate['id']}")
                return str(best_candidate['id']), search_type

            candidates.sort(key=lambda x: x.get('vote_count', 0), reverse=True)
            return str(candidates[0]['id']), search_type

        return str(results[0]['id']), search_type

    return None, None


# --- FUNCTIE NOUA PENTRU PROCESARE IN FUNDAL (THREADING) ---
def run_threaded_extended_search(tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type, final_season, final_episode):
    real_tmdb_id, real_type = resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type)

    if real_tmdb_id:
        try:
            from resources.lib.extended_info_mod import run_extended_info
            
            s_num = int(final_season) if final_season and str(final_season).isdigit() else None
            e_num = int(final_episode) if final_episode and str(final_episode).isdigit() else None
            
            if real_type == 'movie':
                s_num = None
                e_num = None

            log(f"Launching Extended Info: ID={real_tmdb_id}, Type={real_type}, S={s_num}, E={e_num}")
            run_extended_info(real_tmdb_id, real_type, season=s_num, episode=e_num, tv_name=search_title)
            
        except Exception as e:
            import traceback
            log(f"CRASH: {traceback.format_exc()}")
            xbmcgui.Dialog().notification("Extended Info", f"Eroare: {e}", xbmcgui.NOTIFICATION_ERROR)
    else:
        xbmcgui.Dialog().notification("Extended Info", "ID-ul nu a putut fi găsit.", xbmcgui.NOTIFICATION_WARNING)
# -----------------------------------------------------------


def main():
    tmdb_id = get_first_valid(['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId', 'ListItem.Property(uniqueid_tmdb)'])
    imdb_id = get_first_valid(['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 'ListItem.Property(uniqueid_imdb)'])
    tvdb_id = get_first_valid(['ListItem.Property(tvdb_id)', 'ListItem.Property(uniqueid_tvdb)'])

    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    final_type = 'movie'
    final_season = None
    final_episode = None

    if dbtype in ['tvshow', 'season', 'episode', 'tv'] or mediatype in ['tvshow', 'season', 'episode', 'tv']:
        final_type = 'tv'
    
    season = xbmc.getInfoLabel('ListItem.Season') or xbmc.getInfoLabel('ListItem.Property(season)')
    episode = xbmc.getInfoLabel('ListItem.Episode') or xbmc.getInfoLabel('ListItem.Property(episode)')
    
    if season and str(season) != '0': 
        final_season = season
        final_type = 'tv'
    if episode and str(episode) != '0':
        final_episode = episode
        final_type = 'tv'

    # Parse Duration Robust
    duration_str = get_first_valid(['ListItem.Duration', 'ListItem.Runtime', 'ListItem.Property(runtime)', 'ListItem.Property(duration)'])
    duration_min = parse_duration(duration_str)
    
    country = get_first_valid(['ListItem.Country', 'ListItem.Property(country)', 'ListItem.Property(origin_country)'])

    title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    tv_show_title = get_first_valid(['ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)'])
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    premiered = get_first_valid(['ListItem.Premiered', 'ListItem.Date', 'ListItem.Property(premiered)'])

    search_title = tv_show_title if tv_show_title else title
    
    log(f"Detected: Title='{search_title}', Date='{premiered}', Country='{country}', Type='{final_type}', IDs(T:{tmdb_id}/I:{imdb_id})")

    # EXECUTA IN FUNDAL PENTRU VITEZA INSTANTA
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(run_threaded_extended_search, tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type, final_season, final_episode)

if __name__ == '__main__':
    main()