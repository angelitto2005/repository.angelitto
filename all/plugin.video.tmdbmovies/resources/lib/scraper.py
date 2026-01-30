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
# =============================================================================
# LOGGING CU VERIFICARE SETĂRI
# =============================================================================
_debug_cache = None

def _is_debug_enabled():
    """Verifică dacă debug-ul e activat (cu cache pentru performanță)."""
    global _debug_cache
    if _debug_cache is None:
        try:
            _debug_cache = ADDON.getSetting('debug_enabled') == 'true'
        except:
            _debug_cache = True  # Default on dacă nu poate citi setarea
    return _debug_cache

def reset_debug_cache():
    """Resetează cache-ul debug (apelat când se schimbă setările)."""
    global _debug_cache
    _debug_cache = None

def log(msg, level=xbmc.LOGINFO):
    """
    Loghează mesaje respectând setarea debug din addon.
    - LOGERROR și LOGWARNING: se loghează MEREU (erori importante)
    - LOGINFO și LOGDEBUG: doar dacă debug e activat în setări
    """
    # Erorile și warning-urile se loghează mereu
    if level in (xbmc.LOGERROR, xbmc.LOGWARNING):
        xbmc.log(f"[tmdbmovies] {msg}", level)
        return
    
    # Info/Debug doar dacă e activat
    if _is_debug_enabled():
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

