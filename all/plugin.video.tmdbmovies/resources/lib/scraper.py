import requests
import xbmc
import re
import json
from urllib.parse import urlencode, quote
from resources.lib.config import BASE_URL, API_KEY, ADDON, get_headers, get_random_ua
from resources.lib.utils import get_json

# --- HELPERE ---
def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[tmdbmovies] {msg}", level)

def get_external_ids(content_type, tmdb_id):
    url = f"{BASE_URL}/{content_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    return get_json(url)

# =============================================================================
# HELPER PENTRU CONSTRUIREA URL-URILOR CU HEADERE (IMPORTANT!)
# =============================================================================
def build_stream_url(url, referer=None, origin=None):
    """
    Atașează headerele critice la URL folosind sintaxa Kodi (pipe |).
    """
    if '|' in url:
        # Daca are deja headere, nu ne mai bagam, presupunem ca sunt ok
        return url
        
    headers = {
        'User-Agent': get_random_ua(), # UA-ul consistent din config
        'Connection': 'keep-alive'     # Critic pentru sursele free
    }
    
    if referer:
        headers['Referer'] = referer
    if origin:
        headers['Origin'] = origin
        
    return f"{url}|{urlencode(headers)}"

# =============================================================================
# SCRAPERS
# =============================================================================

def _get_tmdb_id_internal(imdb_id):
    try:
        url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
        data = get_json(url)
        results = data.get('movie_results', []) or data.get('tv_results', [])
        if results:
            return results[0].get('id')
    except Exception as e:
        log(f"[VIX-CONVERT] Eroare: {e}")
    return None

def scrape_vixsrc(imdb_id, content_type, season=None, episode=None):
    if ADDON.getSetting('use_vixsrc') == 'false':
        return None

    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None

    try:
        base_ref = 'https://vixsrc.to/'
        if content_type == 'movie':
            page_url = f"https://vixsrc.to/movie/{tmdb_id}"
        else:
            page_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}"

        log(f"[VIXSRC] Interogare: {page_url}")

        # Folosim get_headers() care acum are UA stabil
        # MODIFICARE: Adaugat raise_for_status pentru detectare eroare HTTP
        r = requests.get(page_url, headers=get_headers(), timeout=10)
        r.raise_for_status()

        if r.status_code != 200:
            return None

        content = r.text
        start_marker = "window.masterPlaylist"
        start_pos = content.find(start_marker)
        if start_pos == -1: return None
        json_start = content.find('{', start_pos)
        if json_start == -1: return None
        brace_count = 0
        json_end = -1
        for i, char in enumerate(content[json_start:], start=json_start):
            if char == '{': brace_count += 1
            elif char == '}': 
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1: return None
        json_str = content[json_start:json_end]
        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_-]+)\s*:', r'\1"\2":', json_str)
        json_str = json_str.replace("'", '"')
        json_str = re.sub(r',(\s*})', r'\1', json_str)
        data = json.loads(json_str)

        base_url = data.get('url')
        params = data.get('params', {})
        
        if not base_url: return None
            
        params['h'] = '1'
        params['lang'] = 'en'
        sep = '&' if '?' in base_url else '?'
        final_url = f"{base_url}{sep}{urlencode(params)}"
        
        # AICI APLICAM HEADER-ELE CORECT
        final_url_with_headers = build_stream_url(final_url, referer=base_ref)
        
        return {
            'name': 'VixMovie [HLS]',
            'url': final_url_with_headers,
            'description': 'Direct Stream 1080p'
        }
    except Exception as e:
        # MODIFICARE: Aruncăm eroarea mai departe pentru a fi prinsă de loop-ul principal ca "Timeout/Error"
        raise e

