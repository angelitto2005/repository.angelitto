import requests
import xbmc
import re
import json
import base64
import time
import random
import datetime
import threading
import concurrent.futures
from urllib.parse import urlencode, quote, urlparse
from resources.lib.config import BASE_URL, API_KEY, ADDON, get_headers, get_random_ua
from resources.lib.utils import get_json, clean_text
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === SESSION POOLING PENTRU PERFORMANȚĂ ===
# Refolosește conexiunile TCP în loc să creeze una nouă pentru fiecare request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =============================================================================
# CONSTANTE GLOBALE
# =============================================================================
MAX_WORKERS = 10  # Numărul maxim de thread-uri paralele

def get_session():
    """Returnează o sesiune requests optimizată cu connection pooling."""
    session = requests.Session()
    
    # Retry automat pentru erori temporare
    retry_strategy = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504],
    )
    
    adapter = HTTPAdapter(
        pool_connections=20,
        pool_maxsize=20,
        max_retries=retry_strategy
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# Sesiune globală pentru refolosire
_global_session = None

def get_shared_session():
    """Returnează sesiunea partajată (thread-safe pentru citire)."""
    global _global_session
    if _global_session is None:
        _global_session = get_session()
    return _global_session


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
# FILTRARE CALITATE - PENTRU UI (NU PENTRU CĂUTARE!)
# =============================================================================

def _get_quality_priority(quality_str):
    """
    Returnează prioritatea calității pentru sortare (mai mare = mai bun).
    """
    if not quality_str:
        return 0
    
    q = quality_str.upper()
    
    if '4K' in q or '2160' in q or 'UHD' in q:
        return 4
    elif '1080' in q:
        return 3
    elif '720' in q:
        return 2
    elif '480' in q or '360' in q or 'SD' in q:
        return 1
    else:
        return 0


def _normalize_quality(quality_str):
    """
    Normalizează calitatea la format standard.
    """
    if not quality_str:
        return 'SD'
    
    q = quality_str.upper()
    
    if '4K' in q or '2160' in q or 'UHD' in q:
        return '4K'
    elif '1080' in q:
        return '1080p'
    elif '720' in q:
        return '720p'
    else:
        return 'SD'


def filter_streams_for_display(streams):
    """
    Filtrează streamurile pentru AFIȘARE bazat pe setările curente.
    Apelează această funcție de fiecare dată când afișezi lista!
    
    Returnează: (filtered_streams, stats_dict)
    """
    if not streams:
        return [], {'total': 0, '4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'filtered': 0}
    
    # Citește setările ACUM (la momentul afișării)
    exclude_4k = ADDON.getSetting('exclude_4k') == 'true'
    exclude_1080p = ADDON.getSetting('exclude_1080p') == 'true'
    exclude_720p = ADDON.getSetting('exclude_720p') == 'true'
    exclude_sd = ADDON.getSetting('exclude_sd') == 'true'
    sort_by_quality = ADDON.getSetting('sort_by_quality') == 'true'
    
    # Statistici pentru toate calitățile
    stats = {'total': len(streams), '4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'filtered': 0}
    
    # Numără toate calitățile (înainte de filtrare)
    for stream in streams:
        normalized = _normalize_quality(stream.get('quality', 'SD'))
        stats[normalized] = stats.get(normalized, 0) + 1
    
    # Dacă nu e nimic de exclus, returnează toate
    if not any([exclude_4k, exclude_1080p, exclude_720p, exclude_sd]):
        if sort_by_quality:
            sorted_streams = sorted(streams, key=lambda x: _get_quality_priority(x.get('quality', 'SD')), reverse=True)
            return sorted_streams, stats
        return streams, stats
    
    # Construiește set de calități excluse
    excluded = set()
    if exclude_4k:
        excluded.add('4K')
    if exclude_1080p:
        excluded.add('1080p')
    if exclude_720p:
        excluded.add('720p')
    if exclude_sd:
        excluded.add('SD')
    
    # Filtrează
    filtered = []
    for stream in streams:
        normalized = _normalize_quality(stream.get('quality', 'SD'))
        if normalized not in excluded:
            filtered.append(stream)
    
    stats['filtered'] = len(streams) - len(filtered)
    
    # Sortare
    if sort_by_quality and filtered:
        filtered = sorted(filtered, key=lambda x: _get_quality_priority(x.get('quality', 'SD')), reverse=True)
    
    log(f"[FILTER-UI] Display filter: {len(streams)} total -> {len(filtered)} shown (excluded {stats['filtered']})")
    
    return filtered, stats


def get_quality_stats(streams):
    """
    Returnează statistici despre calități pentru afișare în UI.
    Util pentru a arăta "4K: 5 | 1080p: 12 | 720p: 8 | SD: 3"
    """
    stats = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0}
    
    for stream in streams:
        normalized = _normalize_quality(stream.get('quality', 'SD'))
        stats[normalized] = stats.get(normalized, 0) + 1
    
    return stats


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
        base_name = title_query if title_query else f"TMDb:{tmdb_id}"
        
        if year_query:
            display_name = f"[B][COLOR FFFDBD01]{base_name} ({year_query})[/COLOR][/B]"
        else:
            display_name = f"[B][COLOR FFFDBD01]{base_name}[/COLOR][/B]"

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
        if start_pos == -1: 
            log("[VIXSRC] Nu am găsit masterPlaylist")
            return None
            
        json_start = content.find('{', start_pos)
        if json_start == -1: 
            return None
        
        brace_count = 0
        json_end = -1
        for i, char in enumerate(content[json_start:], start=json_start):
            if char == '{': brace_count += 1
            elif char == '}': 
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end == -1: 
            return None
            
        json_str = content[json_start:json_end]
        json_str = re.sub(r'([{,])\s*([a-zA-Z0-9_-]+)\s*:', r'\1"\2":', json_str)
        json_str = json_str.replace("'", '"')
        json_str = re.sub(r',(\s*})', r'\1', json_str)
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            log(f"[VIXSRC] JSON parse error: {e}")
            return None

        base_url = data.get('url')
        params = data.get('params', {})
        
        if not base_url: 
            log("[VIXSRC] Nu am găsit URL în JSON")
            return None
            
        params['h'] = '1'
        params['lang'] = 'en'
        sep = '&' if '?' in base_url else '?'
        final_url = f"{base_url}{sep}{urlencode(params)}"
        
        final_url_with_headers = build_stream_url(final_url, referer=base_ref)
        
        # ===== FIX: Returnează obiect complet validat =====
        result = {
            'name': 'VixSrc | HLS',
            'url': final_url_with_headers,
            'title': display_name,
            'quality': '1080p',
            'info': ''
        }
        
        log(f"[VIXSRC] ✓ Stream găsit: {final_url[:50]}...")
        return result
        
    except Exception as e:
        log(f"[VIXSRC] Eroare: {e}")
        return None

def scrape_sooti(imdb_id, content_type, season=None, episode=None):
    """
    Scraper pentru Sooti (Alias: SlowNow).
    V3 - Extragere corectă cu source_provider separat.
    """
    if ADDON.getSetting('use_sooti') == 'false':
        return None

    try:
        sooti_config_json = {
            "DebridServices": [{"provider": "httpstreaming", "http4khdhub": True, "httpHDHub4u": True, "httpUHDMovies": True, "httpMoviesDrive": True, "httpMKVCinemas": True, "httpMalluMv": True, "httpCineDoze": True, "httpVixSrc": True}],
            "Languages": [], "Scrapers": [], "IndexerScrapers": [], "minSize": 0, "maxSize": 200, "ShowCatalog": False, "DebridProvider": "httpstreaming"
        }
        encoded_config = quote(json.dumps(sooti_config_json))
        
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
                    if 'streams' in data and data['streams']:
                        found_streams = []
                        
                        for s in data['streams']:
                            url = s.get('url')
                            if not url:
                                continue
                            
                            raw_name = s.get('name', '')
                            raw_title = s.get('title', '')
                            
                            # =================================================
                            # 1. EXTRAGE CALITATEA
                            # =================================================
                            quality = None
                            
                            # 1.1 Câmpul 'resolution' direct
                            resolution = s.get('resolution', '').lower()
                            if resolution:
                                if resolution in ['2160p', '4k', 'uhd']:
                                    quality = '4K'
                                elif resolution == '1080p':
                                    quality = '1080p'
                                elif resolution == '720p':
                                    quality = '720p'
                                elif resolution in ['480p', '360p']:
                                    quality = '480p'
                                elif resolution in ['auto', 'other', 'unknown']:
                                    quality = 'SD'
                            
                            # 1.2 Câmpul 'quality' direct
                            if not quality:
                                q_field = s.get('quality', '').lower()
                                if q_field:
                                    if '4k' in q_field or '2160' in q_field:
                                        quality = '4K'
                                    elif '1080' in q_field:
                                        quality = '1080p'
                                    elif '720' in q_field:
                                        quality = '720p'
                                    elif 'unknown' in q_field:
                                        quality = 'SD'
                            
                            # 1.3 Extrage din 'name' după \n
                            if not quality and '\n' in raw_name:
                                name_parts = raw_name.split('\n')
                                if len(name_parts) >= 2:
                                    qual_part = name_parts[-1].strip().lower()
                                    if qual_part in ['4k', '2160p', 'uhd']:
                                        quality = '4K'
                                    elif qual_part == '1080p':
                                        quality = '1080p'
                                    elif qual_part == '720p':
                                        quality = '720p'
                                    elif qual_part in ['480p', '360p', 'sd']:
                                        quality = '480p'
                                    elif qual_part in ['auto', 'other']:
                                        quality = 'SD'
                            
                            # 1.4 Fallback
                            if not quality:
                                quality = _extract_quality_from_string(raw_title)
                            
                            if not quality:
                                quality = 'SD'
                            
                            # =================================================
                            # 2. EXTRAGE SURSA INTERNĂ (UHDMovies, MoviesDrive, etc)
                            # =================================================
                            source_provider = ""
                            
                            # 2.1 Din title după ultimul "|"
                            if '|' in raw_title:
                                last_part = raw_title.split('|')[-1].strip()
                                last_part = re.sub(r'[^\w\s-]', '', last_part).strip()
                                if last_part and len(last_part) < 25:
                                    source_provider = last_part
                            
                            # 2.2 Din bingeGroup
                            if not source_provider:
                                binge_group = s.get('behaviorHints', {}).get('bingeGroup', '')
                                if binge_group and '-' in binge_group:
                                    provider_part = binge_group.split('-')[-1].lower()
                                    provider_map = {
                                        'uhdmovies': 'UHDMovies',
                                        'moviesdrive': 'MoviesDrive',
                                        'mkvcinemas': 'MKVCinemas',
                                        'hdhub4u': 'HDHub4u',
                                        '4khdhub': '4KHDHub',
                                        'mallumv': 'MalluMV',
                                        'cinedoze': 'CineDoze',
                                        'vixsrc': 'VixSrc',
                                        'streams': ''
                                    }
                                    source_provider = provider_map.get(provider_part, provider_part.title())
                            
                            # =================================================
                            # 3. EXTRAGE SIZE
                            # =================================================
                            size = s.get('size', '')
                            if not size or size == 'null' or size == 'Unknown':
                                size_match = re.search(r'💾\s*([\d.]+\s*(?:GB|MB|TB))', raw_title, re.IGNORECASE)
                                if size_match:
                                    size = size_match.group(1)
                                else:
                                    size_match2 = re.search(r'([\d.]+)\s*(GB|MB|TB)', raw_title, re.IGNORECASE)
                                    if size_match2:
                                        size = f"{size_match2.group(1)} {size_match2.group(2).upper()}"
                            
                            if size:
                                size = size.strip()
                                if re.match(r'^\d+\.?\d*(GB|MB|TB)$', size, re.IGNORECASE):
                                    size = re.sub(r'(\d)(GB|MB|TB)', r'\1 \2', size, flags=re.IGNORECASE)
                            
                            # =================================================
                            # 4. EXTRAGE FILENAME
                            # =================================================
                            filename = s.get('behaviorHints', {}).get('filename', '')
                            if not filename:
                                filename = s.get('fullTitle', '')
                            if not filename:
                                if '\n' in raw_title:
                                    filename = raw_title.split('\n')[0].strip()
                                else:
                                    filename = raw_title
                            
                            filename = re.sub(r'[🇬🇧🇮🇳🇺🇸💾🔗]', '', filename).strip()
                            
                            # =================================================
                            # 5. CONSTRUIEȘTE OBIECTUL STREAM
                            # IMPORTANT: Punem source_provider ca câmp SEPARAT!
                            # =================================================
                            stream_obj = {
                                'name': 'SlowNow',  # Doar alias-ul principal
                                'url': build_stream_url(url, referer="https://vixsrc.to/") if 'vixsrc' in url else build_stream_url(url),
                                'quality': quality,
                                'title': filename,
                                'size': size,  # Câmp separat pentru size
                                'source_provider': source_provider,  # UHDMovies, MoviesDrive, etc
                                'info': '',
                                'provider_id': 'sooti'
                            }
                            
                            found_streams.append(stream_obj)
                        
                        log(f"[SOOTI] ✓ Succes! {len(found_streams)} surse găsite.")
                        return found_streams
                        
            except Exception as e:
                log(f"[SOOTI] Oglinda a eșuat ({e}). Trec la următoarea...")
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
    """Identifică numele host-ului din URL - VERSIUNE V3 cu TrashBytes și altele."""
    if not url:
        return 'Direct'
    
    url_lower = url.lower()
    
    # Ordinea contează - cele mai specifice primele!
    if 'pixeldrain.dev/api/file' in url_lower or 'pixeldrain.com/api/file' in url_lower:
        return 'PixelDrain'
    elif 'pixel.hubcdn' in url_lower:
        return 'HubPixel'
    elif 'trashbytes.net' in url_lower:
        return 'TrashBytes'
    elif 'awsdllaaa' in url_lower or 'aws-storage' in url_lower:
        return 'FastCloud'
    elif 'bbdownload.filesdl' in url_lower:
        if 'adl.php' in url_lower:
            return 'FastCloud-02'
        elif 'fdownload.php' in url_lower:
            return 'DirectDL'
        else:
            return 'FilesDL'
    elif 'busycdn' in url_lower or 'instant.busycdn' in url_lower:
        return 'InstantDL'
    elif 'r2.cloudflarestorage.com' in url_lower:
        return 'FSL-V2'
    elif 'r2.dev' in url_lower or 'pub-' in url_lower:
        return 'CloudR2'
    elif 'gpdl' in url_lower and 'hubcdn' in url_lower:
        return 'HubCDN'
    elif 'fsl-lover' in url_lower:
        return 'FSL-Lover'
    elif 'fsl-buckets' in url_lower or 'fsl.gdboka' in url_lower:
        return 'CDN'
    elif 'gdboka' in url_lower:
        return 'FastServer'
    elif 'polgen.buzz' in url_lower:
        return 'Flash'
    elif 'workers.dev' in url_lower:
        return 'CFWorker'
    elif 'hubcdn' in url_lower:
        return 'HubCDN'
    elif 'hubcloud' in url_lower:
        return 'HubCloud'
    elif 'gdflix' in url_lower:
        return 'GDFlix'
    elif 'filesdl' in url_lower:
        return 'FilesDL'
    elif 'gofile' in url_lower:
        return 'GoFile'
    elif 'mediafire' in url_lower:
        return 'MediaFire'
    elif 'mega.nz' in url_lower or 'mega.co' in url_lower:
        return 'MEGA'
    elif 'streamtape' in url_lower:
        return 'StreamTape'
    elif 'doodstream' in url_lower or 'dood.' in url_lower:
        return 'DoodStream'
    elif 'mixdrop' in url_lower:
        return 'MixDrop'
    elif 'upstream' in url_lower:
        return 'UpStream'
    elif 'buzzheavie' in url_lower:
        return 'BuzzHeavie'
    else:
        # Încearcă să extragă din domeniu
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace('www.', '')
            parts = domain.split('.')
            if parts and len(parts[0]) >= 2:
                # Capitalizează prima literă
                return parts[0].title()
        except:
            pass
        
        return 'Direct'


# =============================================================================
# HELPER: Verifică dacă URL-ul e stream direct (nu intermediar)
# =============================================================================

def _is_direct_video_url(url):
    """
    Verifică dacă URL-ul e un stream video direct (nu intermediar).
    """
    if not url:
        return False
    
    url_lower = url.lower()
    
    # Extensii video
    video_extensions = ['.mkv', '.mp4', '.avi', '.mov', '.webm', '.m3u8', '.ts']
    if any(ext in url_lower for ext in video_extensions):
        return True
    
    # Domenii de stocare directă
    direct_hosts = [
        'r2.dev', 'pub-', 'r2.cloudflarestorage',
        'aws-storage', 'awsdllaaa',
        'pixeldrain.dev/api/file/',
        'pixeldrain.com/api/file/',
        'busycdn.xyz',
        'instant.busycdn',
        'workers.dev',
        'storage.googleapis.com',
    ]
    
    if any(h in url_lower for h in direct_hosts):
        return True
    
    # Token-uri de download (exclude intermediarii)
    if '?token=' in url_lower or '&token=' in url_lower:
        if 'adl.php' not in url_lower and 'fdownload.php' not in url_lower:
            return True
    
    return False


def _resolve_intermediate_url(url, timeout=8):
    """
    Rezolvă URL-uri intermediare (adl.php, fdownload.php) la stream-ul final.
    Returnează URL-ul final sau None dacă eșuează.
    """
    if not url:
        return None
    
    url_lower = url.lower()
    
    # Lista de URL-uri intermediare care necesită rezolvare
    intermediate_patterns = [
        'adl.php',
        'fdownload.php',
        '/dl.php',
        '/download.php',
    ]
    
    # Dacă nu e intermediar, returnează ca atare
    if not any(p in url_lower for p in intermediate_patterns):
        return url
    
    try:
        headers = {
            'User-Agent': get_random_ua(),
            'Referer': 'https://filesdl.top/',
            'Accept': '*/*',
        }
        
        # Încearcă HEAD request
        try:
            r = requests.head(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
            final_url = r.url
            
            if r.status_code == 200 and _is_direct_video_url(final_url):
                log(f"[RESOLVE-URL] ✓ HEAD: {url[:40]}... -> {final_url[:60]}...")
                return final_url
        except:
            pass
        
        # Fallback: GET request
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True, stream=True)
            final_url = r.url
            r.close()
            
            if r.status_code == 200:
                log(f"[RESOLVE-URL] ✓ GET: {url[:40]}... -> {final_url[:60]}...")
                return final_url
        except:
            pass
        
        log(f"[RESOLVE-URL] ✗ Failed: {url[:50]}...")
        return None
        
    except Exception as e:
        log(f"[RESOLVE-URL] ✗ Error: {e}")
        return None


# =============================================================================
# PROCESOR GDFLIX PAGES
# =============================================================================

def _process_gdflix_page(url, quality_label, title_label, branch_label):
    """
    Procesează paginile GDFlix și extrage link-uri directe.
    V2 - Cu server names corecte.
    """
    streams = []
    log(f"[GDFLIX-PAGE] Processing: {url}")
    
    try:
        headers = get_headers()
        r = requests.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
        
        if r.status_code != 200:
            log(f"[GDFLIX-PAGE] Error: Status {r.status_code}")
            return []
        
        html = r.text
        final_url = r.url
        log(f"[GDFLIX-PAGE] Final URL: {final_url}")
        
        # Extrage titlu din pagină
        page_title = title_label
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            raw_title = title_match.group(1).strip()
            raw_title = re.sub(r'\s*-\s*GDFlix.*', '', raw_title, flags=re.IGNORECASE)
            raw_title = re.sub(r'\s*\|\s*GDFlix.*', '', raw_title, flags=re.IGNORECASE)
            if raw_title and len(raw_title) > 5:
                page_title = raw_title
        
        # Extrage calitatea din titlu
        if not quality_label or quality_label == 'SD':
            quality_label = _extract_quality_from_string(page_title) or 'SD'
        
        # =========================================================
        # EXTRAGE MĂRIMEA - GDFlix V3 (FIX pentru 872.27MB fără spațiu)
        # =========================================================
        page_size = ""
        
        # Pattern 1: list-group-item...>Size : 872.27MB</li> (FĂRĂ spațiu)
        size_match = re.search(r'list-group-item[^>]*>[^<]*Size\s*:\s*([\d.,]+)(GB|MB|TB)', html, re.IGNORECASE)
        if size_match:
            page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
            log(f"[GDFLIX-PAGE] Size P1 (list-item no-space): {page_size}")
        
        # Pattern 2: >Size : 872.27MB (FĂRĂ spațiu, general)
        if not page_size:
            size_match = re.search(r'>Size\s*:\s*([\d.,]+)(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                log(f"[GDFLIX-PAGE] Size P2 (no-space): {page_size}")
        
        # Pattern 3: >Size : 9.24 GB (CU spațiu)
        if not page_size:
            size_match = re.search(r'>Size\s*:\s*([\d.,]+)\s+(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                log(f"[GDFLIX-PAGE] Size P3 (with-space): {page_size}")
        
        # Pattern 4: "Size : 872.27MB" oriunde în text
        if not page_size:
            size_match = re.search(r'Size\s*:\s*([\d.,]+)\s*(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                log(f"[GDFLIX-PAGE] Size P4 (anywhere): {page_size}")
        
        # Pattern 5: Căutare brută pentru (număr)(GB|MB)
        if not page_size:
            # Caută în zona cu list-group-item
            list_items = re.findall(r'<li[^>]*list-group-item[^>]*>([^<]+)</li>', html, re.IGNORECASE)
            for item in list_items:
                if 'size' in item.lower():
                    size_match = re.search(r'([\d.,]+)\s*(GB|MB|TB)', item, re.IGNORECASE)
                    if size_match:
                        page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                        log(f"[GDFLIX-PAGE] Size P5 (list-item extract): {page_size}")
                        break
        
        if page_size:
            log(f"[GDFLIX-PAGE] ✓ Final size: {page_size}")
        else:
            log(f"[GDFLIX-PAGE] ✗ No size found in page!")
        
        seen_urls = set()
        
        # =========================================================
        # EXCLUDE GOOGLE
        # =========================================================
        google_patterns = ['googleusercontent.com', 'googlevideo.com', 'photos.google.com']
        
        # =========================================================
        # 1. CLOUD DOWNLOAD R2 (pub-*.r2.dev)
        # =========================================================
        r2_pattern = r'href=["\']?(https://pub-[a-z0-9]+\.r2\.dev/[^"\'>\s]+)["\']?'
        r2_matches = re.findall(r2_pattern, html, re.IGNORECASE)
        
        for r2_url in r2_matches:
            if r2_url in seen_urls:
                continue
            if any(g in r2_url.lower() for g in google_patterns):
                continue
            seen_urls.add(r2_url)
            
            display = f"MKV | CloudR2"
            if page_size:
                display += f" | {page_size}"
            
            streams.append({
                'name': display,
                'url': build_stream_url(r2_url),
                'quality': quality_label,
                'title': page_title,
                'size': page_size,
                'info': branch_label or ""
            })
            log(f"[GDFLIX-PAGE] ✓ R2: {r2_url[:60]}...")
        
        # =========================================================
        # 2. INSTANT DL (busycdn)
        # =========================================================
        instant_pattern = r'href=["\']?(https://instant\.busycdn\.xyz/[^"\'>\s]+)["\']?'
        instant_matches = re.findall(instant_pattern, html, re.IGNORECASE)
        
        for instant_url in instant_matches:
            if instant_url in seen_urls:
                continue
            seen_urls.add(instant_url)
            
            display = f"MKV | InstantDL"
            if page_size:
                display += f" | {page_size}"
            
            streams.append({
                'name': display,
                'url': build_stream_url(instant_url),
                'quality': quality_label,
                'title': page_title,
                'size': page_size,
                'info': branch_label or ""
            })
            log(f"[GDFLIX-PAGE] ✓ Instant: {instant_url[:60]}...")
        
        # =========================================================
        # 3. PIXELDRAIN
        # =========================================================
        # Pattern pentru iframe
        pd_iframe = re.search(r'src=["\']https://pixeldrain\.dev/u/([a-zA-Z0-9]+)\?embed["\']', html, re.IGNORECASE)
        if pd_iframe:
            pd_id = pd_iframe.group(1)
            api_url = f"https://pixeldrain.dev/api/file/{pd_id}"
            if api_url not in seen_urls:
                seen_urls.add(api_url)
                
                display = f"MKV | PixelDrain"
                if page_size:
                    display += f" | {page_size}"
                
                streams.append({
                    'name': display,
                    'url': build_stream_url(api_url),
                    'quality': quality_label,
                    'title': page_title,
                    'size': page_size,
                    'info': branch_label or ""
                })
                log(f"[GDFLIX-PAGE] ✓ PixelDrain: {api_url}")
        
        # Pattern pentru href (backup)
        pd_href = re.search(r'href=["\']https://pixeldrain\.dev/u/([a-zA-Z0-9]+)["\']', html, re.IGNORECASE)
        if pd_href:
            pd_id = pd_href.group(1)
            api_url = f"https://pixeldrain.dev/api/file/{pd_id}"
            if api_url not in seen_urls:
                seen_urls.add(api_url)
                
                display = f"MKV | PixelDrain"
                if page_size:
                    display += f" | {page_size}"
                
                streams.append({
                    'name': display,
                    'url': build_stream_url(api_url),
                    'quality': quality_label,
                    'title': page_title,
                    'size': page_size,
                    'info': branch_label or ""
                })
                log(f"[GDFLIX-PAGE] ✓ PixelDrain (href): {api_url}")
        
        log(f"[GDFLIX-PAGE] Found {len(streams)} streams")
        
    except Exception as e:
        log(f"[GDFLIX-PAGE] Error: {e}", xbmc.LOGERROR)
    
    return streams


def _is_video_url(url):
    """
    Verifică dacă un URL pare a fi un link video direct.
    V2 - FIX: Exclude GoFile pages și GDFlix intermediate pages.
    """
    if not url or not url.startswith('http'):
        return False
    
    url_lower = url.lower()
    
    # =================================================================
    # EXCLUDERE PAGINI INTERMEDIARE (NU SUNT STREAMURI!)
    # =================================================================
    intermediate_pages = [
        'gofile.io/d/',           # GoFile download pages
        'gdflix.dev/file/',       # GDFlix v1
        'gdflix.net/file/',       # GDFlix v2
        'gdflix.filesdl.in/file/',# GDFlix FilesDL variant
        '/zfile/',                # GDFlix zfile pages
        'mulitup.workers.dev',    # Multiup mirrors (typo intentional - site-ul)
        't.me/',                  # Telegram
        'telegram',
    ]
    
    if any(page in url_lower for page in intermediate_pages):
        return False
    
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
        'bit.ly',
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
    
    # =================================================================
    # STREAMURI DIRECTE CUNOSCUTE
    # =================================================================
    
    # Verifică extensii video directe
    video_extensions = ['.mkv', '.mp4', '.avi', '.mov', '.webm', '.m3u8', '.ts']
    if any(ext in url_lower for ext in video_extensions):
        return True
    
    # Domenii de hosting video DIRECTE (nu pages!)
    direct_video_hosts = [
        'pixeldrain.com/api/file/',   # PixelDrain API (direct)
        'pixeldrain.dev/api/file/',   # PixelDrain API v2 (direct)
        'pixel.hubcdn',               # HubCDN Pixel
        'hubcdn.fans/dl',             # HubCDN direct
        'gpdl',                        # GPDL
        'r2.dev',                      # Cloudflare R2
        'pub-',                        # Cloudflare R2 public
        'r2.cloudflarestorage.com',   # Cloudflare R2 storage
        'fsl-buckets',                # FSL buckets
        'fsl-lover',                  # FSL lover
        'fsl.gdboka',                 # FSL gdboka
        'gdboka',                     # GDBoka
        'polgen.buzz',                # Polgen
        'workers.dev',                # CF Workers (direct links)
        'aws-storage',                # AWS storage (direct)
        'awsdllaaa',                  # AWS variant
        'bbdownload.filesdl',         # FilesDL direct download
        'busycdn.xyz',                # BusyCDN (instant DL)
        'instant.busycdn',            # BusyCDN instant
    ]
    
    if any(host in url_lower for host in direct_video_hosts):
        return True
    
    # Verifică parametri token/id (indicator de link direct)
    if '?token=' in url_lower or '&token=' in url_lower:
        if 'google' not in url_lower and 'facebook' not in url_lower:
            # Exclude dacă e pagină intermediară
            if not any(page in url_lower for page in intermediate_pages):
                return True
    
    if '?id=' in url_lower or '&id=' in url_lower:
        # Verifică că nu e fdownload.php sau adl.php (care sunt de fapt directe!)
        if 'fdownload.php' in url_lower or 'adl.php' in url_lower:
            return True
        if 'google' not in url_lower and 'facebook' not in url_lower:
            if not any(page in url_lower for page in intermediate_pages):
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
            
            # Extragere titlu și mărime din HubCloud
            if any(x in url_lower or x in final_url.lower() for x in ['hubcloud', 'vcloud']):
                title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    if any(x in raw_title.lower() for x in ['.mkv', '.mp4', 'x264', 'x265', 'hevc', 'bluray', '1080p', '720p']):
                        current_title = raw_title
                        log(f"[RESOLVE] Title: {current_title[:50]}...")
                
                # Extrage mărimea din pagină (dacă există)
                size_match = re.search(r'>Size\s*:\s*([\d.]+)\s*(GB|MB)', content, re.IGNORECASE)
                if not size_match:
                    size_match = re.search(r'File Size\s*:\s*([\d.]+)\s*(GB|MB)', content, re.IGNORECASE)
                if not size_match:
                    size_match = re.search(r'([\d.]+)\s*(GB|MB)(?:</|<br)', content, re.IGNORECASE)
                
                if size_match:
                    current_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                    log(f"[RESOLVE] Size: {current_size}")

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


# =============================================================================
# SCRAPER HDHUB4U, MKVCINEMAS, MOVIESDRIVE - OPTIMIZAT V2 (FULL PARALLEL)
# =============================================================================

# =============================================================================
# FUNCȚIA LIPSĂ: _get_moviesdrive_base
# =============================================================================

def _get_moviesdrive_base():
    """
    Determină domeniul activ MoviesDrive.
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


# =============================================================================
# FUNCȚIA REPARATĂ: _process_filesdl_cloud_page (V5 - REGEX FIX)
# =============================================================================

def _process_filesdl_cloud_page(url, quality_label, title_label, info_label):
    """
    Procesează paginile FilesDL Cloud cu REZOLVARE intermediari.
    V8 - FIX: Size duplicat, Google exclus, server_name corect.
    """
    streams = []
    log(f"[CLOUD] Processing: {url}")
    
    try:
        headers = get_headers()
        r = requests.get(url, headers=headers, timeout=12, verify=False)
        
        if r.status_code != 200:
            log(f"[CLOUD] Error loading page. Status: {r.status_code}")
            return []
            
        html = r.text
        
        # =========================================================
        # EXTRAGE TITLU
        # =========================================================
        page_title = title_label
        
        title_div = re.search(r"<div class='title'>([^<]+)</div>", html)
        if title_div:
            page_title = title_div.group(1).strip()
        
        if page_title == title_label:
            h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
            if h1_match:
                extracted = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
                if extracted and len(extracted) > 5:
                    page_title = extracted
        
        # Extrage calitatea din titlu
        if not quality_label or quality_label == 'SD':
            quality_label = _extract_quality_from_string(page_title) or 'SD'
        
        # =========================================================
        # EXTRAGE MĂRIME
        # =========================================================
        page_size = ""
        
        size_div = re.search(r"<div class='info'>Size:\s*([\d.]+\s*(?:GB|MB))</div>", html, re.IGNORECASE)
        if size_div:
            page_size = size_div.group(1).strip()
        
        if not page_size:
            size_match = re.search(r'Size[:\s]*([\d.]+)\s*(GB|MB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
        
        log(f"[CLOUD] Title: {page_title[:50]}, Size: {page_size}, Quality: {quality_label}")
        
        # =========================================================
        # EXTRAGE LINK-URI
        # =========================================================
        all_links = re.findall(
            r"<a\s+href='([^']+)'[^>]*class='([^']+)'[^>]*>([^<]+)</a>",
            html, re.IGNORECASE
        )
        
        if not all_links:
            all_links = re.findall(
                r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                html, re.IGNORECASE | re.DOTALL
            )
            all_links = [(u, '', t) for u, t in all_links]
        
        seen_urls = set()
        pending_resolves = []
        
        # =========================================================
        # PROCESARE LINK-URI
        # =========================================================
        for link_url, link_class, link_text in all_links:
            if not link_url or not link_url.startswith('http'):
                continue
            
            link_lower = link_url.lower()
            text_clean = re.sub(r'<[^>]+>', '', link_text).strip()
            
            # =================================================================
            # SKIP: Pagini intermediare, Google, etc
            # =================================================================
            skip_patterns = [
                'gofile.io/d/',
                'gdflix.dev/file/',
                'gdflix.net/file/',
                'gdflix.filesdl.in/file/',
                't.me/',
                'telegram',
                'javascript:',
                'mailto:',
                '/login',
                'facebook.com',
                'twitter.com',
                # GOOGLE - EXCLUDEM COMPLET!
                'googleusercontent.com',
                'googlevideo.com',
                'photos.google.com',
                'drive.google.com',
                'docs.google.com',
            ]
            
            if any(skip in link_lower for skip in skip_patterns):
                log(f"[CLOUD] Skip: {link_url[:50]}...")
                continue
            
            if link_url in seen_urls:
                continue
            
            # =================================================================
            # IDENTIFICARE TIP LINK + SERVER NAME
            # =================================================================
            stream_url = None
            server_name = None
            needs_resolve = False
            
            # 1. Fast Cloud (AWS storage)
            if 'aws-storage' in link_lower or 'awsdllaaa' in link_lower:
                stream_url = link_url
                server_name = 'FastCloud'
            
            # 2. Direct Download (fdownload.php) - NECESITĂ REZOLVARE
            elif 'fdownload.php' in link_lower:
                stream_url = link_url
                server_name = 'DirectDL'
                needs_resolve = True
            
            # 3. Fast Cloud-02 (adl.php) - NECESITĂ REZOLVARE
            elif 'adl.php' in link_lower:
                stream_url = link_url
                server_name = 'FastCloud-02'
                needs_resolve = True
            
            # 4. R2 storage
            elif 'r2.dev' in link_lower or 'pub-' in link_lower:
                stream_url = link_url
                server_name = 'CloudR2'
            
            # 5. BusyCDN
            elif 'busycdn' in link_lower or 'instant.busycdn' in link_lower:
                stream_url = link_url
                server_name = 'InstantDL'
            
            # 6. PixelDrain
            elif 'pixeldrain' in link_lower:
                pd_match = re.search(r'/u/([a-zA-Z0-9]+)', link_url)
                if pd_match:
                    stream_url = f"https://pixeldrain.dev/api/file/{pd_match.group(1)}"
                    server_name = 'PixelDrain'
            
            # 7. Workers.dev
            elif 'workers.dev' in link_lower:
                stream_url = link_url
                server_name = 'CFWorker'
            
            # 8. Alte link-uri cu clasă download/button
            elif 'download' in link_class.lower() or 'button' in link_class.lower():
                if _is_direct_video_url(link_url):
                    stream_url = link_url
                    
            # 8. Alte link-uri cu clasă download/button
            elif 'download' in link_class.lower() or 'button' in link_class.lower():
                if _is_direct_video_url(link_url):
                    stream_url = link_url
                    
                    # =========================================================
                    # FIX V2: EXTRAGE SERVER_NAME CORECT (fără size!)
                    # =========================================================
                    # PRIORITATE 1: Identifică din URL (cel mai sigur!)
                    server_name = _identify_host_from_url(link_url)
                    
                    # PRIORITATE 2: Dacă URL nu a dat rezultat bun, încearcă din text
                    if server_name == 'Direct' or not server_name:
                        # Curăță text-ul de mărime
                        cleaned_text = text_clean
                        # Elimină toate pattern-urile de mărime
                        cleaned_text = re.sub(r'[\d.,]+\s*(GB|MB|TB|gb|mb|tb)', '', cleaned_text, flags=re.IGNORECASE)
                        cleaned_text = re.sub(r'\([\d.,]+\s*\)', '', cleaned_text)  # Elimină (5.28) etc
                        cleaned_text = cleaned_text.replace('-', ' ').strip()
                        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                        
                        # Ia primul cuvânt relevant
                        if cleaned_text and len(cleaned_text) >= 2:
                            skip_words = ['download', 'now', 'click', 'here', 'fast', 'direct', 
                                         'resumeble', 'resumable', 'cloud', 'link', 'button',
                                         'server', 'mirror', 'backup', '']
                            words = cleaned_text.split()
                            for word in words:
                                word_clean = word.strip()
                                if word_clean.lower() not in skip_words:
                                    if len(word_clean) >= 2 and len(word_clean) <= 20:
                                        # Verifică să nu fie număr sau mărime
                                        if not re.match(r'^[\d.,]+$', word_clean):
                                            server_name = word_clean.title()
                                            break
                    
                    # FALLBACK FINAL: Dacă tot nu avem, pune "Direct"
                    if not server_name or server_name in ['', 'Direct']:
                        server_name = 'Direct'
                    # =========================================================
            
            # 9. Link-uri directe fără clasă specifică dar cu URL cunoscut
            elif not stream_url:
                # Verifică dacă URL-ul e de la un host cunoscut
                potential_server = _identify_host_from_url(link_url)
                if potential_server != 'Direct':
                    stream_url = link_url
                    server_name = potential_server
            
            # =================================================================
            # ADAUGĂ STREAM
            # =================================================================
            if stream_url and server_name:
                seen_urls.add(link_url)
                
                if needs_resolve:
                    pending_resolves.append((stream_url, server_name, quality_label, page_title, page_size))
                else:
                    seen_urls.add(stream_url)
                    
                    # Construiește display name FĂRĂ DUPLICARE
                    display = f"MKV | {server_name}"
                    if page_size and page_size not in display:
                        display += f" | {page_size}"
                    
                    streams.append({
                        'name': display,
                        'url': build_stream_url(stream_url),
                        'quality': quality_label,
                        'title': page_title,
                        'size': page_size,
                        'info': info_label or ""
                    })
                    log(f"[CLOUD] ✓ {server_name}: {stream_url[:60]}...")
        
        # =========================================================
        # REZOLVĂ URL-URILE INTERMEDIARE ÎN PARALEL
        # =========================================================
        if pending_resolves:
            log(f"[CLOUD] Resolving {len(pending_resolves)} intermediate URLs...")
            
            def resolve_task(args):
                raw_url, srv_name, qual, title, size = args
                
                resolved_url = _resolve_intermediate_url(raw_url)
                
                if resolved_url:
                    # Verifică că nu e Google
                    if 'google' in resolved_url.lower():
                        log(f"[CLOUD] ✗ Resolved to Google, skip: {resolved_url[:50]}...")
                        return None
                    
                    display = f"MKV | {srv_name}"
                    if size and size not in display:
                        display += f" | {size}"
                    
                    return {
                        'name': display,
                        'url': build_stream_url(resolved_url),
                        'quality': qual,
                        'title': title,
                        'size': size,
                        'info': info_label or ""
                    }
                else:
                    log(f"[CLOUD] ✗ Failed to resolve: {raw_url[:50]}...")
                    return None
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(resolve_task, args) for args in pending_resolves]
                
                for f in concurrent.futures.as_completed(futures, timeout=15):
                    try:
                        result = f.result()
                        if result:
                            url_check = result['url'].split('|')[0]
                            if url_check not in seen_urls:
                                streams.append(result)
                                seen_urls.add(url_check)
                    except Exception as e:
                        log(f"[CLOUD] Resolve error: {e}")

    except Exception as e:
        log(f"[CLOUD] Critical Error: {e}", xbmc.LOGERROR)

    log(f"[CLOUD] Returning {len(streams)} streams")
    return streams

# =============================================================================
# _resolve_hdhub_redirect_parallel - FIX pentru GDFlix pages
# =============================================================================

def _resolve_hdhub_redirect_parallel(url, depth=0, parent_title=None, branch_label=None, executor=None):
    """
    Rezolvă lanțul HDHub4u/MKVCinemas CU PARALELIZARE.
    V4 - FIX: Detectează și returnează GDFlix pages pentru procesare separată.
    """
    if not url or depth > 8: 
        return []
    
    url_lower = url.lower()
    
    # EXCLUDERE DOMENII PROBLEMATICE
    blocked_domains = [
        'gadgetsweb', 'googletagmanager', 'google-analytics', 'facebook.com', 
        'twitter.com', 'instagram.com', 'yandex', 'arc.io', 'ads.', 
        'recaptcha', 'captcha', 'disqus', 'gravatar', 'filepress',
        'bit.ly', 'telegram', 't.me',
        'gofile.io/d/',  # GoFile pages - SKIP!
    ]
    
    if any(blocked in url_lower for blocked in blocked_domains):
        return []
    
    # Exclude fișiere non-video
    if any(ext in url_lower for ext in ['.zip', '.rar', '.css', '.js', '.png', '.jpg', '.gif', '.ico']):
        if 'vcloud.zip' not in url_lower:
            return []
    
    # =========================================================
    # VERIFICĂ PAGINI SPECIALE
    # =========================================================
    
    # Cloud Page
    if 'filesdl' in url_lower and '/cloud/' in url_lower:
        q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
        return [('CloudPage', url, parent_title, q, branch_label)]
    
    # GDFlix Page (toate variantele)
    gdflix_patterns = [
        'gdflix.dev/file/',
        'gdflix.net/file/',
        'gdflix.filesdl.in/file/',
    ]
    if any(p in url_lower for p in gdflix_patterns):
        q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
        return [('GDFlixPage', url, parent_title, q, branch_label)]
    
    # Verifică dacă e link video final
    if _is_video_url(url):
        wrapper_indicators = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 
                              'hblinks', 'inventoryidea', 'hubdrive', 'hubstream', 
                              '/drive/', '/file/', 'vcloud.zip']
        
        if not any(w in url_lower for w in wrapper_indicators):
            host = _identify_host_from_url(url)
            q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
            
            if 'pixeldrain' in url_lower:
                pd_id = re.search(r'/u/([a-zA-Z0-9]+)', url)
                if pd_id:
                    api_url = f"https://pixeldrain.dev/api/file/{pd_id.group(1)}"
                    return [('PixelDrain', api_url, parent_title, q, branch_label)]
            
            return [(host, url, parent_title, q, branch_label)]
    
    # =========================================================
    # DOMENII WRAPPER - procesare recursivă
    # =========================================================
    wrapper_domains = [
        'hubdrive', 'hubstream', 'drive', 'hubcloud', 'katmovie', 
        'gamerxyt', 'cryptoinsights', 'hblinks', 'inventoryidea', 'hubcdn', 
        'hubfiles', 'carnewz', 'vcloud.zip'
    ]
    
    found_urls = []
    seen_urls = set()
    current_title = parent_title
    current_branch = branch_label

    if any(x in url_lower for x in wrapper_domains):
        try:
            log(f"[RESOLVE] D{depth}: {url[:60]}...")
            
            s = requests.Session()
            headers = {
                'User-Agent': get_random_ua(),
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
            
            # VCLOUD: Extrage URL din JavaScript
            if 'vcloud.zip' in url_lower or 'vcloud.zip' in final_url.lower():
                js_url_match = re.search(r"var\s+url\s*=\s*['\"]([^'\"]+)['\"]", content)
                if js_url_match:
                    extracted_url = js_url_match.group(1)
                    log(f"[RESOLVE] VCloud JS: {extracted_url[:50]}...")
                    if extracted_url not in seen_urls:
                        seen_urls.add(extracted_url)
                        sub_results = _resolve_hdhub_redirect_parallel(extracted_url, depth + 1, current_title, current_branch, executor)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
            
            # Extragere titlu ȘI MĂRIME din HubCloud
            if any(x in url_lower or x in final_url.lower() for x in ['hubcloud', 'vcloud']):
                title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    if any(x in raw_title.lower() for x in ['.mkv', '.mp4', 'x264', 'x265', 'hevc', 'bluray', '1080p', '720p']):
                        current_title = raw_title
                        log(f"[RESOLVE] Title: {current_title[:50]}...")
                
                # =========================================================
                # EXTRAGE MĂRIMEA DIN HUBCLOUD
                # =========================================================
                size_extracted = ""
                
                # Pattern 1: File Size<i id="size">1.16 GB</i>
                size_match = re.search(r'File Size<i[^>]*>([^<]+)</i>', content, re.IGNORECASE)
                if size_match:
                    size_extracted = size_match.group(1).strip()
                
                # Pattern 2: id="size">1.16 GB</i>
                if not size_extracted:
                    size_match = re.search(r'id="size">([^<]+)</i>', content, re.IGNORECASE)
                    if size_match:
                        size_extracted = size_match.group(1).strip()
                
                # Pattern 3: >Size : 1.16 GB<
                if not size_extracted:
                    size_match = re.search(r'>Size\s*:\s*([\d.]+\s*(?:GB|MB|TB))', content, re.IGNORECASE)
                    if size_match:
                        size_extracted = size_match.group(1).strip()
                
                # Dacă am găsit mărime, o adăugăm în branch
                if size_extracted:
                    # Normalizare (asigură spațiu între număr și unitate)
                    size_extracted = re.sub(r'(\d)(GB|MB|TB)', r'\1 \2', size_extracted, flags=re.IGNORECASE)
                    size_extracted = size_extracted.upper().replace('  ', ' ').strip()
                    
                    # Adaugă la branch dacă nu e deja acolo
                    if current_branch:
                        if size_extracted not in current_branch:
                            current_branch = f"{current_branch} [{size_extracted}]"
                    else:
                        current_branch = f"[{size_extracted}]"
                    
                    log(f"[RESOLVE] Size: {size_extracted}")

            # Verifică redirect final
            if _is_video_url(final_url):
                wrapper_check = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 'vcloud']
                if not any(w in final_url.lower() for w in wrapper_check):
                    host = _identify_host_from_url(final_url)
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    return [(host, final_url, current_title, q, current_branch)]

            # Bypass Cookie JS
            if 'stck(' in content:
                cookie_match = re.search(r"stck\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", content)
                if cookie_match:
                    c_n, c_v = cookie_match.groups()
                    s.cookies.set(c_n, c_v, domain=urlparse(url).netloc)
                    time.sleep(1)
                    r2 = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
                    content = r2.text

            # =========================================================
            # EXTRACTOR LINK-URI DIRECTE
            # =========================================================
            def add_direct_link(link):
                if link in seen_urls:
                    return
                
                link_lower = link.lower()
                
                # Skip GoFile pages
                if 'gofile.io/d/' in link_lower:
                    return
                
                # Check Cloud Page
                if 'filesdl' in link_lower and '/cloud/' in link_lower:
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    found_urls.append(('CloudPage', link, current_title, q, current_branch))
                    seen_urls.add(link)
                    log(f"[RESOLVE] ✓ Cloud Page: {link[:50]}...")
                    return
                
                # Check GDFlix Page
                if any(p in link_lower for p in ['gdflix.dev/file/', 'gdflix.net/file/', 'gdflix.filesdl.in/file/']):
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    found_urls.append(('GDFlixPage', link, current_title, q, current_branch))
                    seen_urls.add(link)
                    log(f"[RESOLVE] ✓ GDFlix Page: {link[:50]}...")
                    return
                
                blocked = ['googletagmanager', 'facebook', 'twitter', 'yandex', 'gadgetsweb', 
                          'disqus', 'gravatar', 'recaptcha', '.css', '.js', '.png', '.jpg', 
                          'filepress', 'bit.ly', 't.me', 'telegram']
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
                    return
                
                found_urls.append((host, link, current_title, q, current_branch))
                seen_urls.add(link)
                log(f"[RESOLVE] ✓ Direct: {host} -> {link[:50]}...")

            # Extrage din href
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', content)
            for href in all_hrefs:
                if href.startswith('//'):
                    href = 'https:' + href
                elif href.startswith('/') and not href.startswith('//'):
                    continue
                if href.startswith('http'):
                    add_direct_link(href)
            
            # Extrage din JavaScript
            js_patterns = [
                r'["\'](https?://[^"\']*\?token=[^"\']*)["\']',
                r'["\'](https?://[^"\']*\.mkv[^"\']*)["\']',
                r'["\'](https?://[^"\']*\.mp4[^"\']*)["\']',
                r'["\'](https?://[^"\']*r2\.dev[^"\']*)["\']',
                r'["\'](https?://[^"\']*r2\.cloudflarestorage\.com[^"\']*)["\']',
                r'["\'](https?://[^"\']*pixeldrain[^"\']*)["\']',
                r'["\'](https?://[^"\']*pixel\.hubcdn[^"\']*)["\']',
                r'["\'](https?://[^"\']*gpdl[^"\']*hubcdn[^"\']*)["\']',
                r'["\'](https?://[^"\']*fsl-[^"\']*)["\']',
                r'["\'](https?://[^"\']*gdboka[^"\']*)["\']',
                r'["\'](https?://[^"\']*polgen\.buzz[^"\']*)["\']',
                r'["\'](https?://[^"\']*filesdl[^"\']*\/cloud\/[^"\']*)["\']',
                r'["\'](https?://[^"\']*gdflix[^"\']*\/file\/[^"\']*)["\']',
            ]
            
            for pattern in js_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    add_direct_link(match)

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

            next_hops = []
            for pattern in next_hop_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for next_link in matches:
                    if next_link != url and next_link not in seen_urls:
                        if '/admin' not in next_link and '/login' not in next_link:
                            next_hops.append(next_link)
                            seen_urls.add(next_link)

            # PARALELIZARE NEXT HOPS
            if next_hops and depth < 6:
                def resolve_next_hop(next_link):
                    return _resolve_hdhub_redirect_parallel(next_link, depth + 1, current_title, current_branch, None)
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as local_exec:
                    futures = [local_exec.submit(resolve_next_hop, nh) for nh in next_hops[:10]]
                    for f in concurrent.futures.as_completed(futures, timeout=15):
                        try:
                            sub = f.result()
                            for res in sub:
                                if res[1] not in seen_urls:
                                    found_urls.append(res)
                                    seen_urls.add(res[1])
                        except:
                            pass

            # JS Redirect
            js_redirect = re.search(r'window\.location\.href\s*=\s*["\'](https?://[^"\']+)["\']', content)
            if js_redirect:
                redirect_url = js_redirect.group(1)
                if redirect_url not in seen_urls:
                    seen_urls.add(redirect_url)
                    sub = _resolve_hdhub_redirect_parallel(redirect_url, depth + 1, current_title, current_branch, executor)
                    for res in sub:
                        if res[1] not in seen_urls:
                            found_urls.append(res)
                            seen_urls.add(res[1])

        except Exception as e:
            log(f"[RESOLVE] Error: {e}")
            
    # Curățare duplicate
    unique_results = []
    seen_final = set()
    for item in found_urls:
        if item[1] not in seen_final:
            unique_results.append(item)
            seen_final.add(item[1])
            
    return unique_results


# =============================================================================
# HELPER: Procesează rezultate cu suport pentru Cloud și GDFlix Pages
# =============================================================================

def _process_resolved_results(resolved, quality, title, branch, streams_list, seen_urls):
    """
    Procesează rezultatele de la _resolve_hdhub_redirect_parallel.
    V3 - Extrage mărimea din branch și o setează ca câmp separat.
    """
    for host_name, final_url, file_title, file_quality, returned_branch in resolved:
        
        # 1. Cloud Page - procesare specială
        if host_name == 'CloudPage':
            log(f"[PROCESS] Processing Cloud Page: {final_url[:50]}...")
            cloud_streams = _process_filesdl_cloud_page(
                final_url,
                file_quality or quality,
                file_title or title,
                returned_branch or branch
            )
            if cloud_streams:
                for cs in cloud_streams:
                    url_check = cs['url'].split('|')[0]
                    if url_check not in seen_urls:
                        streams_list.append(cs)
                        seen_urls.add(url_check)
            continue
        
        # 2. GDFlix Page - procesare specială
        if host_name == 'GDFlixPage':
            log(f"[PROCESS] Processing GDFlix Page: {final_url[:50]}...")
            gd_streams = _process_gdflix_page(
                final_url,
                file_quality or quality,
                file_title or title,
                returned_branch or branch
            )
            if gd_streams:
                for gs in gd_streams:
                    url_check = gs['url'].split('|')[0]
                    if url_check not in seen_urls:
                        streams_list.append(gs)
                        seen_urls.add(url_check)
            continue
        
        # 3. Link direct video
        if final_url.startswith('http'):
            url_check = final_url.split('|')[0]
            if url_check in seen_urls:
                continue
            
            final_quality = file_quality or quality
            display_title = file_title or title
            
            # =========================================================
            # EXTRAGE MĂRIMEA DIN BRANCH (format: "... [1.16 GB]")
            # =========================================================
            extracted_size = ""
            if returned_branch:
                size_match = re.search(r'\[([\d.]+\s*(?:GB|MB|TB))\]', returned_branch, re.IGNORECASE)
                if size_match:
                    extracted_size = size_match.group(1).strip()
                    # Normalizare
                    extracted_size = re.sub(r'(\d)(GB|MB|TB)', r'\1 \2', extracted_size, flags=re.IGNORECASE)
                    extracted_size = extracted_size.upper().replace('  ', ' ').strip()
            
            # Construiește display name
            display_name = host_name
            if extracted_size:
                display_name = f"{host_name} | {extracted_size}"
            elif returned_branch and '[' not in returned_branch:
                # Dacă branch nu conține mărime dar are alt info
                display_name = f"{host_name} | {returned_branch}"
            
            streams_list.append({
                'name': display_name,
                'url': build_stream_url(final_url),
                'quality': final_quality,
                'title': display_title,
                'size': extracted_size,  # ✓ ACUM AVEM SIZE SEPARAT!
                'info': returned_branch or ""
            })
            seen_urls.add(url_check)


# =============================================================================
# SCRAPER HDHUB4U (V17 - CU CLOUD SUPPORT)
# =============================================================================

def scrape_hdhub4u(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru HDHub4u - COMPLET PARALELIZAT cu suport Cloud Pages.
    """
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
        # CĂUTARE API + FALLBACK
        # =========================================================
        def search_api():
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
                api_headers = {'User-Agent': get_random_ua(), 'Origin': base_url, 'Referer': f"{base_url}/"}
                r = requests.get(api_url, params=params, headers=api_headers, timeout=8, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    if 'hits' in data and data['hits']:
                        for hit in data['hits']:
                            doc = hit.get('document', {})
                            raw_link = doc.get('permalink')
                            raw_title = doc.get('post_title', '').lower()
                            if not raw_link: continue
                            matches = sum(1 for term in search_terms if term in raw_title)
                            if matches >= len(search_terms):
                                parsed_link = urlparse(raw_link)
                                curr_link = f"{base_url}{parsed_link.path}"
                                if year_query and str(year_query) in raw_title:
                                    return curr_link
                                return curr_link
            except:
                pass
            return None

        def search_fallback():
            try:
                search_url = f"{base_url}/search.html?q={quote(clean_search)}&page=1"
                r = requests.get(search_url, headers=get_headers(), timeout=15, verify=False)
                if r.status_code == 200:
                    search_html = r.text
                    links = re.findall(r'href=["\'](/[a-z0-9-]+-(?:20\d{2}|19\d{2})[^"\']*)["\']', search_html, re.IGNORECASE)
                    for rel in links:
                        full_url = base_url + rel
                        link_lower = full_url.lower()
                        if any(ex in link_lower for ex in ['/category/', '/page/', '/tag/']): continue
                        matches = sum(1 for term in search_terms if term in link_lower)
                        if matches >= len(search_terms):
                            if year_query and str(year_query) in full_url:
                                return full_url
                            return full_url
            except:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_api = executor.submit(search_api)
            f_fallback = executor.submit(search_fallback)
            
            try:
                movie_url = f_api.result(timeout=10)
            except:
                pass
            
            if not movie_url:
                try:
                    movie_url = f_fallback.result(timeout=10)
                except:
                    pass

        if not movie_url:
            log(f"[HDHUB] No results for: {clean_search}")
            return None
            
        log(f"[HDHUB] Found: {movie_url}")
        
        # =========================================================
        # ACCESEAZĂ PAGINA
        # =========================================================
        r_movie = requests.get(movie_url, headers=get_headers(), timeout=15, verify=False)
        movie_html = r_movie.text
        
        # Extrage secțiunea download
        download_section = movie_html
        for marker in ['DOWNLOAD LINKS', 'Download Links', ': DOWNLOAD :']:
            pos = movie_html.find(marker)
            if pos != -1:
                download_section = movie_html[pos:]
                break
        
        full_title_match = re.search(r'<h1[^>]*>.*?<span[^>]*>(.*?)</span>', movie_html, re.DOTALL)
        fallback_title = full_title_match.group(1).strip() if full_title_match else title_query

        link_pattern = r'<a\s+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>'
        all_links = re.findall(link_pattern, download_section, re.DOTALL)
        
        log(f"[HDHUB] Found {len(all_links)} links in download section")
        
        valid_domains = ['hubdrive', 'hubcloud', 'hubcdn', 'hubstream', 'hdstream4u', 'gamerxyt', 'vcloud']
        
        # =========================================================
        # PREGĂTIRE TASK-URI
        # =========================================================
        tasks = []
        seen_links = set()
        
        for link, text in all_links:
            link_lower = link.lower()
            text_lower = text.lower()
            clean_text_str = re.sub(r'<[^>]+>', '', text).strip()
            
            if 'hdhub4u' in link_lower: continue
            if not any(d in link_lower for d in valid_domains): continue
            if link in seen_links: continue
            seen_links.add(link)
            
            initial_quality = "SD"
            if '2160p' in text_lower or '4k' in text_lower: initial_quality = "4K"
            elif '1080p' in text_lower: initial_quality = "1080p"
            elif '720p' in text_lower: initial_quality = "720p"
            
            if initial_quality == "SD": continue
            if 'sample' in text_lower or 'gadgetsweb' in link_lower: continue

            branch_label = clean_text_str.replace('Download', '').replace('Watch', '').replace('Links', '').strip()
            branch_label = re.sub(r'\s+', ' ', branch_label).replace('&#038;', '&').replace('&amp;', '&')
            
            tasks.append({
                'link': link,
                'branch_label': branch_label,
                'initial_quality': initial_quality,
                'fallback_title': fallback_title
            })

        log(f"[HDHUB] Tasks to process: {len(tasks)}")
        
        # =========================================================
        # EXECUȚIE PARALELĂ
        # =========================================================
        streams = []
        seen_urls = set()
        streams_lock = threading.Lock()
        
        def process_task(task):
            local_streams = []
            local_seen = set()
            try:
                log(f"[HDHUB-T] Processing: {task['branch_label'][:30]}...")
                
                resolved = _resolve_hdhub_redirect_parallel(
                    task['link'], 0, None, task['branch_label'], None
                )
                
                if resolved:
                    _process_resolved_results(
                        resolved,
                        task['initial_quality'],
                        task['fallback_title'],
                        task['branch_label'],
                        local_streams,
                        local_seen
                    )
            except Exception as e:
                log(f"[HDHUB-T] Error: {e}")
            return local_streams

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_task, t) for t in tasks]
            for future in concurrent.futures.as_completed(futures, timeout=40):
                try:
                    res = future.result()
                    if res:
                        with streams_lock:
                            for s in res:
                                url_check = s['url'].split('|')[0]
                                if url_check not in seen_urls:
                                    streams.append(s)
                                    seen_urls.add(url_check)
                except Exception as e:
                    log(f"[HDHUB] Future error: {e}")

        log(f"[HDHUB] Total streams: {len(streams)}")
        return streams if streams else None

    except Exception as e:
        log(f"[HDHUB] Error: {e}", xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER MKVCINEMAS (V8 - FULL PARALLEL - FIX SPEED)
# =============================================================================

def scrape_mkvcinemas(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru MKVCinemas - V8: FULL PARALLEL pentru viteză maximă.
    """
    if ADDON.getSetting('use_mkvcinemas') == 'false':
        return None
    
    try:
        base_url = "https://mkvcinemas.gl"
        headers = get_headers()
        
        # =========================================================
        # 1. CĂUTARE
        # =========================================================
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        search_url = f"{base_url}/?s={quote(clean_search)}"
        r = requests.get(search_url, headers=headers, timeout=15, verify=False)
        
        if r.status_code != 200:
            return None
        
        search_html = r.text
        
        # Exclude patterns
        exclude_patterns = [
            '/feed/', '/rss', '/category/', '/page/', '/tag/', 
            '/author/', '/wp-', '/comment', '/search/',
            '.jpg', '.png', '.gif', 'facebook', 'twitter', 'instagram',
            '/cdn-cgi/', 'javascript:', 'mailto:'
        ]
        
        # Pattern pentru link-uri de articole
        movie_pattern = rf'href=["\']({re.escape(base_url)}/[a-z0-9-]+-(?:19|20)\d{{2}}[^"\']*)["\']'
        direct_matches = re.findall(movie_pattern, search_html, re.IGNORECASE)
        
        all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', search_html)
        
        movie_links = []
        search_terms = [t.lower() for t in clean_search.split() if len(t) > 2]
        search_slug = clean_search.lower().replace(' ', '-')
        
        for link in direct_matches:
            link_lower = link.lower()
            if any(ex in link_lower for ex in exclude_patterns):
                continue
            if link not in movie_links:
                movie_links.append(link)
        
        for href in all_hrefs:
            href_lower = href.lower()
            if any(ex in href_lower for ex in exclude_patterns):
                continue
            if href.startswith('http'):
                if 'mkvcinemas' not in href_lower:
                    continue
                full_link = href
            elif href.startswith('/') and not href.startswith('//'):
                full_link = base_url + href
            else:
                continue
            matches = sum(1 for t in search_terms if t in href_lower)
            if matches >= max(1, len(search_terms) - 1):
                if full_link not in movie_links:
                    movie_links.append(full_link)
        
        if not movie_links:
            log(f"[MKV] No valid movie links found for: {clean_search}")
            return None
        
        # Selectare rezultat
        movie_url = None
        for link in movie_links:
            link_lower = link.lower()
            if search_slug in link_lower:
                if year_query and str(year_query) in link:
                    movie_url = link
                    log(f"[MKV] ✓ Best match (slug+year): {link}")
                    break
                if not movie_url:
                    movie_url = link
            if not movie_url:
                movie_url = link
        
        if not movie_url:
            return None
        
        if '/feed/' in movie_url or '/rss' in movie_url:
            log(f"[MKV] ERROR: Selected URL is RSS feed")
            return None
        
        log(f"[MKV] Found: {movie_url}")
        
        # =========================================================
        # 2. ACCESEAZĂ PAGINA
        # =========================================================
        r_movie = requests.get(movie_url, headers=headers, timeout=15, verify=False)
        movie_html = r_movie.text
        
        if 'download' not in movie_html.lower() and 'filesdl' not in movie_html.lower():
            return None
        
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', movie_html)
        fallback_title = title_match.group(1).strip() if title_match else title_query
        fallback_title = re.sub(r'\s*(Download|Full Movie|HD).*', '', fallback_title, flags=re.IGNORECASE).strip()
        
        # =========================================================
        # 3. IDENTIFICARE LINK-URI
        # =========================================================
        filesdl_links = list(set(re.findall(r'href=["\']([^"\']*filesdl\.(?:live|top|in|xyz)[^"\']*)["\']', movie_html, re.IGNORECASE)))
        hubcloud_links = list(set(re.findall(r'href=["\']([^"\']*(?:hubcloud|vcloud)[^"\']+)["\']', movie_html, re.IGNORECASE)))
        gdflix_links = list(set(re.findall(r'href=["\']([^"\']*gdflix[^"\']+)["\']', movie_html, re.IGNORECASE)))
        
        log(f"[MKV] Links: FilesDL={len(filesdl_links)}, Hub={len(hubcloud_links)}, GD={len(gdflix_links)}")
        
        if not filesdl_links and not hubcloud_links and not gdflix_links:
            return None
        
        streams = []
        seen_urls = set()
        streams_lock = threading.Lock()
        
        # =========================================================
        # WORKER: PROCESS FILESDL (COMPLET PARALELIZAT)
        # =========================================================
        def process_filesdl(url):
            """Procesează FilesDL page și extrage TOATE stream-urile în paralel."""
            local_streams = []
            local_seen = set()
            
            try:
                r = requests.get(url, headers=headers, timeout=10, verify=False)
                html = r.text
                
                page_title_match = re.search(r'<h1[^>]*class="entry-title"[^>]*>([^<]+)</h1>', html)
                current_title = page_title_match.group(1).strip() if page_title_match else fallback_title
                
                # Extrage toate boxurile de download
                box_pattern = r'<div class="download-box[^"]*">\s*<h2>([^<]+)</h2>\s*<div class="filesize">([^<]+)</div>\s*<div class="download-buttons">(.*?)</div>'
                boxes = re.findall(box_pattern, html, re.DOTALL | re.IGNORECASE)
                
                if not boxes:
                    log(f"[MKV-FILESDL] No download boxes found")
                    return []
                
                # =============================================================
                # FAZA 1: Colectează TOATE URL-urile de procesat
                # =============================================================
                all_tasks = []  # Lista de (task_type, url, quality, branch)
                
                for quality_text, filesize, buttons_html in boxes:
                    quality = "SD"
                    q_lower = quality_text.lower()
                    if '2160p' in q_lower or '4k' in q_lower: 
                        quality = "4K"
                    elif '1080p' in q_lower: 
                        quality = "1080p"
                    elif '720p' in q_lower: 
                        quality = "720p"
                    
                    if quality == "SD": 
                        continue
                    
                    branch = f"{quality_text.replace('DOWNLOAD', '').strip()} [{filesize.strip()}]"
                    
                    # Extrage URL-urile din butoane
                    extracted_urls = re.findall(r'href=["\']([^"\']+)["\']', buttons_html)
                    
                    for dl_url in extracted_urls:
                        if 'javascript' in dl_url or dl_url == '#':
                            continue
                        
                        dl_lower = dl_url.lower()
                        
                        # Identifică tipul și adaugă la tasks
                        if 'filesdl' in dl_lower and '/cloud/' in dl_lower:
                            all_tasks.append(('cloud', dl_url, quality, branch, current_title))
                        elif any(p in dl_lower for p in ['gdflix.dev/file/', 'gdflix.net/file/', 'gdflix.filesdl.in/file/']):
                            all_tasks.append(('gdflix', dl_url, quality, branch, current_title))
                        elif 'gofile.io/d/' in dl_lower:
                            # Skip GoFile pages
                            continue
                        else:
                            # Alte URL-uri - rezolvă prin redirect chain
                            all_tasks.append(('resolve', dl_url, quality, branch, current_title))
                
                log(f"[MKV-FILESDL] Collected {len(all_tasks)} tasks to process in parallel")
                
                # =============================================================
                # FAZA 2: Procesează TOATE în PARALEL
                # =============================================================
                def process_task(task):
                    """Procesează un singur task și returnează streamuri."""
                    task_type, task_url, task_quality, task_branch, task_title = task
                    results = []
                    
                    try:
                        if task_type == 'cloud':
                            results = _process_filesdl_cloud_page(
                                task_url, task_quality, task_title, task_branch
                            )
                        
                        elif task_type == 'gdflix':
                            results = _process_gdflix_page(
                                task_url, task_quality, task_title, task_branch
                            )
                        
                        elif task_type == 'resolve':
                            resolved = _resolve_hdhub_redirect_parallel(
                                task_url, 0, task_title, task_branch, None
                            )
                            if resolved:
                                for host, url, title, qual, branch in resolved:
                                    if host == 'CloudPage':
                                        sub = _process_filesdl_cloud_page(url, qual or task_quality, title or task_title, branch or task_branch)
                                        if sub: results.extend(sub)
                                    elif host == 'GDFlixPage':
                                        sub = _process_gdflix_page(url, qual or task_quality, title or task_title, branch or task_branch)
                                        if sub: results.extend(sub)
                                    elif url.startswith('http'):
                                        display = host
                                        if branch:
                                            display = f"{host} | {branch}"
                                        # Extrage size din branch dacă există
                                        extracted_size = ""
                                        if branch:
                                            size_match = re.search(r'\[([\d.]+\s*(?:GB|MB))\]', branch, re.IGNORECASE)
                                            if size_match:
                                                extracted_size = size_match.group(1)
                                        results.append({
                                            'name': display,
                                            'url': build_stream_url(url),
                                            'quality': qual or task_quality,
                                            'title': title or task_title,
                                            'size': extracted_size,
                                            'info': branch or ""
                                        })
                    except Exception as e:
                        log(f"[MKV-TASK] Error: {e}")
                    
                    return results
                
                # EXECUȚIE PARALELĂ CU THREAD POOL
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(process_task, t) for t in all_tasks]
                    
                    for future in concurrent.futures.as_completed(futures, timeout=25):
                        try:
                            task_results = future.result()
                            if task_results:
                                for s in task_results:
                                    url_check = s['url'].split('|')[0]
                                    if url_check not in local_seen:
                                        local_streams.append(s)
                                        local_seen.add(url_check)
                        except Exception as e:
                            log(f"[MKV-FILESDL] Future error: {e}")
                
            except Exception as e:
                log(f"[MKV-FILESDL] Error: {e}")
            
            return local_streams

        # =========================================================
        # WORKER: HUBCLOUD
        # =========================================================
        def process_hubcloud(url):
            local_streams = []
            local_seen = set()
            try:
                resolved = _resolve_hdhub_redirect_parallel(url, 0, fallback_title, "Direct", None)
                if resolved:
                    # Procesare în paralel
                    tasks = []
                    for host, final_url, title, qual, branch in resolved:
                        if host == 'CloudPage':
                            tasks.append(('cloud', final_url, qual, branch, title))
                        elif host == 'GDFlixPage':
                            tasks.append(('gdflix', final_url, qual, branch, title))
                        elif final_url.startswith('http'):
                            display = host
                            if branch:
                                display = f"{host} | {branch}"
                            # Extrage size din branch
                            extracted_size = ""
                            if branch:
                                size_match = re.search(r'\[([\d.]+\s*(?:GB|MB))\]', branch, re.IGNORECASE)
                                if size_match:
                                    extracted_size = size_match.group(1)
                            local_streams.append({
                                'name': display,
                                'url': build_stream_url(final_url),
                                'quality': qual or '1080p',
                                'title': title or fallback_title,
                                'size': extracted_size,
                                'info': branch or ""
                            })
                    
                    # Procesare paralela pentru Cloud/GDFlix
                    if tasks:
                        def proc_task(t):
                            tt, tu, tq, tb, ti = t
                            if tt == 'cloud':
                                return _process_filesdl_cloud_page(tu, tq or '1080p', ti or fallback_title, tb)
                            elif tt == 'gdflix':
                                return _process_gdflix_page(tu, tq or '1080p', ti or fallback_title, tb)
                            return []
                        
                        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                            for f in concurrent.futures.as_completed([ex.submit(proc_task, t) for t in tasks], timeout=15):
                                try:
                                    res = f.result()
                                    if res:
                                        for s in res:
                                            uc = s['url'].split('|')[0]
                                            if uc not in local_seen:
                                                local_streams.append(s)
                                                local_seen.add(uc)
                                except:
                                    pass
                                    
            except Exception as e:
                log(f"[MKV-HUB] Error: {e}")
            return local_streams

        # =========================================================
        # WORKER: GDFLIX DIRECT
        # =========================================================
        def process_gdflix_direct(url):
            """Procesează link-uri GDFlix găsite direct în pagina principală."""
            return _process_gdflix_page(url, "1080p", fallback_title, "GDFlix Direct")

        # =========================================================
        # EXECUȚIE PARALELĂ - TOATE SURSELE
        # =========================================================
        all_tasks = []
        for url in filesdl_links: 
            all_tasks.append(('filesdl', url))
        for url in hubcloud_links: 
            all_tasks.append(('hub', url))
        for url in gdflix_links:
            # Doar link-uri gdflix.dev/file/ sau similare
            if any(p in url.lower() for p in ['gdflix.dev/file/', 'gdflix.net/file/']):
                all_tasks.append(('gdflix', url))
        
        log(f"[MKV] Total tasks: {len(all_tasks)}")
        
        def dispatch_task(task):
            task_type, url = task
            if task_type == 'filesdl': 
                return process_filesdl(url)
            elif task_type == 'hub': 
                return process_hubcloud(url)
            elif task_type == 'gdflix': 
                return process_gdflix_direct(url)
            return []

        # EXECUȚIE PARALELĂ MASTER
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(dispatch_task, t) for t in all_tasks]
            
            for f in concurrent.futures.as_completed(futures, timeout=45):
                try:
                    res = f.result()
                    if res:
                        for s in res:
                            url_check = s['url'].split('|')[0]
                            with streams_lock:
                                if url_check not in seen_urls:
                                    streams.append(s)
                                    seen_urls.add(url_check)
                except Exception as e:
                    log(f"[MKV] Task error: {e}")

        log(f"[MKV] Total streams: {len(streams)}")
        return streams if streams else None
        
    except Exception as e:
        log(f"[MKV] Error: {e}", xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER MOVIESDRIVE (V4 - CU CLOUD SUPPORT + VARIABLE FIX)
# =============================================================================

def scrape_moviesdrive(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru MoviesDrive - COMPLET PARALELIZAT.
    """
    if ADDON.getSetting('use_moviesdrive') == 'false':
        return None

    try:
        base_url = _get_moviesdrive_base()
        headers = get_headers()
        
        # =========================================================
        # 1. CĂUTARE API
        # =========================================================
        api_url = f"{base_url}/searchapi.php"
        search_term = title_query if (content_type == 'tv' and title_query) else imdb_id
        params = {'q': search_term, 'page': '1'}
        headers['Referer'] = f"{base_url}/search.html?q={search_term}"
        headers['X-Requested-With'] = 'XMLHttpRequest'
        
        r = requests.get(api_url, params=params, headers=headers, timeout=10, verify=False)
        data = r.json()
        
        movie_link = None
        season_link = None
        
        if 'hits' in data and data['hits']:
            if content_type == 'tv' and season:
                season_num = int(season)
                season_patterns = [f"season {season_num}", f"season-{season_num}", f"s{season_num:02d}", f"s{season_num}"]
                
                for hit in data['hits']:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink', '')
                    raw_title = doc.get('post_title', '').lower()
                    if not raw_link: continue
                    
                    full_link = raw_link if raw_link.startswith('http') else base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                    combined = raw_title + ' ' + raw_link.lower()
                    
                    for pattern in season_patterns:
                        if pattern in combined:
                            season_link = full_link
                            break
                    if season_link: break
                
                if not season_link:
                    for hit in data['hits']:
                        doc = hit.get('document', {})
                        raw_link = doc.get('permalink', '')
                        raw_title = doc.get('post_title', '').lower()
                        full_link = raw_link if raw_link.startswith('http') else base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                        if title_query and all(w in raw_title for w in title_query.lower().split() if len(w) > 2):
                            movie_link = full_link
                            break
            else:
                # =========================================================
                # FILME: VALIDARE REZULTAT CĂUTARE
                # =========================================================
                # Dacă nu avem title_query, NU putem valida rezultatele
                if not title_query:
                    log(f"[MDRIVE] ✗ No title_query provided, cannot validate results. Skipping MoviesDrive.")
                    return None
                
                search_title = title_query.lower()
                title_words = [w for w in search_title.split() if len(w) >= 3]
                
                if not title_words:
                    log(f"[MDRIVE] ✗ Title too short to validate: '{title_query}'")
                    return None
                
                for hit in data['hits']:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink', '')
                    raw_title = doc.get('post_title', '')
                    
                    if not raw_link:
                        continue
                    
                    # Combină titlu și link pentru verificare
                    combined = (raw_title + ' ' + raw_link).lower()
                    
                    # Verifică potrivirea cu titlul căutat
                    matches = sum(1 for w in title_words if w in combined)
                    match_ratio = matches / len(title_words)
                    
                    if match_ratio < 0.5:
                        log(f"[MDRIVE] ✗ Skipped (match={match_ratio:.0%}): '{raw_title[:40]}' vs '{title_query}'")
                        continue
                    
                    # Verificare suplimentară: nu e serial
                    serial_patterns = ['season', ' s01', ' s02', ' s03', '-s01', '-s02', 
                                      'episode', ' e01', ' e02', '.s0', 'complete series']
                    is_serial = any(p in combined for p in serial_patterns)
                    
                    if is_serial:
                        log(f"[MDRIVE] ✗ Skipped (TV series detected): '{raw_title[:40]}'")
                        continue
                    
                    # Verificare an (dacă avem year_query)
                    if year_query:
                        year_str = str(year_query)
                        if year_str not in combined:
                            # Toleranță: anul poate fi cu ±1
                            try:
                                y = int(year_query)
                                if str(y-1) not in combined and str(y+1) not in combined:
                                    log(f"[MDRIVE] ✗ Skipped (year mismatch): '{raw_title[:40]}' vs year={year_query}")
                                    continue
                            except:
                                pass
                    
                    log(f"[MDRIVE] ✓ Match OK ({match_ratio:.0%}): '{raw_title[:40]}'")
                    
                    # Rezultat valid
                    movie_link = raw_link if raw_link.startswith('http') else base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                    log(f"[MDRIVE] Selected: {movie_link}")
                    break
                
                if not movie_link:
                    log(f"[MDRIVE] ✗ No matching result for: '{title_query}' ({year_query})")
                    return None

        # =========================================================
        # 2. SERIALE
        # =========================================================
        if content_type == 'tv' and season:
            target_page = season_link or movie_link
            if not target_page: return None
            
            r_page = requests.get(target_page, headers=headers, timeout=15, verify=False)
            page_html = r_page.text
            
            if not season_link:
                season_num = int(season)
                for pattern in [rf'href=["\']([^"\']*season[- ]?{season_num}[^"\']*)["\']', rf'href=["\']([^"\']*s{season_num:02d}[^"\']*)["\']']:
                    matches = re.findall(pattern, page_html, re.IGNORECASE)
                    for m in matches:
                        if 'moviesdrive' in m.lower() or m.startswith('/'):
                            season_link = base_url + m if m.startswith('/') else m
                            break
                    if season_link: break
                
                if season_link:
                    r_page = requests.get(season_link, headers=headers, timeout=15, verify=False)
                    page_html = r_page.text
            
            title_match = re.search(r'<title>(.*?)</title>', page_html)
            page_title = title_match.group(1).split('|')[0].strip() if title_match else title_query
            
            quality_links = {}
            all_mdrive = re.findall(r'<a\s+href=["\']([^"\']*mdrive\.lol/archives/[^"\']+)["\'][^>]*>([^<]*)</a>', page_html, re.IGNORECASE)
            
            for url, text in all_mdrive:
                text_lower = text.lower().strip()
                if 'zip' in text_lower: continue
                if not ('single' in text_lower or 'episode' in text_lower or any(q in text_lower for q in ['720p', '1080p', '2160p', '4k'])): continue
                
                q_key = None
                if '2160' in text_lower or '4k' in text_lower: q_key = '4K'
                elif '1080' in text_lower: q_key = '1080p'
                elif '720' in text_lower: q_key = '720p'
                
                if q_key and q_key not in quality_links:
                    quality_links[q_key] = url
            
            if not quality_links: return None
            
            streams = []
            seen_urls = set()
            streams_lock = threading.Lock()
            episode_num = int(episode) if episode else 1
            
            def process_quality(args):
                q_label, q_url = args
                local_streams = []
                local_seen = set()
                try:
                    r_ep = requests.get(q_url, headers=headers, timeout=10, verify=False)
                    ep_html = r_ep.text
                    
                    if 'LANDER' in ep_html: return []
                    
                    ep_pat = rf'Ep0?{episode_num}\s*</span>|Episode\s*0?{episode_num}\s*</span>|>E0?{episode_num}<'
                    match = re.search(ep_pat, ep_html, re.IGNORECASE)
                    if not match: return []
                    
                    start = match.start()
                    next_pat = rf'Ep0?{episode_num + 1}\s*</span>|<hr'
                    end_match = re.search(next_pat, ep_html[start+50:], re.IGNORECASE)
                    end = (start + 50 + end_match.start()) if end_match else len(ep_html)
                    section = ep_html[start:end]
                    
                    links = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', section, re.IGNORECASE)
                    
                    for link_url, link_text in links:
                        link_lower = link_url.lower()
                        
                        if 'hubcloud' in link_lower or 'vcloud' in link_lower:
                            branch = f"{q_label} Ep{episode_num}"
                            resolved = _resolve_hdhub_redirect_parallel(link_url, 0, page_title, branch, None)
                            if resolved:
                                _process_resolved_results(resolved, q_label, page_title, branch, local_streams, local_seen)
                        
                        elif 'gdflix' in link_lower:
                            try:
                                r_gd = requests.get(link_url, headers=headers, timeout=8, verify=False)
                                gd_content = r_gd.text
                                
                                gd_filename = None
                                meta = re.search(r'property="og:description"\s+content="Download\s+(.*?)\s+-\s+([^"]+)"', gd_content, re.IGNORECASE)
                                if meta: gd_filename = meta.group(1).strip()
                                
                                curr_title = gd_filename or page_title
                                
                                r2_matches = re.findall(r'href=["\'](https?://[^"\']*(?:r2\.dev|cloudflarestorage|workers\.dev)[^"\']*)["\']', gd_content, re.IGNORECASE)
                                for r2 in r2_matches:
                                    local_streams.append({
                                        'name': f"MDrive | GDFlix | Direct",
                                        'url': build_stream_url(r2),
                                        'quality': q_label,
                                        'title': curr_title,
                                        'size': "",
                                        'info': ""
                                    })
                                
                                pd = re.search(r'href=["\'](https?://[^"\']*pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))["\']', gd_content, re.IGNORECASE)
                                if pd:
                                    api = f"https://pixeldrain.dev/api/file/{pd.group(2)}"
                                    local_streams.append({
                                        'name': f"MDrive | GDFlix | PixelDrain",
                                        'url': build_stream_url(api),
                                        'quality': q_label,
                                        'title': curr_title,
                                        'size': "",
                                        'info': ""
                                    })
                            except:
                                pass
                except Exception as e:
                    log(f"[MDRIVE-Q] Error {q_label}: {e}")
                return local_streams

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_quality, (k, v)) for k, v in quality_links.items()]
                for f in concurrent.futures.as_completed(futures, timeout=30):
                    try:
                        res = f.result()
                        if res:
                            with streams_lock:
                                for s in res:
                                    url_check = s['url'].split('|')[0]
                                    if url_check not in seen_urls:
                                        streams.append(s)
                                        seen_urls.add(url_check)
                    except:
                        pass
            
            return streams if streams else None

        # =========================================================
        # 3. FILME
        # =========================================================
        if not movie_link: return None
        
        r_movie = requests.get(movie_link, headers=headers, timeout=10, verify=False)
        movie_html = r_movie.text
        
        title_match = re.search(r'<title>(.*?)</title>', movie_html)
        page_title = title_match.group(1).split('|')[0].strip() if title_match else "Unknown"

        start_pos = movie_html.find("DOWNLOAD LINKS")
        download_section = movie_html[start_pos:] if start_pos != -1 else movie_html
        mdrive_links = re.findall(r'href=["\'](https?://mdrive\.lol/archives/[^"\']+)["\'][^>]*>(.*?)</a>', download_section, re.IGNORECASE)
        
        streams = []
        seen_urls = set()
        streams_lock = threading.Lock()
        
        def process_movie_link(args):
            mdrive_url, link_text = args
            local_streams = []
            local_seen = set()
            clean_text_str = re.sub(r'<[^>]+>', '', link_text).strip()
            
            quality = "SD"
            clean_lower = clean_text_str.lower()
            if '2160p' in clean_lower or '4k' in clean_lower: quality = "4K"
            elif '1080p' in clean_lower: quality = "1080p"
            elif '720p' in clean_lower: quality = "720p"
            if '480p' in clean_lower: return []
            
            try:
                r_md = requests.get(mdrive_url, headers={'Referer': movie_link, 'User-Agent': get_random_ua()}, timeout=10, verify=False)
                md_html = r_md.text
                if 'LANDER' in md_html: return []

                dest_links = re.findall(r'href=["\'](https?://[^"\']*(?:hubcloud|gdflix|vcloud)[^"\']+)["\']', md_html, re.IGNORECASE)
                
                for dest_url in dest_links:
                    if 'hubcloud' in dest_url.lower() or 'vcloud' in dest_url.lower():
                        resolved = _resolve_hdhub_redirect_parallel(dest_url, 0, page_title, clean_text_str, None)
                        if resolved:
                            _process_resolved_results(resolved, quality, page_title, clean_text_str, local_streams, local_seen)
                    
                    elif 'gdflix' in dest_url.lower():
                        try:
                            r_gd = requests.get(dest_url, headers=headers, timeout=8, verify=False)
                            gd_content = r_gd.text
                            
                            gd_filename = None
                            meta = re.search(r'property="og:description"\s+content="Download\s+(.*?)\s+-\s+([^"]+)"', gd_content, re.IGNORECASE)
                            if meta: gd_filename = meta.group(1).strip()
                            
                            curr_title = gd_filename or page_title
                            
                            r2_matches = re.findall(r'href=["\'](https?://[^"\']*(?:r2\.dev|cloudflarestorage|workers\.dev)[^"\']*)["\']', gd_content, re.IGNORECASE)
                            for r2 in r2_matches:
                                local_streams.append({
                                    'name': "MDrive | GDFlix | Direct",
                                    'url': build_stream_url(r2),
                                    'quality': quality,
                                    'title': curr_title,
                                    'size': "",
                                    'info': clean_text_str
                                })
                            
                            pd = re.search(r'href=["\'](https?://[^"\']*pixeldrain\.(?:com|dev)/u/([a-zA-Z0-9]+))["\']', gd_content, re.IGNORECASE)
                            if pd:
                                api = f"https://pixeldrain.dev/api/file/{pd.group(2)}"
                                local_streams.append({
                                    'name': "MDrive | GDFlix | PixelDrain",
                                    'url': build_stream_url(api),
                                    'quality': quality,
                                    'title': curr_title,
                                    'size': "",
                                    'info': clean_text_str
                                })
                        except:
                            pass
                        
            except Exception as e:
                log(f"[MDRIVE-M] Error: {e}")
            return local_streams

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_movie_link, item) for item in mdrive_links]
            for f in concurrent.futures.as_completed(futures, timeout=35):
                try:
                    res = f.result()
                    if res:
                        with streams_lock:
                            for s in res:
                                url_check = s['url'].split('|')[0]
                                if url_check not in seen_urls:
                                    streams.append(s)
                                    seen_urls.add(url_check)
                except:
                    pass

        return streams if streams else None

    except Exception as e:
        log(f"[MDRIVE] Error: {e}", xbmc.LOGERROR)
        return None

# =============================================================================
# HELPER PROVIDERI JSON (Vega, Nuvio, StreamVix, Vidzee, Webstreamr)
# =============================================================================
def _scrape_json_provider(base_url, pattern, label, imdb_id, content_type, season, episode):
    """
    Helper pentru providerii JSON (Vega, Nuvio, StreamVix, Vidzee, Webstreamr).
    FIX: Extrage calitatea din name/title.
    """
    local_streams = []
    
    # Timeout mai mic pentru provideri cunoscuți ca lenți
    if 'nuvio' in base_url.lower():
        timeout = 8  # 8 secunde în loc de 15
    else:
        timeout = 12
    
    try:
        if content_type == 'movie':
            api_url = f"{base_url}/stream/movie/{imdb_id}.json" if pattern == 'stream' else f"{base_url}/movie/{imdb_id}.json"
        else:
            api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json" if pattern == 'stream' else f"{base_url}/series/{imdb_id}:{season}:{episode}.json"

        r = requests.get(api_url, headers=get_headers(), timeout=timeout, verify=False)
        r.raise_for_status()

        if r.status_code == 200:
            data = r.json()
            if 'streams' in data:
                ref = base_url + '/'
                origin = base_url

                for s in data['streams']:
                    url = s.get('url', '')
                    if not url:
                        continue
                    
                    clean_check_url = url.split('|')[0]
                    
                    # Extrage name și title pentru procesare
                    raw_name = s.get('name', '')
                    raw_title = s.get('title', '')
                    
                    # Curățare nume de unicode/emojis
                    try:
                        clean_name = raw_name.encode('ascii', 'ignore').decode('ascii')
                    except:
                        clean_name = raw_name

                    # Eliminare nume provider din afișare
                    banned_names = ['WebStreamr', 'Nuvio', 'StreamVix', 'Vidzee', 'Vega', 'Sooti', 'Sootio']
                    for bn in banned_names:
                        clean_name = clean_name.replace(bn, '').strip()
                    
                    clean_name = clean_name.replace('|', '').strip()
                    clean_name = clean_name.replace('\n', ' ').strip()  # Newlines în spații
                    while '  ' in clean_name:
                        clean_name = clean_name.replace('  ', ' ')

                    if clean_name:
                        final_name = f"{label} | {clean_name}"
                    else:
                        final_name = label
                    
                    # =====================================================
                    # FIX: EXTRAGE CALITATEA DIN NAME SAU TITLE
                    # =====================================================
                    quality = None
                    
                    # 1. Încearcă câmpul 'quality' direct (unii provideri îl au)
                    if s.get('quality'):
                        quality = s.get('quality')
                    
                    # 2. Extrage din name (ex: "Provider\n4K" sau "Provider 1080p")
                    if not quality or quality.upper() == 'SD':
                        quality = _extract_quality_from_string(raw_name)
                    
                    # 3. Extrage din title (ex: "Movie.2024.2160p.WEB-DL...")
                    if not quality:
                        quality = _extract_quality_from_string(raw_title)
                    
                    # 4. Fallback: caută în behaviorHints.filename
                    if not quality:
                        filename = s.get('behaviorHints', {}).get('filename', '')
                        if filename:
                            quality = _extract_quality_from_string(filename)
                    
                    # 5. Default SD dacă nu s-a găsit nimic
                    if not quality:
                        quality = 'SD'
                    # =====================================================
                    
                    # Construiește stream object
                    stream_obj = {
                        'name': final_name,
                        'url': build_stream_url(url, referer=ref, origin=origin),
                        'quality': quality,
                        'title': raw_title,
                        'info': s.get('behaviorHints', {}).get('filename', '')
                    }
                    
                    local_streams.append(stream_obj)
                
                log(f"[SCRAPER] ✓ {label}: {len(local_streams)} surse")
                
    except Exception as e:
        log(f"[JSON-PROV] Error {label}: {e}")

    return local_streams


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
# MAIN ORCHESTRATION FUNCTION (PARALLEL / MULTITHREADING)
# =============================================================================
def get_stream_data(imdb_id, content_type, season=None, episode=None, progress_callback=None, target_providers=None):
    """
    Orchestrează scanarea PARALELĂ (Multithreading).
    """
    all_streams = []
    seen_urls = set()
    failed_providers = [] 
    was_canceled = False
    
    # 1. EXTRAGERE TITLU ȘI AN DIN TMDB (Necesar pentru providerii HTML)
    extra_title = ""
    extra_year = ""
    
    title_based_scrapers = ['hdhub4u', 'mkvcinemas', 'vixsrc', 'moviesdrive']
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
    
    # 2. DEFINIRE PROVIDERI
    # Folosim functii lambda pentru a captura parametrii specifici
    providers_map = {
        'sooti': ('SlowNow', lambda: scrape_sooti(imdb_id, content_type, season, episode)),
        'nuvio': ('NotNow', lambda: _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'NotNow', imdb_id, content_type, season, episode)),
        'webstreamr': ('WebNow', lambda: _scrape_json_provider("https://webstreamr.hayd.uk", 'stream', 'WebNow', imdb_id, content_type, season, episode)),
        'streamvix': ('StreamNow', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamNow', imdb_id, content_type, season, episode)),
        'xdmovies': ('SmileNow', lambda: scrape_xdmovies(imdb_id, content_type, season, episode)),
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'rogflix': ('Rogflix', lambda: scrape_rogflix(imdb_id, content_type, season, episode)),
        'vega': ('Vega', lambda: _scrape_json_provider("https://vega.vflix.life", 'stream', 'Vega', imdb_id, content_type, season, episode)),
        'vidzee': ('Vidzee', lambda: _scrape_json_provider("https://vidzee.vflix.life", 'direct', 'Vidzee', imdb_id, content_type, season, episode)),
        'hdhub4u': ('HDHub4u', lambda: scrape_hdhub4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'mkvcinemas': ('MKVCinemas', lambda: scrape_mkvcinemas(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'moviesdrive': ('MoviesDrive', lambda: scrape_moviesdrive(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
    }

    # 3. SELECȚIE PROVIDERI ACTIVI
    to_run = []
    
    # Notă: Pentru providerii JSON (Vega, Nuvio etc), _scrape_json_provider modifică lista 'all_streams' direct.
    # Dar pentru thread-safety, e mai bine să returneze lista.
    # Am modificat apelurile lambda de mai sus să primească set() și list() locale temporare,
    # dar _scrape_json_provider curent adaugă în listă (append). 
    # Pentru siguranță în multithreading, vom folosi un wrapper.

    if target_providers is not None:
        for pid in target_providers:
            if pid in providers_map:
                setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
                if ADDON.getSetting(setting_id) == 'true':
                    to_run.append((pid, providers_map[pid][0], providers_map[pid][1]))
    else:
        for pid, (pname, pfunc) in providers_map.items():
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if ADDON.getSetting(setting_id) == 'true':
                to_run.append((pid, pname, pfunc))
    
    total_providers = len(to_run)
    if total_providers == 0:
        return [], [], False

    # 4. FUNCȚIA WRAPPER PENTRU THREAD
    def run_provider(provider_info):
        """
        Execută un provider și returnează rezultatele.
        Returnează: (pid, pname, result, success)
        """
        pid, pname, pfunc = provider_info
        
        try:
            # Executăm funcția providerului
            result = pfunc()
            
            # Verificăm dacă avem rezultate valide
            if result:
                # Poate fi listă, dict, sau alt format
                return (pid, pname, result, True)  # success=True
            else:
                # Provider-ul nu a găsit nimic
                return (pid, pname, None, False)  # success=False
            
        except Exception as e:
            log(f"[THREAD] Error in {pname}: {e}")
            return (pid, pname, None, False)  # success=False (eroare)

    # 5. EXECUȚIE PARALELĂ - OPTIMIZATĂ
    MAX_TIMEOUT = 20  # Redus de la 25 pentru răspuns mai rapid
    MAX_WORKERS = 12  # Crescut de la 10 pentru mai multă paralelizare
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_provider = {executor.submit(run_provider, p): p for p in to_run}
        
        finished_count = 0
        
        try:
            for future in concurrent.futures.as_completed(future_to_provider, timeout=MAX_TIMEOUT):
                finished_count += 1
                
                # Check Cancel
                if progress_callback:
                    percent = int((finished_count / total_providers) * 100)
                    msg = f"[COLOR white]Scanare activă: [B][COLOR cyan]{finished_count}/{total_providers}[/B] [COLOR white]provideri\nSurse găsite: [B][COLOR magenta]{len(all_streams)}[/COLOR][/B]"
                    
                    keep_going = progress_callback(percent, msg)
                    if keep_going is False:
                        was_canceled = True
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                try:
                    # ✅ MODIFICAT: Acum primim și success
                    pid, pname, result, success = future.result()
                    
                    # ✅ ADĂUGAT: Tracking provideri eșuați
                    if not success:
                        failed_providers.append(pid)
                        log(f"[SCRAPER] ✗ {pname}: eșuat sau fără rezultate")
                        continue
                    
                    # ===== VALIDARE REZULTATE =====
                    if result:
                        items_to_add = []
                        
                        # Normalizare: transformă în listă
                        if isinstance(result, dict):
                            items_to_add = [result]
                        elif isinstance(result, list):
                            items_to_add = result
                        
                        # Procesare fiecare item
                        added_count = 0
                        for item in items_to_add:
                            # Skip dacă nu e dict valid
                            if not isinstance(item, dict):
                                continue
                            
                            # Skip dacă lipsește URL
                            url = item.get('url', '')
                            if not url or not isinstance(url, str):
                                continue
                            
                            # Extrage URL curat pentru deduplicare
                            clean_url = url.split('|')[0]
                            
                            if clean_url not in seen_urls:
                                # Asigură că are toate câmpurile necesare
                                item.setdefault('name', pname)
                                item.setdefault('quality', 'SD')
                                item.setdefault('title', '')
                                item.setdefault('info', '')
                                item['provider_id'] = pid
                                
                                all_streams.append(item)
                                seen_urls.add(clean_url)
                                added_count += 1
                        
                        if added_count > 0:
                            log(f"[SCRAPER] ✓ {pname}: {added_count} surse adăugate")
                        else:
                            # A returnat ceva, dar nimic valid
                            failed_providers.append(pid)

                except Exception as exc:
                    log(f"[SCRAPER] Thread exception: {exc}")
                    # Încearcă să recuperezi pid-ul din future_to_provider
                    try:
                        failed_pid = future_to_provider[future][0]
                        if failed_pid not in failed_providers:
                            failed_providers.append(failed_pid)
                    except:
                        pass

        except concurrent.futures.TimeoutError:
            log(f"[SCRAPER] Global timeout ({MAX_TIMEOUT}s)")
            # Adaugă providerii care nu au terminat la failed
            for future, provider_info in future_to_provider.items():
                if not future.done():
                    pid = provider_info[0]
                    if pid not in failed_providers:
                        failed_providers.append(pid)
                        log(f"[SCRAPER] ✗ {provider_info[1]}: timeout")

    log(f"[SCRAPER] Finalizat: {len(all_streams)} surse, {len(failed_providers)} provideri eșuați")
    return all_streams, failed_providers, was_canceled