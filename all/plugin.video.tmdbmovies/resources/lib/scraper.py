import requests
import xbmc
import re
import json
from urllib.parse import urlencode, quote # Importam quote pentru a URL-encoda JSON-ul
from resources.lib.config import BASE_URL, API_KEY, ADDON, get_headers
from resources.lib.utils import get_json

# --- HELPERE ---
def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[tmdbmovies] {msg}", level)

def get_external_ids(content_type, tmdb_id):
    url = f"{BASE_URL}/{content_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    return get_json(url)

# =============================================================================
# FUNCȚII SPECIFICE VIXSRC (Izolate)
# =============================================================================

def _get_tmdb_id_internal(imdb_id):
    """
    Conversie privată doar pentru VixSrc.
    Transformă tt12345 -> 550 (TMDb ID).
    """
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
    """
    Scraper VixSrc care folosește TMDb ID intern pentru a garanta succesul.
    Folosește metoda sigură de extragere JSON (numărare paranteze).
    """
    if ADDON.getSetting('use_vixsrc') == 'false':
        return None

    # 1. Conversie internă IMDb -> TMDb
    # (VixSrc merge mult mai bine cu structura URL bazată pe TMDb)
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    
    if not tmdb_id:
        log(f"[VIXSRC] Nu am putut găsi TMDb ID pentru {imdb_id}. Skip.")
        return None

    try:
        # 2. Construcția URL-ului (formatul care știm că merge)
        if content_type == 'movie':
            page_url = f"https://vixsrc.to/movie/{tmdb_id}"
        else:
            page_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}"

        log(f"[VIXSRC] Interogare (TMDb Mode): {page_url}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://vixsrc.to/'
        }
        
        r = requests.get(page_url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return None

        content = r.text
        
        # 3. Extragere sigură JSON (fără Regex complex, cu numărare)
        start_marker = "window.masterPlaylist"
        start_pos = content.find(start_marker)
        if start_pos == -1:
            return None
            
        json_start = content.find('{', start_pos)
        if json_start == -1:
            return None

        brace_count = 0
        json_end = -1
        
        for i, char in enumerate(content[json_start:], start=json_start):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1:
            return None
            
        json_str = content[json_start:json_end]

        # 4. Curățare JSON
        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_-]+)\s*:', r'\1"\2":', json_str)
        json_str = json_str.replace("'", '"')
        json_str = re.sub(r',(\s*})', r'\1', json_str)

        data = json.loads(json_str)

        base_url = data.get('url')
        params = data.get('params', {})
        
        if not base_url:
            return None
            
        params['h'] = '1'
        params['lang'] = 'en'
        sep = '&' if '?' in base_url else '?'
        final_url = f"{base_url}{sep}{urlencode(params)}"
        
        return {
            'name': 'VixMovie [HLS]',
            'url': final_url,
            'description': 'Direct Stream 1080p'
        }

    except Exception as e:
        log(f"[VIXSRC] Eroare: {e}", xbmc.LOGERROR)
        return None

# =============================================================================
# FUNCȚII SPECIFICE SOOTI (Izolate)
# =============================================================================
def scrape_sooti(imdb_id, content_type, season=None, episode=None):
    """
    Scraper Sooti care utilizează URL-ul complex cu configurație JSON în cale.
    """
    if ADDON.getSetting('use_sooti') == 'false':
        return None

    try:
        # Configurația JSON, așa cum apare în URL-ul din browser
        sooti_config_json = {
            "DebridServices": [
                {
                    "provider": "httpstreaming",
                    "http4khdhub": True,
                    "httpHDHub4u": True,
                    "httpUHDMovies": True,
                    "httpMoviesDrive": True,
                    "httpMKVCinemas": True
                }
            ],
            "Languages": [],
            "Scrapers": [],
            "IndexerScrapers": ["stremthru"],
            "minSize": 0,
            "maxSize": 200,
            "ShowCatalog": True,
            "DebridProvider": "httpstreaming"
        }
        
        # Codifică JSON-ul și adaugă-l la URL-ul de bază
        encoded_config = quote(json.dumps(sooti_config_json))
        base_sooti_url = f"https://sooti.info/{encoded_config}"

        if content_type == 'movie':
            api_url = f"{base_sooti_url}/stream/movie/{imdb_id}.json"
        else:
            api_url = f"{base_sooti_url}/stream/series/{imdb_id}:{season}:{episode}.json"

        log(f"[SOOTI] Interogare: {api_url}")

        # Folosim HEADERS globale din config (presupunand ca User-Agent e acolo)
        r = requests.get(api_url, headers=get_headers(), timeout=15, verify=False)
        
        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                found_streams = []
                for s in data['streams']:
                    # Sooti returneaza "name" deja cu [HS+] Sootio
                    # Ne asiguram ca name si url exista si adaugam eticheta
                    if s.get('url'):
                        s['name'] = s.get('name', 'Sooti') # Daca nu exista nume, punem default
                        if 'Sooti' not in s['name'] and '[HS+]' not in s['name']:
                             s['name'] = f"Sooti {s['name']}" # Prefix doar daca nu e deja acolo
                        
                        found_streams.append(s)
                return found_streams
        else:
            log(f"[SOOTI] Eroare HTTP {r.status_code}: {api_url}")
            return None

    except requests.exceptions.Timeout:
        log(f"[SOOTI] Eroare: Timeout la {api_url}", xbmc.LOGERROR)
    except requests.exceptions.ConnectionError as ce:
        log(f"[SOOTI] Eroare de Conexiune: {ce}", xbmc.LOGERROR)
    except Exception as e:
        log(f"[SOOTI] Eroare generală: {e}", xbmc.LOGERROR)
    return None

