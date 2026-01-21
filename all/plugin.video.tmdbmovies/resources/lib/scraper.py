import requests
import xbmc
import re
import json
import base64
import time
import random
import datetime
from urllib.parse import urlencode, quote, urlparse
from resources.lib.config import BASE_URL, API_KEY, ADDON, get_headers, get_random_ua
from resources.lib.utils import get_json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        return url
        
    headers = {
        'User-Agent': get_random_ua(),
        'Connection': 'keep-alive'
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
            f"https://sooti.click/{encoded_config}",
            f"https://sootiofortheweebs.midnightignite.me/{encoded_config}",
            f"https://sooti.info/{encoded_config}"
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
# SCRAPER HDHUB4U (V10 - UNIVERSAL RECURSIVE & NAMING FIX)
# =============================================================================

def _get_hdhub_base_url():
    """
    Găsește domeniul REAL folosind logica de timp din hdhub4u.tv (scriptul chkh).
    """
    try:
        # 1. Metoda API (Exact ca in browser)
        # Formula din JS: (Year*1000000) + (Month*10000) + (Day*100) + Hour + 1
        t = time.gmtime() # Folosim UTC sau Local? Site-ul pare sa ia local browser time.
        # Ajustam o marja de eroare, incercam ora curenta si ora trecuta
        
        seeds = []
        # Ora curenta
        seeds.append((t.tm_year * 1000000) + ((t.tm_mon) * 10000) + (t.tm_mday * 100) + t.tm_hour + 1)
        # Ora viitoare (pentru diferente de fus orar)
        seeds.append((t.tm_year * 1000000) + ((t.tm_mon) * 10000) + (t.tm_mday * 100) + t.tm_hour + 2)
        
        api_url = "https://cdn.hub4u.cloud/host/"
        
        for seed in seeds:
            try:
                params = {'v': seed}
                # log(f"[HDHUB-DOM] Checking API seed: {seed}")
                r = requests.get(api_url, params=params, headers=get_headers(), timeout=3, verify=False)
                
                if r.status_code == 200:
                    data = r.json()
                    if 'h' in data:
                        encoded_host = data['h']
                        # Decodare Base64
                        real_host = base64.b64decode(encoded_host).decode('utf-8')
                        final_url = f"https://{real_host}"
                        log(f"[HDHUB-DOM] API Success: {final_url}")
                        return final_url
            except:
                continue

    except Exception as e:
        log(f"[HDHUB-DOM] API logic error: {e}")

    # 2. Fallback HARDCODED (dacă API-ul pică, folosim ce știm că merge acum)
    # Aici pui link-ul care stii tu ca merge, ca ultima solutie
    log("[HDHUB-DOM] Using fallback domain.")
    return "https://new2.hdhub4u.fo" 


# =============================================================================
# SCRAPER HDHUB4U (V15 - ADDED MISSING DOMAINS + BRANCH LABEL)
# =============================================================================

def _extract_quality_from_string(text):
    """Extrage calitatea dintr-un string (titlu, nume fișier, etc.)"""
    if not text:
        return None
    text_lower = text.lower()
    if '2160p' in text_lower or '4k' in text_lower:
        return '4K'
    elif '1080p' in text_lower:
        return '1080p'
    elif '720p' in text_lower:
        return '720p'
    elif '480p' in text_lower:
        return '480p'
    return None

def _resolve_hdhub_redirect(url, depth=0, parent_title=None, branch_label=None):
    """
    Rezolvă lanțul complex HDHub4u și returnează TOATE link-urile video finale găsite.
    Returnează: list de tuple (host_name, url, file_title, quality, branch_label)
    """
    if not url or depth > 10: 
        return []
    
    # =================================================================
    # LISTA COMPLETĂ DE DOMENII FINALE (DIRECT PLAYABLE)
    # =================================================================
    final_domains = [
        'gdboka', 'workers.dev', 'cf-worker', 'fast-server',
        'polgen.buzz',           # love.polgen.buzz, etc
        'pixel.hubcdn.fans',     # pixel.hubcdn.fans/?id=...
        'fsl-buckets',           # cdn.fsl-buckets.life
        'fukggl',                # cdn.fukggl
    ]
    
    # 1. Verificare dacă URL-ul curent e final (direct playable)
    if any(x in url for x in final_domains):
        q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
        # Determinăm numele host-ului
        if 'polgen.buzz' in url:
            host = 'Polgen'
        elif 'pixel.hubcdn' in url:
            host = 'HubPixel'
        elif 'fsl-buckets' in url or 'fsl.gdboka' in url:
            host = 'FastServer'
        elif 'workers.dev' in url or 'cf-worker' in url:
            host = 'CFWorker'
        else:
            host = 'Direct'
        return [(host, url, parent_title, q, branch_label)]
    
    if 'pixeldrain' in url:
        pd_id = re.search(r'/u/([a-zA-Z0-9]+)', url)
        if pd_id:
            api_url = f"https://pixeldrain.dev/api/file/{pd_id.group(1)}"
            q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
            return [('PixelDrain', api_url, parent_title, q, branch_label)]

    if 'googleusercontent' in url:
        q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
        return [('Google', url, parent_title, q, branch_label)]

    # Domenii de procesat (wrapper/redirect pages)
    wrapper_domains = [
        'hubdrive', 'gadgetsweb', 'hubstream', 'drive', 'hubcloud', 'katmovie', 
        'gamerxyt', 'cryptoinsights', 'hblinks', 'inventoryidea', 'hubcdn', 'hubfiles'
    ]
    
    found_urls = []
    seen_urls = set()
    current_title = parent_title
    current_branch = branch_label

    if any(x in url for x in wrapper_domains):
        try:
            log(f"[HDHUB-RES] Step {depth} Processing: {url}")
            
            s = requests.Session()
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://new2.hdhub4u.fo/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            
            # BYPASS PREVENTIV
            if 'gamerxyt' in url or 'cryptoinsights' in url:
                domain = urlparse(url).netloc
                s.cookies.set("xyt", "2", domain=domain)
                s.cookies.set("xyt", "2", domain=".gamerxyt.com") 

            r = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
            content = r.text
            final_url = r.url
            
            # =========================================================
            # EXTRAGERE TITLU DIN HUBCLOUD
            # =========================================================
            if 'hubcloud' in url.lower() or 'hubcloud' in final_url.lower():
                title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    file_indicators = ['.mkv', '.mp4', '.avi', '.mov', 'x264', 'x265', 
                                       'hevc', 'bluray', 'webrip', 'webdl', 'hdrip', 
                                       'dvdrip', 'brrip', '1080p', '720p', '2160p', '4k']
                    if raw_title and len(raw_title) > 10:
                        if any(x in raw_title.lower() for x in file_indicators):
                            current_title = raw_title
                            log(f"[HDHUB-RES] ✓ Extracted HubCloud title: {current_title[:60]}...")

            # A. Verificare dacă redirect-ul final e direct playable
            if any(x in final_url for x in final_domains):
                q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                if 'polgen.buzz' in final_url:
                    return [('Polgen', final_url, current_title, q, current_branch)]
                elif 'pixel.hubcdn' in final_url:
                    return [('HubPixel', final_url, current_title, q, current_branch)]
                else:
                    return [('FastServer', final_url, current_title, q, current_branch)]
                    
            if 'googleusercontent' in final_url:
                q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                return [('Google', final_url, current_title, q, current_branch)]

            # BYPASS JS COOKIE
            if 'stck(' in content or 'Redirecting' in content:
                cookie_match = re.search(r"stck\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", content)
                if cookie_match:
                    c_n, c_v = cookie_match.groups()
                    log(f"[HDHUB-RES] Bypassing Cookie: {c_n}={c_v}")
                    s.cookies.set(c_n, c_v, domain=urlparse(url).netloc)
                    time.sleep(1.5)
                    r2 = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
                    content = r2.text
                    
                    if 'googleusercontent' in r2.url:
                        q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                        return [('Google', r2.url, current_title, q, current_branch)]

            # =========================================================
            # B. EXTRACTOR LINKURI - TOATE TIPURILE
            # =========================================================

            # Helper pentru adăugare URL
            def add_found(host, link):
                if link not in seen_urls:
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    found_urls.append((host, link, current_title, q, current_branch))
                    seen_urls.add(link)

            # 1. FastServer / Workers
            fsl_matches = re.findall(r'["\'](https?://[^"\']*(?:fsl\.gdboka|workers\.dev|cf-worker)[^"\']*)["\']', content)
            for link in fsl_matches:
                add_found('FastServer', link)

            # 2. PixelDrain
            px_matches = re.findall(r'["\'](https?://pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))', content)
            for full_link, file_id in px_matches:
                api_link = f"https://pixeldrain.dev/api/file/{file_id}"
                add_found('PixelDrain', api_link)
            
            # 3. Google
            goog_matches = re.findall(r'["\'](https?://video-downloads\.googleusercontent[^"\']*)["\']', content)
            for link in goog_matches:
                add_found('Google', link)

            # 4. CDN FSL/Fukggl
            cdn_matches = re.findall(r'["\'](https?://[^"\']*(?:cdn\.fsl|fsl-buckets|cdn\.fukggl)[^"\']*)["\']', content)
            for link in cdn_matches:
                add_found('CDN', link)
            
            # 5. HubCDN Download
            gp_matches = re.findall(r'["\'](https?://[^"\']*(?:gpdl\.hubcdn|hubcdn\.fans/dl)[^"\']*)["\']', content)
            for link in gp_matches:
                add_found('HubCDN', link)

            # =========================================================
            # 6. POLGEN.BUZZ (NOU!)
            # =========================================================
            polgen_matches = re.findall(r'["\'](https?://[a-zA-Z0-9.-]*polgen\.buzz[^"\']*)["\']', content)
            for link in polgen_matches:
                add_found('Polgen', link)
            
            # =========================================================
            # 7. PIXEL.HUBCDN.FANS (NOU!)
            # =========================================================
            pixelhub_matches = re.findall(r'["\'](https?://pixel\.hubcdn\.fans[^"\']*)["\']', content)
            for link in pixelhub_matches:
                add_found('HubPixel', link)

            # =========================================================
            # 8. Link-uri NEXT HOP (Ramuri recursive)
            # =========================================================
            next_hop_patterns = [
                r'href=["\'](https?://[^"\']*hubcloud[^"\']*/drive/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*gamerxyt\.com[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hblinks[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*inventoryidea[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubcdn\.fans/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubdrive[^"\']*/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*(?:gadgetsweb|hubstream)[^"\']*)["\']'
            ]

            for pattern in next_hop_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for next_link in matches:
                    if next_link != url and next_link not in seen_urls:
                        if 'hblinks' in next_link or 'inventoryidea' in next_link:
                            log(f"[HDHUB-RES] Found Critical Branch: {next_link}")
                        
                        # Propagăm current_title ȘI current_branch
                        sub_results = _resolve_hdhub_redirect(next_link, depth + 1, current_title, current_branch)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])

            # C. JS Redirect
            js_redirect = re.search(r'window\.location\.href\s*=\s*["\'](https?://[^"\']+)["\']', content)
            if js_redirect:
                sub = _resolve_hdhub_redirect(js_redirect.group(1), depth + 1, current_title, current_branch)
                found_urls.extend(sub)

        except Exception as e:
            log(f"[HDHUB-RES] Error on {url}: {e}")
            pass
            
    # Curățare duplicate
    unique_results = []
    seen_final = set()
    for item in found_urls:
        if item[1] not in seen_final:
            unique_results.append(item)
            seen_final.add(item[1])
            
    return unique_results