def scrape_sooti(imdb_id, content_type, season=None, episode=None):
    if ADDON.getSetting('use_sooti') == 'false':
        return None

    last_exception = None
    success_any = False

    try:
        # Configurația JSON (comprimată)
        sooti_config_json = {
            "DebridServices": [{"provider": "httpstreaming", "http4khdhub": True, "httpHDHub4u": True, "httpUHDMovies": True, "httpMoviesDrive": True, "httpMKVCinemas": True, "httpMalluMv": True, "httpCineDoze": True, "httpVixSrc": True}],
            "Languages": [], "Scrapers": [], "IndexerScrapers": [], "minSize": 0, "maxSize": 200, "ShowCatalog": False, "DebridProvider": "httpstreaming"
        }
        encoded_config = quote(json.dumps(sooti_config_json))
        
        # Lista de oglinzi (Mirrors)
        base_urls = [
            f"https://sooti.info/{encoded_config}",
            f"https://sootiofortheweebs.midnightignite.me/{encoded_config}"
        ]

        for base_sooti_url in base_urls:
            # Construim URL-ul API
            if content_type == 'movie':
                api_url = f"{base_sooti_url}/stream/movie/{imdb_id}.json"
            else:
                api_url = f"{base_sooti_url}/stream/series/{imdb_id}:{season}:{episode}.json"

            log(f"[SOOTI] Încerc oglinda: {base_sooti_url[:30]}...")

            try:
                # Timeout mai scurt (10s) pentru a trece rapid la următoarea dacă una e moartă
                r = requests.get(api_url, headers=get_headers(), timeout=10, verify=False)
                r.raise_for_status()
                
                if r.status_code == 200:
                    data = r.json()
                    success_any = True
                    if 'streams' in data and data['streams']:
                        found_streams = []
                        for s in data['streams']:
                            if s.get('url'):
                                s['name'] = s.get('name', 'Sooti')
                                if 'Sooti' not in s['name'] and '[HS+]' not in s['name']: 
                                    s['name'] = f"Sooti {s['name']}"
                                
                                # Fix VixSrc in Sooti
                                if 'vixsrc' in s['url'] and '|' not in s['url']:
                                    s['url'] = build_stream_url(s['url'], referer="https://vixsrc.to/")
                                elif '|' not in s['url']:
                                    s['url'] = build_stream_url(s['url'])
                                    
                                found_streams.append(s)
                        
                        log(f"[SOOTI] ✓ Succes! {len(found_streams)} surse găsite.")
                        return found_streams # Dacă am găsit, ieșim și returnăm
                else:
                    log(f"[SOOTI] Eroare HTTP {r.status_code} pe oglinda curentă.")

            except Exception as e:
                log(f"[SOOTI] Oglinda a eșuat ({e}). Trec la următoarea...")
                last_exception = e
                continue # Trecem explicit la următoarea iterație din bucla `base_urls`

    except Exception as e:
        log(f"[SOOTI] Eroare critică configurare: {e}", xbmc.LOGERROR)
        raise e
        
    # Dacă nicio oglindă nu a răspuns (toate au dat eroare), ridicăm eroarea
    if not success_any and last_exception:
        raise last_exception
        
    return None

def scrape_rogflix(imdb_id, content_type, season=None, episode=None):
    if ADDON.getSetting('use_rogflix') == 'false': return None
    base_url = "https://rogflix.vflix.life/stremio/stream"
    try:
        if content_type == 'movie': api_url = f"{base_url}/movie/{imdb_id}.json"
        else: api_url = f"{base_url}/series/{imdb_id}:{season}:{episode}.json"
        
        r = requests.get(api_url, headers=get_headers(), timeout=15, verify=False)
        r.raise_for_status()

        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                found_streams = []
                # Rogflix are nevoie de Origin specific
                ref = 'https://rogflix.vflix.life/'
                origin = 'https://rogflix.vflix.life'
                
                for s in data['streams']:
                    url = s.get('url')
                    if url:
                        raw_name = s.get('name', 'Rogflix').replace('\n', ' ')
                        extra = s.get('title', '')
                        if extra: raw_name = f"{raw_name} - {extra}"
                        
                        s['name'] = raw_name
                        s['url'] = build_stream_url(url, referer=ref, origin=origin)
                        found_streams.append(s)
                return found_streams
    except Exception as e:
        log(f"[ROGFLIX] Eroare: {e}", xbmc.LOGERROR)
        raise e
    return None

# =============================================================================
# HELPER PROVIDERI JSON (Vega, Nuvio, StreamVix, Vidzee, Webstreamr)
# =============================================================================
def _scrape_json_provider(base_url, pattern, label, imdb_id, content_type, season, episode, all_streams, seen_urls):
    try:
        if content_type == 'movie':
            api_url = f"{base_url}/stream/movie/{imdb_id}.json" if pattern == 'stream' else f"{base_url}/movie/{imdb_id}.json"
        else:
            api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json" if pattern == 'stream' else f"{base_url}/series/{imdb_id}:{season}:{episode}.json"

        r = requests.get(api_url, headers=get_headers(), timeout=15, verify=False)
        r.raise_for_status()

        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                count = 0
                # Definim Referer/Origin specifice bazei
                ref = base_url + '/'
                origin = base_url

                for s in data['streams']:
                    url = s.get('url', '')
                    clean_check_url = url.split('|')[0]
                    
                    if url and clean_check_url not in seen_urls:
                        if 'name' not in s: s['name'] = label
                        elif label not in s['name']: s['name'] = f"{label} {s['name']}"
                        
                        # Construim URL-ul complet cu headerele consistente
                        s['url'] = build_stream_url(url, referer=ref, origin=origin)
                        
                        all_streams.append(s)
                        seen_urls.add(clean_check_url)
                        count += 1
                log(f"[SCRAPER] ✓ {label}: {count} surse")
    except Exception as e:
        # MODIFICARE: Aruncăm eroarea pentru ca funcția principală să marcheze providerul ca FAILED
        raise e