# =============================================================================
# FUNCȚIE SPECIFICĂ ROGFLIX
# =============================================================================
def scrape_rogflix(imdb_id, content_type, season=None, episode=None):
    """
    Scraper pentru Rogflix (VFlix) cu fix pentru headere.
    """
    if ADDON.getSetting('use_rogflix') == 'false':
        return None

    base_url = "https://rogflix.vflix.life/stremio/stream"
    
    try:
        if content_type == 'movie':
            api_url = f"{base_url}/movie/{imdb_id}.json"
        else:
            api_url = f"{base_url}/series/{imdb_id}:{season}:{episode}.json"

        log(f"[ROGFLIX] Interogare: {api_url}")
        
        # HEADERS PENTRU INTEROGARE API (Nu pentru redare încă)
        r = requests.get(api_url, headers=get_headers(), timeout=15, verify=False)

        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                found_streams = []
                
                # HEADERE OBLIGATORII PENTRU REDARE (Player)
                # Acestea vor fi atașate la link prin "|"
                stream_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Origin': 'https://rogflix.vflix.life',
                    'Referer': 'https://rogflix.vflix.life/'
                }
                
                for s in data['streams']:
                    url = s.get('url')
                    if url:
                        # Curățare nume (scoatem \n)
                        raw_name = s.get('name', 'Rogflix')
                        clean_name = raw_name.replace('\n', ' ')
                        extra_title = s.get('title', '')
                        if extra_title:
                            clean_name = f"{clean_name} - {extra_title}"
                        
                        s['name'] = clean_name
                        
                        # ATAȘARE HEADERE LA URL
                        # Exemplu: https://link.m3u8|User-Agent=...&Referer=...
                        s['url'] = f"{url}|{urlencode(stream_headers)}"
                        
                        found_streams.append(s)
                return found_streams
        else:
            log(f"[ROGFLIX] Eroare HTTP {r.status_code}")
            
    except Exception as e:
        log(f"[ROGFLIX] Eroare: {e}", xbmc.LOGERROR)
    
    return None

