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
    xbmc.log(f"[tmdbmovies-context] {msg}", xbmc.LOGINFO)

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
            hours = minutes = 0
            h_match = re.search(r'(\d+)\s*h', s)
            m_match = re.search(r'(\d+)\s*m', s)
            if h_match: hours = int(h_match.group(1))
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
            return int(val / 60) if val > 300 else val
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
    """Deep check - DOAR pentru coliziuni de titlu"""
    url = f"{BASE_URL}/{media_type}/{tmdb_id}?api_key={API_KEY}"
    data = get_json(url)
    if not data: return 0, 999
    
    tmdb_runtime = 0
    if media_type == 'movie': 
        tmdb_runtime = data.get('runtime', 0)
    else: 
        runtimes = data.get('episode_run_time', [])
        if runtimes: tmdb_runtime = runtimes[0]
        
    score = 0
    diff = 999
    
    # Verifica durata
    if kodi_duration_min > 0 and tmdb_runtime:
        diff = abs(tmdb_runtime - kodi_duration_min)
        if diff <= 15: score += 1
    
    # Verifica tara
    if kodi_country:
        tmdb_countries = []
        if 'production_countries' in data:
            tmdb_countries = [c.get('name', '').lower() for c in data['production_countries']]
            tmdb_countries += [c.get('iso_3166_1', '').lower() for c in data['production_countries']]
        if 'origin_country' in data:
            tmdb_countries += [c.lower() for c in data['origin_country']]
        
        kodi_list = [c.strip().lower() for c in re.split(r'[ /,\.]', kodi_country) if len(c) > 2]
        for kc in kodi_list:
            if any(kc in tc or tc in kc for tc in tmdb_countries):
                score += 1
                break

    return score, diff

def resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, title, year, premiered, duration_min, country, media_type):
    """Rezolvare ULTRA-RAPIDA - deep check doar la coliziuni"""
    
    # ══════════════════════════════════════════════════════════════
    # TIER 1: INSTANT (0 API calls)
    # ══════════════════════════════════════════════════════════════
    if tmdb_id: 
        log(f"INSTANT: TMDB ID existent -> {tmdb_id}")
        return tmdb_id, media_type
    
    # ══════════════════════════════════════════════════════════════
    # TIER 2: FAST (1 API call - external ID lookup)
    # ══════════════════════════════════════════════════════════════
    if imdb_id:
        data = get_json(f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
        if data:
            if data.get('movie_results'): 
                log(f"FAST: IMDB lookup -> {data['movie_results'][0]['id']}")
                return str(data['movie_results'][0]['id']), 'movie'
            if data.get('tv_results'): 
                log(f"FAST: IMDB lookup -> {data['tv_results'][0]['id']}")
                return str(data['tv_results'][0]['id']), 'tv'
            
    if tvdb_id:
        data = get_json(f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id")
        if data and data.get('tv_results'): 
            log(f"FAST: TVDB lookup -> {data['tv_results'][0]['id']}")
            return str(data['tv_results'][0]['id']), 'tv'

    # ══════════════════════════════════════════════════════════════
    # TIER 3: SEARCH (1 API call - title search)
    # ══════════════════════════════════════════════════════════════
    if not title: return None, None
    
    search_type = 'movie' if media_type == 'movie' else 'tv'
    clean_title = title.split('(')[0].strip()
    
    # Cautare cu an
    url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_title)}"
    if year and str(year).isdigit():
        url += f"&primary_release_year={year}" if search_type == 'movie' else f"&first_air_date_year={year}"
        
    data = get_json(url)
    results = data.get('results', [])
    
    # Retry fara an daca nu gaseste
    if not results and year:
        data = get_json(f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={quote_plus(clean_title)}")
        results = data.get('results', [])

    if not results: 
        log("NO RESULTS FOUND")
        return None, None

    # ──────────────────────────────────────────────────────────────
    # SUPER FAST: Un singur rezultat total = INSTANT RETURN
    # ──────────────────────────────────────────────────────────────
    if len(results) == 1:
        log(f"SUPER FAST: Single result -> {results[0]['id']}")
        return str(results[0]['id']), search_type

    # ──────────────────────────────────────────────────────────────
    # FAST: Verificare data exacta (NU face API call suplimentar)
    # ──────────────────────────────────────────────────────────────
    norm_premiered = normalize_date(premiered)
    if norm_premiered:
        for item in results:
            item_date = item.get('release_date') or item.get('first_air_date') or ''
            if item_date == norm_premiered:
                log(f"FAST: Exact date match -> {item['id']}")
                return str(item['id']), search_type

    # ──────────────────────────────────────────────────────────────
    # Gaseste candidati cu titlu EXACT
    # ──────────────────────────────────────────────────────────────
    search_query = clean_str(clean_title)
    exact_matches = []
    
    for item in results:
        item_title = clean_str(item.get('title') or item.get('name', ''))
        item_orig = clean_str(item.get('original_title') or item.get('original_name', ''))
        
        if search_query == item_title or search_query == item_orig:
            exact_matches.append(item)

    # ──────────────────────────────────────────────────────────────
    # FAST: Un singur titlu exact = INSTANT RETURN
    # ──────────────────────────────────────────────────────────────
    if len(exact_matches) == 1:
        log(f"FAST: Single exact title -> {exact_matches[0]['id']}")
        return str(exact_matches[0]['id']), search_type

    # ══════════════════════════════════════════════════════════════
    # TIER 4: DEEP CHECK (doar la COLIZIUNI - mai multe titluri identice)
    # ══════════════════════════════════════════════════════════════
    if len(exact_matches) > 1:
        log(f"COLLISION DETECTED: {len(exact_matches)} movies with same title. Starting deep check...")
        
        # Doar daca avem informatii utile pentru deep check
        if duration_min > 0 or country:
            best = None
            best_score = -1
            best_diff = 999
            
            for item in exact_matches:
                score, diff = check_details_match(item['id'], search_type, duration_min, country)
                log(f"  -> ID {item['id']}: score={score}, diff={diff}")
                
                if score > best_score or (score == best_score and diff < best_diff):
                    best_score, best_diff, best = score, diff, item
            
            if best and best_score > 0:
                log(f"DEEP CHECK WIN: {best['id']} (score={best_score})")
                return str(best['id']), search_type
        
        # Fallback: cel mai popular dintre titlurile exacte
        exact_matches.sort(key=lambda x: x.get('vote_count', 0), reverse=True)
        log(f"POPULARITY FALLBACK (exact): {exact_matches[0]['id']}")
        return str(exact_matches[0]['id']), search_type

    # ──────────────────────────────────────────────────────────────
    # FALLBACK: Cel mai popular rezultat general
    # ──────────────────────────────────────────────────────────────
    results.sort(key=lambda x: x.get('vote_count', 0), reverse=True)
    log(f"POPULARITY FALLBACK (general): {results[0]['id']}")
    return str(results[0]['id']), search_type

def main():
    tmdb_id = get_first_valid(['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId', 'ListItem.Property(uniqueid_tmdb)'])
    imdb_id = get_first_valid(['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 'ListItem.Property(uniqueid_imdb)'])
    tvdb_id = get_first_valid(['ListItem.Property(tvdb_id)', 'ListItem.Property(uniqueid_tvdb)'])

    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    final_type = 'movie'
    if dbtype in ['season', 'episode', 'tvshow'] or mediatype in ['season', 'episode', 'tvshow']:
        final_type = 'tv'
    
    season = xbmc.getInfoLabel('ListItem.Season')
    episode = xbmc.getInfoLabel('ListItem.Episode')
    duration_str = get_first_valid(['ListItem.Duration', 'ListItem.Runtime', 'ListItem.Property(runtime)', 'ListItem.Property(duration)'])
    duration_min = parse_duration(duration_str)
    country = get_first_valid(['ListItem.Country', 'ListItem.Property(country)', 'ListItem.Property(origin_country)'])
    title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    tv_show_title = get_first_valid(['ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)'])
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    premiered = get_first_valid(['ListItem.Premiered', 'ListItem.Date', 'ListItem.Property(premiered)'])
    
    search_title = tv_show_title if tv_show_title else title
    
    real_tmdb_id, real_type = resolve_tmdb_id(tmdb_id, imdb_id, tvdb_id, search_title, year, premiered, duration_min, country, final_type)

    if real_tmdb_id:
        path = "plugin://plugin.video.tmdbmovies/"
        api_type = 'movie' if real_type == 'movie' else 'tv'
        extra_langs = "en,null,xx,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ro,ru,pt,zh,ja,ko"
        
        params = f"?mode=global_info&type={api_type}&tmdb_id={quote_plus(real_tmdb_id)}"
        params += f"&include_video_language={quote_plus(extra_langs)}"
        params += f"&append_to_response=videos,credits,images,external_ids,release_dates"
        
        if season and str(season).isdigit(): params += f"&season={quote_plus(season)}"
        if episode and str(episode).isdigit(): params += f"&episode={quote_plus(episode)}"

        xbmc.executebuiltin(f"RunPlugin({path}{params})")
    else:
        xbmcgui.Dialog().notification("TMDb Info", "ID-ul nu a putut fi găsit.", xbmcgui.NOTIFICATION_WARNING)

if __name__ == '__main__':
    main()