def scrape_hdhub4u(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_hdhub4u') == 'false':
        return None

    try:
        base_url = _get_hdhub_base_url()
        
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        
        api_url = "https://search.pingora.fyi/collections/post/documents/search"
        today = datetime.date.today().isoformat()
        
        params = {
            'q': clean_search,
            'query_by': 'post_title,category,stars,director,imdb_id',
            'sort_by': 'sort_by_date:desc',
            'limit': 15,
            'analytics_tag': today
        }
        
        api_headers = {
            'User-Agent': get_random_ua(),
            'Origin': base_url,
            'Referer': f"{base_url}/"
        }
        
        r = requests.get(api_url, params=params, headers=api_headers, timeout=10, verify=False)
        movie_url = None
        
        if r.status_code == 200:
            data = r.json()
            if 'hits' in data and data['hits']:
                for hit in data['hits']:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink')
                    raw_title = doc.get('post_title')
                    
                    if not raw_link or not raw_title: continue
                    parsed_link = urlparse(raw_link)
                    curr_link = f"{base_url}{parsed_link.path}"
                    
                    if clean_search.lower() in raw_title.lower():
                        if year_query and str(year_query) in raw_title:
                            movie_url = curr_link
                            break
                        if not movie_url: movie_url = curr_link
        
        if not movie_url:
            log(f"[HDHUB] No results from API.")
            return None
            
        log(f"[HDHUB] Entering: {movie_url}")
        r_movie = requests.get(movie_url, headers=get_headers(), timeout=15, verify=False)
        movie_html = r_movie.text
        
        # Titlul din pagina principală (FALLBACK)
        full_title_match = re.search(r'<h1 class="page-title">.*?<span.*?>(.*?)</span>', movie_html, re.DOTALL)
        fallback_title = full_title_match.group(1).strip() if full_title_match else title_query

        # 4. Extragere Linkuri Principale
        link_pattern = r'<a\s+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>'
        all_links = re.findall(link_pattern, movie_html)
        
        streams = []
        
        for link, text in all_links:
            text_lower = text.lower()
            
            # Curățăm textul de HTML tags
            clean_text = re.sub(r'<[^>]+>', '', text).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            # Identificare Calitate inițială din textul linkului (FALLBACK)
            initial_quality = "SD"
            if '2160p' in text_lower or '4k' in text_lower: initial_quality = "4K"
            elif '1080p' in text_lower: initial_quality = "1080p"
            elif '720p' in text_lower: initial_quality = "720p"
            
            # FILTRARE STRICTĂ (Doar HD/4K)
            if initial_quality == "SD": continue

            is_valid = False
            if any(x in link for x in ['hubdrive', 'gadgetsweb', 'drive', 'hubstream', 'hdstream4u']):
                is_valid = True
            elif any(x in text_lower for x in ['download', 'watch', 'mb]', 'gb]']):
                if 'http' in link and len(link) > 25 and 'facebook' not in link:
                    is_valid = True
            
            if is_valid:
                # =========================================================
                # Creăm branch_label din textul original
                # Ex: "720p HEVC [960MB]", "1080p x264 [3.2GB]"
                # =========================================================
                branch_label = clean_text.replace('Download', '').replace('Watch', '').replace('Links', '').replace('Online', '').strip()
                branch_label = re.sub(r'\s+', ' ', branch_label)
                
                log(f"[HDHUB] Processing branch: {branch_label} -> {link[:50]}...")
                
                # Rezolvare - pasăm branch_label de la început
                resolved_links = _resolve_hdhub_redirect(link, 0, None, branch_label)
                
                if resolved_links:
                    for host_name, final_url, file_title, file_quality, returned_branch in resolved_links:
                        if 'http' in final_url:
                            # CALITATE: file_quality (HubCloud) > initial_quality (text link)
                            final_quality = file_quality if file_quality else initial_quality
                            
                            # TITLU: file_title (HubCloud) > fallback_title
                            display_title = file_title if file_title else fallback_title
                            
                            # =========================================
                            # NUME SURSĂ: "HostName | 720p HEVC [960MB]"
                            # =========================================
                            if returned_branch:
                                display_name = f"{host_name} | {returned_branch}"
                            else:
                                display_name = host_name
                            
                            streams.append({
                                'name': display_name,
                                'url': build_stream_url(final_url),
                                'quality': final_quality,
                                'title': display_title,
                                'info': returned_branch if returned_branch else ""
                            })

        log(f"[HDHUB] Found {len(streams)} streams.")
        return streams

    except Exception as e:
        log(f"[HDHUB] Error: {e}", xbmc.LOGERROR)
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
# MAIN ORCHESTRATION FUNCTION (MODIFICATĂ PENTRU SMART RETRY + CANCEL)
# =============================================================================
def get_stream_data(imdb_id, content_type, season=None, episode=None, progress_callback=None, target_providers=None):
    """
    Orchestrează scanarea.
    Returns:
        (all_streams, failed_providers, was_canceled)
    """
    all_streams = []
    seen_urls = set()
    failed_providers = [] 
    was_canceled = False # <--- Flag nou
    
    # --- INSEREAZA CODUL DE MAI JOS AICI ---
    extra_title = ""
    extra_year = ""
    if ADDON.getSetting('use_hdhub4u') == 'true':
        try:
            url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
            data = get_json(url)
            res = data.get('movie_results', []) or data.get('tv_results', [])
            if res:
                extra_title = res[0].get('title') or res[0].get('name')
                dt = res[0].get('release_date') or res[0].get('first_air_date')
                extra_year = dt[:4] if dt else ""
        except: pass
    # --- SFARSIT INSERTIE ---

    # Mapare completă ID -> (Nume, Funcție de execuție)
    providers_map = {
        'sooti': ('Sooti', lambda: scrape_sooti(imdb_id, content_type, season, episode)),
        'nuvio': ('Nuvio', lambda: _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'Nuvio', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'webstreamr': ('WebStreamr', lambda: _scrape_json_provider("https://webstreamr.hayd.uk", 'stream', 'WebStreamr', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode)),
        'rogflix': ('Rogflix', lambda: scrape_rogflix(imdb_id, content_type, season, episode)),
        'vega': ('Vega', lambda: _scrape_json_provider("https://vega.vflix.life", 'stream', 'Vega', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'streamvix': ('StreamVix', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamVix', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'vidzee': ('Vidzee', lambda: _scrape_json_provider("https://vidzee.vflix.life", 'direct', 'Vidzee', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'hdhub4u': ('HDHub4u', lambda: scrape_hdhub4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year))
    }

    to_run = []
    
    if target_providers is not None:
        log(f"[SCRAPER] Retry mode activat pentru: {target_providers}")
        for pid in target_providers:
            if pid in providers_map:
                setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
                if ADDON.getSetting(setting_id) == 'true':
                    pname, pfunc = providers_map[pid]
                    to_run.append((pid, pname, pfunc))
    else:
        for pid, (pname, pfunc) in providers_map.items():
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if ADDON.getSetting(setting_id) == 'true':
                to_run.append((pid, pname, pfunc))
    
    total = len(to_run)
    if total == 0:
        return [], [], False # <--- Returnăm 3 valori

    for idx, (pid, pname, pfunc) in enumerate(to_run):
        if progress_callback: 
            # Verificăm dacă userul a dat Cancel
            should_continue = progress_callback(int(((idx+1)/total)*80)+10, pname)
            if should_continue is False: 
                log(f"[SCRAPER] Căutare oprită de utilizator (Cancel).")
                was_canceled = True # <--- Setăm flag-ul
                break 
        
        try:
            result = pfunc()
            
            if result:
                if isinstance(result, list):
                    for item in result:
                        cl = item['url'].split('|')[0]
                        if cl not in seen_urls:
                            item['provider_id'] = pid
                            all_streams.append(item)
                            seen_urls.add(cl)
                elif isinstance(result, dict):
                    cl = result['url'].split('|')[0]
                    if cl not in seen_urls:
                        result['provider_id'] = pid
                        all_streams.append(result)
                        seen_urls.add(cl)
                        
        except Exception as e:
            log(f"[SCRAPER] ✗ {pname} a eșuat (Timeout/Eroare): {e}", xbmc.LOGWARNING)
            failed_providers.append(pid)

    # Returnăm Flag-ul de anulare la final
    return all_streams, failed_providers, was_canceled