# =============================================================================
# FUNCȚIA PRINCIPALĂ (Aici nu am stricat nimic la providerii vechi)
# =============================================================================
def get_stream_data(imdb_id, content_type, season=None, episode=None, progress_callback=None):
    """
    Caută surse de streaming. Include Rogflix.
    """
    all_streams = []
    seen_urls = set()
    
    active_providers = []
    
    # Verificăm setările și construim lista
    if ADDON.getSetting('use_vixsrc') == 'true':
        active_providers.append(('vixsrc', 'VixSrc'))
    if ADDON.getSetting('use_sooti') == 'true':
        active_providers.append(('sooti', 'Sooti'))
    if ADDON.getSetting('use_rogflix') == 'true':      # <--- NOU
        active_providers.append(('rogflix', 'Rogflix'))
    if ADDON.getSetting('use_nuviostreams') == 'true':
        active_providers.append(('nuvio', 'Nuvio'))
    if ADDON.getSetting('use_webstreamr') == 'true':
        active_providers.append(('webstreamr', 'WebStreamr'))
    if ADDON.getSetting('use_vidzee') == 'true':
        active_providers.append(('vidzee', 'Vidzee'))
    
    total_providers = len(active_providers)
    
    for idx, (prov_id, prov_name) in enumerate(active_providers):
        percent = int(((idx + 1) / total_providers) * 80) + 10
        if progress_callback:
            progress_callback(percent, prov_name)
        
        log(f"[SCRAPER] Searching: {prov_name}")
        
        try:
            if prov_id == 'vixsrc':
                vix_stream = scrape_vixsrc(imdb_id, content_type, season, episode)
                if vix_stream:
                    all_streams.append(vix_stream)
                    seen_urls.add(vix_stream['url'])
                    log(f"[SCRAPER] ✓ {prov_name}: 1 sursă")
                    
            elif prov_id == 'sooti':
                sooti_streams = scrape_sooti(imdb_id, content_type, season, episode)
                if sooti_streams:
                    for s in sooti_streams:
                        if s.get('url') and s['url'] not in seen_urls:
                            all_streams.append(s)
                            seen_urls.add(s['url'])
                    log(f"[SCRAPER] ✓ {prov_name}: {len(sooti_streams)} surse")
            
            elif prov_id == 'rogflix': # <--- APELARE NOUĂ
                rog_streams = scrape_rogflix(imdb_id, content_type, season, episode)
                if rog_streams:
                    for s in rog_streams:
                        # Curățăm URL-ul pentru verificare unicitate
                        clean_url = s['url'].split('|')[0]
                        if clean_url not in seen_urls:
                            all_streams.append(s)
                            seen_urls.add(clean_url)
                    log(f"[SCRAPER] ✓ {prov_name}: {len(rog_streams)} surse")
                    
            elif prov_id == 'nuvio':
                _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'Nuvio', 
                                      imdb_id, content_type, season, episode, all_streams, seen_urls)
                                      
            elif prov_id == 'webstreamr':
                _scrape_json_provider("https://webstreamr.hayd.uk", 'stream', 'WebStreamr',
                                      imdb_id, content_type, season, episode, all_streams, seen_urls)
                                      
            elif prov_id == 'vidzee':
                _scrape_json_provider("https://vidzee.vflix.life", 'direct', 'Vidzee',
                                      imdb_id, content_type, season, episode, all_streams, seen_urls)
                                      
        except Exception as e:
            log(f"[SCRAPER] ✗ {prov_name}: {e}")

    log(f"[SCRAPER] Total: {len(all_streams)} surse")
    return all_streams


# =============================================================================
# HELPER PROVIDERI JSON (Nuvio, Vidzee, Webstreamr)
# =============================================================================
def _scrape_json_provider(base_url, pattern, label, imdb_id, content_type, season, episode, all_streams, seen_urls):
    """
    Helper generic MODIFICAT să atașeze headere pentru a preveni erorile 403.
    """
    try:
        if content_type == 'movie':
            if pattern == 'stream':
                api_url = f"{base_url}/stream/movie/{imdb_id}.json"
            else:
                api_url = f"{base_url}/movie/{imdb_id}.json"
        else:
            if pattern == 'stream':
                api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json"
            else:
                api_url = f"{base_url}/series/{imdb_id}:{season}:{episode}.json"

        # Interogare API
        r = requests.get(api_url, headers=get_headers(), timeout=15, verify=False)

        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                count = 0
                
                # Definim headerele de redare bazate pe URL-ul providerului
                stream_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': base_url + '/',
                    'Origin': base_url
                }

                for s in data['streams']:
                    url = s.get('url', '')
                    
                    # Verificăm dacă URL-ul curat (fără headere) a mai fost găsit
                    clean_check_url = url.split('|')[0]
                    
                    if url and clean_check_url not in seen_urls:
                        if 'name' not in s:
                            s['name'] = label
                        elif label not in s['name']:
                            s['name'] = f"{label} {s['name']}"
                        
                        # MODIFICARE: Atașăm headerele la URL
                        s['url'] = f"{url}|{urlencode(stream_headers)}"
                        
                        all_streams.append(s)
                        seen_urls.add(clean_check_url)
                        count += 1
                log(f"[SCRAPER] ✓ {label}: {count} surse")
        else:
            log(f"[SCRAPER] ✗ {label}: HTTP {r.status_code}")
            
    except requests.exceptions.Timeout:
        log(f"[SCRAPER] ✗ {label}: Timeout")
    except Exception as e:
        log(f"[SCRAPER] ✗ {label}: {e}")