def scrape_vixsrc(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_vixsrc') == 'false':
        return None

    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None

    try:
        # =========================================================
        # CONSTRUIRE TITLU PENTRU LABEL 2 (Nume + An + Episod)
        # =========================================================
        base_name = title_query if title_query else f"TMDb:{tmdb_id}"
        
        # Adăugăm anul dacă există
        if year_query:
            display_name = f"[B][COLOR FFFDBD01]{base_name} ({year_query})[/COLOR][/B]"
        else:
            display_name = base_name

        # Dacă e serial, adăugăm S01E01 la final
        if content_type == 'tv' and season and episode:
            display_name = f"{display_name} [B][COLOR FFFDBD01]S{int(season):02d}E{int(episode):02d}[/COLOR][/B]"

        base_ref = 'https://vixsrc.to/'
        if content_type == 'movie':
            page_url = f"https://vixsrc.to/movie/{tmdb_id}"
        else:
            page_url = f"https://vixsrc.to/tv/{tmdb_id}/{season}/{episode}"

        log(f"[VIXSRC] Interogare: {page_url}")

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
        
        final_url_with_headers = build_stream_url(final_url, referer=base_ref)
        
        return {
            'name': 'VixSrc | HLS',
            'url': final_url_with_headers,
            'title': display_name, # Afișează: "Nume Film (2024)" sau "Nume Serial (2024) S01E01"
            'quality': '1080p'
        }
    except Exception as e:
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
            f"https://sooti.info/{encoded_config}",
            f"https://sootiofortheweebs.midnightignite.me/{encoded_config}"
        ]

        for base_sooti_url in base_urls:
            if content_type == 'movie':
                api_url = f"{base_sooti_url}/stream/movie/{imdb_id}.json"
            else:
                api_url = f"{base_sooti_url}/stream/series/{imdb_id}:{season}:{episode}.json"

            log(f"[SOOTI] Încerc oglinda: {base_sooti_url[:30]}...")

            try:
                r = requests.get(api_url, headers=get_headers(), timeout=10, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    success_any = True
                    if 'streams' in data and data['streams']:
                        found_streams = []
                        for s in data['streams']:
                            if s.get('url'):
                                # --- MODIFICARE ALIAS UNDERCOVER (FIX PENTRU "SOOTIO") ---
                                original_name = s.get('name', 'Sooti')
                                
                                # PASUL 1: Înlocuim explicit "Sootio" (cu "o" la final) primul!
                                # Astfel "Sootio" devine "SlowNow", fără "o" în plus.
                                safe_name = original_name.replace('Sootio', 'SlowNow')
                                
                                # PASUL 2: Înlocuim și varianta simplă "Sooti" (pentru cazurile normale)
                                safe_name = safe_name.replace('Sooti', 'SlowNow')
                                
                                # Construim numele final
                                # Verificăm dacă noul nume conține deja Aliasul sau tag-ul [HS+]
                                if 'SlowNow' not in safe_name and '[HS+]' not in safe_name: 
                                    s['name'] = f"SlowNow {safe_name}"
                                else:
                                    s['name'] = safe_name
                                # -----------------------------------
                                
                                if 'vixsrc' in s['url'] and '|' not in s['url']:
                                    s['url'] = build_stream_url(s['url'], referer="https://vixsrc.to/")
                                elif '|' not in s['url']:
                                    s['url'] = build_stream_url(s['url'])
                                    
                                found_streams.append(s)
                        
                        log(f"[SOOTI] ✓ Succes! {len(found_streams)} surse găsite.")
                        return found_streams
            except Exception as e:
                log(f"[SOOTI] Oglinda a eșuat ({e}). Trec la următoarea...")
                last_exception = e
                continue

    except Exception as e:
        log(f"[SOOTI] Eroare critică: {e}", xbmc.LOGERROR)
    
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
    """
    Extrage calitatea video dintr-un string.
    PRIORITATE: Calitatea care apare IMEDIAT după an (2024, 2025, etc.)
    DS4K, HDR4K și alte variante FALSE sunt COMPLET IGNORATE.
    """
    if not text:
        return None
    
    t = text.lower()
    
    # =================================================================
    # METODA 1 (PRIORITARĂ): Caută AN.CALITATE sau AN-CALITATE
    # Exemplu: "2025.720p" sau "2025-1080p" sau "2025.4K"
    # =================================================================
    
    # Captează ce vine IMEDIAT după an (primul segment)
    after_year_match = re.search(r'(?:19|20)\d{2}[\.\-\s_]+([^\.\-\s_]+)', t)
    if after_year_match:
        first_segment = after_year_match.group(1).lower()
        
        # Verifică calități standard
        if first_segment.startswith('2160p'):
            log(f"[QUALITY] Found 2160p after year -> 4K")
            return '4K'
        if first_segment.startswith('1080p'):
            log(f"[QUALITY] Found 1080p after year")
            return '1080p'
        if first_segment.startswith('720p'):
            log(f"[QUALITY] Found 720p after year")
            return '720p'
        if first_segment.startswith('480p'):
            log(f"[QUALITY] Found 480p after year")
            return '480p'
        if first_segment.startswith('360p'):
            log(f"[QUALITY] Found 360p after year")
            return '360p'
        # 4K trebuie să fie EXACT "4k" la început, nu parte din alt cuvânt
        if first_segment == '4k' or first_segment.startswith('4k-') or first_segment.startswith('4k.'):
            log(f"[QUALITY] Found 4K after year")
            return '4K'
    
    # =================================================================
    # METODA 2 (FALLBACK): Caută oriunde în text
    # IMPORTANT: 720p și 1080p au PRIORITATE față de 4K!
    # =================================================================
    
    # Verifică calitățile numerice ÎN ORDINE DE PRIORITATE
    # (evităm să găsim 4K din DS4K înainte de 720p real)
    if '720p' in t:
        log(f"[QUALITY] Fallback: found 720p in text")
        return '720p'
    
    if '1080p' in t:
        log(f"[QUALITY] Fallback: found 1080p in text")
        return '1080p'
    
    if '2160p' in t:
        log(f"[QUALITY] Fallback: found 2160p in text -> 4K")
        return '4K'
    
    if '480p' in t:
        log(f"[QUALITY] Fallback: found 480p in text")
        return '480p'
    
    if '360p' in t:
        log(f"[QUALITY] Fallback: found 360p in text")
        return '360p'
    
    # 4K DOAR dacă nu e precedat de literă (evită DS4K, HDR4K, SDR4K)
    # Pattern: spațiu/punct/început + 4k + non-literă
    if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', t):
        log(f"[QUALITY] Fallback: found standalone 4K")
        return '4K'
    
    # UHD = 4K
    if 'uhd' in t or 'ultrahd' in t:
        log(f"[QUALITY] Fallback: found UHD -> 4K")
        return '4K'
    
    log(f"[QUALITY] No quality found in: {t[:50]}")
    return None


def _identify_host_from_url(url):
    """Identifică numele host-ului din URL"""
    url_lower = url.lower()
    
    if 'r2.cloudflarestorage.com' in url_lower:
        return 'FSL-V2'
    elif 'r2.dev' in url_lower or 'pub-' in url_lower:
        return 'Flash'
    elif 'gpdl' in url_lower and 'hubcdn' in url_lower:
        return 'HubCDN'
    elif 'fsl-lover' in url_lower:
        return 'FSL-Lover'
    elif 'fsl-buckets' in url_lower or 'fsl.gdboka' in url_lower:
        return 'CDN'
    elif 'gdboka' in url_lower:
        return 'FastServer'
    elif 'pixel.hubcdn' in url_lower:
        return 'HubPixel'
    elif 'pixeldrain' in url_lower:
        return 'PixelDrain'
    elif 'polgen.buzz' in url_lower:
        return 'Flash'
    elif 'workers.dev' in url_lower or 'cloudserver' in url_lower:
        return 'CFWorker'
    elif 'googleusercontent' in url_lower:
        return 'Google'
    elif 'hubcdn' in url_lower:
        return 'HubCDN'
    else:
        return 'Direct'


def _is_video_url(url):
    """Verifică dacă un URL pare a fi un link video direct."""
    if not url or not url.startswith('http'):
        return False
    
    url_lower = url.lower()
    
    # Domenii blocate
    blocked_domains = [
        'googletagmanager.com', 'google-analytics.com', 'googlesyndication.com',
        'doubleclick.net', 'facebook.com', 'twitter.com', 'instagram.com',
        'yandex.ru', 'mc.yandex', 'metrika', 'analytics',
        'gadgetsweb', 'arc.io', 
        'gravatar.com', 'wp.com', 'wordpress.com',
        'disqus.com', 'addthis.com', 'sharethis.com',
        'cloudflare.com/cdn-cgi', 'challenges.cloudflare.com',
        'recaptcha', 'captcha', 'hcaptcha',
        'ads.', 'ad.', 'adserver', 'adservice',
        'tracker.', 'tracking.', 'pixel.facebook', 'pixel.ads',
        'gtag/js', 'gtm.js', 'ga.js',
        'bit.ly', 't.me', 'telegram',
    ]
    
    if any(blocked in url_lower for blocked in blocked_domains):
        return False
    
    # Exclude fișiere archive și resurse (DAR nu vcloud.zip!)
    if any(ext in url_lower for ext in ['.zip', '.rar', '.7z', '.tar', '.gz']):
        if 'vcloud.zip' not in url_lower:
            return False
    
    # Exclude resurse web
    if any(x in url_lower for x in ['/admin', '/login', '/signup', '/register', '/account', 
                                      'javascript:', 'mailto:', '#', '/page/', '/category/',
                                      '.css', '.js?', '.png', '.jpg', '.jpeg', '.gif', '.svg',
                                      '.woff', '.woff2', '.ttf', '.eot', '.ico']):
        return False
    
    # Verifică extensii video directe
    video_extensions = ['.mkv', '.mp4', '.avi', '.mov', '.webm', '.m3u8', '.ts']
    if any(ext in url_lower for ext in video_extensions):
        return True
    
    # Verifică parametri token/id
    if '?token=' in url_lower or '&token=' in url_lower:
        if 'google' not in url_lower and 'facebook' not in url_lower:
            return True
    if '?id=' in url_lower or '&id=' in url_lower:
        if 'google' not in url_lower and 'facebook' not in url_lower:
            return True
    
    # Domenii de hosting video cunoscute
    video_hosts = [
        'pixeldrain', 'pixel.hubcdn', 'hubcdn.fans/dl', 'gpdl', 'r2.dev', 'pub-',
        'r2.cloudflarestorage.com',  # FSL V2
        'fsl-buckets', 'fsl-lover', 'fsl.gdboka', 'gdboka', 'polgen.buzz',
        'workers.dev', 'cloudserver', 'googleusercontent', 'fukggl',
        'fastserver', 'cf-worker'
    ]
    if any(host in url_lower for host in video_hosts):
        return True
    
    return False


def _resolve_hdhub_redirect(url, depth=0, parent_title=None, branch_label=None):
    """
    Rezolvă lanțul complex HDHub4u/MKVCinemas și returnează TOATE link-urile video finale găsite.
    """
    if not url or depth > 10: 
        return []
    
    url_lower = url.lower()
    
    # =================================================================
    # EXCLUDERE DOMENII PROBLEMATICE
    # =================================================================
    blocked_domains = [
        'gadgetsweb',
        'googletagmanager.com', 'google-analytics.com', 'gtag/js',
        'googlesyndication.com', 'doubleclick.net',
        'facebook.com', 'twitter.com', 'instagram.com',
        'yandex.ru', 'mc.yandex', 'metrika',
        'arc.io', 'ads.', 'adserver',
        'recaptcha', 'captcha', 'hcaptcha', 'challenges.cloudflare',
        'disqus.com', 'gravatar.com',
        'filepress.cloud', 'new4.filepress',
        'bit.ly', 'telegram', 't.me',
    ]
    
    if any(blocked in url_lower for blocked in blocked_domains):
        log(f"[HDHUB-RES] Skipping blocked domain: {url[:60]}...")
        return []
    
    # Exclude fișiere archive și resurse web
    if any(ext in url_lower for ext in ['.zip', '.rar', '.7z', '.tar', '.css', '.js?', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff']):
        # EXCEPȚIE: vcloud.zip e un domeniu valid!
        if 'vcloud.zip' not in url_lower:
            return []
    
    # Verifică dacă URL-ul curent e deja un link video final
    if _is_video_url(url):
        wrapper_indicators = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 
                              'hblinks', 'inventoryidea', 'hubdrive',
                              'hubstream', '/drive/', '/file/', 'vcloud.zip']
        
        is_wrapper = any(w in url_lower for w in wrapper_indicators)
        
        if not is_wrapper:
            host = _identify_host_from_url(url)
            q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
            
            if 'pixeldrain' in url_lower:
                pd_id = re.search(r'/u/([a-zA-Z0-9]+)', url)
                if pd_id:
                    api_url = f"https://pixeldrain.dev/api/file/{pd_id.group(1)}"
                    return [('PixelDrain', api_url, parent_title, q, branch_label)]
            
            return [(host, url, parent_title, q, branch_label)]
    
    # =================================================================
    # DOMENII WRAPPER
    # =================================================================
    wrapper_domains = [
        'hubdrive', 'hubstream', 'drive', 'hubcloud', 'katmovie', 
        'gamerxyt', 'cryptoinsights', 'hblinks', 'inventoryidea', 'hubcdn', 
        'hubfiles', 'carnewz',
        'vcloud.zip',  # VCloud
    ]
    
    found_urls = []
    seen_urls = set()
    current_title = parent_title
    current_branch = branch_label

    if any(x in url_lower for x in wrapper_domains):
        try:
            log(f"[HDHUB-RES] Step {depth} Processing: {url}")
            
            s = requests.Session()
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://mkvcinemas.gd/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            
            # Cookie bypass
            if any(x in url for x in ['gamerxyt', 'cryptoinsights', 'carnewz']):
                domain = urlparse(url).netloc
                s.cookies.set("xyt", "2", domain=domain)
                s.cookies.set("xyt", "2", domain=".gamerxyt.com") 

            r = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
            content = r.text
            final_url = r.url
            
            # =================================================================
            # VCLOUD SPECIAL: Extrage URL din JavaScript "var url = '...'"
            # =================================================================
            if 'vcloud.zip' in url_lower or 'vcloud.zip' in final_url.lower():
                js_url_match = re.search(r"var\s+url\s*=\s*['\"]([^'\"]+)['\"]", content)
                if js_url_match:
                    extracted_url = js_url_match.group(1)
                    log(f"[HDHUB-RES] ✓ VCloud extracted URL: {extracted_url[:60]}...")
                    
                    # Urmează acest URL (de obicei gamerxyt.com)
                    if extracted_url not in seen_urls:
                        seen_urls.add(extracted_url)
                        sub_results = _resolve_hdhub_redirect(extracted_url, depth + 1, current_title, current_branch)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
                else:
                    log(f"[HDHUB-RES] VCloud: No JS URL found in page")
            
            # Extragere titlu din HubCloud / VCloud
            if any(x in url_lower or x in final_url.lower() for x in ['hubcloud', 'vcloud']):
                title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    file_indicators = ['.mkv', '.mp4', '.avi', '.mov', 'x264', 'x265', 
                                       'hevc', 'bluray', 'webrip', 'webdl', 'hdrip', 
                                       'dvdrip', 'brrip', '1080p', '720p', '2160p', '4k']
                    if raw_title and len(raw_title) > 10:
                        if any(x in raw_title.lower() for x in file_indicators):
                            current_title = raw_title
                            log(f"[HDHUB-RES] ✓ Extracted title: {current_title[:60]}...")

            # Verifică dacă redirect-ul final e un link video
            if _is_video_url(final_url):
                wrapper_check = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 'vcloud']
                if not any(w in final_url.lower() for w in wrapper_check):
                    host = _identify_host_from_url(final_url)
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    return [(host, final_url, current_title, q, current_branch)]

            # Bypass JS Cookie (stck function)
            if 'stck(' in content or 'Redirecting' in content:
                cookie_match = re.search(r"stck\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", content)
                if cookie_match:
                    c_n, c_v = cookie_match.groups()
                    log(f"[HDHUB-RES] Bypassing Cookie: {c_n}={c_v}")
                    s.cookies.set(c_n, c_v, domain=urlparse(url).netloc)
                    time.sleep(1.5)
                    r2 = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
                    content = r2.text

            # =========================================================
            # EXTRACTOR GENERIC
            # =========================================================
            
            def add_found(link):
                if link in seen_urls:
                    return
                
                link_lower = link.lower()
                
                blocked = [
                    'googletagmanager', 'google-analytics', 'gtag/js',
                    'facebook.com', 'twitter.com', 'yandex', 'metrika',
                    'gadgetsweb', 'arc.io', 'disqus', 'gravatar',
                    'recaptcha', 'captcha', 'cloudflare.com/cdn-cgi',
                    '.css', '.js?v=', '.png', '.jpg', '.gif', '.svg', '.ico',
                    'filepress.cloud', 'new4.filepress',
                    'bit.ly', 't.me', 'telegram'
                ]
                if any(b in link_lower for b in blocked):
                    return
                    
                if not _is_video_url(link):
                    return
                
                wrapper_check = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 
                                '/drive/', '/file/', 'hblinks', 'inventoryidea', 'vcloud.zip']
                if any(w in link_lower for w in wrapper_check):
                    return
                
                host = _identify_host_from_url(link)
                q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                
                if 'pixeldrain' in link_lower:
                    pd_id = re.search(r'/u/([a-zA-Z0-9]+)', link)
                    if pd_id:
                        api_link = f"https://pixeldrain.dev/api/file/{pd_id.group(1)}"
                        if api_link not in seen_urls:
                            found_urls.append(('PixelDrain', api_link, current_title, q, current_branch))
                            seen_urls.add(api_link)
                            log(f"[HDHUB-RES] ✓ Found: PixelDrain -> {api_link[:60]}...")
                    return
                
                found_urls.append((host, link, current_title, q, current_branch))
                seen_urls.add(link)
                log(f"[HDHUB-RES] ✓ Found: {host} -> {link[:60]}...")

            # Extrage toate link-urile din href
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', content)
            
            for href in all_hrefs:
                if href.startswith('//'):
                    href = 'https:' + href
                elif href.startswith('/') and not href.startswith('//'):
                    continue
                
                if href.startswith('http'):
                    add_found(href)
            
            # Extrage link-uri din JavaScript
            js_patterns = [
                r'["\'](https?://[^"\']*\?token=[^"\']*)["\']',
                r'["\'](https?://[^"\']*\?id=[^"\']*)["\']',
                r'["\'](https?://[^"\']*\.mkv[^"\']*)["\']',
                r'["\'](https?://[^"\']*\.mp4[^"\']*)["\']',
                r'["\'](https?://[^"\']*r2\.dev[^"\']*)["\']',
                r'["\'](https?://[^"\']*r2\.cloudflarestorage\.com[^"\']*)["\']',  # NOU! FSL v2
                r'["\'](https?://[^"\']*pixeldrain[^"\']*)["\']',
                r'["\'](https?://[^"\']*pixel\.hubcdn[^"\']*)["\']',
                r'["\'](https?://[^"\']*gpdl[^"\']*hubcdn[^"\']*)["\']',  # NOU! gpdl2.hubcdn.fans
                r'["\'](https?://[^"\']*fsl-[^"\']*)["\']',
                r'["\'](https?://[^"\']*gdboka[^"\']*)["\']',
                r'["\'](https?://[^"\']*polgen\.buzz[^"\']*)["\']',
            ]
            
            for pattern in js_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    add_found(match)

            # =========================================================
            # NEXT HOP PATTERNS
            # =========================================================
            next_hop_patterns = [
                r'href=["\'](https?://[^"\']*hubcloud[^"\']*/drive/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*vcloud\.zip[^"\']+)["\']',
                r'href=["\'](https?://[^"\']*gamerxyt\.com[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hblinks[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*inventoryidea[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubcdn\.fans/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubdrive[^"\']*/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubstream[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*carnewz\.site[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*cryptoinsights\.site[^"\']*)["\']',
            ]

            for pattern in next_hop_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for next_link in matches:
                    if next_link != url and next_link not in seen_urls:
                        if '/admin' in next_link or '/login' in next_link:
                            continue
                        
                        seen_urls.add(next_link)
                        sub_results = _resolve_hdhub_redirect(next_link, depth + 1, current_title, current_branch)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])

            # JS Redirect
            js_redirect = re.search(r'window\.location\.href\s*=\s*["\'](https?://[^"\']+)["\']', content)
            if js_redirect:
                redirect_url = js_redirect.group(1)
                if redirect_url not in seen_urls:
                    seen_urls.add(redirect_url)
                    sub = _resolve_hdhub_redirect(redirect_url, depth + 1, current_title, current_branch)
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
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        movie_url = None
        search_terms = [t.lower() for t in clean_search.split() if len(t) > 2]
        
        # =========================================================
        # METHOD 1: Pingora API
        # =========================================================
        try:
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
            
            r = requests.get(api_url, params=params, headers=api_headers, timeout=8, verify=False)
            
            if r.status_code == 200:
                data = r.json()
                if 'hits' in data and data['hits']:
                    for hit in data['hits']:
                        doc = hit.get('document', {})
                        raw_link = doc.get('permalink')
                        raw_title = doc.get('post_title', '').lower()
                        
                        if not raw_link: 
                            continue
                        
                        matches = sum(1 for term in search_terms if term in raw_title)
                        if matches < len(search_terms):
                            continue
                        
                        parsed_link = urlparse(raw_link)
                        curr_link = f"{base_url}{parsed_link.path}"
                        
                        if year_query and str(year_query) in raw_title:
                            movie_url = curr_link
                            log(f"[HDHUB] API match with year: {curr_link}")
                            break
                        if not movie_url: 
                            movie_url = curr_link
                            log(f"[HDHUB] API match: {curr_link}")
                                
        except Exception as e:
            log(f"[HDHUB] Pingora API failed: {e}")
        
        # =========================================================
        # METHOD 2: Site native search (FALLBACK)
        # =========================================================
        if not movie_url:
            try:
                search_url = f"{base_url}/search.html?q={quote(clean_search)}&page=1"
                log(f"[HDHUB] Fallback search: {search_url}")
                
                r_search = requests.get(search_url, headers=get_headers(), timeout=15, verify=False)
                
                if r_search.status_code == 200:
                    search_html = r_search.text
                    
                    direct_links = re.findall(r'href=["\'](' + re.escape(base_url) + r'/[a-z0-9-]+-\d{4}[^"\']*)["\']', search_html, re.IGNORECASE)
                    
                    rel_links = re.findall(r'href=["\'](/[a-z0-9-]+-(?:20\d{2}|19\d{2})[^"\']*)["\']', search_html, re.IGNORECASE)
                    for rel in rel_links:
                        full_url = base_url + rel
                        if full_url not in direct_links:
                            direct_links.append(full_url)
                    
                    exclude_patterns = ['/category/', '/page/', '/tag/', '/author/', '/search', '/wp-', '/feed/', '.jpg', '.png']
                    
                    for link in direct_links:
                        link_lower = link.lower()
                        if any(ex in link_lower for ex in exclude_patterns):
                            continue
                        
                        matches = sum(1 for term in search_terms if term in link_lower)
                        if matches < len(search_terms):
                            continue
                        
                        if year_query and str(year_query) in link:
                            movie_url = link
                            log(f"[HDHUB] Fallback match with year: {link}")
                            break
                        if not movie_url:
                            movie_url = link
                            log(f"[HDHUB] Fallback match: {link}")
                            break
                                
            except Exception as e:
                log(f"[HDHUB] Fallback search failed: {e}")
        
        if not movie_url:
            log(f"[HDHUB] No results found for: {clean_search}")
            return None
            
        log(f"[HDHUB] Entering: {movie_url}")
        r_movie = requests.get(movie_url, headers=get_headers(), timeout=15, verify=False)
        movie_html = r_movie.text
        
        # =========================================================
        # EXTRAGE DOAR SECȚIUNEA DOWNLOAD LINKS
        # =========================================================
        download_section = ""
        
        # Caută începutul secțiunii de download
        download_start_markers = [
            'DOWNLOAD LINKS',
            'Download Links', 
            ': DOWNLOAD :',
            'Download Now',
            'download links'
        ]
        
        start_pos = -1
        for marker in download_start_markers:
            pos = movie_html.find(marker)
            if pos != -1:
                start_pos = pos
                log(f"[HDHUB] Found download section at marker: {marker}")
                break
        
        if start_pos != -1:
            # Caută sfârșitul secțiunii (următorul <footer>, </article>, sau alt container major)
            end_markers = ['<footer', '</article>', 'class="related"', 'class="widget"', 'id="comments"', '</main>']
            end_pos = len(movie_html)
            
            for marker in end_markers:
                pos = movie_html.find(marker, start_pos)
                if pos != -1 and pos < end_pos:
                    end_pos = pos
            
            download_section = movie_html[start_pos:end_pos]
            log(f"[HDHUB] Extracted download section: {len(download_section)} chars")
        else:
            # Fallback: folosește întreaga pagină dar cu filtrare strictă
            log(f"[HDHUB] No download marker found, using filtered full page")
            download_section = movie_html
        
        # Titlul din pagina principală
        full_title_match = re.search(r'<h1 class="page-title">.*?<span.*?>(.*?)</span>', movie_html, re.DOTALL)
        fallback_title = full_title_match.group(1).strip() if full_title_match else title_query

        # Extragere Linkuri DOAR din secțiunea de download
        link_pattern = r'<a\s+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>'
        all_links = re.findall(link_pattern, download_section, re.DOTALL)
        
        log(f"[HDHUB] Found {len(all_links)} links in download section")
        
        streams = []
        
        # =========================================================
        # DOMENII VALIDE pentru download
        # =========================================================
        valid_download_domains = [
            'hubdrive.space', 'hubcloud', 'hubcdn.fans/file', 'hubstream', 'hdstream4u',
            'gadgetsweb', 'gamerxyt', 'vcloud',
        ]
        
        for link, text in all_links:
            link_lower = link.lower()
            text_lower = text.lower()
            clean_text_str = re.sub(r'<[^>]+>', '', text).strip()
            clean_text_str = re.sub(r'\s+', ' ', clean_text_str)
            
            # =========================================================
            # SKIP: Link-uri care duc către alte pagini de film pe același site
            # =========================================================
            if 'hdhub4u' in link_lower and '/drive-' in link_lower:
                log(f"[HDHUB] Skipping internal movie link: {link[:60]}...")
                continue
            if 'hdhub4u' in link_lower and link_lower != movie_url.lower():
                # Orice alt link către hdhub4u care nu e pagina curentă
                log(f"[HDHUB] Skipping other internal link: {link[:60]}...")
                continue
            
            # =========================================================
            # SKIP: Link-uri care NU sunt pe domenii de download valide
            # =========================================================
            if not any(domain in link_lower for domain in valid_download_domains):
                continue
            
            # Detectare calitate
            initial_quality = "SD"
            if '2160p' in text_lower or '4k' in text_lower: 
                initial_quality = "4K"
            elif '1080p' in text_lower or 'hq 1080' in text_lower: 
                initial_quality = "1080p"
            elif '720p' in text_lower: 
                initial_quality = "720p"
            
            # Skip SD și Sample
            if initial_quality == "SD": 
                continue
            if 'sample' in text_lower:
                continue

            # Skip blocked domains
            if 'gadgetsweb' in link_lower:
                log(f"[HDHUB] Skipping blocked domain: {link[:50]}...")
                continue

            branch_label = clean_text_str.replace('Download', '').replace('Watch', '').replace('Links', '').replace('Online', '').strip()
            branch_label = re.sub(r'\s+', ' ', branch_label)
            # Curăță HTML entities
            branch_label = branch_label.replace('&#038;', '&').replace('&amp;', '&')
            
            log(f"[HDHUB] Processing download: {branch_label} -> {link[:50]}...")
            
            resolved_links = _resolve_hdhub_redirect(link, 0, None, branch_label)
            
            if resolved_links:
                for host_name, final_url, file_title, file_quality, returned_branch in resolved_links:
                    if 'http' in final_url:
                        final_quality = file_quality if file_quality else initial_quality
                        display_title = file_title if file_title else fallback_title
                        
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
# SCRAPER MKVCINEMAS (V3 - FIXED SEARCH)
# =============================================================================