# =============================================================================
# MAIN ORCHESTRATION FUNCTION (MODIFICATĂ PENTRU SMART RETRY)
# =============================================================================
def get_stream_data(imdb_id, content_type, season=None, episode=None, progress_callback=None, target_providers=None):
    """
    Orchestrează scanarea.
    
    Args:
        target_providers: Listă de ID-uri de provideri (ex: ['sooti', 'vega']). 
                          Dacă e specificată, scanează DOAR acești provideri.
                          
    Returns:
        (all_streams, failed_providers) - returnează și lista celor care au eșuat.
    """
    all_streams = []
    seen_urls = set()
    failed_providers = [] # Lista în care reținem cine a dat timeout
    
    # Mapare completă ID -> (Nume, Funcție de execuție)
    # Folosim lambda pentru a întârzia execuția până la iterare
    # --- AICI S-A MODIFICAT ORDINEA ---
    providers_map = {
        # 1. Sooti
        'sooti': ('Sooti', lambda: scrape_sooti(imdb_id, content_type, season, episode)),
        # 2. Nuvio
        'nuvio': ('Nuvio', lambda: _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'Nuvio', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        # 3. WebStreamr
        'webstreamr': ('WebStreamr', lambda: _scrape_json_provider("https://webstreamr.hayd.uk", 'stream', 'WebStreamr', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        # 4. VixSrc
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode)),
        
        # --- Restul ---
        'rogflix': ('Rogflix', lambda: scrape_rogflix(imdb_id, content_type, season, episode)),
        'vega': ('Vega', lambda: _scrape_json_provider("https://vega.vflix.life", 'stream', 'Vega', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'streamvix': ('StreamVix', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamVix', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'vidzee': ('Vidzee', lambda: _scrape_json_provider("https://vidzee.vflix.life", 'direct', 'Vidzee', imdb_id, content_type, season, episode, all_streams, seen_urls))
    }

    # Construim lista de execuție (to_run)
    to_run = []
    
    if target_providers is not None:
        # RETRY MODE: Scanăm doar providerii specificați în listă
        log(f"[SCRAPER] Retry mode activat pentru: {target_providers}")
        for pid in target_providers:
            if pid in providers_map:
                # Verificăm totuși dacă utilizatorul nu l-a dezactivat între timp din setări
                setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
                if ADDON.getSetting(setting_id) == 'true':
                    pname, pfunc = providers_map[pid]
                    to_run.append((pid, pname, pfunc))
    else:
        # NORMAL MODE: Scanăm toți providerii activați în ordinea din dicționar
        for pid, (pname, pfunc) in providers_map.items():
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if ADDON.getSetting(setting_id) == 'true':
                to_run.append((pid, pname, pfunc))
    
    total = len(to_run)
    if total == 0:
        return [], []

    # Bucla de execuție
    for idx, (pid, pname, pfunc) in enumerate(to_run):
        if progress_callback: 
            progress_callback(int(((idx+1)/total)*80)+10, pname)
        
        try:
            result = pfunc()
            
            if result:
                if isinstance(result, list):
                    for item in result:
                        cl = item['url'].split('|')[0]
                        if cl not in seen_urls:
                            item['provider_id'] = pid  # <--- LINIE NOUĂ: Etichetăm sursa
                            all_streams.append(item)
                            seen_urls.add(cl)
                elif isinstance(result, dict):
                    cl = result['url'].split('|')[0]
                    if cl not in seen_urls:
                        result['provider_id'] = pid  # <--- LINIE NOUĂ: Etichetăm sursa
                        all_streams.append(result)
                        seen_urls.add(cl)
                        
        except Exception as e:
            log(f"[SCRAPER] ✗ {pname} a eșuat (Timeout/Eroare): {e}", xbmc.LOGWARNING)
            failed_providers.append(pid)

    return all_streams, failed_providers