def scrape_mkvcinemas(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru MKVCinemas.gd
    """
    if ADDON.getSetting('use_mkvcinemas') == 'false':
        return None
    
    try:
        base_url = "https://mkvcinemas.gd"
        
        # =========================================================
        # 1. CĂUTARE
        # =========================================================
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)  # Remove double spaces
        
        search_url = f"{base_url}/?s={quote(clean_search)}"
        
        log(f"[MKVCINEMAS] Searching: {search_url}")
        
        headers = get_headers()
        r = requests.get(search_url, headers=headers, timeout=15, verify=False)
        
        if r.status_code != 200:
            log(f"[MKVCINEMAS] Search failed with status {r.status_code}")
            return None
        
        search_html = r.text
        
        # =========================================================
        # 2. GĂSEȘTE PAGINA FILMULUI
        # =========================================================
        all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', search_html)
        
        log(f"[MKVCINEMAS] Found {len(all_hrefs)} total hrefs on page")
        
        movie_links = []
        
        exclude_patterns = [
            '/category/', '/page/', '/tag/', '/author/', '/wp-', '/feed/', 
            '/comment', '/attachment/', '/download-tips/', '/dmca/', '/contact/',
            '/privacy', '/terms', '/about', '/sitemap', '/cdn-cgi/',
            'javascript:', 'mailto:', '#', 'xmlrpc.php',
            '.jpg', '.png', '.gif', '.webp', '.css', '.js', '.ico', '.svg',
            'facebook.com', 'twitter.com', 'instagram.com', 'youtube.com',
            'google.com', 't.me', 'telegram', 'whatsapp'
        ]
        
        for href in all_hrefs:
            href_lower = href.lower()
            
            if any(ex in href_lower for ex in exclude_patterns):
                continue
            
            is_valid = False
            
            if 'mkvcinemas' in href:
                is_valid = True
            elif href.startswith('/') and not href.startswith('//'):
                href = base_url + href
                is_valid = True
            
            if not is_valid:
                continue
            
            path = href.replace(base_url, '').replace('https://mkvcinemas.gd', '').replace('https://mkvcinemas.gy', '').strip('/')
            
            if not path or len(path) < 5:
                continue
            
            if path.startswith('?'):
                continue
            
            # Skip homepage links
            if path == '' or path == '/':
                continue
            
            if href not in movie_links:
                movie_links.append(href)
        
        log(f"[MKVCINEMAS] Filtered to {len(movie_links)} potential movie links")
        
        if movie_links:
            log(f"[MKVCINEMAS] Sample links: {movie_links[:5]}")
        
        movie_url = None
        search_slug = clean_search.lower().replace(' ', '-')
        search_terms = clean_search.lower().split()
        
        for link in movie_links:
            link_lower = link.lower()
            
            if search_slug in link_lower:
                if year_query and str(year_query) in link:
                    movie_url = link
                    log(f"[MKVCINEMAS] ✓ Exact match with year: {link}")
                    break
                if not movie_url:
                    movie_url = link
                    log(f"[MKVCINEMAS] ✓ Exact slug match: {link}")
            
            if not movie_url:
                # Verifică dacă TOATE cuvintele lungi din căutare sunt în link
                long_terms = [t for t in search_terms if len(t) > 2]
                matches = sum(1 for term in long_terms if term in link_lower)
                if matches >= len(long_terms):
                    movie_url = link
                    log(f"[MKVCINEMAS] ✓ All terms match: {link}")
        
        if not movie_url:
            for link in movie_links:
                if any(x in link.lower() for x in ['movie', 'download', 'full', 'hindi', 'bollywood', 'hollywood', '2024', '2025', '2026']):
                    movie_url = link
                    log(f"[MKVCINEMAS] ✓ Fallback match: {link}")
                    break
        
        if not movie_url and movie_links:
            movie_url = movie_links[0]
            log(f"[MKVCINEMAS] Using first result: {movie_url}")
        
        if not movie_url:
            log(f"[MKVCINEMAS] No movie found for: {clean_search}")
            return None
        
        log(f"[MKVCINEMAS] Found movie page: {movie_url}")
        
        # =========================================================
        # 3. ACCESEAZĂ PAGINA FILMULUI
        # =========================================================
        r_movie = requests.get(movie_url, headers=headers, timeout=15, verify=False)
        movie_html = r_movie.text
        
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', movie_html)
        fallback_title = title_match.group(1).strip() if title_match else title_query
        
        fallback_title = re.sub(r'\s*(Download|Full Movie|HD|Hindi|Bollywood|Hollywood).*', '', fallback_title, flags=re.IGNORECASE).strip()
        
        # =========================================================
        # 4. GĂSEȘTE LINK-URILE FILESDL.LIVE
        # =========================================================
        filesdl_links = re.findall(r'href=["\']([^"\']*filesdl\.live[^"\']*)["\']', movie_html, re.IGNORECASE)
        hubcloud_direct = re.findall(r'href=["\']([^"\']*(?:hubcloud|vcloud)[^"\']+)["\']', movie_html, re.IGNORECASE)
        
        log(f"[MKVCINEMAS] Found {len(filesdl_links)} filesdl links, {len(hubcloud_direct)} hubcloud/vcloud links")
        
        streams = []
        seen_urls = set()
        
        # =========================================================
        # 5. PROCESARE FILESDL.LIVE
        # =========================================================
        if filesdl_links:
            unique_filesdl = list(dict.fromkeys(filesdl_links))
            
            for filesdl_url in unique_filesdl:
                log(f"[MKVCINEMAS] Processing filesdl: {filesdl_url}")
                
                try:
                    r_files = requests.get(filesdl_url, headers=headers, timeout=15, verify=False)
                    files_html = r_files.text
                    
                    page_title_match = re.search(r'<h1[^>]*class="entry-title"[^>]*>([^<]+)</h1>', files_html)
                    if page_title_match:
                        page_title = page_title_match.group(1).strip()
                        if len(page_title) > 3:
                            fallback_title = page_title
                    
                    # EXTRAGE DOWNLOAD BOXES
                    box_pattern = r'<div class="download-box[^"]*">\s*<h2>([^<]+)</h2>\s*<div class="filesize">([^<]+)</div>\s*<div class="download-buttons">\s*<a href="([^"]+)"[^>]*class="btn-gdflix"'
                    
                    boxes = re.findall(box_pattern, files_html, re.DOTALL | re.IGNORECASE)
                    
                    log(f"[MKVCINEMAS] Found {len(boxes)} download boxes")
                    
                    for quality_text, filesize, download_url in boxes:
                        quality_text = quality_text.strip()
                        filesize = filesize.strip()
                        
                        quality = "SD"
                        quality_lower = quality_text.lower()
                        
                        if '2160p' in quality_lower or '4k' in quality_lower or 'ultra' in quality_lower:
                            quality = "4K"
                        elif '1080p' in quality_lower:
                            quality = "1080p"
                        elif '720p' in quality_lower:
                            quality = "720p"
                        elif '480p' in quality_lower:
                            quality = "480p"
                        
                        if quality in ["SD", "480p"]:
                            log(f"[MKVCINEMAS] Skipping {quality}: {quality_text}")
                            continue
                        
                        clean_quality_text = quality_text.replace('DOWNLOAD', '').strip()
                        branch_label = f"{clean_quality_text} [{filesize}]"
                        
                        log(f"[MKVCINEMAS] Processing: {branch_label} -> {download_url[:50]}...")
                        
                        # =========================================================
                        # PROCESARE: HubCloud, VCloud, și alte domenii wrapper
                        # =========================================================
                        wrapper_domains = ['hubcloud', 'vcloud', 'hubdrive', 'hubstream']
                        
                        if any(domain in download_url.lower() for domain in wrapper_domains):
                            log(f"[MKVCINEMAS] Resolving wrapper: {download_url[:50]}...")
                            resolved_links = _resolve_hdhub_redirect(download_url, 0, None, branch_label)
                            
                            if resolved_links:
                                for host_name, final_url, file_title, file_quality, returned_branch in resolved_links:
                                    if 'http' in final_url and final_url not in seen_urls:
                                        final_quality = file_quality if file_quality else quality
                                        display_title = file_title if file_title else fallback_title
                                        
                                        # --- FIX AFISARE SIZE (Logic identic cu MoviesDrive) ---
                                        final_info = returned_branch if returned_branch else branch_label
                                        display_name = f"MKV | {host_name}"
                                        
                                        # Cautam toate marimile in text (ex: [1.5GB] [1.01 GB])
                                        # Luam ultima marime gasita, deoarece ea vine de obicei din HubCloud (cea reala)
                                        sizes = re.findall(r'\[(\d+(?:\.\d+)?\s*(?:GB|MB))\]', final_info, re.IGNORECASE)
                                        if sizes:
                                            real_size = sizes[-1]
                                            display_name = f"MKV | {host_name} | {real_size}"
                                        elif returned_branch:
                                            # Fallback daca nu gasim pattern-ul de size
                                            display_name = f"MKV | {host_name} | {returned_branch}"
                                        
                                        streams.append({
                                            'name': display_name,
                                            'url': build_stream_url(final_url),
                                            'quality': final_quality,
                                            'title': display_title,
                                            'info': final_info
                                        })
                                        seen_urls.add(final_url)
                                        log(f"[MKVCINEMAS] ✓ Added: {display_name}")
                            else:
                                log(f"[MKVCINEMAS] No streams resolved from wrapper")

# --- MODIFICARE START: SUPORT GDFLIX (META TAG & HTML PARSE) ---
                        elif 'gdflix' in download_url.lower():
                            log(f"[MKVCINEMAS] Resolving GDFlix: {download_url[:50]}...")
                            try:
                                r_gd = requests.get(download_url, headers=headers, timeout=10, verify=False)
                                gd_content = r_gd.text
                                
                                # Initializam variabilele
                                current_quality = quality
                                current_title = fallback_title
                                current_info = branch_label
                                size_str = ""
                                gd_filename = None
                                gd_size_val = None

                                # METODA 1: Extragere din Meta Description (Cea mai sigura si rapida)
                                # <meta property="og:description" content="Download [Nume] - [Size]">
                                meta_match = re.search(r'property="og:description"\s+content="Download\s+(.*?)\s+-\s+([^"]+)"', gd_content, re.IGNORECASE)
                                if meta_match:
                                    gd_filename = meta_match.group(1).strip()
                                    gd_size_val = meta_match.group(2).strip()
                                    log(f"[MKVCINEMAS] GDFlix Data from Meta: {gd_filename} | {gd_size_val}")

                                # METODA 2: Fallback la HTML List Items (Daca Meta esueaza)
                                # Cautam ">Size :" pentru a evita CSS-ul sau scripturile
                                if not gd_filename:
                                    name_html = re.search(r'>\s*Name\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                    if name_html: gd_filename = name_html.group(1).strip()
                                
                                if not gd_size_val:
                                    size_html = re.search(r'>\s*Size\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                    if size_html: gd_size_val = size_html.group(1).strip()

                                # Procesare Date Extrase
                                if gd_filename:
                                    current_title = gd_filename
                                    gd_lower = gd_filename.lower()
                                    
                                    # Recalculare calitate din numele fisierului
                                    # IMPORTANT: Ordinea contează! 720p/1080p PRIMUL, 4K ULTIMUL cu regex!
                                    if '720p' in gd_lower:
                                        current_quality = "720p"
                                    elif '1080p' in gd_lower:
                                        current_quality = "1080p"
                                    elif '2160p' in gd_lower:
                                        current_quality = "4K"
                                    # 4K DOAR dacă e cuvânt separat (nu "224Kbps", "384Kbps" etc.)
                                    elif re.search(r'(?:^|[\.\-\s_\(])4k(?:$|[\.\-\s_\)\.])', gd_lower):
                                        current_quality = "4K"
                                
                                if gd_size_val:
                                    # Curatam size-ul de eventuale spatii si il validam (sa nu fie cod CSS)
                                    gd_size_val = gd_size_val.strip()
                                    if len(gd_size_val) < 15: # Un size real gen "1.04GB" e scurt
                                        size_str = gd_size_val
                                        current_info = size_str

                                # 2. Cautam link-uri DIRECTE (Cloud Download / R2 / Workers)
                                r2_matches = re.findall(r'href=["\'](https?://[^"\']*(?:r2\.dev|cloudflarestorage|workers\.dev)[^"\']*)["\']', gd_content, re.IGNORECASE)
                                for r2_link in r2_matches:
                                    if r2_link not in seen_urls:
                                        display_name = f"MKV | GDFlix | Direct"
                                        if size_str:
                                            display_name += f" | {size_str}"

                                        streams.append({
                                            'name': display_name,
                                            'url': build_stream_url(r2_link),
                                            'quality': current_quality,
                                            'title': current_title,
                                            'info': current_info
                                        })
                                        seen_urls.add(r2_link)
                                        log(f"[MKVCINEMAS] ✓ Found GDFlix Direct: {display_name}")

                                # 3. Cautam PIXELDRAIN
                                pd_match = re.search(r'href=["\'](https?://[^"\']*pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))["\']', gd_content, re.IGNORECASE)
                                if pd_match:
                                    pd_id = pd_match.group(2)
                                    pd_api = f"https://pixeldrain.dev/api/file/{pd_id}"
                                    if pd_api not in seen_urls:
                                        display_name = f"MKV | GDFlix | PixelDrain"
                                        if size_str:
                                            display_name += f" | {size_str}"

                                        streams.append({
                                            'name': display_name,
                                            'url': build_stream_url(pd_api),
                                            'quality': current_quality,
                                            'title': current_title,
                                            'info': current_info
                                        })
                                        seen_urls.add(pd_api)
                                        log(f"[MKVCINEMAS] ✓ Found GDFlix PixelDrain: {display_name}")

                            except Exception as e:
                                log(f"[MKVCINEMAS] GDFlix Error: {e}")
                        # --- MODIFICARE END ---
                
                except Exception as e:
                    log(f"[MKVCINEMAS] Error processing filesdl: {e}")
                    continue
        
# =========================================================
        # 6. PROCESARE HUBCLOUD/VCLOUD DIRECT (fallback)
        # =========================================================
        if hubcloud_direct and not streams:
            log(f"[MKVCINEMAS] Trying direct HubCloud/VCloud links: {len(hubcloud_direct)}")
            
            for wrapper_url in hubcloud_direct:
                if wrapper_url in seen_urls:
                    continue
                    
                resolved_links = _resolve_hdhub_redirect(wrapper_url, 0, None, "Direct")
                
                if resolved_links:
                    for host_name, final_url, file_title, file_quality, returned_branch in resolved_links:
                        if 'http' in final_url and final_url not in seen_urls:
                            final_quality = file_quality if file_quality else "1080p"
                            display_title = file_title if file_title else fallback_title
                            
                            # --- FIX AFISARE SIZE ---
                            final_info = returned_branch if returned_branch else "Direct"
                            display_name = f"MKV | {host_name}"
                            
                            sizes = re.findall(r'\[(\d+(?:\.\d+)?\s*(?:GB|MB))\]', final_info, re.IGNORECASE)
                            if sizes:
                                real_size = sizes[-1]
                                display_name = f"MKV | {host_name} | {real_size}"
                            
                            streams.append({
                                'name': display_name,
                                'url': build_stream_url(final_url),
                                'quality': final_quality,
                                'title': display_title,
                                'info': final_info
                            })
                            seen_urls.add(final_url)
        
        log(f"[MKVCINEMAS] Total streams found: {len(streams)}")
        return streams if streams else None
        
    except Exception as e:
        log(f"[MKVCINEMAS] Error: {e}", xbmc.LOGERROR)
        raise e


# =============================================================================
# SCRAPER MOVIESDRIVE (V2 - TV SHOWS SUPPORT)
# =============================================================================

def _get_moviesdrive_base():
    """
    Determina domeniul activ MoviesDrive.
    """
    # 1. API CHECK
    try:
        api_url = "https://cdn.mdrivecdn.net/host/"
        headers = get_headers()
        headers['Origin'] = "https://moviesdrives.cv"
        headers['Referer'] = "https://moviesdrives.cv/"
        
        r = requests.get(api_url, headers=headers, timeout=5, verify=False)
        
        if r.status_code == 200:
            data = r.json()
            if 'h' in data:
                decoded_host = base64.b64decode(data['h']).decode('utf-8')
                if 'moviesdrives.cv' not in decoded_host:
                    base = f"https://{decoded_host}"
                    log(f"[MOVIESDRIVE] Base URL from API: {base}")
                    return base
    except Exception as e:
        log(f"[MOVIESDRIVE] API check failed: {e}")

    # 2. REDIRECTOR CHECK
    try:
        redirector_url = "https://mdrive.today/?re=md"
        headers = get_headers()
        headers['Referer'] = "https://moviesdrives.cv/" 
        
        r = requests.get(redirector_url, headers=headers, timeout=10, verify=False)
        
        final_url = r.url
        parsed = urlparse(final_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        
        if 'moviesdrives.cv' not in base_domain and 'mdrive.today' not in base_domain:
            log(f"[MOVIESDRIVE] Base URL from Redirector: {base_domain}")
            return base_domain
            
    except Exception as e:
        log(f"[MOVIESDRIVE] Redirector check failed: {e}")

    # 3. FALLBACK HARDCODED
    log("[MOVIESDRIVE] Using hardcoded fallback.")
    return "https://new1.moviesdrive.surf"


def scrape_moviesdrive(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru MoviesDrive - suportă atât filme cât și seriale.
    """
    if ADDON.getSetting('use_moviesdrive') == 'false':
        return None

    try:
        base_url = _get_moviesdrive_base()
        
        # =========================================================
        # 1. CĂUTARE PRIN API (JSON)
        # =========================================================
        api_url = f"{base_url}/searchapi.php"
        
        if content_type == 'tv' and title_query:
            search_term = title_query
        else:
            search_term = imdb_id
            
        params = {'q': search_term, 'page': '1'}
        
        log(f"[MOVIESDRIVE] API Search: {api_url} ? q={search_term}")
        
        headers = get_headers()
        headers['Referer'] = f"{base_url}/search.html?q={search_term}"
        headers['X-Requested-With'] = 'XMLHttpRequest'
        
        r = requests.get(api_url, params=params, headers=headers, timeout=10, verify=False)
        
        movie_link = None
        season_link = None
        
        try:
            data = r.json()
            if 'hits' in data and data['hits']:
                
                if content_type == 'tv' and season:
                    season_num = int(season)
                    
                    season_patterns = [
                        f"season {season_num}",
                        f"season-{season_num}",
                        f"s{season_num:02d}",
                        f"s{season_num}",
                        f"(season {season_num})",
                    ]
                    
                    for hit in data['hits']:
                        doc = hit.get('document', {})
                        raw_link = doc.get('permalink', '')
                        raw_title = doc.get('post_title', '').lower()
                        
                        if not raw_link:
                            continue
                        
                        if title_query:
                            title_words = title_query.lower().split()
                            if not all(word in raw_title for word in title_words if len(word) > 2):
                                continue
                        
                        link_lower = raw_link.lower()
                        title_and_link = raw_title + ' ' + link_lower
                        
                        for pattern in season_patterns:
                            if pattern in title_and_link:
                                if raw_link.startswith('http'):
                                    season_link = raw_link
                                else:
                                    season_link = base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                                log(f"[MOVIESDRIVE] Found season {season_num} page: {season_link}")
                                break
                        
                        if season_link:
                            break
                    
                    if not season_link:
                        for hit in data['hits']:
                            doc = hit.get('document', {})
                            raw_link = doc.get('permalink', '')
                            raw_title = doc.get('post_title', '').lower()
                            
                            if title_query and all(word in raw_title for word in title_query.lower().split() if len(word) > 2):
                                if raw_link.startswith('http'):
                                    movie_link = raw_link
                                else:
                                    movie_link = base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                                log(f"[MOVIESDRIVE] Found show page (will search for season): {movie_link}")
                                break
                
                else:
                    doc = data['hits'][0].get('document', {})
                    raw_link = doc.get('permalink')
                    if raw_link:
                        if raw_link.startswith('http'):
                            movie_link = raw_link
                        else:
                            movie_link = base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                        log(f"[MOVIESDRIVE] Found via API: {doc.get('post_title')} -> {movie_link}")
                        
        except ValueError:
            pass

        # =========================================================
        # 2. PENTRU SERIALE: NAVIGARE LA PAGINA SEZONULUI
        # =========================================================
        if content_type == 'tv' and season:
            target_page = season_link if season_link else movie_link
            
            if not target_page:
                log(f"[MOVIESDRIVE] No TV show found for {title_query}")
                return None
            
            log(f"[MOVIESDRIVE] Accessing page: {target_page}")
            
            try:
                session = requests.Session()
                session.headers.update(get_headers())
                r_page = session.get(target_page, timeout=(5, 15), verify=False)
                log(f"[MOVIESDRIVE] Page loaded: {len(r_page.text)} bytes")
            except Exception as e:
                log(f"[MOVIESDRIVE] Error loading page: {e}")
                return None
            
            page_html = r_page.text
            
            # Dacă suntem pe pagina principală, căutăm link-ul către sezon
            if not season_link:
                season_num = int(season)
                
                season_link_patterns = [
                    rf'href=["\']([^"\']*season[- ]?{season_num}[^"\']*)["\']',
                    rf'href=["\']([^"\']*s{season_num:02d}[^"\']*)["\']',
                    rf'href=["\']([^"\']*-s{season_num}[^"\']*)["\']',
                ]
                
                for pattern in season_link_patterns:
                    matches = re.findall(pattern, page_html, re.IGNORECASE)
                    for match in matches:
                        if 'moviesdrive' in match.lower() or match.startswith('/'):
                            if match.startswith('/'):
                                season_link = base_url + match
                            else:
                                season_link = match
                            log(f"[MOVIESDRIVE] Found season link in page: {season_link}")
                            break
                    if season_link:
                        break
                
                if season_link:
                    r_page = session.get(season_link, timeout=(5, 15), verify=False)
                    page_html = r_page.text
            
            # Titlul paginii
            title_match = re.search(r'<title>(.*?)</title>', page_html)
            page_title = title_match.group(1).split('|')[0].strip() if title_match else title_query
            
            # =========================================================
            # 3. EXTRAGERE LINK-URI PENTRU CALITĂȚI - FIX PERFORMANCE!
            # =========================================================
            quality_links = {}
            
            log(f"[MOVIESDRIVE] DEBUG: Parsing quality links...")
            
            # FIX: Pattern simplu și rapid - găsim toate link-urile mdrive.lol
            all_mdrive_pattern = r'<a\s+href=["\']([^"\']*mdrive\.lol/archives/[^"\']+)["\'][^>]*>([^<]*)</a>'
            all_mdrive_matches = re.findall(all_mdrive_pattern, page_html, re.IGNORECASE)
            
            log(f"[MOVIESDRIVE] DEBUG: Found {len(all_mdrive_matches)} mdrive links")
            
            for url, text in all_mdrive_matches:
                text_lower = text.lower().strip()
                
                # Skip Zip links
                if 'zip' in text_lower:
                    continue
                
                # Căutăm doar "Single Episode" links sau link-uri cu calitate explicită
                is_single_ep = 'single' in text_lower or 'episode' in text_lower
                has_quality_in_text = any(q in text_lower for q in ['720p', '1080p', '2160p', '4k'])
                
                if not is_single_ep and not has_quality_in_text:
                    continue
                
                # Detectare calitate din text-ul link-ului
                quality_key = None
                
                if '2160' in text_lower or '4k' in text_lower:
                    quality_key = '4K'
                elif '1080' in text_lower:
                    quality_key = '1080p'
                elif '720' in text_lower:
                    quality_key = '720p'
                elif '480' in text_lower:
                    quality_key = '480p'
                
                # Dacă nu am găsit calitatea în text, căutăm în HTML-ul din jur
                if not quality_key:
                    url_pos = page_html.find(url)
                    if url_pos > 0:
                        # Căutăm în ultimele 500 caractere înainte de link
                        context_start = max(0, url_pos - 500)
                        context_before = page_html[context_start:url_pos].lower()
                        
                        if '2160p' in context_before or '>4k<' in context_before or '>4k ' in context_before:
                            quality_key = '4K'
                        elif '1080p' in context_before:
                            quality_key = '1080p'
                        elif '720p' in context_before:
                            quality_key = '720p'
                        elif '480p' in context_before:
                            quality_key = '480p'
                
                if not quality_key:
                    continue
                
                # Skip 480p
                if quality_key == '480p':
                    log(f"[MOVIESDRIVE] Skipping 480p quality")
                    continue
                
                # Extragem size din context dacă există
                size_per_ep = ""
                url_pos = page_html.find(url)
                if url_pos > 0:
                    context_before = page_html[max(0, url_pos - 300):url_pos]
                    size_match = re.search(r'\[([^\]]*(?:MB|GB)[^\]]*)\]', context_before, re.IGNORECASE)
                    if size_match:
                        size_per_ep = size_match.group(1)
                
                # Adăugăm doar dacă nu există deja această calitate
                if quality_key not in quality_links:
                    quality_links[quality_key] = {
                        'url': url,
                        'size': size_per_ep
                    }
                    log(f"[MOVIESDRIVE] Found quality link: {quality_key} ({size_per_ep}) -> {url}")
            
            log(f"[MOVIESDRIVE] DEBUG: Total quality links: {len(quality_links)}")
            
            if not quality_links:
                log(f"[MOVIESDRIVE] No quality links found on season page")
                return None
            
            # =========================================================
            # 4. PENTRU FIECARE CALITATE, ACCESEAZĂ PAGINA CU EPISOADE
            # =========================================================
            episode_num = int(episode) if episode else 1
            streams = []
            seen_urls = set()
            
            for quality, info in quality_links.items():
                mdrive_url = info['url']
                size_hint = info['size']
                
                log(f"[MOVIESDRIVE] Accessing episode list for {quality}: {mdrive_url}")
                
                try:
                    headers_md = get_headers()
                    headers_md['Referer'] = target_page
                    
                    r_ep = requests.get(mdrive_url, headers=headers_md, timeout=(5, 10), verify=False)
                    ep_html = r_ep.text
                    
                    if 'LANDER_SYSTEM' in ep_html or 'parking-lander' in ep_html:
                        log(f"[MOVIESDRIVE] Hit Parking Page on {mdrive_url}")
                        continue
                    
                    # =========================================================
                    # 5. GĂSEȘTE SECȚIUNEA EPISODULUI CĂUTAT
                    # =========================================================
                    episode_patterns = [
                        rf'Ep0?{episode_num}\s*</span>',
                        rf'Episode\s*0?{episode_num}\s*</span>',
                        rf'EP0?{episode_num}\s*</span>',
                        rf'>Ep0?{episode_num}<',
                        rf'>E0?{episode_num}<',
                    ]
                    
                    ep_section_start = -1
                    for pattern in episode_patterns:
                        match = re.search(pattern, ep_html, re.IGNORECASE)
                        if match:
                            ep_section_start = match.start()
                            log(f"[MOVIESDRIVE] Found episode {episode_num} marker at position {ep_section_start}")
                            break
                    
                    if ep_section_start == -1:
                        log(f"[MOVIESDRIVE] Episode {episode_num} not found in {quality} page")
                        continue
                    
                    next_ep_patterns = [
                        rf'Ep0?{episode_num + 1}\s*</span>',
                        rf'Episode\s*0?{episode_num + 1}\s*</span>',
                        rf'>Ep0?{episode_num + 1}<',
                        r'<hr\s*/?>',
                    ]
                    
                    ep_section_end = len(ep_html)
                    remaining_html = ep_html[ep_section_start + 50:]
                    
                    for pattern in next_ep_patterns:
                        match = re.search(pattern, remaining_html, re.IGNORECASE)
                        if match:
                            potential_end = ep_section_start + 50 + match.start()
                            if potential_end < ep_section_end:
                                ep_section_end = potential_end
                    
                    ep_section = ep_html[ep_section_start:ep_section_end]
                    log(f"[MOVIESDRIVE] Episode section: {len(ep_section)} chars")
                    
                    # =========================================================
                    # 6. EXTRAGE LINK-URILE DIN SECȚIUNEA EPISODULUI
                    # =========================================================
                    link_pattern = r'<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>'
                    links_in_section = re.findall(link_pattern, ep_section, re.IGNORECASE)
                    
                    for link_url, link_text in links_in_section:
                        link_lower = link_url.lower()
                        
                        # === HUBCLOUD ===
                        if 'hubcloud' in link_lower or 'vcloud' in link_lower:
                            log(f"[MOVIESDRIVE] Resolving HubCloud for Ep{episode_num}: {link_url}")
                            
                            branch_label = f"{quality} Ep{episode_num}"
                            if size_hint:
                                branch_label += f" [{size_hint}]"
                            
                            resolved = _resolve_hdhub_redirect(link_url, 0, page_title, branch_label)
                            
                            if resolved:
                                for host, final_url, f_title, f_qual, f_branch in resolved:
                                    if final_url not in seen_urls:
                                        final_quality = f_qual if f_qual else quality
                                        final_info = f_branch if f_branch else branch_label
                                        
                                        display_name = f"MDrive | {host}"
                                        size_match = re.search(r'\[(\d+(?:\.\d+)?\s*(?:GB|MB))\]', final_info, re.IGNORECASE)
                                        if size_match:
                                            display_name += f" | {size_match.group(1)}"
                                        
                                        streams.append({
                                            'name': display_name,
                                            'url': build_stream_url(final_url),
                                            'quality': final_quality,
                                            'title': f_title if f_title else page_title,
                                            'info': final_info
                                        })
                                        seen_urls.add(final_url)
                                        log(f"[MOVIESDRIVE] ✓ Added: {display_name} ({final_quality})")
                        
                        # === GDFLIX ===
                        elif 'gdflix' in link_lower:
                            log(f"[MOVIESDRIVE] Resolving GDFlix for Ep{episode_num}: {link_url}")
                            
                            try:
                                r_gd = requests.get(link_url, headers=get_headers(), timeout=(5, 8), verify=False)
                                gd_content = r_gd.text
                                
                                gd_filename = None
                                gd_size_val = None
                                
                                meta_match = re.search(r'property="og:description"\s+content="Download\s+(.*?)\s+-\s+([^"]+)"', gd_content, re.IGNORECASE)
                                if meta_match:
                                    gd_filename = meta_match.group(1).strip()
                                    gd_size_val = meta_match.group(2).strip()
                                
                                if not gd_filename:
                                    name_html = re.search(r'>\s*Name\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                    if name_html:
                                        gd_filename = name_html.group(1).strip()
                                if not gd_size_val:
                                    size_html = re.search(r'>\s*Size\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                    if size_html:
                                        gd_size_val = size_html.group(1).strip()
                                
                                curr_qual = quality
                                curr_title = page_title
                                size_info = ""
                                
                                if gd_filename:
                                    curr_title = gd_filename
                                    gd_lower = gd_filename.lower()
                                    if '720p' in gd_lower:
                                        curr_qual = "720p"
                                    elif '1080p' in gd_lower:
                                        curr_qual = "1080p"
                                    elif '2160p' in gd_lower:
                                        curr_qual = "4K"
                                    elif re.search(r'(?:^|[\.\-\s_\(])4k(?:$|[\.\-\s_\)\.])', gd_lower):
                                        curr_qual = "4K"
                                
                                if gd_size_val and len(gd_size_val) < 15:
                                    size_info = gd_size_val
                                
                                r2_matches = re.findall(r'href=["\'](https?://[^"\']*(?:r2\.dev|cloudflarestorage|workers\.dev)[^"\']*)["\']', gd_content, re.IGNORECASE)
                                for r2_link in r2_matches:
                                    if r2_link not in seen_urls:
                                        disp = f"MDrive | GDFlix | Direct"
                                        if size_info:
                                            disp += f" | {size_info}"
                                        streams.append({
                                            'name': disp,
                                            'url': build_stream_url(r2_link),
                                            'quality': curr_qual,
                                            'title': curr_title,
                                            'info': size_info
                                        })
                                        seen_urls.add(r2_link)
                                        log(f"[MOVIESDRIVE] ✓ Added GDFlix Direct: {disp}")
                                
                                pd_match = re.search(r'href=["\'](https?://[^"\']*pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))["\']', gd_content, re.IGNORECASE)
                                if pd_match:
                                    pd_api = f"https://pixeldrain.dev/api/file/{pd_match.group(2)}"
                                    if pd_api not in seen_urls:
                                        disp = f"MDrive | GDFlix | PixelDrain"
                                        if size_info:
                                            disp += f" | {size_info}"
                                        streams.append({
                                            'name': disp,
                                            'url': build_stream_url(pd_api),
                                            'quality': curr_qual,
                                            'title': curr_title,
                                            'info': size_info
                                        })
                                        seen_urls.add(pd_api)
                                        log(f"[MOVIESDRIVE] ✓ Added GDFlix PixelDrain: {disp}")
                                        
                            except Exception as e:
                                log(f"[MOVIESDRIVE] GDFlix Error: {e}")
                
                except Exception as e:
                    log(f"[MOVIESDRIVE] Error processing quality {quality}: {e}")
                    continue
            
            log(f"[MOVIESDRIVE] Total TV streams: {len(streams)}")
            return streams if streams else None
        
        # =========================================================
        # FILME: LOGICA EXISTENTĂ
        # =========================================================
        if not movie_link:
            log(f"[MOVIESDRIVE] No movie found for {imdb_id}")
            return None
        
        log(f"[MOVIESDRIVE] Processing movie: {movie_link}")
        r_movie = requests.get(movie_link, headers=get_headers(), timeout=(5, 10), verify=False)
        movie_html = r_movie.text
        
        title_match = re.search(r'<title>(.*?)</title>', movie_html)
        page_title = title_match.group(1).split('|')[0].strip() if title_match else "Unknown"

        start_pos = movie_html.find("DOWNLOAD LINKS")
        download_section = movie_html[start_pos:] if start_pos != -1 else movie_html
            
        mdrive_links = re.findall(r'href=["\'](https?://mdrive\.lol/archives/[^"\']+)["\'][^>]*>(.*?)</a>', download_section, re.IGNORECASE)
        
        streams = []
        seen_urls = set()
        
        log(f"[MOVIESDRIVE] Found {len(mdrive_links)} intermediate links")
        
        for mdrive_url, link_text in mdrive_links:
            clean_text = re.sub(r'<[^>]+>', '', link_text).strip()
            
            quality = "SD"
            clean_lower = clean_text.lower()
            if '2160p' in clean_lower or '4k' in clean_lower:
                quality = "4K"
            elif '1080p' in clean_lower:
                quality = "1080p"
            elif '720p' in clean_lower:
                quality = "720p"
            
            if '480p' in clean_lower:
                log(f"[MOVIESDRIVE] Skipping 480p: {clean_text}")
                continue
            
            log(f"[MOVIESDRIVE] Processing wrapper: {clean_text} -> {mdrive_url}")
            
            try:
                headers_md = get_headers()
                headers_md['Referer'] = movie_link 
                
                r_md = requests.get(mdrive_url, headers=headers_md, timeout=(5, 10), verify=False)
                md_html = r_md.text
                
                if 'LANDER_SYSTEM' in md_html or 'parking-lander' in md_html:
                    log(f"[MOVIESDRIVE] Hit Parking Page on {mdrive_url}")
                    continue

                dest_links = re.findall(r'href=["\'](https?://[^"\']*(?:hubcloud|gdflix)[^"\']+)["\']', md_html, re.IGNORECASE)
                
                if not dest_links:
                    log(f"[MOVIESDRIVE] No destination links found in {mdrive_url}")
                
                for dest_url in dest_links:
                    
                    if 'hubcloud' in dest_url.lower() or 'vcloud' in dest_url.lower():
                        log(f"[MOVIESDRIVE] Resolving HubCloud: {dest_url}")
                        resolved = _resolve_hdhub_redirect(dest_url, 0, page_title, clean_text)
                        if resolved:
                            for host, final_url, f_title, f_qual, f_branch in resolved:
                                if final_url not in seen_urls:
                                    final_info = f_branch if f_branch else clean_text
                                    display_name = f"MDrive | {host}"
                                    
                                    size_match = re.search(r'\[(\d+(?:\.\d+)?\s*(?:GB|MB))\]', final_info, re.IGNORECASE)
                                    if size_match:
                                        display_name += f" | {size_match.group(1)}"
                                    
                                    streams.append({
                                        'name': display_name,
                                        'url': build_stream_url(final_url),
                                        'quality': f_qual if f_qual else quality,
                                        'title': f_title if f_title else page_title,
                                        'info': final_info
                                    })
                                    seen_urls.add(final_url)

                    elif 'gdflix' in dest_url.lower():
                        log(f"[MOVIESDRIVE] Resolving GDFlix: {dest_url}")
                        try:
                            r_gd = requests.get(dest_url, headers=get_headers(), timeout=(5, 8), verify=False)
                            gd_content = r_gd.text
                            
                            gd_filename = None
                            gd_size_val = None
                            
                            meta_match = re.search(r'property="og:description"\s+content="Download\s+(.*?)\s+-\s+([^"]+)"', gd_content, re.IGNORECASE)
                            if meta_match:
                                gd_filename = meta_match.group(1).strip()
                                gd_size_val = meta_match.group(2).strip()
                            
                            if not gd_filename:
                                name_html = re.search(r'>\s*Name\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                if name_html:
                                    gd_filename = name_html.group(1).strip()
                            if not gd_size_val:
                                size_html = re.search(r'>\s*Size\s*:\s*([^<]+)', gd_content, re.IGNORECASE)
                                if size_html:
                                    gd_size_val = size_html.group(1).strip()
                                    
                            curr_qual = quality
                            curr_title = page_title
                            size_info = ""
                            
                            if gd_filename:
                                curr_title = gd_filename
                                gd_lower = gd_filename.lower()
                                if '720p' in gd_lower:
                                    curr_qual = "720p"
                                elif '1080p' in gd_lower:
                                    curr_qual = "1080p"
                                elif '2160p' in gd_lower:
                                    curr_qual = "4K"
                                elif re.search(r'(?:^|[\.\-\s_\(])4k(?:$|[\.\-\s_\)\.])', gd_lower):
                                    curr_qual = "4K"
                                    
                            if gd_size_val and len(gd_size_val) < 15:
                                size_info = gd_size_val
                            
                            r2_matches = re.findall(r'href=["\'](https?://[^"\']*(?:r2\.dev|cloudflarestorage|workers\.dev)[^"\']*)["\']', gd_content, re.IGNORECASE)
                            for r2_link in r2_matches:
                                if r2_link not in seen_urls:
                                    disp = f"MDrive | GDFlix | Direct"
                                    if size_info:
                                        disp += f" | {size_info}"
                                    streams.append({
                                        'name': disp,
                                        'url': build_stream_url(r2_link),
                                        'quality': curr_qual,
                                        'title': curr_title,
                                        'info': size_info
                                    })
                                    seen_urls.add(r2_link)
                            
                            pd_match = re.search(r'href=["\'](https?://[^"\']*pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))["\']', gd_content, re.IGNORECASE)
                            if pd_match:
                                pd_api = f"https://pixeldrain.dev/api/file/{pd_match.group(2)}"
                                if pd_api not in seen_urls:
                                    disp = f"MDrive | GDFlix | PixelDrain"
                                    if size_info:
                                        disp += f" | {size_info}"
                                    streams.append({
                                        'name': disp,
                                        'url': build_stream_url(pd_api),
                                        'quality': curr_qual,
                                        'title': curr_title,
                                        'info': size_info
                                    })
                                    seen_urls.add(pd_api)
                                    
                        except Exception as e:
                            log(f"[MOVIESDRIVE] GDFlix Error: {e}")

            except Exception as e:
                log(f"[MOVIESDRIVE] Error processing mdrive link: {e}")
                continue

        log(f"[MOVIESDRIVE] Total streams: {len(streams)}")
        return streams if streams else None

    except Exception as e:
        log(f"[MOVIESDRIVE] Critical Error: {e}", xbmc.LOGERROR)
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
                ref = base_url + '/'
                origin = base_url

                for s in data['streams']:
                    url = s.get('url', '')
                    clean_check_url = url.split('|')[0]
                    
                    if url and clean_check_url not in seen_urls:
                        # --- FIX PENTRU NUME DUBLAT SI UNICODE ---
                        raw_name = s.get('name', '')
                        
                        # 1. CURĂȚARE UNICODE AGRESIVĂ
                        # Transformă string-ul în ASCII și elimină orice nu poate fi convertit (emojis, simboluri grafice)
                        # "🤌 GuardaHD 🎬" devine " GuardaHD "
                        try:
                            clean_name = raw_name.encode('ascii', 'ignore').decode('ascii')
                        except:
                            clean_name = raw_name # Fallback în caz extrem

                        # 2. Ștergem numele vechi cunoscute
                        banned_names = ['WebStreamr', 'Nuvio', 'StreamVix', 'Vidzee', 'Vega']
                        
                        for bn in banned_names:
                            clean_name = clean_name.replace(bn, '').strip()
                        
                        # 3. Curățăm caracterele rămase (ex: pipe-uri, spații duble)
                        # Eliminăm '|' explicit dacă a rămas de la split-uri anterioare sau din provider
                        clean_name = clean_name.replace('|', '').strip()
                        
                        # Eliminăm spațiile duble care pot apărea după ștergerea emojis
                        while '  ' in clean_name:
                            clean_name = clean_name.replace('  ', ' ')

                        # Setăm noul nume curat: "Label | Restul numelui"
                        if clean_name:
                            s['name'] = f"{label} | {clean_name}"
                        else:
                            s['name'] = label
                        # ------------------------------
                        
                        s['url'] = build_stream_url(url, referer=ref, origin=origin)
                        
                        all_streams.append(s)
                        seen_urls.add(clean_check_url)
                        count += 1
                log(f"[SCRAPER] ✓ {label}: {count} surse")
    except Exception as e:
        raise e


# =============================================================================
# SCRAPER XDMOVIES
# =============================================================================

def scrape_xdmovies(imdb_id, content_type, season=None, episode=None):
    """
    Scraper pentru XDMovies API (Alias: SmileNow).
    """
    if ADDON.getSetting('use_xdmovies') == 'false':
        return None
    
    try:
        base_url = "https://xdmovies-stremio.hdmovielover.workers.dev"
        
        # Construiește URL-ul API
        if content_type == 'movie':
            api_url = f"{base_url}/movie?imdbid={imdb_id}"
        else:
            api_url = f"{base_url}/series?imdbid={imdb_id}&s={season}&e={episode}"
        
        log(f"[XDMOVIES] Fetching: {api_url}")
        
        headers = get_headers()
        r = requests.get(api_url, headers=headers, timeout=15, verify=False)
        
        if r.status_code != 200:
            log(f"[XDMOVIES] API returned status {r.status_code}")
            return None
        
        try:
            data = r.json()
        except:
            log(f"[XDMOVIES] Failed to parse JSON response")
            return None
        
        streams_data = data.get('streams', [])
        
        if not streams_data:
            log(f"[XDMOVIES] No streams found")
            return None
        
        log(f"[XDMOVIES] Found {len(streams_data)} streams")
        
        streams = []
        
        for s in streams_data:
            url = s.get('url', '')
            name = s.get('name', '')
            title = s.get('title', '')
            
            if not url:
                continue
            
            # Extrage calitatea din name (ex: "XDM - 2160p")
            quality = "SD"
            name_lower = name.lower()
            if '2160p' in name_lower or '4k' in name_lower:
                quality = "4K"
            elif '1080p' in name_lower:
                quality = "1080p"
            elif '720p' in name_lower:
                quality = "720p"
            
            # Skip SD/480p
            if quality == "SD":
                continue
            
            # Extrage size din title (ex: "📦5.57 GB")
            size = ""
            size_match = re.search(r'📦\s*([\d.]+)\s*(GB|MB)', title, re.IGNORECASE)
            if size_match:
                size = f"{size_match.group(1)}{size_match.group(2).upper()}"
            
            # Curăță titlul (elimină size și newlines)
            clean_title = title.split('\n')[0].strip() if '\n' in title else title
            clean_title = re.sub(r'📦.*$', '', clean_title).strip()
            
            # Construiește display name - ALIAS SMILENOW
            display_name = f"SmileNow | {quality}"
            if size:
                display_name = f"SmileNow | {size}"
            
            streams.append({
                'name': display_name,
                'url': build_stream_url(url, referer="https://xdmovies-stremio.hdmovielover.workers.dev/"),
                'quality': quality,
                'title': clean_title,
                'info': f"{quality} {size}".strip()
            })
            
            log(f"[XDMOVIES] ✓ Added: {quality} - {size}")
        
        log(f"[XDMOVIES] Total streams: {len(streams)}")
        return streams if streams else None
        
    except Exception as e:
        log(f"[XDMOVIES] Error: {e}", xbmc.LOGERROR)
        raise e

# =============================================================================
# MAIN ORCHESTRATION FUNCTION (MODIFICATĂ PENTRU MKVCINEMAS)
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
    was_canceled = False
    
    # =========================================================
    # EXTRAGERE TITLU ȘI AN DIN TMDB
    # Se face pentru toate scraperele care au nevoie de căutare după nume
    # =========================================================
    extra_title = ""
    extra_year = ""
    
    # Lista de scrapere care au nevoie de titlu pentru căutare
    title_based_scrapers = ['hdhub4u', 'mkvcinemas', 'vixsrc']
    
    # Verifică dacă vreunul din aceste scrapere e activat
    needs_title = any(
        ADDON.getSetting(f'use_{scraper}') == 'true' 
        for scraper in title_based_scrapers
    )
    
    if needs_title:
        try:
            url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
            data = get_json(url)
            res = data.get('movie_results', []) or data.get('tv_results', [])
            if res:
                extra_title = res[0].get('title') or res[0].get('name')
                dt = res[0].get('release_date') or res[0].get('first_air_date')
                extra_year = dt[:4] if dt else ""
                log(f"[SCRAPER] Title resolved: '{extra_title}' ({extra_year})")
        except Exception as e:
            log(f"[SCRAPER] Could not resolve title from TMDB: {e}")
    
    # =========================================================
    # MAPARE PROVIDERI
    # =========================================================
# Mapare PROVIDERI CU ALIASURI (Pentru notificarea de scanare)
    providers_map = {
        # Sooti -> SlowNow (deja rezolvat în funcția dedicată, dar eticheta e SlowNow)
        'sooti': ('SlowNow', lambda: scrape_sooti(imdb_id, content_type, season, episode)),
        # Nuvio -> Trimitem 'NotNow' ca label
        'nuvio': ('NotNow', lambda: _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'NotNow', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        # WebStreamr -> Trimitem 'WebNow' ca label
        'webstreamr': ('WebNow', lambda: _scrape_json_provider("https://webstreamr.hayd.uk", 'stream', 'WebNow', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        # StreamVix -> Trimitem 'StreamNow' ca label
        'streamvix': ('StreamNow', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamNow', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        # XDMovies -> SmileNow (funcția scrape_xdmovies am modificat-o anterior să returneze SmileNow)
        'xdmovies': ('SmileNow', lambda: scrape_xdmovies(imdb_id, content_type, season, episode)),
        # Ceilalți provideri
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'rogflix': ('Rogflix', lambda: scrape_rogflix(imdb_id, content_type, season, episode)),
        'vega': ('Vega', lambda: _scrape_json_provider("https://vega.vflix.life", 'stream', 'Vega', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'vidzee': ('Vidzee', lambda: _scrape_json_provider("https://vidzee.vflix.life", 'direct', 'Vidzee', imdb_id, content_type, season, episode, all_streams, seen_urls)),
        'hdhub4u': ('HDHub4u', lambda: scrape_hdhub4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'mkvcinemas': ('MKVCinemas', lambda: scrape_mkvcinemas(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'moviesdrive': ('MoviesDrive', lambda: scrape_moviesdrive(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
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
        return [], [], False

    for idx, (pid, pname, pfunc) in enumerate(to_run):
        if progress_callback: 
            should_continue = progress_callback(int(((idx+1)/total)*80)+10, pname)
            if should_continue is False: 
                log(f"[SCRAPER] Căutare oprită de utilizator (Cancel).")
                was_canceled = True
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

    return all_streams, failed_providers, was_canceled