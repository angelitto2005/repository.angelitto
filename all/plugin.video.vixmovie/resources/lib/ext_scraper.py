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
from resources.lib.ext_config import BASE_URL, API_KEY, ADDON, get_headers, get_random_ua
from resources.lib.ext_utils import get_json, clean_text
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
        xbmc.log(f"[TMDb Movies] {msg}", level)
        return
    
    # Info/Debug doar dacă e activat
    if _is_debug_enabled():
        xbmc.log(f"[TMDb Movies] {msg}", level)

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


def _parse_m3u8_variants(master_url, custom_headers=None):
    """Parses master m3u8 playlist to find available resolutions."""
    try:
        session = get_shared_session()
        headers = custom_headers if custom_headers else {"User-Agent": "Mozilla/5.0"}
        resp = session.get(master_url, headers=headers, timeout=10, verify=False)
        if resp.status_code != 200:
            return []
            
        content = resp.text
        lines = content.splitlines()
        variants = []
        base = master_url.rsplit("/", 1)[0]
        
        for i, line in enumerate(lines):
            if "#EXT-X-STREAM-INF" in line:
                resolution = "UNKNOWN"
                if "RESOLUTION=" in line:
                    try:
                        resolution = line.split("RESOLUTION=")[1].split(",")[0]
                    except: pass
                
                # Căutăm următoarea linie care nu e comentariu și nu e goală
                final_url = None
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if not next_line or next_line.startswith("#"):
                        continue
                    
                    if next_line.startswith("http"):
                        final_url = next_line
                    elif next_line.startswith("/"):
                        parsed = urlparse(master_url)
                        final_url = f"{parsed.scheme}://{parsed.netloc}{next_line}"
                    else:
                        final_url = f"{base}/{next_line}"
                    break
                
                if final_url:
                    variants.append({
                        "resolution": resolution,
                        "url": final_url
                    })
        return variants
    except Exception as e:
        log(f"[M3U8] Error parsing variants for {master_url}: {e}")
        return []


def _get_quality_from_res(res_val):
    """Detectează eticheta de calitate (1080p, 720p etc.) din string-ul de rezoluție."""
    if not res_val or res_val == "UNKNOWN": return 'SD'
    res_val = res_val.lower()
    if '2160' in res_val or '3840' in res_val or '4k' in res_val: return '4K'
    if '1080' in res_val or '1920' in res_val: return '1080p'
    if '720' in res_val or '1280' in res_val: return '720p'
    match = re.search(r'x(\d+)', res_val)
    if match:
        h = int(match.group(1))
        if h >= 2160: return '4K'
        if h >= 1000: return '1080p'
        if h >= 700: return '720p'
    return 'SD'


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
    try: exclude_hdr_dv = ADDON.getSetting('exclude_hdr_dv') == 'true'
    except: exclude_hdr_dv = False
    sort_by_quality = ADDON.getSetting('sort_by_quality') == 'true'
    
    # Statistici pentru toate calitățile
    stats = {'total': len(streams), '4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'filtered': 0}
    
    # Numără toate calitățile (înainte de filtrare)
    for stream in streams:
        normalized = _normalize_quality(stream.get('quality', 'SD'))
        stats[normalized] = stats.get(normalized, 0) + 1
    
    # Dacă nu e nimic de exclus, returnează toate
    if not any([exclude_4k, exclude_1080p, exclude_720p, exclude_sd, exclude_hdr_dv]):
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
    filtered =[]
    for stream in streams:
        normalized = _normalize_quality(stream.get('quality', 'SD'))
        if normalized in excluded:
            continue
            
        if exclude_hdr_dv:
            full_text = (str(stream.get('name', '')) + ' ' + str(stream.get('title', '')) + ' ' + str(stream.get('info', ''))).lower()
            if isinstance(stream.get('info'), dict):
                full_text += ' ' + str(stream['info'].get('original_info_str', '')).lower()
                full_text += ' ' + str(stream['info'].get('releaseGroup', '')).lower()
                
            if 'hdr' in full_text or 'dolby vision' in full_text or '.dv.' in full_text or 'hlg' in full_text or 'dovi' in full_text:
                continue
                
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


# =============================================================================
# HELPERE NOI PENTRU VIXSRC
# =============================================================================
from urllib.parse import urljoin, urlencode, parse_qsl, urlunparse

def _merge_url_query(url, query_dict):
    if not query_dict:
        return url
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query))
    params.update(query_dict)
    parts = list(parsed)
    parts[4] = urlencode(params)
    return urlunparse(parts)

def _extract_video_from_page_vixsrc(session, url, referer=''):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': referer or url}
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
            
        text = resp.text
        m3u8_pattern = r'(https?://[^\s\'"<>\)\]\}\\]+\.m3u8[^\s\'"<>\)\]\}\\]*)'
        matches = re.findall(m3u8_pattern, text)
        for match in matches:
            if 'ad' not in match.lower() or '.m3u8' in match.lower():
                return match
        
        mp4_pattern = r'(https?://[^\s\'"<>\)\]\}\\]+\.mp4[^\s\'"<>\)\]\}\\]*)'
        matches = re.findall(mp4_pattern, text)
        for match in matches:
            if 'ad' not in match.lower():
                return match
    except Exception as e:
        log(f"[VIXSRC] Generic extraction error for {url}: {e}")
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
            display_name = f"{base_name} ({year_query})"
        else:
            display_name = f"{base_name}"

        if content_type == 'tv' and season and episode:
            display_name = f"{display_name} S{int(season):02d}E{int(episode):02d}"

        base_url = 'https://vixsrc.to'
        if content_type == 'movie':
            url = f'{base_url}/movie/{tmdb_id}'
        else:
            url = f'{base_url}/tv/{tmdb_id}/{season}/{episode}'

        log(f"[VIXSRC] Interogare: {url}")
        
        session = get_shared_session()
        # VixSrc este sensibil la User-Agent. Folosim unul fix de Firefox pentru consistență.
        headers = {'Referer': f'{base_url}/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'}
        
        # New API fetch logic
        api_url = url.replace('/tv/', '/api/tv/').replace('/movie/', '/api/movie/')
        try:
            api_resp = session.get(api_url, headers=headers, timeout=10)
            target_fetch_url = url
            if api_resp.status_code == 200:
                api_json = api_resp.json()
                if 'src' in api_json:
                    target_fetch_url = urljoin(base_url, api_json['src'])
        except Exception:
            target_fetch_url = url

        wp_resp = session.get(target_fetch_url, headers={'Referer': url, 'User-Agent': headers['User-Agent']}, timeout=10)
        if wp_resp.status_code != 200:
            return None
            
        wp = wp_resp.text
        tk_match = re.search(r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]", wp)
        
        # Fallback to legacy iframe parsing just in case
        if not tk_match:
            wp_fallback = wp
            for _ in range(3):
                tk_match = re.search(r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]", wp_fallback)
                if tk_match:
                    wp = wp_fallback
                    break
                
                ip_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', wp_fallback, re.IGNORECASE)
                if not ip_match:
                    break
                
                v_match = re.search(r'data-page=["\'].*?"version"\s*:\s*"([^"]+)"', wp_fallback)
                if v_match:
                    headers.update({'x-inertia': 'true', 'x-inertia-version': v_match.group(1)})
                
                url_fallback = urljoin(url, ip_match.group(1))
                headers['Referer'] = url_fallback
                
                resp_fallback = session.get(url_fallback, headers=headers, timeout=10)
                if resp_fallback.status_code == 200:
                    wp_fallback = resp_fallback.text
                else:
                    break
        
        tk_match = re.search(r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]", wp)
        final_stream_url = None
        
        if tk_match:
            tk = tk_match.group(1)
            raw_url_match = re.search(r"(?:['\"]url['\"]|url)\s*:\s*['\"]([^'\"]+)['\"]", wp)
            if raw_url_match:
                raw_url = raw_url_match.group(1).replace('\\/', '/').replace('\\u0026', '&').replace('\\u003d', '=')
                # Transform playlist URL
                su = re.sub(r'(/playlist/[^/?]+)(?!\.m3u8)(?=[?#]|$)', r'\1.m3u8', raw_url)
                
                exp_match = re.search(r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]", wp)
                q = {'token': tk}
                if exp_match:
                    q['expires'] = exp_match.group(1)
                
                if re.search(r'canPlayFHD\s*=\s*true', wp):
                    q['h'] = '1'
                
                final_url = _merge_url_query(su, q)
                final_stream_url = f"{final_url}|Referer={url}&Origin={base_url}&User-Agent={headers['User-Agent']}"
        
        if not final_stream_url:
            raw_url = _extract_video_from_page_vixsrc(session, url, f'{base_url}/')
            if raw_url:
                final_stream_url = f"{raw_url}|Referer={url}&Origin={base_url}&User-Agent={headers['User-Agent']}"
                
        if final_stream_url:
            log(f"[VIXSRC] Master playlist URL (final_url): {final_url}")
            
            # Fetch variants from master playlist to flatten the UI
            custom_headers = {'Referer': url, 'User-Agent': headers['User-Agent']}
            variants = _parse_m3u8_variants(final_url, custom_headers=custom_headers)
            
            if variants:
                results = []
                for v in variants:
                    v_res = v.get("resolution", "UNKNOWN")
                    q_label = _get_quality_from_res(v_res)
                    
                    var_url = v.get("url")
                    if not var_url:
                        continue
                    
                    # Append headers to individual variant stream
                    stream_url_var = f"{var_url}|Referer={url}&Origin={base_url}&User-Agent={headers['User-Agent']}"
                    
                    res_obj = {
                        'name': f'VixSrc | {v_res}',
                        'url': stream_url_var,
                        'title': display_name,
                        'quality': q_label,
                        'info': '',
                        'provider_id': 'vixsrc'
                    }
                    results.append(res_obj)
                    
                log(f"[VIXSRC] ✓ {len(results)} streams (rezoluții) găsite.")
                return results
            else:
                # Fallback to single stream if master playlist parsing fails
                result = {
                    'name': 'VixSrc | HLS',
                    'url': final_stream_url,
                    'title': display_name,
                    'quality': '1080p',
                    'info': '',
                    'provider_id': 'vixsrc'
                }
                log(f"[VIXSRC] ✓ Stream găsit (fallback master): {final_stream_url[:50]}...")
                return [result]
            
        return None
        
    except Exception as e:
        log(f"[VIXSRC] Eroare: {e}")
        return None


def scrape_sooti(imdb_id, content_type, season=None, episode=None):
    """
    Scraper pentru Sooti.
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
                                'name': 'Sootio',  # Doar alias-ul principal
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

# =============================================================================
# SCRAPER DOOFLIX
# =============================================================================
def scrape_dooflix(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_dooflix') == 'false': return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id: return None

    try:
        base_api = "https://panel.watchkaroabhi.com"
        api_key = "qNhKLJiZVyoKdi9NCQGz8CIGrpUijujE"
        headers = {"X-Package-Name": "com.king.moja", "User-Agent": "dooflix", "X-App-Version": "305"}
        stream_referer = "https://molop.art/"

        if content_type == 'movie':
            req_url = f"{base_api}/api/3/movie/{tmdb_id}/links?api_key={api_key}"
        else:
            req_url = f"{base_api}/api/3/tv/{tmdb_id}/season/{season}/episode/{episode}/links?api_key={api_key}"

        session = get_shared_session()
        r = session.get(req_url, headers=headers, timeout=10, verify=False)
        if r.status_code != 200: return None
        links = r.json().get('links', [])
        if not links: return None

        streams = []
        # GENERARE TITLU PENTRU KODI UI
        display_title = title_query if title_query else "DooFlix Stream"
        if year_query and content_type == 'movie': display_title += f" ({year_query})"
        if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

        for link_obj in links:
            initial_url = link_obj.get('url')
            if not initial_url: continue
            host = link_obj.get('host', 'Server')
            try:
                res = session.get(initial_url, headers={"Referer": stream_referer, "User-Agent": headers["User-Agent"]}, allow_redirects=False, timeout=8, verify=False)
                stream_url = res.headers.get('Location') or res.headers.get('location') or res.url
                if stream_url and stream_url != initial_url:
                    if '.m3u8' in stream_url:
                        variants = _parse_m3u8_variants(stream_url, custom_headers={"Referer": stream_referer, "User-Agent": headers["User-Agent"]})
                        if variants:
                            for var in variants:
                                final_url = build_stream_url(var['url'], referer=stream_referer)
                                res_val = var['resolution']
                                quality = _get_quality_from_res(res_val)
                                streams.append({
                                    'name': f"DooFlix | {host} ({res_val})",
                                    'url': final_url,
                                    'quality': quality,
                                    'title': display_title,
                                    'size': '',
                                    'info': f"{host} | {res_val}",
                                    'provider_id': 'dooflix'
                                })
                            continue
                    
                    final_url = build_stream_url(stream_url, referer=stream_referer)
                    quality = _get_quality_from_res(host)
                    
                    streams.append({
                        'name': f"DooFlix | {host}",
                        'url': final_url,
                        'quality': quality,
                        'title': display_title,
                        'size': '',
                        'info': host,
                        'provider_id': 'dooflix'
                    })
            except Exception: pass
        return streams if streams else None
    except Exception as e:
        log(f"[DOOFLIX] Eroare: {e}", xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER VIDLINK
# =============================================================================
def scrape_vidlink(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_vidlink') == 'false': return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id: return None
    
    try:
        session = get_shared_session()
        enc_res = session.get(f"https://enc-dec.app/api/enc-vidlink?text={tmdb_id}", headers=get_headers(), timeout=10, verify=False).json()
        enc_id = enc_res.get('result')
        if not enc_id: return None
        
        headers = get_headers()
        headers.update({"Referer": "https://vidlink.pro/", "Origin": "https://vidlink.pro"})
        
        if content_type == 'movie':
            api_url = f"https://vidlink.pro/api/b/movie/{enc_id}?multiLang=0"
        else:
            api_url = f"https://vidlink.pro/api/b/tv/{enc_id}/{season}/{episode}?multiLang=0"
            
        data = session.get(api_url, headers=headers, timeout=10, verify=False).json()
        
        streams = []
        display_title = title_query if title_query else "VidLink Stream"
        if year_query and content_type == 'movie': display_title += f" ({year_query})"
        if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

        if data.get('stream', {}).get('playlist'):
            playlist_url = data['stream']['playlist']
            streams.append({
                'name': "VidLink",
                'url': build_stream_url(playlist_url, referer="https://vidlink.pro/"),
                'quality': "1080p",
                'title': display_title,
                'size': '',
                'info': "Auto HLS",
                'provider_id': 'vidlink'
            })
        
        return streams if streams else None
    except Exception as e:
        log(f"[VIDLINK] Error: {e}")
        return None


# =============================================================================
# SCRAPER VSEMBED (PlayIMDb) - IFRAME CHAIN RESOLVER (JS BYPASS)
# =============================================================================
def scrape_vsembed(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_vsembed') == 'false': return None
    if not imdb_id or not str(imdb_id).startswith('tt'): return None
    
    try:
        base_url = "https://vsembed.ru"
        play_url = f"{base_url}/embed/{imdb_id}/"
        s = get_shared_session()
        
        # Headere care imită un browser legit
        user_agent = get_random_ua()
        s.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        log(f"[VSEMBED-DEBUG] 1. Start. URL: {play_url}")
        r_play = s.get(play_url, timeout=10, verify=False)
        html = r_play.text
        
        target_url = play_url
        if content_type == 'tv':
            clean_s = str(int(season))
            clean_e = str(int(episode))
            
            ep_divs = re.findall(r'<div[^>]+class=["\']ep[^>]*>.*?</div>', html, re.IGNORECASE | re.DOTALL)
            found_iframe = None
            
            for div in ep_divs:
                if (f'data-s="{clean_s}"' in div or f"data-s='{clean_s}'" in div) and \
                   (f'data-e="{clean_e}"' in div or f"data-e='{clean_e}'" in div):
                    i_match = re.search(r'data-iframe=["\']([^"\']+)["\']', div, re.IGNORECASE)
                    if i_match:
                        found_iframe = i_match.group(1)
                        break
            
            if not found_iframe:
                all_tags = re.findall(r'<[^>]+data-iframe=["\'][^"\']+["\'][^>]*>', html, re.IGNORECASE)
                for tag in all_tags:
                    if re.search(rf'data-s=["\']{clean_s}["\']', tag) and re.search(rf'data-e=["\']{clean_e}["\']', tag):
                        i_match = re.search(r'data-iframe=["\']([^"\']+)["\']', tag, re.IGNORECASE)
                        if i_match:
                            found_iframe = i_match.group(1)
                            break
            
            if found_iframe:
                target_url = found_iframe if found_iframe.startswith('http') else f"{base_url}{found_iframe}"
                
        # --- TRAVERSARE IFRAMES (PÂNĂ LA 6 NIVELURI) cu RETRY anti-bot ---
        current_url = target_url
        current_referer = f"{base_url}/"
        prorcp_match = None
        hidden_div_match = None
        direct_m3u8 = None
        urls = []
        final_html = ""
        cloud_domain = ""
        
        for retry_attempt in range(2):  # Max 2 încercări
            if retry_attempt > 0:
                import time as _time
                _time.sleep(1.5)
                log(f"[VSEMBED-DEBUG] RETRY #{retry_attempt}: Re-fetch vsembed pentru IP warmup...")
                try:
                    r_play = s.get(play_url, timeout=10, verify=False)
                    html = r_play.text
                except:
                    break
                current_url = target_url
                current_referer = f"{base_url}/"
                prorcp_match = None
                hidden_div_match = None
                direct_m3u8 = None
            
            for depth in range(6):
                log(f"[VSEMBED-DEBUG] Traversare Nivel {depth}: {current_url}")
                try:
                    r = s.get(current_url, headers={'Referer': current_referer}, timeout=10, verify=False)
                    current_html = r.text
                    from urllib.parse import urlparse
                    cloud_domain = f"https://{urlparse(current_url).netloc}"
                except Exception as e:
                    log(f"[VSEMBED-DEBUG] Eroare accesare {current_url}: {e}")
                    break
                    
                # Condiție de ieșire 1: Am găsit scriptul prorcp
                prorcp_match = re.search(r'["\'](\\?/prorcp\\?/[^"\']+)["\']', current_html)
                
                # Condiție de ieșire 2: Am găsit direct div-ul ascuns (Cloudnestra nou)
                hidden_div_match = re.search(r'<div[^>]*id=["\']([^"\']+)["\'][^>]*style=["\']display\s*:\s*none;?["\'][^>]*>([a-zA-Z0-9:\/.,{}\-_=+ ]+)<\/div>', current_html, re.IGNORECASE)
                
                # Condiție de ieșire 3: Am găsit link direct M3U8 (VSEmbed direct)
                direct_m3u8 = re.search(r'file\s*:\s*["\'](https?://[^\s"\'<>)]+\.m3u8[^\s"\'<>)]*)["\']', current_html)
                
                if prorcp_match or hidden_div_match or direct_m3u8:
                    log(f"[VSEMBED-DEBUG] Am găsit target-ul (datele) la Nivelul {depth}!")
                    final_html = current_html
                    break
                    
                # Urmărim următorul iframe
                iframe_match = re.search(r'<iframe[^>]+id="player_iframe"[^>]+src=["\']([^"\']+)["\']', current_html, re.IGNORECASE)
                if not iframe_match:
                    iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', current_html, re.IGNORECASE)
                    
                if iframe_match:
                    next_url = iframe_match.group(1)
                    if next_url.startswith('//'): 
                        next_url = 'https:' + next_url
                    elif next_url.startswith('/'): 
                        next_url = cloud_domain + next_url
                    
                    # REPARARE: Iframe-urile pot pierde parametrii de serial
                    if content_type == 'tv' and ('s=' not in next_url and 'season=' not in next_url) and ('embed' in next_url or 'vidsrc' in next_url or 'brightpath' in next_url):
                        sep = '&' if '?' in next_url else '?'
                        next_url += f"{sep}season={season}&episode={episode}&s={season}&e={episode}"
                        
                    current_referer = current_url
                    current_url = next_url
                else:
                    log("[VSEMBED-DEBUG] Nu mai există niciun iframe de urmărit în această pagină.")
                    break
            
            # Dacă am găsit ce căutam, ieșim din bucla de retry
            if prorcp_match or hidden_div_match or direct_m3u8:
                break
            else:
                log(f"[VSEMBED-DEBUG] Traversarea #{retry_attempt} eșuată. {'Reîncercăm...' if retry_attempt == 0 else 'Abandonăm.'}")
                
        # --- PROCESARE ȘI DECRIPTARE FINALĂ ---
        
        # Cazul 1: Am găsit M3U8 direct în codul paginii
        if direct_m3u8:
            log(f"[VSEMBED-DEBUG] Link m3u8 extras direct din cod!")
            urls.append(direct_m3u8.group(1))
            
        # Cazul 2: Avem de urmat scriptul Prorcp (Varianta veche)
        elif prorcp_match:
            prorcp_path = prorcp_match.group(1).replace('\\/', '/')
            prorcp_url = cloud_domain + prorcp_path
            
            log(f"[VSEMBED-DEBUG] Accesăm Prorcp: {prorcp_url}")
            try:
                r_final = s.get(prorcp_url, headers={'Referer': current_url}, timeout=10, verify=False)
                final_html = r_final.text
            except Exception as e:
                log(f"[VSEMBED-DEBUG] Eroare la accesare prorcp: {e}")
                
        # Acum decriptăm div-ul (indiferent dacă era direct pe pagina RCP sau din scriptul Prorcp)
        if final_html and not urls:
            hidden_div = re.search(r'<div[^>]*id=["\']([^"\']+)["\'][^>]*style=["\']display\s*:\s*none;?["\'][^>]*>([a-zA-Z0-9:\/.,{}\-_=+ ]+)<\/div>', final_html, re.IGNORECASE)
            
            if hidden_div:
                div_id = hidden_div.group(1)
                div_text = hidden_div.group(2)
                log("[VSEMBED-DEBUG] Trimit datele la decriptare API enc-dec.app...")
                
                try:
                    dec_res = s.post('https://enc-dec.app/api/dec-cloudnestra', json={'text': div_text, 'div_id': div_id}, timeout=10)
                    if dec_res.status_code == 200:
                        urls = dec_res.json().get('result', [])
                    else:
                        log(f"[VSEMBED-DEBUG] Eroare API decriptare: Status {dec_res.status_code}")
                except Exception as e:
                    log(f"[VSEMBED-DEBUG] Eroare rețea API decriptare: {e}")
            else:
                log("[VSEMBED-DEBUG] AVERTISMENT: Nu s-a găsit div-ul ascuns în HTML-ul final!")
                    
            # Fallback pentru m3u8 raw (fără enc-dec app)
            if not urls:
                m3u8s = list(dict.fromkeys(re.findall(r'https?://[^\s"\'<>)]+\.m3u8[^\s"\'<>)]*', final_html)))
                _CDN_DOMAINS = ['cloudnestra.com', 'brightpathsignals.com', 'neonhorizonworkshops.com', 'wanderlynest.com', 'orchidpixelgardens.com']
                for u in m3u8s:
                    if '{v' in u:
                        for d in _CDN_DOMAINS:
                            temp = re.sub(r'\{v\d+\}', d, u)
                            urls.append(temp)
                    else:
                        urls.append(u)
                            
        log(f"[VSEMBED-DEBUG] FINAL: S-au extras {len(urls)} link-uri master valide.")
        
        # --- ADAUGARE ÎN LISTA DE STREAM-URI KODI ---
        if urls and isinstance(urls, list):
            streams = []
            display_title = title_query if title_query else "VSEmbed Stream"
            if year_query and content_type == 'movie': display_title += f" ({year_query})"
            if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

            seen_urls = set()
            for master_url in urls:
                if master_url in seen_urls or '{v' in master_url: continue
                seen_urls.add(master_url)
                
                lang = 'HN' if '_hi' in master_url.lower() or 'hindi' in master_url.lower() else 'EN'
                
                # Headere pentru parsarea playlist-ului
                custom_headers = {'Referer': 'https://cloudnestra.com/', 'User-Agent': user_agent}
                
                # Parsăm variantele M3U8
                variants = _parse_m3u8_variants(master_url, custom_headers=custom_headers)
                
                if variants:
                    for v in variants:
                        res_val = v.get("resolution", "UNKNOWN")
                        quality = _get_quality_from_res(res_val)
                        
                        var_url = v.get("url")
                        if not var_url: continue
                        
                        streams.append({
                            'name': f"VSEmbed [{lang}] | {res_val}",
                            'url': build_stream_url(var_url, referer="https://cloudnestra.com/"),
                            'quality': quality,
                            'title': display_title,
                            'size': '',
                            'info': f"Direct | {res_val}",
                            'provider_id': 'vsembed'
                        })
                else:
                    # FALLBACK: Dacă parsarea eșuează, punem direct Master URL
                    quality = '1080p' if '1080' in master_url else '720p' if '720' in master_url else 'SD'
                    if '2160' in master_url or '4k' in master_url.lower(): quality = '4K'
                    
                    streams.append({
                        'name': f"VSEmbed [{lang}]",
                        'url': build_stream_url(master_url, referer="https://cloudnestra.com/"),
                        'quality': quality,
                        'title': display_title,
                        'size': '',
                        'info': "Auto HLS",
                        'provider_id': 'vsembed'
                    })
                    
            return streams
            
    except Exception as e:
        import traceback
        log(f"[VSEMBED-DEBUG] EROARE PYTHON CRITICĂ: {e}\n{traceback.format_exc()}")
        
    return None


# =============================================================================
# SCRAPER VIDEASY (UNIFICAT ȘI ÎMBUNĂTĂȚIT)
# Înlocuiește atât scrape_fmovies, cât și scrape_videasy
# =============================================================================
def scrape_videasy(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_videasy') == 'false':
        return None
        
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None

    # Servere optimizate cu setări corecte
    servers = [
        {
            'name': 'Yoru', 
            'path': 'cdn', 
            'supports_tv': False,  # ❗ DOAR MOVIES
            'referer': 'https://www.fmovies.gd/',
            'filter_workers': True,  # Doar workers.dev
            'label': 'Original'
        },
        {
            'name': 'Vyse', 
            'path': 'hdmovie', 
            'supports_tv': True,
            'referer': 'https://www.fmovies.gd/',
            'filter_workers': False,
            'label': 'Multi-Lang'
        },
        {
            'name': 'Cypher', 
            'path': 'moviebox', 
            'supports_tv': True,
            'referer': 'https://player.videasy.net/',
            'filter_workers': False,
            'label': 'Premium'
        }
    ]

    s = get_shared_session()
    streams = []
    
    # Construim titlul afișat
    display_title = title_query or "Videasy Stream"
    if year_query and content_type == 'movie': 
        display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: 
        display_title += f" S{int(season):02d}E{int(episode):02d}"

    for srv in servers:
        # ❗ Skip servere care nu suportă TV
        if content_type == 'tv' and not srv['supports_tv']:
            log(f"[VIDEASY] Skipping {srv['name']} (movies only)")
            continue

        url = f"https://api.videasy.net/{srv['path']}/sources-with-title"
        
        params = {
            'title': title_query or '',
            'mediaType': content_type,
            'year': year_query or '',
            'tmdbId': tmdb_id,
            'imdbId': imdb_id if str(imdb_id).startswith('tt') else ''
        }
        if content_type == 'tv':
            params.update({'seasonId': season, 'episodeId': episode})

        try:
            log(f"[VIDEASY] Querying {srv['name']} ({srv['path']})...")
            
            # 1. Request cu verify=False pentru SSL issues
            r_text = s.get(url, params=params, headers=get_headers(), timeout=10, verify=False).text
            
            # Validare răspuns
            if not r_text or len(r_text) < 50 or r_text.startswith('<!') or r_text == 'Not found':
                log(f"[VIDEASY] {srv['name']} returned invalid data")
                continue

            # 2. Decriptare
            dec_res = s.post(
                'https://enc-dec.app/api/dec-videasy', 
                json={'text': r_text, 'id': str(tmdb_id)}, 
                timeout=10
            ).json()
            
            # 3. Parsare sigură (robust parsing)
            sources = []
            if isinstance(dec_res, dict):
                result_obj = dec_res.get('result', {})
                if isinstance(result_obj, dict):
                    sources = result_obj.get('sources', [])
                elif 'sources' in dec_res:
                    sources = dec_res.get('sources', [])
            
            if not isinstance(sources, list):
                log(f"[VIDEASY] {srv['name']}: 'sources' is not a list")
                continue

            log(f"[VIDEASY] {srv['name']} returned {len(sources)} sources")

            for src in sources:
                if not isinstance(src, dict) or not src.get('url'):
                    continue
                
                s_url = src['url']
                
                # ❗ Filtrare workers.dev pentru Yoru
                if srv.get('filter_workers') and 'workers.dev' not in s_url:
                    continue
                
                q_str = src.get('quality', 'Auto').lower()
                
                # Determinare calitate precisă
                if '2160' in q_str or '4k' in q_str: 
                    quality = '4K'
                elif '1080' in q_str: 
                    quality = '1080p'
                elif '720' in q_str: 
                    quality = '720p'
                elif '480' in q_str: 
                    quality = 'SD'
                else: 
                    quality = 'Auto'

                streams.append({
                    'name': f"Videasy | {srv['name']}",
                    'url': build_stream_url(
                        s_url, 
                        referer=srv['referer'],
                        origin=srv['referer'].rstrip('/')
                    ),
                    'quality': quality,
                    'title': f"{display_title} [{srv['label']}]",
                    'size': '',
                    'info': f"HLS | {src.get('quality', 'Auto')}",
                    'provider_id': 'videasy'
                })
                
        except Exception as e:
            log(f"[VIDEASY] Error on {srv['name']}: {e}")

    log(f"[VIDEASY] Total: {len(streams)} streams")
    return streams if streams else None


# =============================================================================
# SCRAPER NETMIRROR (Fixed API Headers)
# =============================================================================
def scrape_netmirror(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_netmirror') == 'false': return None
    if not title_query: return None

    import time, json
    s = get_shared_session()
    base_url = "https://net22.cc"
    play_url = "https://net52.cc"

    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    try:
        # Generăm cookie-ul inițial
        r_auth = s.post(f"{play_url}/tv/p.php", headers=get_headers(), timeout=10, verify=False)
        cookie_hdr = r_auth.headers.get('set-cookie', '')
        t_hash_t = re.search(r't_hash_t=([^;,\s]+)', cookie_hdr)
        if not t_hash_t: return None
        t_hash = t_hash_t.group(1)

        platforms = [
            {'id': 'netflix', 'ott': 'nf', 'search': f"{base_url}/search.php", 'post': f"{base_url}/post.php"},
            {'id': 'primevideo', 'ott': 'pv', 'search': f"{base_url}/pv/search.php", 'post': f"{base_url}/pv/post.php"},
            {'id': 'disney', 'ott': 'hs', 'search': f"{base_url}/mobile/hs/search.php", 'post': f"{base_url}/mobile/hs/post.php"}
        ]

        streams = []

        for plat in platforms:
            cookie_str = f"t_hash_t={t_hash}; user_token=233123f803cf02184bf6c67e149cdd50; hd=on; ott={plat['ott']}"
            
            # Header-e esențiale pentru AJAX-ul lor
            api_headers = {
                "User-Agent": get_random_ua(),
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": cookie_str,
                "Referer": f"{base_url}/tv/home"
            }

            r_search = s.get(f"{plat['search']}?s={quote(title_query)}&t={int(time.time())}", headers=api_headers, timeout=10, verify=False)
            if r_search.status_code != 200: continue
            
            try: results = r_search.json().get('searchResult', [])
            except: continue
            
            if not results: continue

            # Potrivire flexibilă
            best_match = None
            title_words = [w.lower() for w in re.sub(r'[^a-zA-Z0-9]', ' ', title_query).split() if len(w) > 2]
            for res in results:
                rtitle = res.get('t', '').lower()
                if sum(1 for w in title_words if w in rtitle) >= min(2, len(title_words)):
                    best_match = res
                    break
            if not best_match: best_match = results[0]

            target_id = best_match.get('id')
            if not target_id: continue

            r_post = s.get(f"{plat['post']}?id={target_id}&t={int(time.time())}", headers=api_headers, timeout=10, verify=False).json()

            if content_type == 'tv':
                episodes = r_post.get('episodes', [])
                ep_obj = None
                for ep in episodes:
                    eps = str(ep.get('s', ep.get('season', ''))).replace('S', '')
                    epe = str(ep.get('ep', ep.get('episode', ''))).replace('E', '')
                    if eps == str(season) and epe == str(episode):
                        ep_obj = ep
                        break
                if not ep_obj: continue
                target_id = ep_obj.get('id')

            r_play1 = s.post(f"{base_url}/play.php", data=f"id={target_id}", headers={**api_headers, "Content-Type": "application/x-www-form-urlencoded"}, timeout=10, verify=False).json()
            h_param = r_play1.get('h')
            if not h_param: continue

            r_play2 = s.get(f"{play_url}/play.php?id={target_id}&{h_param}", headers=api_headers, timeout=10, verify=False).text
            data_h = re.search(r'data-h="([^"]+)"', r_play2)
            if not data_h: continue

            pl_path = '/playlist.php' if plat['id'] == 'netflix' else ('/pv/playlist.php' if plat['id'] == 'primevideo' else '/mobile/hs/playlist.php')
            pl_url = f"{play_url}{pl_path}?id={target_id}&t={quote(title_query)}&tm={int(time.time())}&h={quote(data_h.group(1))}"
            r_pl = s.get(pl_url, headers={**api_headers, "Referer": f"{play_url}/"}, timeout=10, verify=False).json()

            for item in r_pl:
                for src in item.get('sources', []):
                    file_url = src.get('file', '')
                    if not file_url: continue
                    if not file_url.startswith('http'): file_url = f"{play_url}{file_url if file_url.startswith('/') else '/' + file_url}"

                    q_label = src.get('label', '')
                    quality = '1080p' if '1080' in q_label else '720p' if '720' in q_label else '480p' if '480' in q_label else 'SD'

                    lang_list = [l.get('l', '') for l in r_post.get('lang', []) if l.get('l')]
                    lang_str = f" [{lang_list[0]}]" if lang_list else ""

                    streams.append({
                        'name': f"NetMirror | {plat['id'].title()}",
                        'url': build_stream_url(file_url, referer=f"{play_url}/"),
                        'quality': quality,
                        'title': f"{display_title}{lang_str}",
                        'size': '',
                        'info': "Direct HLS",
                        'provider_id': 'netmirror'
                    })
            if streams: break
        return streams if streams else None
    except Exception as e:
        log(f"[NETMIRROR] Error: {e}")
        return None


# =============================================================================
# SCRAPER CASTLE (Decriptare AES)
# =============================================================================
def scrape_castle(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_castle') == 'false': return None
    if not title_query: return None

    import json
    s = get_shared_session()
    base_api = "https://api.fstcy.com"
    dec_api = "https://aesdec.nuvioapp.space/decrypt-castle"

    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    def decrypt(encrypted_b64, key):
        res = s.post(dec_api, json={'encryptedData': encrypted_b64, 'securityKey': key}, timeout=10, verify=False).json()
        if 'decrypted' in res: return json.loads(res['decrypted'])
        return {}

    def get_cipher(url, params=None, method='GET', json_data=None):
        h = {'User-Agent': 'okhttp/4.9.3', 'Referer': base_api}
        if method == 'GET': r = s.get(url, params=params, headers=h, timeout=10, verify=False)
        else: r = s.post(url, json=json_data, headers=h, timeout=10, verify=False)
        try: return r.json().get('data', r.text.strip())
        except: return r.text.strip()

    try:
        r_sec = s.get(f"{base_api}/v0.1/system/getSecurityKey/1?channel=IndiaA&clientType=1&lang=en-US", headers={'User-Agent': 'okhttp/4.9.3'}, timeout=10, verify=False).json()
        sec_key = r_sec.get('data')
        if not sec_key: return None

        search_url = f"{base_api}/film-api/v1.1.0/movie/searchByKeyword"
        search_params = {'channel': 'IndiaA', 'clientType': '1', 'keyword': title_query, 'lang': 'en-US', 'mode': '1', 'packageName': 'com.external.castle', 'page': '1', 'size': '30'}
        cipher_search = get_cipher(search_url, params=search_params)
        search_data = decrypt(cipher_search, sec_key)

        rows = search_data.get('data', {}).get('rows', [])
        if not rows: return None
        
        target_id = None
        for row in rows:
            if title_query.lower() in str(row.get('title', '')).lower():
                target_id = row.get('id') or row.get('redirectId')
                break
        if not target_id: target_id = rows[0].get('id') or rows[0].get('redirectId')
        if not target_id: return None

        det_url = f"{base_api}/film-api/v1.1/movie?channel=IndiaA&clientType=1&lang=en-US&movieId={target_id}&packageName=com.external.castle"
        cipher_det = get_cipher(det_url)
        det_data = decrypt(cipher_det, sec_key)
        d = det_data.get('data', {})

        episode_id = None
        if content_type == 'tv':
            eps = d.get('episodes', [])
            for ep in eps:
                if str(ep.get('number')) == str(episode):
                    episode_id = ep.get('id')
                    break
        else:
            eps = d.get('episodes', [])
            if eps: episode_id = eps[0].get('id')

        if not episode_id: return None

        vid_url = f"{base_api}/film-api/v2.0.1/movie/getVideo2?clientType=1&packageName=com.external.castle&channel=IndiaA&lang=en-US"
        body = {'mode':'1', 'appMarket':'GuanWang', 'clientType':'1', 'woolUser':'false', 'apkSignKey':'ED0955EB04E67A1D9F3305B95454FED485261475', 'androidVersion':'13', 'movieId':str(target_id), 'episodeId':str(episode_id), 'isNewUser':'true', 'resolution':'2', 'packageName':'com.external.castle'}
        cipher_vid = get_cipher(vid_url, method='POST', json_data=body)
        vid_data = decrypt(cipher_vid, sec_key)

        vdata = vid_data.get('data', {})
        video_url = vdata.get('videoUrl')
        
        streams = []
        if video_url:
            streams.append({
                'name': 'Castle',
                'url': build_stream_url(video_url),
                'quality': '720p',
                'title': display_title,
                'size': '',
                'info': "Direct Video",
                'provider_id': 'castle'
            })
        
        if vdata.get('videos'):
            for v in vdata['videos']:
                if v.get('url'):
                    streams.append({
                        'name': 'Castle',
                        'url': build_stream_url(v['url']),
                        'quality': '1080p' if '1080' in str(v.get('resolutionDescription', '')) else '720p',
                        'title': display_title,
                        'size': '',
                        'info': str(v.get('resolutionDescription', 'Direct Video')),
                        'provider_id': 'castle'
                    })

        unique_streams = []
        seen = set()
        for s in streams:
            if s['url'] not in seen:
                unique_streams.append(s)
                seen.add(s['url'])

        return unique_streams if unique_streams else None

    except Exception as e:
        log(f"[CASTLE] Error: {e}")
        return None


# =============================================================================
# SCRAPER VIDMODY (Strict Timeout Fix)
# =============================================================================
def scrape_vidmody(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_vidmody') == 'false': return None
    if not imdb_id or not str(imdb_id).startswith('tt'): return None
    
    display_title = title_query if title_query else "Vidmody Stream"
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    target_url = f"https://vidmody.com/vs/{imdb_id}#.m3u8" if content_type == 'movie' else f"https://vidmody.com/vs/{imdb_id}/s{season}/e{int(episode):02d}#.m3u8"

    try:
        import requests
        # Folosim o cerere nativă requests (fără session retry) cu timeout agresiv de 3 secunde
        res = requests.head(target_url.replace('#.m3u8', ''), headers=get_headers(), timeout=3, verify=False, allow_redirects=True)
        if res.status_code == 200:
            return [{
                'name': 'Vidmody',
                'url': build_stream_url(target_url, referer="https://vidmody.com/"),
                'quality': '1080p',
                'title': display_title,
                'size': '',
                'info': 'Auto HLS',
                'provider_id': 'vidmody'
            }]
    except Exception as e: 
        log(f"[VIDMODY] Skipped (Timeout or Error): {e}")
    return None


# =============================================================================
# SCRAPER MOVIEBLAST (HMAC-SHA256 Token Auth)
# =============================================================================
def scrape_movieblast(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_movieblast') == 'false': return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id: return None
    
    import hmac, hashlib, base64, time
    from urllib.parse import urlparse

    base_url = "https://app.cloud-mb.xyz"
    token = "jdvhhjv255vghhghdhvfch2565656jhdcghfdf"
    sign_secret = b"GJ8reydarI7Jqat9rvbAJKNQ9gY4DoEQF2H5nfuI1gi"
    headers = {"user-agent": "okhttp/5.0.0-alpha.6", "x-request-x": "com.movieblast"}
    search_headers = {**headers, "hash256": "86dc03244adddb3cbedbf0ae36074a736ee293a64774b18e82a6244eafd0df30", "packagename": "com.movieblast"}

    display_title = title_query if title_query else "MovieBlast Stream"
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    def gen_signed_url(url_str):
        try:
            path = urlparse(url_str).path
            ts = str(int(time.time()))
            msg = (path + ts).encode('utf-8')
            h = hmac.new(sign_secret, msg, hashlib.sha256).digest()
            sig = base64.b64encode(h).decode('utf-8')
            return f"{url_str}?verify={ts}-{quote(sig)}"
        except: return url_str

    s = get_shared_session()
    try:
        s_res = s.get(f"{base_url}/api/search/{quote(title_query)}/{token}", headers=search_headers, timeout=10, verify=False).json()
        results = s_res.get('search', [])
        if not results: return None
        
        match = next((r for r in results if title_query.lower() in r.get('name', '').lower()), results[0])
        internal_id = match['id']
        is_series = 'serie' in match.get('type', '').lower() or content_type == 'tv'
        
        detail_path = "series/show" if is_series else "media/detail"
        d_res = s.get(f"{base_url}/api/{detail_path}/{internal_id}/{token}", headers=headers, timeout=10, verify=False).json()
        
        target_videos = []
        if is_series:
            for season_obj in d_res.get('seasons', []):
                if str(season_obj.get('season_number')) == str(season):
                    for ep_obj in season_obj.get('episodes', []):
                        if str(ep_obj.get('episode_number')) == str(episode):
                            target_videos = ep_obj.get('videos', [])
                            break
                    break
        else:
            target_videos = d_res.get('videos', [])
            
        if not target_videos: return None
        
        streams = []
        for vid in target_videos:
            raw_url = vid.get('link')
            if not raw_url: continue
            https_url = raw_url if raw_url.startswith('http') else f"https://{raw_url}"
            
            srv = str(vid.get('server', '')).lower()
            quality = '4K' if '2160' in srv or '4k' in srv else '1080p' if '1080' in srv else '720p' if '720' in srv else 'SD'
            
            streams.append({
                'name': f"MovieBlast | {vid.get('server', 'Server')}",
                'url': build_stream_url(gen_signed_url(https_url), referer="MovieBlast"),
                'quality': quality,
                'title': f"{display_title} [{vid.get('lang', 'EN')}]",
                'size': '',
                'info': "Signed API",
                'provider_id': 'movieblast'
            })
        return streams if streams else None
    except Exception as e:
        log(f"[MOVIEBLAST] Error: {e}")
        return None


# =============================================================================
# SCRAPER MOVIEBOX (CU REZOLVARE DE REDIRECT)
# =============================================================================
def scrape_moviebox(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_moviebox') == 'false': return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id: return None
    
    worker_base = "https://moviebox.s4nch1tt.workers.dev"
    # Folosim quote_plus pentru siguranță maximă la encodare URL
    from urllib.parse import quote_plus
    url = f"{worker_base}/streams?tmdb_id={tmdb_id}&type={content_type}&proxy={quote_plus(worker_base)}"
    if content_type == 'tv': url += f"&se={season}&ep={episode}"
    
    try:
        s = get_shared_session()
        r = s.get(url, headers={'Accept': 'application/json', 'User-Agent': 'Nuvio/1.0'}, timeout=15).json()
        
        raw_streams = r if isinstance(r, list) else r.get('streams', [])
        if not raw_streams:
            return None
            
        streams = []
        display_title = title_query if title_query else "MovieBox Stream"
        if year_query and content_type == 'movie': display_title += f" ({year_query})"
        if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

        for item in raw_streams:
            # Luăm întotdeauna proxy_url dacă există, așa cum face și codul JS
            proxy_url = item.get('proxy_url')
            if not proxy_url:
                continue

            # --- AICI ESTE MAGIA: REZOLVAREA REDIRECT-ULUI ---
            resolved_url = None
            try:
                log(f"[MOVIEBOX] Resolving redirect for: {proxy_url}")
                # Folosim o cerere HEAD pentru eficiență - nu descărcăm tot conținutul, doar header-ele
                # allow_redirects=True este implicit, dar îl punem pentru claritate
                # stream=True ajută la a nu citi tot corpul în memorie
                # Este important să folosim o sesiune nouă sau una curată pentru a evita conflictele de cookie-uri
                # Dar vom încerca cu sesiunea partajată inițial.
                
                # În loc de o sesiune nouă, folosim direct librăria requests pentru a fi siguri
                # că nu avem header-e conflictuale de la sesiunea anterioară.
                # Cererea GET este uneori mai fiabilă decât HEAD pentru servere prost configurate.
                with requests.get(proxy_url, headers={'User-Agent': 'Nuvio/1.0'}, stream=True, timeout=10, allow_redirects=True) as res:
                    # După ce toate redirect-urile s-au terminat, `res.url` va conține URL-ul final
                    resolved_url = res.url
                    log(f"[MOVIEBOX] Resolved to: {resolved_url}")

            except Exception as resolve_error:
                log(f"[MOVIEBOX] Failed to resolve URL: {resolve_error}")
                continue # Trecem la următorul stream dacă rezolvarea eșuează

            if not resolved_url:
                continue
            # --------------------------------------------------

            res_str = str(item.get('resolution', ''))
            quality = '4K' if '2160' in res_str else '1080p' if '1080' in res_str else '720p' if '720' in res_str else 'SD'
            
            lang_match = re.search(r'\(([^)]+)\)', item.get('name', ''))
            lang = lang_match.group(1) if lang_match else 'Original'
            
            size_mb = item.get('size_mb')
            size_str = f"{size_mb} MB" if size_mb and float(size_mb) > 0 else ""
            codec = item.get('codec', '')
            
            streams.append({
                'name': f"MovieBox | {lang}",
                # Folosim URL-ul rezolvat, nu cel proxy!
                'url': resolved_url,
                'quality': quality,
                'title': display_title,
                'size': size_str,
                'info': codec,
                'provider_id': 'moviebox'
            })
            
        return streams if streams else None
        
    except Exception as e:
        import traceback
        log(f"[MOVIEBOX] Scraper Error: {e}\n{traceback.format_exc()}")
        return None


# =============================================================================
# SCRAPER LAMOVIE (Cu Resolvere Native: Vimeos, StreamWish, VOE)
# =============================================================================

def _unpack_eval(payload, radix, symtab):
    """Decodor nativ pentru scripturi JS împachetate cu P.A.C.K.E.R."""
    import string
    chars = string.digits + string.ascii_lowercase + string.ascii_uppercase
    
    def baseN_to_10(word, base):
        res = 0
        for char in word:
            if char not in chars: return 0
            res = res * base + chars.index(char)
        return res
        
    def repl(match):
        word = match.group(0)
        idx = baseN_to_10(word, radix)
        if idx < len(symtab) and symtab[idx]:
            return symtab[idx]
        return word
        
    return re.sub(r'\b([0-9a-zA-Z]+)\b', repl, payload)

def _voe_decode(ct, luts):
    """Decriptare avansată pentru VOE.SX"""
    import base64
    try:
        raw_luts = re.sub(r"^\[|\]$", "", luts).split("','")
        raw_luts = [s.strip("'") for s in raw_luts]
        txt = ""
        for ci in range(len(ct)):
            x = ord(ct[ci])
            if 64 < x < 91: x = (x - 52) % 26 + 65
            elif 96 < x < 123: x = (x - 84) % 26 + 97
            txt += chr(x)
        for lut in raw_luts:
            txt = txt.replace(lut, "_")
        txt = txt.replace("_", "")
        decoded1 = base64.b64decode(txt).decode('utf-8', errors='ignore')
        step4 = ""
        for si in range(len(decoded1)):
            step4 += chr((ord(decoded1[si]) - 3 + 256) % 256)
        rev_base64 = step4[::-1]
        final_str = base64.b64decode(rev_base64).decode('utf-8', errors='ignore')
        import json
        return json.loads(final_str)
    except Exception as e:
        return None

def scrape_lamovie(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_lamovie') == 'false': return None
    if not title_query: return None
    
    base_url = "https://la.movie"
    api_url = f"{base_url}/wp-api/v1"
    s = get_shared_session()
    
    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    def resolve_embed(embed_url):
        from urllib.parse import urlparse
        try:
            # 1. VIMEOS
            if 'vimeos' in embed_url:
                html = s.get(embed_url, headers={"Referer": f"{base_url}/"}, timeout=10, verify=False).text
                pack_match = re.search(r'eval\(function\(p,a,c,k,e,[a-z]\)\{[\s\S]+?\}\(\'([\s\S]+?)\',(\d+),(\d+),\'([\s\S]+?)\'\.split\(\'\|\'\)', html)
                if pack_match:
                    payload, radix, count, symtab_str = pack_match.groups()
                    symtab = symtab_str.split('|')
                    unpacked = _unpack_eval(payload, int(radix), symtab)
                    file_match = re.search(r'file:"(https?:\/\/[^"]+\.m3u8[^"]*)"', unpacked) or re.search(r'["\'](https?:\/\/[^"\']+\.m3u8[^"\']*)[\'"]', unpacked)
                    if file_match:
                        return file_match.group(1), {"Referer": "https://vimeos.net/"}
                        
            # 2. STREAMWISH / HLSWISH / VIBUXER
            elif any(x in embed_url for x in ['hlswish', 'streamwish', 'strwish', 'vibuxer']):
                host = f"https://{urlparse(embed_url).netloc}"
                html = s.get(embed_url, headers={"Referer": "https://embed69.org/"}, timeout=10, verify=False).text
                
                file_match = re.search(r'file\s*:\s*["\']([^"\']+)["\']', html)
                if file_match: return file_match.group(1), {"Referer": f"{host}/"}
                
                pack_match = re.search(r'eval\(function\(p,a,c,k,e,[a-z]\)\{[^}]+\}\s*\(\'([\s\S]+?)\',\s*(\d+),\s*(\d+),\s*\'([\s\S]+?)\'\.split\(\'\|\'\)', html)
                if pack_match:
                    payload, radix, count, symtab_str = pack_match.groups()
                    symtab = symtab_str.split('|')
                    unpacked = _unpack_eval(payload, int(radix), symtab)
                    m3_match = re.search(r'["\']([^"\']{30,}\.m3u8[^"\']*)[\'"]', unpacked)
                    if m3_match:
                        return m3_match.group(1), {"Referer": f"{host}/"}
                        
                raw_m3 = re.search(r'https?:\/\/[^"\'\s\\]+\.m3u8[^"\'\s\\]*', html)
                if raw_m3: return raw_m3.group(0), {"Referer": f"{host}/"}
                
            # 3. VOE
            elif 'voe' in embed_url:
                html = s.get(embed_url, timeout=10, verify=False).text
                r_main = re.search(r'json">\s*\[s*[\'"]([^\'"]+)[\'"]\s*\]\s*<\/script>\s*<script[^>]*src=[\'"]([^\'"]+)[\'"]', html)
                if r_main:
                    encoded_arr, js_url = r_main.groups()
                    js_url = js_url if js_url.startswith('http') else f"https://{urlparse(embed_url).netloc}{js_url}"
                    js_data = s.get(js_url, timeout=10, verify=False).text
                    repl_match = re.search(r'(\[(?:\'[^\']{1,10}\'[\s,]*){4,12}\])', js_data) or re.search(r'(\[(?:"[^"]{1,10}"[,\s]*){4,12}\])', js_data)
                    if repl_match:
                        decoded = _voe_decode(encoded_arr, repl_match.group(1))
                        if decoded and (decoded.get('source') or decoded.get('direct_access_url')):
                            return decoded.get('source') or decoded.get('direct_access_url'), {"Referer": embed_url}
                
                raw_mp4 = re.search(r'(?:mp4|hls)[\'"\s]*:\s*[\'"]([^\'"]+)[\'"]', html)
                if raw_mp4:
                    url = raw_mp4.group(1)
                    if url.startswith('aHR0'):
                        import base64
                        try: url = base64.b64decode(url).decode('utf-8')
                        except: pass
                    return url, {"Referer": embed_url}
                    
        except Exception as e:
            log(f"[LAMOVIE] Resolver Error for {embed_url}: {e}")
            
        return None, None

    try:
        ptype = "movies" if content_type == 'movie' else "tvshows"
        r_search = s.get(f"{api_url}/search?q={quote(title_query)}&postType={ptype}&postsPerPage=10", headers={"Accept": "application/json", "Referer": f"{base_url}/"}, timeout=10, verify=False).json()
        
        posts = r_search.get('data', {}).get('posts', [])
        if not posts: return None
        
        best_post = posts[0]
        post_id = best_post.get('_id')
        if not post_id: return None
        
        target_id = post_id
        if content_type == 'tv':
            r_eps = s.get(f"{api_url}/single/episodes/list?_id={post_id}&season={season}&page=1&postsPerPage=50", headers={"Accept": "application/json", "Referer": f"{base_url}/"}, timeout=10, verify=False).json()
            eps = r_eps.get('data', {}).get('posts', [])
            ep_post = next((e for e in eps if str(e.get('season_number')) == str(season) and str(e.get('episode_number')) == str(episode)), None)
            if not ep_post: return None
            target_id = ep_post.get('_id')

        r_player = s.get(f"{api_url}/player?postId={target_id}&demo=0", headers={"Accept": "application/json", "Referer": f"{base_url}/"}, timeout=10, verify=False).json()
        embeds = r_player.get('data', {}).get('embeds', [])
        if not embeds: return None
        
        streams = []
        import concurrent.futures
        
        # Rezolvăm iframe-urile în paralel pentru viteză
        def process_embed(embed):
            e_url = embed.get('url')
            if not e_url: return None
            
            final_url, extra_headers = resolve_embed(e_url)
            if not final_url: return None
            
            server_name = "StreamWish" if any(x in e_url for x in ['wish','vibux']) else "VOE" if 'voe' in e_url else "Vimeos" if 'vimeos' in e_url else "Online"
            
            # FIX PENTRU CALITATEA "FULL HD" vs "1080p"
            raw_q = embed.get('quality', '1080p').lower()
            if '1080' in raw_q or 'full' in raw_q or 'fhd' in raw_q: quality = '1080p'
            elif '720' in raw_q or 'hd' in raw_q: quality = '720p'
            elif '4k' in raw_q or '2160' in raw_q: quality = '4K'
            else: quality = 'SD'
            
            # Combinăm refererul cerut de host cu cel din Kodi
            from urllib.parse import urlencode
            hdrs = {'User-Agent': get_random_ua()}
            if extra_headers: hdrs.update(extra_headers)
            url_with_headers = f"{final_url}|{urlencode(hdrs)}"
            
            return {
                'name': f"LaMovie | {server_name}",
                'url': url_with_headers,
                'quality': quality,
                'title': display_title,
                'size': '',
                'info': "Direct Video",
                'provider_id': 'lamovie'
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_embed, e) for e in embeds]
            for f in concurrent.futures.as_completed(futures, timeout=15):
                res = f.result()
                if res: streams.append(res)
            
        return streams if streams else None
    except Exception as e:
        log(f"[LAMOVIE] Fatal Error: {e}")
        return None

# =============================================================================
# SCRAPER ONLYKDRAMA (FilePress + AJAX)
# =============================================================================
def scrape_onlykdrama(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_onlykdrama') == 'false': return None
    if not title_query: return None

    base_url = "https://onlykdrama.top"
    s = get_shared_session()
    
    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    try:
        r_search = s.get(f"{base_url}/?s={quote(title_query)}", headers=get_headers(), timeout=20, verify=False).text
        link_regex = r'href=["\'](https?://onlykdrama\.top/(?:movies|drama)/[^"\']+)["\']'
        links = re.findall(link_regex, r_search, re.I)
        if not links: return None
        
        # Filtrăm primul link valid
        target_url = links[0]
        html = s.get(target_url, headers=get_headers(), timeout=10, verify=False).text
        streams = []

        if content_type == 'movie':
            options = re.findall(r'data-post=["\']([^"\']+)["\'][^>]*data-nume=["\']([^"\']+)["\'][^>]*data-type=["\']([^"\']+)["\']', html)
            for post, nume, ttype in options:
                res = s.post(f"{base_url}/wp-admin/admin-ajax.php", data={"action":"doo_player_ajax", "post":post, "nume":nume, "type":ttype}, headers={"Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest", "Referer": target_url}, timeout=10, verify=False).json()
                embed = res.get('embed_url', '')
                if embed:
                    parsed_url = embed.split('source=')[-1] if 'source=' in embed else embed
                    streams.append({'name': 'OnlyKDrama', 'url': build_stream_url(parsed_url), 'quality': '1080p', 'title': display_title, 'size': '', 'info': 'Fast Stream', 'provider_id': 'onlykdrama'})
        else:
            anchors = re.findall(r'<a[^>]+href=["\'](https://new3\.filepress\.wiki/file/([A-Za-z0-9]+))["\'][^>]*>([\s\S]*?)</a>', html, re.I)
            for full_url, file_id, text in anchors:
                if f"E{int(episode):02d}" in text or f"Episode {int(episode)}" in text or f"E{int(episode)}" in text:
                    fp_headers = {"Origin": "https://new3.filepress.wiki", "Referer": full_url, "Content-Type": "application/json", "User-Agent": get_random_ua()}
                    
                    r1 = s.post("https://new3.filepress.wiki/api/file/downlaod/", json={"id":file_id, "method":"indexDownlaod", "captchaValue":""}, headers=fp_headers, timeout=10, verify=False).json()
                    if r1.get('status') and r1.get('data'):
                        r2 = s.post("https://new3.filepress.wiki/api/file/downlaod2/", json={"id":r1['data'], "method":"indexDownlaod", "captchaValue":""}, headers=fp_headers, timeout=10, verify=False).json()
                        final_url = r2.get('data', [''])[0] if isinstance(r2.get('data'), list) else r2.get('data')
                        if final_url:
                            streams.append({'name': 'OnlyKDrama', 'url': build_stream_url(final_url), 'quality': '1080p', 'title': display_title, 'size': '', 'info': 'FilePress API', 'provider_id': 'onlykdrama'})
                    break

        return streams if streams else None
    except Exception as e:
        log(f"[ONLYKDRAMA] Error: {e}")
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
    return "https://new1.hdhub4u.limo" 


# =============================================================================
# SCRAPER HDHUB4U (V15 - ADDED MISSING DOMAINS + BRANCH LABEL)
# =============================================================================

def _extract_quality_from_string(text):
    """
    Extrage calitatea video dintr-un string.
    """
    if not text:
        return None
    
    t = text.lower()
    
    # === ADAUGARE NOUĂ: Detectare Multi-Rezoluție (pentru link-uri generice) ===
    clean_t = t.replace('ds4k', '').replace('hdr4k', '').replace('sdr4k', '').replace('4khdhub', '')
    res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in t)
    if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_t) and '2160p' not in t: 
        res_count += 1
    
    if res_count >= 2:
        # log(f"[QUALITY] Multi-resolution detected -> forcing SD")
        return 'SD'
    # =======================================================================
    
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
            # log(f"[QUALITY] Found 2160p after year -> 4K")
            return '4K'
        if first_segment.startswith('1080p'):
            # log(f"[QUALITY] Found 1080p after year")
            return '1080p'
        if first_segment.startswith('720p'):
            # log(f"[QUALITY] Found 720p after year")
            return '720p'
        if first_segment.startswith('480p'):
            # log(f"[QUALITY] Found 480p after year")
            return '480p'
        if first_segment.startswith('360p'):
            # log(f"[QUALITY] Found 360p after year")
            return '360p'
        # 4K trebuie să fie EXACT "4k" la început, nu parte din alt cuvânt
        if first_segment == '4k' or first_segment.startswith('4k-') or first_segment.startswith('4k.'):
            # log(f"[QUALITY] Found 4K after year")
            return '4K'
    
    # =================================================================
    # METODA 2 (FALLBACK): Caută oriunde în text
    # IMPORTANT: 720p și 1080p au PRIORITATE față de 4K!
    # =================================================================
    
    # Verifică calitățile numerice ÎN ORDINE DE PRIORITATE
    # (evităm să găsim 4K din DS4K înainte de 720p real)
    if '720p' in t:
        # log(f"[QUALITY] Fallback: found 720p in text")
        return '720p'
    
    if '1080p' in t:
        # log(f"[QUALITY] Fallback: found 1080p in text")
        return '1080p'
    
    if '2160p' in t:
        # log(f"[QUALITY] Fallback: found 2160p in text -> 4K")
        return '4K'
    
    if '480p' in t:
        # log(f"[QUALITY] Fallback: found 480p in text")
        return '480p'
    
    if '360p' in t:
        # log(f"[QUALITY] Fallback: found 360p in text")
        return '360p'
    
    # 4K DOAR dacă nu e precedat de literă (evită DS4K, HDR4K, SDR4K)
    # Pattern: spațiu/punct/început + 4k + non-literă
    if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', t):
        # log(f"[QUALITY] Fallback: found standalone 4K")
        return '4K'
    
    # UHD = 4K
    if 'uhd' in t or 'ultrahd' in t:
        # log(f"[QUALITY] Fallback: found UHD -> 4K")r
        return '4K'
    
    # log(f"[QUALITY] No quality found in: {t[:50]}")
    return None


def _is_web_source(text):
    """
    Filtrează doar dacă textul conține: 
    webrip, bdrip, hdrip, dvdrip, web-dl, web dl, web.dl, web-dlrip, web dlrip, web.dlrip.
    Ignoră complet 'web' (izolat) sau 'webdl' (legat).
    """
    if not text:
        return False
    
    # Am scos \b de la capete pentru ca termenii sa fie gasiti chiar si daca
    # sunt lipiti de underscore (_) ca in: _2026_WEBRip
    pattern = r'webrip|bdrip|hdrip|dvdrip|web[- .]dl(rip)?'
    
    if re.search(pattern, text, re.IGNORECASE):
        return True
        
    return False


def _identify_host_from_url(url):
    """Identifică numele host-ului din URL - VERSIUNE V3 cu TrashBytes și altele."""
    if not url:
        return 'Direct'
    
    url_lower = url.lower()
    
    # Ordinea contează - cele mai specifice primele!
    if 'pixeldrain.dev/api/file' in url_lower or 'pixeldrain.com/api/file' in url_lower:
        return 'PixelDrain'
    elif 'pixel.hubcdn' in url_lower:
        return 'HubPixel (10Gbps)'
    elif 'yummy.monster' in url_lower:
        return 'FSL Server'
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
        'googleusercontent.com', # <--- ADĂUGAT
        'googlevideo.com'        # <--- ADĂUGAT
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
        'yummy.monster',              # FSL / Hub Yummy Monster (NOU)
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
        'googleusercontent.com', 'googlevideo.com'
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
                'Referer': 'https://mkvcinemas.al/',
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
                        # log(f"[RESOLVE] Title: {current_title[:50]}...")
                
                # Extrage mărimea din pagină (dacă există)
                size_match = re.search(r'>Size\s*:\s*([\d.]+)\s*(GB|MB)', content, re.IGNORECASE)
                if not size_match:
                    size_match = re.search(r'File Size\s*:\s*([\d.]+)\s*(GB|MB)', content, re.IGNORECASE)
                if not size_match:
                    size_match = re.search(r'([\d.]+)\s*(GB|MB)(?:</|<br)', content, re.IGNORECASE)
                
                if size_match:
                    current_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                    # log(f"[RESOLVE] Size: {current_size}")

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
    return "https://new2.moviesdrives.my"


# =============================================================================
# FUNCȚIA REPARATĂ: _process_filesdl_cloud_page (V13 - SUPORT COMPLET DRIVE & HUBCLOUD)
# =============================================================================

def _process_filesdl_cloud_page(url, quality_label, title_label, info_label):
    """
    Procesează paginile FilesDL / HubCDN cu REZOLVARE intermediari.
    V13 - FIX: Suportă și URL-uri cu /drive/ și rezolvă HubCloud/GDFlix incluse!
    """
    streams = []
    log(f"[CLOUD] Processing URL: {url}")
    
    try:
        headers = get_headers()
        domain_netloc = urlparse(url).netloc
        headers['Referer'] = f'https://{domain_netloc}/'
        
        r = requests.get(url, headers=headers, timeout=12, verify=False)
        if r.status_code != 200:
            return []
            
        html = r.text
        
        # 1. HubCDN DL Bypass
        dl_link = None
        dl_match = re.search(r'["\'](https?://[^"\']*/dl/\?link=[^"\']+)["\']', html)
        if not dl_match: dl_match = re.search(r'["\'](/dl/\?link=[^"\']+)["\']', html)
        if dl_match: dl_link = dl_match.group(1)
        else:
            js_token = re.search(r'/dl/\?link=["\']?\s*\+?\s*["\']([a-zA-Z0-9_-]+)["\']', html)
            if js_token: dl_link = f"/dl/?link={js_token.group(1)}"
        if dl_link:
            if dl_link.startswith('/'): dl_link = f"https://{domain_netloc}{dl_link}"
            r2 = requests.get(dl_link, headers=headers, timeout=12, verify=False)
            if r2.status_code == 200: html = r2.text

        # 2. Google Direct Extractor
        vd_match = re.search(r'id=["\']vd["\'][^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not vd_match: vd_match = re.search(r'href=["\']([^"\']+video-downloads\.googleusercontent[^"\']+)["\']', html, re.IGNORECASE)
        if vd_match:
            direct_google_url = vd_match.group(1)
            safe_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            streams.append({
                'name': 'MKV | GoogleDrive',
                'url': f"{direct_google_url}|User-Agent={safe_ua}&seekable=0",
                'quality': quality_label,
                'title': title_label,
                'size': '',
                'info': info_label or ""
            })
            return streams 

        # 3. Parsare pagină normală
        page_title = title_label
        page_size = ""
        size_match = re.search(r'Size:\s*([\d.]+)\s*(GB|MB)', html, re.IGNORECASE)
        if size_match: page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
        
        all_a_tags = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
        seen_urls = set()
        pending_resolves = []
        
        for link_url, link_text in all_a_tags:
            if not link_url.startswith('http'): continue
            link_lower = link_url.lower()
            
            if any(skip in link_lower for skip in ['gofile.io', 't.me', 'javascript:', '/login', 'facebook.com']): continue
            if link_url in seen_urls: continue
            seen_urls.add(link_url)
            
            # ATENȚIE: Dacă găsește un WRAPPER (Hubcloud/GDFlix) înăuntrul paginii, îl trimitem la rezolvat!
            if 'hubcloud' in link_lower or 'vcloud' in link_lower:
                resolved = _resolve_hdhub_redirect_parallel(link_url, 0, page_title, info_label, None)
                if resolved:
                    _process_resolved_results(resolved, quality_label, page_title, info_label, streams, seen_urls)
                continue
                
            if 'gdflix' in link_lower:
                gd_streams = _process_gdflix_page(link_url, quality_label, page_title, info_label)
                if gd_streams:
                    for gs in gd_streams:
                        uc = gs['url'].split('|')[0]
                        if uc not in seen_urls:
                            streams.append(gs)
                            seen_urls.add(uc)
                continue

            # Altfel, URL intermediar/direct
            stream_url = link_url
            server_name = 'Direct'
            needs_resolve = False
            
            if 'aws-storage' in link_lower or 'awsdllaaa' in link_lower:
                server_name = 'FastCloud'
            elif 'fdownload.php' in link_lower:
                server_name = 'DirectDL'; needs_resolve = True
            elif 'adl.php' in link_lower:
                server_name = 'FastCloud-02'; needs_resolve = True
            elif 'r2.dev' in link_lower or 'pub-' in link_lower:
                server_name = 'CloudR2'
            elif 'busycdn' in link_lower or 'instant.busycdn' in link_lower:
                server_name = 'InstantDL'
            elif 'pixeldrain' in link_lower:
                pd_match = re.search(r'/u/([a-zA-Z0-9]+)', link_url)
                if pd_match:
                    stream_url = f"https://pixeldrain.dev/api/file/{pd_match.group(1)}"
                    server_name = 'PixelDrain'
            elif 'workers.dev' in link_lower:
                server_name = 'CFWorker'
            else:
                server_name = _identify_host_from_url(link_url)

            if stream_url and server_name:
                if needs_resolve:
                    pending_resolves.append((stream_url, server_name, quality_label, page_title, page_size))
                else:
                    display = f"MKV | {server_name}"
                    if page_size: display += f" | {page_size}"
                    
                    streams.append({
                        'name': display,
                        'url': build_stream_url(stream_url, referer=f'https://{domain_netloc}/'),
                        'quality': quality_label,
                        'title': page_title,
                        'size': page_size,
                        'info': info_label or ""
                    })

        if pending_resolves:
            def resolve_task(args):
                raw_url, srv_name, qual, title, size = args
                resolved_url = _resolve_intermediate_url(raw_url)
                if resolved_url:
                    display = f"MKV | {srv_name}"
                    if size: display += f" | {size}"
                    
                    if 'googleusercontent' in resolved_url.lower() or 'googlevideo' in resolved_url.lower() or 'pixel.hubcdn' in resolved_url.lower():
                        safe_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        final_url = f"{resolved_url}|User-Agent={safe_ua}&seekable=0"
                    else:
                        final_url = build_stream_url(resolved_url, referer=f'https://{domain_netloc}/')
                        
                    return {
                        'name': display,
                        'url': final_url,
                        'quality': qual,
                        'title': title,
                        'size': size,
                        'info': info_label or ""
                    }
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
                    except: pass

    except Exception as e:
        log(f"[CLOUD] Critical Error: {e}", xbmc.LOGERROR)

    return streams


# =============================================================================
# _resolve_hdhub_redirect_parallel - FIX pentru GDFlix, HubCDN si Referer
# =============================================================================

def _resolve_hdhub_redirect_parallel(url, depth=0, parent_title=None, branch_label=None, executor=None):
    """
    Rezolvă lanțul HDHub4u/MKVCinemas CU PARALELIZARE.
    V6 - FIX: Suport pentru link-uri token relative (href="/drive/..." sau var url = "/drive/...")
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
    # VERIFICĂ PAGINI SPECIALE (CLOUD PAGES)
    # =========================================================
    
    # Cloud Page (FilesDL sau HubCDN)
    if ('filesdl' in url_lower and '/cloud/' in url_lower) or ('hubcdn.fans/file/' in url_lower):
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
    
    # Verifică dacă e link video final direct
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
            s = requests.Session()
            domain_netloc = urlparse(url).netloc
            base_domain = f"https://{domain_netloc}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
                'Referer': f'{base_domain}/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            
            # Cookie bypass
            if any(x in url for x in ['gamerxyt', 'cryptoinsights', 'carnewz']):
                s.cookies.set("xyt", "2", domain=domain_netloc)
                s.cookies.set("xyt", "2", domain=".gamerxyt.com") 

            r = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
            content = r.text
            final_url = r.url
            
            # VCLOUD & HubCloud: Extrage URL din JavaScript (var url = '/drive/...')
            # Aceasta rezolvă linkurile token relative!
            js_url_match = re.search(r"var\s+url\s*=\s*['\"]([^'\"]+)['\"]", content)
            if js_url_match:
                extracted_url = js_url_match.group(1)
                
                # Transformă link-ul relativ în absolut!
                if extracted_url.startswith('/'):
                    extracted_url = base_domain + extracted_url
                    
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
                
                size_extracted = ""
                size_match = re.search(r'File Size<i[^>]*>([^<]+)</i>', content, re.IGNORECASE)
                if size_match: size_extracted = size_match.group(1).strip()
                
                if not size_extracted:
                    size_match = re.search(r'id="size">([^<]+)</i>', content, re.IGNORECASE)
                    if size_match: size_extracted = size_match.group(1).strip()
                
                if not size_extracted:
                    size_match = re.search(r'>Size\s*:\s*([\d.]+\s*(?:GB|MB|TB))', content, re.IGNORECASE)
                    if size_match: size_extracted = size_match.group(1).strip()
                
                if size_extracted:
                    size_extracted = re.sub(r'(\d)(GB|MB|TB)', r'\1 \2', size_extracted, flags=re.IGNORECASE).upper().replace('  ', ' ').strip()
                    if current_branch:
                        if size_extracted not in current_branch:
                            current_branch = f"{current_branch} [{size_extracted}]"
                    else:
                        current_branch = f"[{size_extracted}]"

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
                    s.cookies.set(c_n, c_v, domain=domain_netloc)
                    time.sleep(1)
                    r2 = s.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
                    content = r2.text

            # =========================================================
            # EXTRACTOR LINK-URI DIRECTE (Cauta in elemente href)
            # =========================================================
            def add_direct_link(link):
                if link in seen_urls: return
                link_lower = link.lower()
                
                if 'gofile.io/d/' in link_lower: return
                
                if ('filesdl' in link_lower and '/cloud/' in link_lower) or ('hubcdn.fans/file/' in link_lower):
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    found_urls.append(('CloudPage', link, current_title, q, current_branch))
                    seen_urls.add(link)
                    return
                
                if any(p in link_lower for p in ['gdflix.dev/file/', 'gdflix.net/file/', 'gdflix.filesdl.in/file/']):
                    q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                    found_urls.append(('GDFlixPage', link, current_title, q, current_branch))
                    seen_urls.add(link)
                    return
                
                blocked = ['googletagmanager', 'facebook', 'twitter', 'yandex', 'gadgetsweb', 
                          'disqus', 'gravatar', 'recaptcha', '.css', '.js', '.png', '.jpg', 
                          'filepress', 'bit.ly', 't.me', 'telegram']
                if any(b in link_lower for b in blocked): return
                    
                if not _is_video_url(link): return
                
                wrapper_check = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 
                                '/drive/', '/file/', 'hblinks', 'inventoryidea', 'vcloud.zip']
                if any(w in link_lower for w in wrapper_check): return
                
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

            # Acum transformăm și href-urile relative în absolute!
            all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', content)
            for href in all_hrefs:
                if href.startswith('//'): 
                    href = 'https:' + href
                elif href.startswith('/') and not href.startswith('//'): 
                    href = base_domain + href # Le transformăm!
                
                if href.startswith('http'): 
                    add_direct_link(href)
            
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
                r'["\'](https?://[^"\']*yummy\.monster[^"\']*)["\']', # NOU
                r'["\'](https?://[^"\']*gdboka[^"\']*)["\']',
                r'["\'](https?://[^"\']*polgen\.buzz[^"\']*)["\']',
                r'["\'](https?://[^"\']*filesdl[^"\']*\/cloud\/[^"\']*)["\']',
                r'["\'](https?://[^"\']*hubcdn\.fans\/file\/[^"\']*)["\']',
                r'["\'](https?://[^"\']*gdflix[^"\']*\/file\/[^"\']*)["\']',
            ]
            
            for pattern in js_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches: add_direct_link(match)

            next_hop_patterns = [
                r'href=["\'](https?://[^"\']*hubcloud[^"\']*/drive/[^"\']*)["\']',
                r'href=["\'](/drive/[^"\']*\?token=[^"\']*)["\']', # Pentru href token relativ
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
                    if next_link.startswith('/'):
                        next_link = base_domain + next_link
                    
                    if next_link != url and next_link not in seen_urls:
                        if '/admin' not in next_link and '/login' not in next_link:
                            next_hops.append(next_link)
                            seen_urls.add(next_link)

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
                        except: pass

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
            log(f"[RESOLVE] Eroare la procesare {url}: {e}")
            
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
# SCRAPER HDHUB4U (V19 - FIX HBLINKS & LOGURI REDUSE)
# =============================================================================

def scrape_hdhub4u(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_hdhub4u') == 'false':
        return None

    try:
        base_url = _get_hdhub_base_url()
        
        search_query = imdb_id if imdb_id else title_query
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        movie_url = None
        
        # =========================================================
        # CĂUTARE API (Pingora)
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
                    for hit in data.get('hits', []):
                        doc = hit.get('document', {})
                        raw_link = doc.get('permalink')
                        raw_title = doc.get('post_title', '').lower()
                        doc_imdb = doc.get('imdb_id', '')
                        
                        if not raw_link: continue
                            
                        is_match = False
                        
                        if imdb_id and doc_imdb and imdb_id in str(doc_imdb):
                            is_match = True
                        elif title_query:
                            clean_raw_title = re.sub(r'[^\w\s]', ' ', raw_title).lower()
                            queries_to_check = [title_query.lower()]
                            if ' 2' in title_query: queries_to_check.append(title_query.replace(' 2', ' ii').lower())
                            if ' 3' in title_query: queries_to_check.append(title_query.replace(' 3', ' iii').lower())

                            for q_check in queries_to_check:
                                terms = [t for t in q_check.split() if t.strip()]
                                all_terms_found = True
                                for term in terms:
                                    if not re.search(r'\b' + re.escape(term) + r'\b', clean_raw_title):
                                        all_terms_found = False
                                        break
                                
                                if all_terms_found:
                                    if year_query:
                                        if str(year_query) in clean_raw_title or str(year_query) in raw_link:
                                            is_match = True
                                    else:
                                        is_match = True
                                    break

                        if is_match:
                            parsed_link = urlparse(raw_link)
                            return f"{base_url}{parsed_link.path}"
            except: pass
            return None

        # =========================================================
        # CĂUTARE FALLBACK
        # =========================================================
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
                        
                        is_match = False
                        clean_link_text = link_lower.replace('-', ' ').replace('/', ' ')
                        
                        if title_query:
                            queries_to_check = [title_query.lower()]
                            if ' 2' in title_query: queries_to_check.append(title_query.replace(' 2', ' ii').lower())
                            if ' 3' in title_query: queries_to_check.append(title_query.replace(' 3', ' iii').lower())

                            for q_check in queries_to_check:
                                terms = [t for t in q_check.split() if t.strip()]
                                all_terms_found = True
                                for term in terms:
                                    if not re.search(r'\b' + re.escape(term) + r'\b', clean_link_text):
                                        all_terms_found = False
                                        break
                                
                                if all_terms_found:
                                    if year_query:
                                        if str(year_query) in link_lower:
                                            is_match = True
                                    else:
                                        is_match = True
                                    break
                            
                        if is_match: return full_url
            except: pass
            return None

        movie_url = search_api()
        if not movie_url: movie_url = search_fallback()

        if not movie_url: return None
        
        r_movie = requests.get(movie_url, headers=get_headers(), timeout=15, verify=False)
        if r_movie.status_code != 200: return None

        movie_html = r_movie.text
        
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
        
        # ---> FIX: AICI AM ADĂUGAT hblinks <---
        valid_domains = ['hubdrive', 'hubcloud', 'hubcdn', 'hubstream', 'hdstream4u', 'gamerxyt', 'vcloud', 'hblinks']
        
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

        streams = []
        seen_urls = set()
        streams_lock = threading.Lock()
        
        def process_task(task):
            local_streams = []
            local_seen = set()
            try:
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
            except: pass
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
                except: pass

        return streams if streams else None

    except Exception as e:
        log(f"[HDHUB] Eroare Generală: {e}", xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER MKVCINEMAS (V11 - FULL PARALLEL + WP API BYPASS CLOUDFLARE)
# =============================================================================

def scrape_mkvcinemas(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """
    Scraper pentru MKVCinemas - V11: FIX Cloudflare Captcha prin Sesiuni Pseudo-Chrome.
    """
    if ADDON.getSetting('use_mkvcinemas') == 'false':
        return None
    
    try:
        base_url = "https://mkvcinemas.sh"
        headers = get_headers()
        
        # =========================================================
        # 1. CĂUTARE
        # =========================================================
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        search_url = f"{base_url}/?s={quote(clean_search)}"
        r = requests.get(search_url, headers=headers, timeout=15, verify=False, allow_redirects=True)
        
        if r.status_code != 200:
            return None
        
        search_html = r.text
        movie_links = []
        
        title_links = re.findall(r'<h2 class="entry-title"><a href=["\']([^"\']+)["\']', search_html, re.IGNORECASE)
        for link in title_links:
            if link not in movie_links:
                movie_links.append(link)
        
        if not movie_links:
            article_links = re.findall(r'href=["\'](https?://[^"\']+mkvcinemas[^"\']+/(?:\d+/)?[a-z0-9-]+-(?:19|20)\d{2}[^"\']*)["\']', search_html, re.IGNORECASE)
            for link in article_links:
                if any(ex in link.lower() for ex in ['/feed/', '/category/', '/tag/', '/page/', '/author/']):
                    continue
                if link not in movie_links:
                    movie_links.append(link)
        
        if not movie_links:
            log(f"[MKV] No valid movie links found for: {clean_search}")
            return None
        
        search_slug = clean_search.lower().replace(' ', '-')
        movie_url = None
        
        for link in movie_links:
            link_lower = link.lower()
            if search_slug in link_lower:
                if year_query and str(year_query) in link_lower:
                    movie_url = link
                    log(f"[MKV] ✓ Best match (slug+year): {link}")
                    break
                if not movie_url:
                    movie_url = link
        
        if not movie_url:
            movie_url = movie_links[0]
        
        log(f"[MKV] Found Movie URL: {movie_url}")
        
        # =========================================================
        # 2. ACCESEAZĂ PAGINA FILMULUI
        # =========================================================
        r_movie = requests.get(movie_url, headers=headers, timeout=15, verify=False, allow_redirects=True)
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
        # WORKER: PROCESS FILESDL (API BYPASS CLOUDFLARE ROBUST)
        # =========================================================
        def process_filesdl(url):
            local_streams = []
            local_seen = set()
            try:
                domain = urlparse(url).netloc
                post_id = None
                
                match = re.search(r'/view/(\d+)', url)
                if not match: match = re.search(r'\?p=(\d+)', url)
                if match: post_id = match.group(1)
                
                html = ""
                current_title = fallback_title
                
                # Sesiune FAKE Chrome Anti-Cloudflare
                s = requests.Session()
                s.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': f'https://{domain}/',
                    'Connection': 'keep-alive',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'same-origin'
                })
                
                # BYPASS 1: API Direct
                if post_id:
                    api_url = f"https://{domain}/wp-json/wp/v2/posts/{post_id}"
                    try:
                        r_api = s.get(api_url, timeout=10, verify=False)
                        if r_api.status_code == 200:
                            data = r_api.json()
                            html = data.get('content', {}).get('rendered', '')
                            title_ren = data.get('title', {}).get('rendered', '')
                            if title_ren: current_title = title_ren
                            log(f"[MKV-FILESDL] ✓ API Bypass 1 (ID) Succes!")
                    except: pass
                
                # BYPASS 2: API Search (După Slug)
                if not html and fallback_title:
                    slug = fallback_title.lower().replace(' ', '-')
                    api_url2 = f"https://{domain}/wp-json/wp/v2/posts?slug={slug}"
                    try:
                        r_api2 = s.get(api_url2, timeout=10, verify=False)
                        if r_api2.status_code == 200:
                            data2 = r_api2.json()
                            if len(data2) > 0:
                                html = data2[0].get('content', {}).get('rendered', '')
                                title_ren = data2[0].get('title', {}).get('rendered', '')
                                if title_ren: current_title = title_ren
                                log(f"[MKV-FILESDL] ✓ API Bypass 2 (Slug) Succes!")
                    except: pass
                
                # FALLBACK 3: Pagina Normală
                if not html or 'download-box' not in html:
                    log(f"[MKV-FILESDL] API blocat, încerc pagina normală: {url}")
                    s.headers.update({'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
                    try:
                        r = s.get(url, timeout=10, verify=False, allow_redirects=True)
                        if r.status_code == 200:
                            html = r.text
                            page_title_match = re.search(r'<h1[^>]*class="entry-title"[^>]*>([^<]+)</h1>', html)
                            if page_title_match:
                                current_title = page_title_match.group(1).strip()
                    except: pass
                
                if not html or 'download-box' not in html:
                    log("[MKV-FILESDL] ✗ CF a blocat tot, sau pagina e goală!")
                    return []
                
                blocks = html.split('download-box')
                all_tasks = []
                for block in blocks[1:]:
                    quality_match = re.search(r'<h2[^>]*>([^<]+)</h2>', block, re.IGNORECASE)
                    size_match = re.search(r'class="filesize"[^>]*>([^<]+)</div>', block, re.IGNORECASE)
                    buttons_match = re.search(r'class="download-buttons"[^>]*>(.*?)</div>', block, re.IGNORECASE | re.DOTALL)
                    
                    if not quality_match or not buttons_match:
                        continue
                        
                    quality_text = quality_match.group(1).strip()
                    filesize = size_match.group(1).strip() if size_match else ""
                    buttons_html = buttons_match.group(1)
                    
                    quality = "SD"
                    q_lower = quality_text.lower()
                    if '2160p' in q_lower or '4k' in q_lower: quality = "4K"
                    elif '1080p' in q_lower: quality = "1080p"
                    elif '720p' in q_lower: quality = "720p"
                    
                    if quality == "SD": continue
                    
                    branch = quality_text.replace('DOWNLOAD', '').strip()
                    if filesize:
                        branch += f" [{filesize}]"
                    
                    extracted_urls = re.findall(r'href=["\']([^"\']+)["\']', buttons_html)
                    for dl_url in extracted_urls:
                        if 'javascript' in dl_url or dl_url == '#': continue
                        dl_lower = dl_url.lower()
                        
                        # ACUM SE TRIMIT TOATE /drive/ și /cloud/ la procesorul principal
                        if 'filesdl' in dl_lower and ('/cloud/' in dl_lower or '/drive/' in dl_lower):
                            all_tasks.append(('cloud', dl_url, quality, branch, current_title))
                        elif any(p in dl_lower for p in ['gdflix.dev/file/', 'gdflix.net/file/', 'gdflix.filesdl.in/file/']):
                            all_tasks.append(('gdflix', dl_url, quality, branch, current_title))
                        elif 'gofile.io/d/' in dl_lower:
                            continue
                        else:
                            all_tasks.append(('resolve', dl_url, quality, branch, current_title))
                
                def process_task(task):
                    task_type, task_url, task_quality, task_branch, task_title = task
                    results = []
                    try:
                        if task_type == 'cloud':
                            results = _process_filesdl_cloud_page(task_url, task_quality, task_title, task_branch)
                        elif task_type == 'gdflix':
                            results = _process_gdflix_page(task_url, task_quality, task_title, task_branch)
                        elif task_type == 'resolve':
                            resolved = _resolve_hdhub_redirect_parallel(task_url, 0, task_title, task_branch, None)
                            if resolved:
                                for host, u, title, qual, branch in resolved:
                                    if host == 'CloudPage':
                                        sub = _process_filesdl_cloud_page(u, qual or task_quality, title or task_title, branch or task_branch)
                                        if sub: results.extend(sub)
                                    elif host == 'GDFlixPage':
                                        sub = _process_gdflix_page(u, qual or task_quality, title or task_title, branch or task_branch)
                                        if sub: results.extend(sub)
                                    elif u.startswith('http'):
                                        display = host
                                        if branch: display = f"{host} | {branch}"
                                        
                                        extracted_size = ""
                                        if branch:
                                            size_match = re.search(r'\[([\d.]+\s*(?:GB|MB))\]', branch, re.IGNORECASE)
                                            if size_match: extracted_size = size_match.group(1)
                                            
                                        if 'pixel.hubcdn' in u.lower() or 'google' in u.lower():
                                            safe_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                                            final_url = f"{u}|User-Agent={safe_ua}&seekable=0"
                                        else:
                                            final_url = build_stream_url(u)

                                        results.append({
                                            'name': display,
                                            'url': final_url,
                                            'quality': qual or task_quality,
                                            'title': title or task_title,
                                            'size': extracted_size,
                                            'info': branch or ""
                                        })
                    except Exception as e:
                        log(f"[MKV-TASK] Error: {e}")
                    return results
                
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
                        except: pass
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
                    tasks = []
                    for host, final_url, title, qual, branch in resolved:
                        if host == 'CloudPage':
                            tasks.append(('cloud', final_url, qual, branch, title))
                        elif host == 'GDFlixPage':
                            tasks.append(('gdflix', final_url, qual, branch, title))
                        elif final_url.startswith('http'):
                            display = host
                            if branch: display = f"{host} | {branch}"
                            extracted_size = ""
                            if branch:
                                size_match = re.search(r'\[([\d.]+\s*(?:GB|MB))\]', branch, re.IGNORECASE)
                                if size_match: extracted_size = size_match.group(1)
                                
                            if 'pixel.hubcdn' in final_url.lower() or 'google' in final_url.lower():
                                safe_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                                the_url = f"{final_url}|User-Agent={safe_ua}&seekable=0"
                            else:
                                the_url = build_stream_url(final_url)

                            local_streams.append({
                                'name': display,
                                'url': the_url,
                                'quality': qual or '1080p',
                                'title': title or fallback_title,
                                'size': extracted_size,
                                'info': branch or ""
                            })
                    
                    if tasks:
                        def proc_task(t):
                            tt, tu, tq, tb, ti = t
                            if tt == 'cloud': return _process_filesdl_cloud_page(tu, tq or '1080p', ti or fallback_title, tb)
                            elif tt == 'gdflix': return _process_gdflix_page(tu, tq or '1080p', ti or fallback_title, tb)
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
                                except: pass
            except Exception as e:
                log(f"[MKV-HUB] Error: {e}")
            return local_streams

        def process_gdflix_direct(url):
            return _process_gdflix_page(url, "1080p", fallback_title, "GDFlix Direct")

        # =========================================================
        # EXECUȚIE PARALELĂ MASTER
        # =========================================================
        all_tasks = []
        for url in filesdl_links: all_tasks.append(('filesdl', url))
        for url in hubcloud_links: all_tasks.append(('hub', url))
        for url in gdflix_links:
            if any(p in url.lower() for p in ['gdflix.dev/file/', 'gdflix.net/file/']):
                all_tasks.append(('gdflix', url))
        
        def dispatch_task(task):
            task_type, url = task
            if task_type == 'filesdl': return process_filesdl(url)
            elif task_type == 'hub': return process_hubcloud(url)
            elif task_type == 'gdflix': return process_gdflix_direct(url)
            return []

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
                except: pass

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
                # Definim pattern-urile de sezon (S01, Season 1, etc)
                season_patterns = [f"season {season_num}", f"season-{season_num}", f"s{season_num:02d}", f"s{season_num}"]
                
                # --- MODIFICARE: Validare Strictă Show (ID/Titlu) + Sezon ---
                for hit in data['hits']:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink', '')
                    raw_title = doc.get('post_title', '').lower()
                    doc_imdb = doc.get('imdb_id', '') # ID-ul IMDb din rezultate
                    
                    if not raw_link: continue
                    
                    full_link = raw_link if raw_link.startswith('http') else base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                    combined = (raw_title + ' ' + raw_link).lower()
                    
                    # PAS 1: Verificăm dacă este SERIALUL corect (ID sau Titlu Strict)
                    is_correct_show = False
                    
                    # A. Verificare ID (Prioritate Maximă)
                    if imdb_id and (imdb_id in str(doc_imdb) or imdb_id in raw_title or imdb_id in raw_link):
                        is_correct_show = True
                        log(f"[MDRIVE] ✓ TV ID Match: {raw_title}")
                    
                    # B. Verificare Titlu Strictă (Word Boundaries)
                    elif title_query:
                        clean_raw = re.sub(r'[^\w\s]', ' ', raw_title).lower()
                        clean_q = re.sub(r'[^\w\s]', ' ', title_query).lower()
                        
                        terms = [t for t in clean_q.split() if t.strip()]
                        all_terms_found = True
                        for term in terms:
                            # Cuvântul trebuie să existe delimitat (ex: "This" nu matcheaza "ThisIsUs")
                            if not re.search(r'\b' + re.escape(term) + r'\b', clean_raw):
                                all_terms_found = False
                                break
                        
                        if all_terms_found:
                            # Validare suplimentară: excludem titluri care au DOAR un cuvânt comun
                            # (ex: "Nobody Wants This" vs "Let This Grieving Soul Retire")
                            # Calculăm procentul de potrivire a lungimii sau cuvintelor totale
                            raw_words = set(clean_raw.split())
                            q_words = set(terms)
                            common = raw_words.intersection(q_words)
                            
                            # Dacă titlul găsit are MULT mai multe cuvinte, e suspect (doar dacă query-ul nu e scurt)
                            if len(terms) > 1 and len(common) == len(terms):
                                is_correct_show = True
                    
                    if not is_correct_show:
                        continue # Trecem la următorul rezultat
                        
                    # PAS 2: Verificăm dacă este SEZONUL corect
                    # Căutăm pattern-uri de sezon în titlu sau link
                    # Dar ne asigurăm că nu e "Episode X" fără "Season X" (ca să nu luăm episoade individuale din greșeală)
                    found_season = False
                    for pattern in season_patterns:
                        # Regex boundary pentru season (să nu ia s12 când căutăm s1)
                        # Pattern simplu: boundary + pattern + boundary sau non-digit
                        if re.search(r'[\b\-\s]' + re.escape(pattern) + r'[\b\-\s\.]', combined):
                            found_season = True
                            break
                    
                    # Fallback: dacă nu găsim sezon specific, dar e "Complete Series" sau titlu generic,
                    # îl luăm și sperăm să găsim linkurile înăuntru (Mdrive grupează des sezoanele)
                    if not found_season:
                        if "complete" in combined or "series" in combined or "collection" in combined:
                            found_season = True

                    if found_season:
                        season_link = full_link
                        log(f"[MDRIVE] Selected Season Page: {season_link}")
                        break
                # -----------------------------------------------------------
                
                # Fallback vechi (pentru situații disperate), îl lăsăm comentat sau îl ștergem
                # deoarece logica de mai sus e mult mai robustă.
                # if not season_link: ...
            else:
                # =========================================================
                # FILME: VALIDARE REZULTAT CĂUTARE
                # =========================================================
                
                # --- MODIFICARE: Prioritate ID și Validare Regex (Word Boundary) ---
                for hit in data['hits']:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink', '')
                    raw_title = doc.get('post_title', '')
                    doc_imdb = doc.get('imdb_id', '') # Uneori există acest câmp
                    
                    if not raw_link: continue

                    is_match = False
                    
                    # 1. VERIFICARE ID (Prioritate absolută)
                    # Verificăm dacă ID-ul căutat apare în câmpul imdb_id, titlu sau link
                    if imdb_id and (imdb_id in str(doc_imdb) or imdb_id in raw_title or imdb_id in raw_link):
                        is_match = True
                        log(f"[MDRIVE] ✓ ID Match confirmed: {raw_title}")
                    
                    # 2. VERIFICARE TITLU STRICTĂ (Fallback)
                    elif title_query:
                        # Curățăm titlurile pentru regex
                        clean_raw_title = re.sub(r'[^\w\s]', ' ', raw_title).lower()
                        clean_query = re.sub(r'[^\w\s]', ' ', title_query).lower()
                        
                        # Generăm variante (ex: '2' -> 'ii')
                        queries_to_check = [clean_query]
                        if ' 2 ' in f" {clean_query} ": queries_to_check.append(clean_query.replace(' 2', ' ii'))

                        for q_check in queries_to_check:
                            terms = [t for t in q_check.split() if t.strip()]
                            all_terms_found = True
                            
                            for term in terms:
                                # Regex \b pt a nu găsi '2' în '2025' sau 'War' în 'Warrior'
                                if not re.search(r'\b' + re.escape(term) + r'\b', clean_raw_title):
                                    all_terms_found = False
                                    break
                            
                            if all_terms_found:
                                # Verificare An (dacă există)
                                if year_query:
                                    # Acceptăm anul în titlu sau în URL
                                    if str(year_query) in clean_raw_title or str(year_query) in raw_link:
                                        is_match = True
                                    # Toleranță +/- 1 an
                                    elif any(str(y) in clean_raw_title for y in [int(year_query)-1, int(year_query)+1]):
                                        is_match = True
                                else:
                                    is_match = True
                                break

                    if is_match:
                        # Rezultat valid
                        movie_link = raw_link if raw_link.startswith('http') else base_url.rstrip('/') + '/' + raw_link.lstrip('/')
                        log(f"[MDRIVE] Selected: {movie_link}")
                        break
                # -------------------------------------------------------------------
                
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
def _scrape_json_provider(base_url, pattern, label, imdb_id, content_type, season, episode, title_query=None, year_query=None):
    """
    Helper pentru providerii JSON (Vega, Nuvio, StreamVix, Vidzee, Webstreamr, MeowTV).
    FIX: Extrage calitatea din name/title/description și folosește titlul fallback.
    """
    local_streams = []
    
    if 'nuvio' in base_url.lower(): timeout = 10
    else: timeout = 12
    
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
                    if not url: continue

                    # =====================================================
                    # FIX 1: OCOLIM CLOUDFLARE EXTRĂGÂND URL-UL DIRECT (M3U8)
                    # =====================================================
                    import urllib.parse
                    if 'meowserver' in url and 'url=' in url:
                        try:
                            parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                            if 'url' in parsed_qs:
                                url = parsed_qs['url'][0]
                        except:
                            pass
                    
                    raw_name = s.get('name', '')
                    raw_title = s.get('title', '')
                    description = s.get('description', '')

                    # =====================================================
                    # FIX 2: IGNORĂM CALITATEA "AUTO" PENTRU A EVITA DEDUPLICAREA GRESITĂ A 1080P
                    # =====================================================
                    if 'Auto' in raw_name or 'Auto' in description:
                        continue

                    # =====================================================
                    # EXTRAGERE FILENAME ORIGINAL (Din description pt Volecitor/etc)
                    # =====================================================
                    if description:
                        first_line = description.split('\n')[0].strip()
                        # Verificăm strict dacă pe prima linie există o extensie video
                        if re.search(r'(\.mkv|\.mp4|\.avi|\.ts|\.webm)', first_line, re.IGNORECASE):
                            # Eliminăm doar parantezele pătrate de la început (ex: [10Gbps] [💾 9.58 GB])
                            clean_filename = re.sub(r'^(\[[^\]]+\]\s*)+', '', first_line).strip()
                            if clean_filename:
                                raw_title = clean_filename
                    
                    # APLICARE TITLU FALLBACK (Dacă nu s-a extras niciun fișier video și raw_title e gol)
                    if not raw_title and title_query:
                        if label == 'MeowTV':
                            base_name = f"{title_query} ({year_query})" if year_query else title_query
                            if content_type == 'tv' and season and episode:
                                raw_title = f"{base_name} S{int(season):02d}E{int(episode):02d}"
                            else:
                                raw_title = f"{base_name}"
                        else:
                            if content_type == 'tv' and season and episode:
                                raw_title = f"{title_query} S{int(season):02d}E{int(episode):02d}"
                            else:
                                raw_title = title_query

                    try: clean_name = raw_name.encode('ascii', 'ignore').decode('ascii')
                    except: clean_name = raw_name

                    # Eliminare nume provider din afișare
                    banned_names = ['WebStreamr', 'Nuvio', 'StreamVix', 'Vidzee', 'Vega', 'Sooti', 'Sootio', 'MeowTV', 'HDHub']
                    for bn in banned_names:
                        clean_name = clean_name.replace(bn, '').strip()
                    
                    clean_name = clean_name.replace('|', '').replace('[', '').replace(']', '').strip()
                    clean_name = clean_name.replace('\n', ' ').strip()
                    while '  ' in clean_name: clean_name = clean_name.replace('  ', ' ')

                    final_name = f"{label} | {clean_name}" if clean_name else label
                    
                    # Extragere Calitate
                    quality = None
                    if s.get('quality'): quality = s.get('quality')
                    if not quality and description: quality = _extract_quality_from_string(description)
                    if not quality or quality.upper() == 'SD': quality = _extract_quality_from_string(raw_name)
                    if not quality: quality = _extract_quality_from_string(raw_title)
                    if not quality: quality = _extract_quality_from_string(s.get('behaviorHints', {}).get('filename', ''))
                    if not quality: quality = 'SD'
                    
                    # Înglobăm description în info pentru ca regex-urile din player.py să extragă corect mărimea (ex: 💾 9.58 GB)
                    info_text = str(s.get('behaviorHints', {}).get('filename', '')) + " " + description
                    
                    stream_obj = {
                        'name': final_name,
                        'url': build_stream_url(url, referer=ref, origin=origin),
                        'quality': quality,
                        'title': raw_title,
                        'info': info_text.strip(),
                        'provider_id': label.lower()
                    }
                    local_streams.append(stream_obj)
                
                log(f"[SCRAPER] ✓ {label}: {len(local_streams)} surse")
                
    except Exception as e:
        log(f"[JSON-PROV] Error {label}: {e}")

    return local_streams
    


def _extract_release_group(filename):
    """Extrage Release Group din coada numelui (ex: ...-BYNDR.mkv -> BYNDR) ca fallback."""
    if not filename: return ""
    import re
    clean_name = filename.strip()
    
    # Eliminăm extensia video dacă există
    clean_name = re.sub(r'(?i)\.(mkv|mp4|avi|ts|webm|m4v)$', '', clean_name)
    
    # Căutăm ultimul '-' urmat de litere/cifre (dar nu prea lung, max 15 caractere)
    m = re.search(r'-([a-zA-Z0-9_]+)$', clean_name)
    if m:
        grp = m.group(1)
        # Excludem codecuri/rezoluții care ar putea apărea din greșeală după ultimul '-'
        bad_groups = ['x264', 'x265', 'h264', 'h265', 'hevc', '1080p', '720p', '2160p', '4k', 'hdr', 'sdr', 'remux', 'ESub', 'DV', 'Dual', 'e']
        if grp.lower() not in bad_groups and len(grp) < 15:
            return grp
    return ""

import urllib.parse

def full_unquote(text):
    """Decodează repetat (ex: %2520 -> %20 -> Spațiu) pentru Mediafusion."""
    if not text: return ""
    prev = text
    for _ in range(3):
        text = urllib.parse.unquote(text)
        if text == prev: break
        prev = text
    return text

def _parse_stremio_addon_stream(s, addon_name, provider_id):
    """
    Extrage Numele Fișierului, Debrid, Indexer și Seederi.
    Rezolvă URL parameters pt Comet și double encoding pt Mediafusion.
    """
    url = s.get('url')
    if not url: return None
    
    raw_name = s.get('name', '')
    raw_title = s.get('title', '')
    name_upper = raw_name.upper()
    url_lower = url.lower()
    
    # 1. Debrid & Cached Status
    is_cached = False
    debrid_service = ""
    
    if '[RD+]' in name_upper: is_cached = True; debrid_service = 'realdebrid'
    elif '[AD+]' in name_upper: is_cached = True; debrid_service = 'alldebrid'
    elif '[PM+]' in name_upper: is_cached = True; debrid_service = 'premiumize'
    elif '[TB+]' in name_upper: is_cached = True; debrid_service = 'torbox'
    elif '[EN+]' in name_upper or '[EN]' in name_upper: is_cached = True; debrid_service = 'easynews'
    elif '[RD]' in name_upper: is_cached = False; debrid_service = 'realdebrid'
    elif '[AD]' in name_upper: is_cached = False; debrid_service = 'alldebrid'
    
    if not debrid_service:
        if '/realdebrid/' in url_lower or '/rd/' in url_lower: debrid_service = 'realdebrid'
        elif '/alldebrid/' in url_lower or '/ad/' in url_lower: debrid_service = 'alldebrid'
        elif '/premiumize/' in url_lower or '/pm/' in url_lower: debrid_service = 'premiumize'
        elif '/torbox/' in url_lower or '/tb/' in url_lower: debrid_service = 'torbox'

    # 2. Separăm informațiile (Decodăm title pentru Mediafusion)
    raw_title_unquoted = full_unquote(raw_title)
    lines = [line.strip() for line in raw_title_unquoted.split('\n') if line.strip()]
    filename = raw_title_unquoted.replace('\n', ' ')
    info_line = ""
    
    for line in lines:
        if '👤' in line or '💾' in line or '⚙️' in line or 'GB' in line.upper() or 'MB' in line.upper() or ' peers ' in line.lower() or 'multi audio' in line.lower() or '🇵🇱' in line:
            info_line = line
        else:
            filename = line
            
    if filename == info_line and len(lines) > 1:
        filename = lines[1] if '👤' in lines[0] or '💾' in lines[0] else lines[0]

    # 3. EXTRAȚIE NUME FIȘIER DIN URL (Pentru Comet / Fallback)
    def is_valid_filename(fname):
        return bool(re.search(r'\.(mkv|mp4|avi|ts|webm|m4v)', fname, re.IGNORECASE))
        
    # Dacă numele e gol, e doar un hash random (jyWAbK...), sau n-are extensie
    if not is_valid_filename(filename) or len(filename) < 5 or (' ' not in filename and '.' not in filename):
        try:
            clean_url = url.split('|')[0]
            parsed_url = urllib.parse.urlparse(clean_url)
            qs = urllib.parse.parse_qs(parsed_url.query)
            
            # Verificăm variabilele din link (Comet folosește torrent_name= sau name=)
            if 'torrent_name' in qs:
                filename = qs['torrent_name'][0]
            elif 'name' in qs:
                filename = qs['name'][0]
            else:
                # Nu are parametri, încercăm din Path (Torrentio)
                url_name = ""
                if '/null/0/' in clean_url: url_name = clean_url.split('/null/0/')[-1]
                elif '/null/undefined/' in clean_url: url_name = clean_url.split('/null/undefined/')[-1]
                else: url_name = clean_url.split('/')[-1]
                
                url_name = url_name.split('?')[0] # Tăiem query string-ul dacă a mai rămas
                
                if url_name and len(url_name) > 5:
                    filename = url_name
        except:
            pass

    filename = full_unquote(filename).strip(' |-,')
    
    # 3.5 BLOCARE FIȘIERE GUNOI / MALWARE (.exe, .msi, etc)
    bad_extensions = ['.exe', '.msi', '.bat', '.cmd', '.scr']
    if any(filename.lower().endswith(ext) for ext in bad_extensions) or '.exe ' in filename.lower() or '.exe' == filename.lower()[-4:]:
        return None

    # 3.6 FILTRU WEB (Opțional din setări) - DOAR PENTRU RD
    try:
        if ADDON.getSetting('filter_web_sources') == 'true' and debrid_service == 'realdebrid':
            if _is_web_source(filename) or _is_web_source(raw_title) or _is_web_source(raw_name):
                # log(f"[FILTER-WEB] Excluzând sursa WEB RD: {filename[:50]}...")
                return None
    except:
        pass

    # 4. Mărime și Seederi
    size_match = re.search(r'([\d.,]+\s*(?:GB|MB|TB))', raw_title_unquoted, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else ""
    
    seeders = 0
    seed_match = re.search(r'(?:👤|👥|S:|P:|Peers:)\s*(\d+)', raw_title_unquoted, re.IGNORECASE)
    if seed_match: seeders = int(seed_match.group(1))
    
    # 5. Indexer
    indexer = ""
    idx_match = re.search(r'⚙️\s*(.*)', raw_title_unquoted)
    if idx_match:
        indexer = idx_match.group(1).strip()
    elif info_line:
        clean = re.sub(r'[\d.,]+\s*(?:GB|MB|TB)', '', info_line, flags=re.IGNORECASE)
        clean = re.sub(r'(?:👤|👥|S:|P:|Peers:)\s*\d+', '', clean, flags=re.IGNORECASE)
        clean = clean.replace('👤', '').replace('💾', '').replace('⚙️', '').strip(' |-,')
        if clean and not is_valid_filename(clean): indexer = clean
            
    # 6. Calitate
    quality = _extract_quality_from_string(raw_name)
    if not quality or quality == 'SD':
        quality = _extract_quality_from_string(filename) or 'SD'
        
    stream_obj = {
        'name': filename, 
        'url': build_stream_url(url),
        'quality': quality,
        'title': filename, 
        'size': size,
        'source_provider': addon_name,
        'server': indexer,
        'provider_id': provider_id,
        'info': {
            'debrid_service': debrid_service,
            'is_cached': is_cached,
            'addon': addon_name,
            'indexer': indexer,
            'seeders': seeders,
            'releaseGroup': _extract_release_group(filename)  # <--- MODIFICAT AICI
        }
    }
    return stream_obj


def scrape_stremio_addon(imdb_id, content_type, season, episode, addon_id, addon_name):
    """Scraper universal pentru Torrentio/Comet/Mediafusion etc. cu Instanțe Multiple"""
    if ADDON.getSetting(f'use_{addon_id}') == 'false':
        return None

    # 1. Aflăm indexul instanței selectate (0, 1, 2...)
    try:
        instance_idx = int(ADDON.getSetting(f'{addon_id}_instance') or '0')
    except:
        instance_idx = 0

    # 2. Citim URL-ul manifestului corespunzător acelei instanțe
    # Formatul este: idaddon_manifest.0, idaddon_manifest.1 etc.
    manifest_url = ADDON.getSetting(f'{addon_id}_manifest.{instance_idx}').strip()

    if not manifest_url:
        log(f"[{addon_name.upper()}] URL manifest.json lipseste pentru instanta {instance_idx}!")
        return None
        
    # Restul codului rămâne identic...
    base_url = manifest_url.split('/manifest.json')[0].rstrip('/')
    
    try:
        if content_type == 'movie': api_url = f"{base_url}/stream/movie/{imdb_id}.json"
        else: api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json"
            
        r = get_shared_session().get(api_url, headers=get_headers(), timeout=15, verify=False)
        if r.status_code == 200:
            data = r.json()
            found_streams = []
            for s in data.get('streams', []):
                stream_obj = _parse_stremio_addon_stream(s, addon_name, addon_id)
                if stream_obj: found_streams.append(stream_obj)
            log(f"[{addon_name.upper()}] Găsite: {len(found_streams)} surse.")
            return found_streams
    except Exception as e:
        log(f"[{addon_name.upper()}] Eroare: {e}", xbmc.LOGERROR)
        
    return None


# =============================================================================
# AIO STREAMS
# =============================================================================
def scrape_aiostreams(imdb_id, content_type, season=None, episode=None):
    if ADDON.getSetting('use_aiostreams') == 'false':
        return None

    try:
        instance_id = int(ADDON.getSetting('aiostreams_instance') or '0')
    except:
        instance_id = 0

    default_urls =[
        'https://aiostreams.stremio.ru', 'https://aiostreams-nightly.stremio.ru',
        'https://aiostreams.viren070.me', 'https://aiostreams.fortheweak.cloud',
        'https://aiostreams-nightly.fortheweak.cloud', 'https://aiostreamsfortheweebsstable.midnightignite.me',
        'https://aiostreamsfortheweebs.midnightignite.me', 'https://aiostreams.elfhosted.com', ''
    ]

    if instance_id == 8: # Custom
        base_url = (ADDON.getSetting('aio_url.8') or '').strip().rstrip('/')
    else:
        base_url = (ADDON.getSetting(f'aio_url.{instance_id}') or '').strip().rstrip('/')
        if not base_url and instance_id < len(default_urls):
            base_url = default_urls[instance_id]

    aio_uuid = ADDON.getSetting(f'aio_uuid.{instance_id}') or ''
    aio_pass = ADDON.getSetting(f'aio_password.{instance_id}') or ''

    aio_auth = None
    if aio_uuid and aio_pass: aio_auth = (aio_uuid, aio_pass)
    elif aio_uuid: aio_auth = (aio_uuid, '')

    search_link = f"{base_url}/api/v1/search"
    m_type = 'series' if content_type in ('tv', 'show', 'episode') else 'movie'

    # Preluăm timeout-ul global din setări pentru a nu tăia conexiunea prematur
    try: req_timeout = int(ADDON.getSetting('scraper_timeout'))
    except: req_timeout = 25

    def _fetch(st_id):
        try:
            # Adăugăm headere complete (inclusiv User-Agent) pentru a nu fi blocați de Cloudflare
            headers = get_headers()
            headers['Accept'] = 'application/json'
            
            log(f"[AIO] Cerere API: {search_link} | type: {m_type} | id: {st_id} | timeout: {req_timeout}s")
            
            r = get_shared_session().get(
                search_link, params={'type': m_type, 'id': st_id},
                auth=aio_auth, headers=headers, timeout=req_timeout, verify=False
            )
            if r.status_code == 200: 
                res = r.json().get('data', {}).get('results', [])
                log(f"[AIO] ✓ Succes! Am primit {len(res)} surse de la server.")
                return res
            else:
                log(f"[AIO] Eroare HTTP {r.status_code}: {r.text[:100]}", xbmc.LOGWARNING)
        except Exception as e: 
            log(f"[AIO] Eroare conexiune: {e}", xbmc.LOGERROR)
        return[]

    streams =[]
    if m_type == 'movie' or not season:
        results = _fetch(str(imdb_id))
    else:
        ep_num = int(episode or 1)
        results = _fetch(f"{imdb_id}:{season}:{ep_num}")

    for item in results:
        try:
            if 'p2p' in str(item.get('type', '')).lower(): continue
            play_url = item.get('url', '')
            if not play_url or not play_url.startswith('http'): continue

            parsed = item.get('parsedFile', {})
            bh = item.get('behaviorHints', {})
            
            full_title_raw = str(item.get('title', ''))
            title = str(item.get('filename') or bh.get('filename') or parsed.get('filename') or '').strip()
            if not title or len(title) < 5:
                title = full_title_raw.split('\n')[0].strip()

            if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync)\b', title):
                continue
                
            # BLOCARE FIȘIERE GUNOI / MALWARE
            bad_extensions = ['.exe', '.msi', '.bat', '.cmd', '.scr']
            if any(title.lower().endswith(ext) for ext in bad_extensions) or '.exe ' in title.lower() or '.exe' == title.lower()[-4:]:
                continue

            # FILTRU WEB (Opțional din setări) - DOAR PENTRU RD
            try:
                if ADDON.getSetting('filter_web_sources') == 'true':
                    # Extragem service-ul mai devreme pentru a filtra doar RD
                    aio_service = str(item.get('service', '')).strip().lower()
                    if aio_service == 'realdebrid' or aio_service == 'rd':
                        if _is_web_source(title) or _is_web_source(full_title_raw):
                            # log(f"[FILTER-WEB] Excluzând sursa WEB RD AIO: {title[:50]}...")
                            continue
            except:
                pass

            res_tag = "SD"
            check_text = (str(parsed.get('resolution', '')) + ' ' + full_title_raw + ' ' + title).upper()
            
            # --- FIX: Multi-rezoluție și izolare grupuri (inclusiv 4KHDHUB) ---
            clean_text = check_text.replace('DS4K', '').replace('SDR4K', '').replace('HDR4K', '').replace('4KHDHUB', '')
            
            res_count = sum(1 for r in ['2160P', '1080P', '720P', '480P', '360P'] if r in check_text)
            if '4K' in clean_text and '2160P' not in check_text: res_count += 1
            
            if res_count >= 2: res_tag = 'SD'
            elif any(x in check_text for x in['2160P', '2160', 'UHD']) or '4K' in clean_text: res_tag = '4K'
            elif any(x in check_text for x in ['1080P', '1080I', 'FHD']): res_tag = '1080p'
            elif any(x in check_text for x in['720P', '720I', 'HD']): res_tag = '720p'
            else: res_tag = 'SD'

            size_bytes = item.get('size') or bh.get('videoSize') or 0
            size_str = ""
            if size_bytes:
                try:
                    size_bytes = float(size_bytes)
                    for factor, suffix in[(1024**4, ' TB'), (1024**3, ' GB'), (1024**2, ' MB'), (1024**1, ' KB'), (1024**0, ' B')]:
                        if size_bytes >= factor: 
                            size_str = f"{round(size_bytes / factor, 2)}{suffix}"
                            break
                except: pass

            # --- EXTRAGERE PUTERNICĂ SEEDERI (Fallback din titlu) ---
            seeders = 0
            try:
                s_val = item.get('seeders')
                if s_val:
                    seeders = int(s_val)
                else:
                    m_seeds = re.search(
                        r'(?:👤|👥|S:)\s*(\d+)',
                        full_title_raw + str(item.get('description', '')),
                        re.IGNORECASE)
                    if m_seeds:
                        seeders = int(m_seeds.group(1))
            except: pass

            # --- Extragere service ---
            debrid_service = str(item.get('service', '')).strip()
            
            # Anihilăm valoarea literală "None" de pe server
            if debrid_service.lower() == 'none':
                debrid_service = ''
                
            is_cached = bool(item.get('cached', False))
            is_cloud = 'cloud' in str(item.get('indexer', '')).lower() or 'cloud' in str(item.get('type', '')).lower()
            source_addon = str(item.get('addon') or item.get('provider') or parsed.get('source') or '').strip()
            indexer = str(item.get('indexer', '')).strip()
            
            # --- Extragere Release Group ---
            release_group = str(item.get('releaseGroup') or parsed.get('releaseGroup') or '').strip()
            # Fallback inteligent din nume dacă serverul nu ne dă grupul
            if not release_group:
                release_group = _extract_release_group(title)
            
            streams.append({
                'name': title,
                'url': build_stream_url(play_url),
                'quality': res_tag,
                'title': title,
                'size': size_str,
                'source_provider': source_addon,
                'server': indexer,
                'provider_id': 'aiostreams',
                'info': {
                    'debrid_service': debrid_service,
                    'is_cached': is_cached,
                    'is_cloud': is_cloud,
                    'addon': source_addon,
                    'indexer': indexer,
                    'seeders': seeders,
                    'releaseGroup': release_group
                }
            })
        except: continue
    return streams


def scrape_torrentio(imdb_id, content_type, season=None, episode=None):
    if ADDON.getSetting('use_torrentio') == 'false':
        return None

    manifest_url = ADDON.getSetting('torrentio_manifest').strip()
    if not manifest_url:
        log("[TORRENTIO] Lipseste URL manifest.json din setari!")
        return None

    # Extragem baza URL-ului (tot ce e inainte de /manifest.json)
    base_url = manifest_url.split('/manifest.json')[0].rstrip('/')

    try:
        if content_type == 'movie':
            api_url = f"{base_url}/stream/movie/{imdb_id}.json"
        else:
            api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json"

        log(f"[TORRENTIO] Caut pe: {api_url[:80]}...")
        r = get_shared_session().get(api_url, headers=get_headers(), timeout=15, verify=False)
        
        if r.status_code == 200:
            data = r.json()
            found_streams = []
            
            for s in data.get('streams', []):
                url = s.get('url')
                if not url: continue
                
                raw_name = s.get('name', '')
                raw_title = s.get('title', '')
                
                # FILTRU WEB (Opțional din setări) - DOAR PENTRU RD
                try:
                    if ADDON.getSetting('filter_web_sources') == 'true':
                        name_up = raw_name.upper()
                        if '[RD+]' in name_up or '[RD]' in name_up:
                            if _is_web_source(raw_name) or _is_web_source(raw_title):
                                continue
                except:
                    pass

                name_upper = raw_name.upper()
                
                # 1. Detectare Debrid / Cached (Pentru a aparea RD+ in stanga)
                is_cached = False
                debrid_service = ""
                
                if '[RD+]' in name_upper: is_cached = True; debrid_service = 'realdebrid'
                elif '[AD+]' in name_upper: is_cached = True; debrid_service = 'alldebrid'
                elif '[PM+]' in name_upper: is_cached = True; debrid_service = 'premiumize'
                elif '[TB+]' in name_upper: is_cached = True; debrid_service = 'torbox'
                elif '[EN+]' in name_upper or '[EN]' in name_upper: is_cached = True; debrid_service = 'easynews'
                
                # 2. Extragere Marime si Seederi
                size_match = re.search(r'([\d.]+\s*(?:GB|MB|TB))', raw_title, re.IGNORECASE)
                size = size_match.group(1).upper() if size_match else ""
                
                seeders = 0
                seed_match = re.search(r'(?:👤|👥|S:)\s*(\d+)', raw_title)
                if seed_match: seeders = int(seed_match.group(1))

                # 3. Extragere Nume Fisier REAL (pt Subtitrari si UI linia 1) si Indexer
                lines = raw_title.split('\n')
                filename = lines[-1].strip() if lines else raw_title
                
                indexer = ""
                if len(lines) > 1:
                    # Curatam prima linie de emoji-uri si marimi pentru a pastra doar numele site-ului
                    first_line = lines[0].replace('👤', '').replace('💾', '').replace('⚙️', '').replace('☁️', '')
                    first_line = re.sub(r'[\d.]+\s*(?:GB|MB|TB)', '', first_line, flags=re.IGNORECASE)
                    first_line = re.sub(r'\d+', '', first_line).strip(' |-,')
                    indexer = first_line

                # Fallback in caz ca numele fisierului extras e prea scurt
                if len(filename) < 5:
                    filename = raw_title.replace('\n', ' ')

                # 4. Calitate
                quality = _extract_quality_from_string(raw_name) 
                if not quality or quality == 'SD':
                    quality = _extract_quality_from_string(filename) or 'SD'
                
                stream_obj = {
                    'name': filename,  # Linia 1 in UI
                    'url': build_stream_url(url),
                    'quality': quality,
                    'title': filename, # Salvat aici pentru a fi gasit de Wyzie (Subtitrari)
                    'size': size,
                    'source_provider': 'Torrentio',
                    'server': indexer,
                    'provider_id': 'torrentio',
                    'info': {
                        'debrid_service': debrid_service,
                        'is_cached': is_cached,
                        'addon': 'Torrentio',
                        'indexer': indexer,
                        'seeders': seeders,
                        'releaseGroup': ''
                    }
                }
                found_streams.append(stream_obj)

            log(f"[TORRENTIO] Găsite: {len(found_streams)} surse.")
            return found_streams
    except Exception as e:
        log(f"[TORRENTIO] Eroare: {e}", xbmc.LOGERROR)

    return None


# =============================================================================
# SCRAPER YFLIX ([YFX])
# =============================================================================
def scrape_yflix(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_yflix') == 'false':
        return None
    
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None

    _API      = 'https://enc-dec.app/api'
    _DB_API   = 'https://enc-dec.app/db/flix'
    _AJAX     = 'https://yflix.to/ajax'
    _UA       = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                 'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')

    def _encrypt(sess, text):
        r = sess.get(f'{_API}/enc-movies-flix', params={'text': text}, timeout=10)
        r.raise_for_status()
        return r.json()['result']

    def _decrypt(sess, text):
        r = sess.post(f'{_API}/dec-movies-flix', json={'text': text}, timeout=10)
        r.raise_for_status()
        return r.json()['result']

    def _parse_html(sess, html):
        r = sess.post(f'{_API}/parse-html', json={'text': html}, timeout=10)
        r.raise_for_status()
        return r.json()['result']

    def _dec_rapid(sess, text):
        r = sess.post(f'{_API}/dec-rapid', json={'text': text, 'agent': _UA}, timeout=15)
        r.raise_for_status()
        return r.json()['result']

    def _find_db(sess, tmdb_id, media_type):
        t = 'movie' if media_type == 'movie' else 'tv'
        r = sess.get(f'{_DB_API}/find', params={'tmdb_id': tmdb_id, 'type': t}, timeout=10)
        r.raise_for_status()
        results = r.json()
        return results[0] if results else None

    def _rapid_sources(sess, embed_url):
        media_url = re.sub(r'/e2?/', '/media/', embed_url)
        r = sess.get(media_url, timeout=15)
        r.raise_for_status()
        encrypted = r.json().get('result', '')
        if not encrypted:
            return []
        rapid = _dec_rapid(sess, encrypted)
        if not isinstance(rapid, dict):
            return []
        return [s['file'] for s in rapid.get('sources', []) if s.get('file')]

    def _servers_for_eid(sess, eid):
        enc_eid = _encrypt(sess, eid)
        r = sess.get(f'{_AJAX}/links/list', params={'eid': eid, '_': enc_eid}, timeout=15)
        r.raise_for_status()
        raw_html = r.json().get('result', '')
        parsed = _parse_html(sess, raw_html)
        lids = []
        for stype, sdict in parsed.items():
            for skey, sval in sdict.items():
                lid = sval.get('lid')
                if lid:
                    lids.append(lid)
        return lids

    def _resolve_lid(sess, lid):
        enc_lid = _encrypt(sess, lid)
        r = sess.get(f'{_AJAX}/links/view', params={'id': lid, '_': enc_lid}, timeout=15)
        r.raise_for_status()
        enc_embed = r.json().get('result', '')
        decrypted = _decrypt(sess, enc_embed)
        if not isinstance(decrypted, dict):
            return []
        url = decrypted.get('url', '')
        if 'rapidshare' in url:
            return _rapid_sources(sess, url)
        return []

    try:
        sess = get_shared_session()
        # Ensure we have the right headers for YFlix
        sess.headers.update({'User-Agent': _UA})

        db = _find_db(sess, tmdb_id, content_type)
        if not db:
            log(f'[YFLIX] nu în DB pentru tmdb={tmdb_id}', xbmc.LOGWARNING)
            return []

        episodes = db.get('episodes', {})

        s_key = str(season or 1)
        e_key = str(episode or 1)
        ep_data = (episodes.get(s_key) or {}).get(e_key)
        if not ep_data:
            log(f'[YFLIX] episod S{season}E{episode} negăsit pentru tmdb={tmdb_id}', xbmc.LOGWARNING)
            return []

        eid = ep_data.get('eid')
        if not eid:
            return []

        lids = _servers_for_eid(sess, eid)
        m3u8s = []
        seen = set()
        for lid in lids:
            try:
                for url in _resolve_lid(sess, lid):
                    if url not in seen:
                        seen.add(url)
                        m3u8s.append(url)
            except Exception as e:
                log(f'[YFLIX] lid={lid} eroare: {e}', xbmc.LOGWARNING)

        sources = []
        display_title = f"{title_query} ({year_query})" if title_query else "YFlix"
        
        for url in m3u8s:
            variants = _parse_m3u8_variants(url, custom_headers={'User-Agent': _UA})
            if variants:
                for var in variants:
                    res_val = var['resolution']
                    quality = _get_quality_from_res(res_val)
                    sources.append({
                        'url':        f"{var['url']}|User-Agent={_UA}",
                        'name':       f"{display_title} | {res_val}",
                        'quality':    quality,
                        'title':      '',
                        'info': {
                            'original_info_str': f'YFlix | Rapid | {res_val}',
                            'provider': 'YFlix',
                            'source_provider': f'| Rapid | {res_val}',
                            'size': ''
                        },
                        'source_provider': f'| Rapid | {res_val}',
                        'provider_id': 'yflix',
                    })
            else:
                sources.append({
                    'url':        f'{url}|User-Agent={_UA}',
                    'name':       display_title,
                    'quality':    _get_quality_from_res(display_title),
                    'title':      '',
                    'info': {
                        'original_info_str': 'YFlix | Rapid',
                        'provider': 'YFlix',
                        'source_provider': '| Rapid',
                        'size': ''
                    },
                    'source_provider': '| Rapid',
                    'provider_id': 'yflix',
                })

        log(f'[YFLIX] {len(sources)} surse pentru tmdb={tmdb_id}', xbmc.LOGINFO)
        return sources

    except Exception as e:
        log(f'[YFLIX] eroare: {e}', xbmc.LOGERROR)
        return []


# =============================================================================
# SCRAPER PRIMESRC.ME ([PSM])
# =============================================================================
THRAX_KEY = "7d9f4987bcd1a2026e6a422931bd7dbff0060977d189f37fa5727d9288b4abbb"
THRAX_HEADERS = {"X-Thrax-Key": THRAX_KEY}

def scrape_primesrc(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    """Scraper Direct pentru PrimeSrc via vidsrcme.ru -> cloudnestra."""
    if ADDON.getSetting('use_primesrc') == 'false':
        return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None
    try:
        _UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        _CDN_DOMAINS = ['neonhorizonworkshops.com', 'wanderlynest.com', 'orchidpixelgardens.com', 'cloudnestra.com']
        _HEADERS = {'User-Agent': _UA}
        
        sess = get_shared_session()
        vidsrc_url = f'https://vidsrcme.ru/embed/{content_type}/{tmdb_id}'
        if content_type == 'tv':
            vidsrc_url += f'?s={season}&e={episode}'
        log(f'[PRIMESRC-D] Interogare vidsrcme: {vidsrc_url}')
        r1 = sess.get(vidsrc_url, headers={**_HEADERS, 'Accept': 'text/html', 'Referer': 'https://primesrc.me/'}, timeout=15, verify=False)
        if not r1.ok:
            log(f'[PRIMESRC-D] vidsrcme eșuat: {r1.status_code}')
            return None
        iframe_m = re.search(r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']', r1.text, re.I)
        if not iframe_m: return None
        iframe_url = iframe_m.group(1)
        if iframe_url.startswith('//'): iframe_url = 'https:' + iframe_url
        if 'cloudnestra' not in iframe_url: return None
        # --- REPARARE RATE-LIMIT: retry + referer corect + validare inteligentă ---
        r2 = None
        for retry in range(3):
            try:
                r2 = sess.get(iframe_url, headers={**_HEADERS, 'Accept': 'text/html', 'Referer': iframe_url}, timeout=15, verify=False)
                if r2.ok:
                    # Validare inteligentă: conținut >= 1500 bytes SAU conține pattern-ul prorcp
                    if len(r2.text) >= 1500 or re.search(r'["\'/]prorcp/', r2.text):
                        log(f'[PRIMESRC-D] cloudnestra OK (încercarea {retry+1}, {len(r2.text)} bytes)')
                        break
                    else:
                        log(f'[PRIMESRC-D] cloudnestra conținut prea mic (încercarea {retry+1}, {len(r2.text)} bytes)')
                else:
                    log(f'[PRIMESRC-D] cloudnestra HTTP {r2.status_code} (încercarea {retry+1})')
                r2 = None
            except Exception as e:
                log(f'[PRIMESRC-D] cloudnestra excepție (încercarea {retry+1}): {e}')
                r2 = None
            
            if retry < 2:
                import time as _time
                _time.sleep(2 + retry)  # Backoff: 2s, 3s, 4s
        
        if r2 is None:
            log('[PRIMESRC-D] cloudnestra rate-limit după 3 încercări, abandon')
            return None
        prorcp_m = re.search(r'["\'/]prorcp/([^"\'>\s]+)', r2.text)
        if not prorcp_m: return None
        prorcp_url = f'https://cloudnestra.com/prorcp/{prorcp_m.group(1)}'
        r3 = sess.get(prorcp_url, headers={**_HEADERS, 'Accept': 'text/html', 'Referer': iframe_url}, timeout=15, verify=False)
        
        m3u8s = list(dict.fromkeys(re.findall(r'https?://[^\s"\'<>)]+\.m3u8[^\s"\'<>)]*', r3.text)))
        
        sources = []
        # Modificăm scraperul Direct pentru a returna și link-ul de embed vidsrcme.ru
        # Acesta va fi rezolvat în player.py prin resolve_primesrcme (Thrax)
        display_name_embed = f"{title_query} ({year_query})" if title_query else f"PrimeSrc Embed | {tmdb_id}"
        if content_type == 'tv' and title_query:
            display_name_embed = f"{title_query} S{int(season):02d}E{int(episode):02d}"
        # Adăugăm sursa embed ca opțiune sigură care folosește Thrax (din primesrcme logic)
        sources.append({
            'url': vidsrc_url,
            'name': f"{display_name_embed} | [COLOR FF00BFFF]Auto[/COLOR]",
            'quality': '1080p',
            'title': '',
            'tmdb_id': f"{tmdb_id}:{content_type}{':'+str(season)+':'+str(episode) if content_type=='tv' else ''}",
            'info': {
                'original_info_str': 'PrimeSrc | Embed',
                'provider': 'PrimeSrc',
                'source_provider': '| Embed',
                'size': ''
            },
            'source_provider': '| Embed',
            'provider_id': 'primesrcme', # ID-ul primesrcme forțează player.py să folosească resolve_primesrcme
        })
        display_name = f"{title_query} ({year_query})" if title_query else f"PrimeSrc | {tmdb_id}"
        if content_type == 'tv' and title_query:
            display_name = f"{title_query} S{int(season):02d}E{int(episode):02d}"
        for url in m3u8s:
            if '{v' in url:
                for domain in _CDN_DOMAINS:
                    temp_url = re.sub(r'\{v\d+\}', domain, url)
                    try:
                        rv = sess.get(temp_url, headers={**_HEADERS, 'Referer': 'https://cloudnestra.com/'}, timeout=8, verify=False)
                        if rv.ok and '#EXTM3U' in rv.text:
                            variants = _parse_m3u8_variants(temp_url, custom_headers={**_HEADERS, 'Referer': 'https://cloudnestra.com/'})
                            if variants:
                                for var in variants:
                                    res_val = var['resolution']
                                    quality = _get_quality_from_res(res_val)
                                    sources.append({
                                        'url': f"{var['url']}|User-Agent={_UA}&Referer=https://cloudnestra.com/",
                                        'name': f"{display_name} | {res_val}",
                                        'quality': quality,
                                        'title': '',
                                        'info': {
                                            'original_info_str': f'PrimeSrc | Direct | {res_val}',
                                            'provider': 'PrimeSrc',
                                            'source_provider': f'| Direct | {res_val}',
                                            'size': ''
                                        },
                                        'source_provider': f'| Direct | {res_val}',
                                        'provider_id': 'primesrc',
                                    })
                            else:
                                sources.append({
                                    'url': f"{temp_url}|User-Agent={_UA}&Referer=https://cloudnestra.com/",
                                    'name': display_name,
                                    'quality': _get_quality_from_res(temp_url),
                                    'title': '',
                                    'info': {
                                        'original_info_str': 'PrimeSrc | Direct',
                                        'provider': 'PrimeSrc',
                                        'source_provider': '| Direct',
                                        'size': ''
                                    },
                                    'source_provider': '| Direct',
                                    'provider_id': 'primesrc',
                                })
                            break
                    except: pass
            else:
                try:
                    rv = sess.get(url, headers={**_HEADERS, 'Referer': 'https://cloudnestra.com/'}, timeout=8, verify=False)
                    if not (rv.ok and '#EXTM3U' in rv.text): continue
                    
                    variants = _parse_m3u8_variants(url, custom_headers={**_HEADERS, 'Referer': 'https://cloudnestra.com/'})
                    if variants:
                        for var in variants:
                            res_val = var['resolution']
                            quality = _get_quality_from_res(res_val)
                            sources.append({
                                'url': f"{var['url']}|User-Agent={_UA}&Referer=https://cloudnestra.com/",
                                'name': f"{display_name} | {res_val}",
                                'quality': quality,
                                'title': '',
                                'info': {
                                    'original_info_str': f'PrimeSrc | Direct | {res_val}',
                                    'provider': 'PrimeSrc',
                                    'source_provider': f'| Direct | {res_val}',
                                    'size': ''
                                },
                                'source_provider': f'| Direct | {res_val}',
                                'provider_id': 'primesrc',
                            })
                    else:
                        sources.append({
                            'url': f"{url}|User-Agent={_UA}&Referer=https://cloudnestra.com/",
                            'name': display_name,
                            'quality': _get_quality_from_res(url),
                            'title': '',
                            'info': {
                                'original_info_str': 'PrimeSrc | Direct',
                                'provider': 'PrimeSrc',
                                'source_provider': '| Direct',
                                'size': ''
                            },
                            'source_provider': '| Direct',
                            'provider_id': 'primesrc',
                        })
                except: continue
        log(f'[PRIMESRC-D] Găsite {len(sources)} surse.')
        return sources
    except Exception as e:
        log(f'[PRIMESRC-D] eroare: {e}', xbmc.LOGERROR)
        return None

def scrape_primesrcme(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_primesrcme') == 'false':
        return None

    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None

    _BASE        = 'https://primesrc.me'
    _UA          = 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0'
    _HEADERS     = {
        'User-Agent': _UA,
        'Referer':    f'{_BASE}/',
        'Accept':     'application/json',
    }

    def _get_servers(media_type, tmdb_id, season=None, episode=None):
        params = {'type': media_type, 'tmdb': tmdb_id}
        if season is not None:
            params['season'] = season
        if episode is not None:
            params['episode'] = episode
        try:
            r = requests.get(f'{_BASE}/api/v1/s', params=params, headers=_HEADERS, timeout=10)
            if r.ok:
                return r.json().get('servers', [])
            if r.status_code == 403 and 'cloudflare' in r.text.lower():
                log(f'[PRIMESRC] /api/v1/s blocat Cloudflare pentru tmdb={tmdb_id}', xbmc.LOGWARNING)
            else:
                log(f'[PRIMESRC] /api/v1/s status={r.status_code}', xbmc.LOGWARNING)
        except Exception as e:
            log(f'[PRIMESRC] get_servers: {e}', xbmc.LOGWARNING)
        return []

    try:
        servers = _get_servers(content_type, tmdb_id, season, episode)
        if not servers:
            log(f'[PRIMESRC] niciun server pentru tmdb={tmdb_id}', xbmc.LOGWARNING)
            return []

        sources = []
        seen    = set()

        for srv in servers:
            key  = srv.get('key', '')
            name = srv.get('name', '')
            if not key:
                continue
            api_url = f'{_BASE}/api/v1/l?key={key}'
            if api_url in seen:
                continue
            seen.add(api_url)

            size       = srv.get('file_size') or ''
            quality    = srv.get('quality') or '1080p'
            audio_type = srv.get('audio_type') or ''
            audio_lang = srv.get('audio_language') or ''

            display_title = f"{title_query} ({year_query})" if title_query else name

            # Construim tmdb_id pentru Thrax caching
            if content_type == 'movie':
                tmdb_id_str = f"{tmdb_id}:movie"
            else:
                tmdb_id_str = f"{tmdb_id}:tv:{season}:{episode}"

            sources.append({
                'url':        api_url,
                'name':       display_title,
                'quality':    quality,
                'title':      '',
                'tmdb_id':    tmdb_id_str,
                'info': {
                    'original_info_str': f'PrimeSrc | {name}',
                    'provider': 'PrimeSrc',
                    'source_provider': f'| {name}',
                    'size': size
                },
                'source_provider': f'| {name}',
                'provider_id': 'primesrcme',
            })

        log(f'[PRIMESRC] {len(sources)} surse pentru tmdb={tmdb_id}', xbmc.LOGINFO)
        return sources

    except Exception as e:
        log(f'[PRIMESRC] eroare: {e}', xbmc.LOGERROR)
        return []


def resolve_primesrcme(url, tmdb_id=None):
    """Extrage key-ul din URL și îl rezolvă prin Thrax API (FlareSolverr server-side).
    Dacă se specifică tmdb_id, acesta e transmis la Thrax pentru caching automat."""
    from urllib.parse import urlparse, parse_qs
    _THRAX = 'https://api.derzis.xyz'
    
    qs = parse_qs(urlparse(url).query)
    key = (qs.get('key') or [''])[0]
    if not key:
        log(f'[PRIMESRC] resolve_primesrcme: key lipsă din {url}', xbmc.LOGWARNING)
        return None
    try:
        params = {'key': key}
        if tmdb_id:
            params['tmdb_id'] = tmdb_id
        r = requests.get(f'{_THRAX}/primesrcme/resolve', params=params, timeout=90,
                         headers={**THRAX_HEADERS, 'Accept-Encoding': 'gzip, deflate'})
        if not r.ok:
            log(f'[PRIMESRC] Thrax /primesrcme/resolve HTTP {r.status_code}', xbmc.LOGWARNING)
            return None
        data = r.json()
        link = data.get('link', '')
        if not link:
            log(f'[PRIMESRC] Thrax: câmpul link lipsă: {data}', xbmc.LOGWARNING)
            return None
        
        return link
    except Exception as e:
        log(f'[PRIMESRC] resolve_primesrcme eroare: {e}', xbmc.LOGWARNING)
        return None


# =============================================================================
# HELPER PENTRU ID-URI TMDB
# =============================================================================
def _get_tmdb_id_internal(id_str):
    if not id_str: return None
    id_str = str(id_str)
    if id_str.startswith('tmdb:'):
        return id_str.replace('tmdb:', '')
    if id_str.startswith('tt'):
        try:
            url = f"{BASE_URL}/find/{id_str}?api_key={API_KEY}&external_source=imdb_id"
            data = get_json(url)
            # Prioritate pentru tv_episode_results (luăm show_id)
            if data.get('tv_episode_results'):
                return str(data['tv_episode_results'][0].get('show_id'))
            results = data.get('movie_results', []) or data.get('tv_results', [])
            if results:
                return str(results[0]['id'])
        except: pass
    return id_str

# =============================================================================
# SCRAPER VAPLAYER (VAPlayer.ru)
# =============================================================================
def scrape_vaplayer(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_vaplayer') == 'false':
        return None
        
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        return None
        
    try:
        api_url = "https://streamdata.vaplayer.ru/api.php"
        params = {
            "tmdb": tmdb_id,
            "type": "movie" if content_type == 'movie' else 'tv'
        }
        if content_type == 'tv':
            params['season'] = season
            params['episode'] = episode

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://brightpathsignals.com/",
            "Origin": "https://brightpathsignals.com",
            "Accept": "*/*",
            "Accept-Language": "ro-RO,ro-GB;q=0.9,en;q=0.8"
        }
        
        session = get_shared_session()
        resp = session.get(api_url, params=params, headers=headers, timeout=10, verify=False)
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        if not data or data.get('status') == 'error':
            return None
            
        inner_data = data.get('data', {})
        # Luăm doar prima parte din file_name (înainte de slash)
        file_name = inner_data.get('file_name', '')
        if '/' in file_name:
            file_name = file_name.split('/')[0].strip()
        
        release_title = file_name or inner_data.get('title') or title_query or "VAPlayer"
        streams = inner_data.get('stream_urls', [])
        
        if not streams:
            return None
        
        # Curățăm titlul de tag-uri de calitate pentru a evita detecția greșită în player.py
        clean_release_title = re.sub(r'(?i)\b(2160p|1080p|720p|480p|360p|4k|sd|uhd|hd)\b', '', release_title)
        # Curățăm doar parantezele drepte, păstrând conținutul (pentru ca tag-urile să fie încă detectate)
        clean_release_title = clean_release_title.replace('[', '').replace(']', '')
        clean_release_title = re.sub(r'\s+', ' ', clean_release_title).strip()

        # Detectăm o calitate de bază din titlul original pentru fallback
        base_quality = '1080p'
        if '2160' in release_title or '4K' in release_title: base_quality = '4K'
        elif '1080' in release_title: base_quality = '1080p'
        elif '720' in release_title: base_quality = '720p'
        elif '480' in release_title or 'SD' in release_title: base_quality = 'SD'

        # Extragem release group (de obicei după ultimul crâmpei de după cratimă, ignorând extensia)
        temp_title = re.sub(r'\.(mkv|mp4|avi|mov|ts|m3u8)$', '', release_title, flags=re.I)
        release_group = ""
        group_match = re.search(r'-([A-Za-z0-9]+)$', temp_title)
        if group_match:
            release_group = group_match.group(1)
        
        # Dacă nu am găsit cu cratimă, încercăm să vedem dacă e în paranteze pătrate la final
        if not release_group:
            group_match = re.search(r'\[([A-Za-z0-9.]+)\]$', temp_title)
            if group_match:
                release_group = group_match.group(1)

        results = []
        for master_url in streams:
            # Parserul m3u8 acum folosește doar User-Agent simplu (ca în scriptul tău)
            variants = _parse_m3u8_variants(master_url)
            
            if not variants:
                # Dacă nu putem parsa variantele, adăugăm master-ul cu calitatea detectată din titlu
                results.append({
                    'name': f'VAPlayer | {base_quality} | {clean_release_title}',
                    'url': build_stream_url(master_url, referer="https://brightpathsignals.com/"),
                    'quality': base_quality,
                    'title': clean_release_title,
                    'info': {
                        'original_info_str': 'VAPlayer',
                        'provider': 'VAPlayer',
                        'source_provider': '',
                        'releaseGroup': release_group,
                        'size': ''
                    },
                    'source_provider': '',
                    'provider_id': 'vaplayer'
                })
                continue
                
            for v in variants:
                raw_res = v['resolution']
                # Normalizare rezoluție mai permisivă (pentru formate ultra-wide etc.)
                if any(x in raw_res for x in ['2160', '3840', '4K', '4k']):
                    quality = '4K'
                elif any(x in raw_res for x in ['1080', '1920']):
                    quality = '1080p'
                elif any(x in raw_res for x in ['720', '1280']):
                    quality = '720p'
                else:
                    quality = 'SD'
                    
                results.append({
                    'name': f"VAPlayer | {quality} | {clean_release_title}",
                    'url': build_stream_url(v['url'], referer="https://brightpathsignals.com/"),
                    'quality': quality,
                    'title': clean_release_title,
                    'info': {
                        'original_info_str': 'VAPlayer',
                        'provider': 'VAPlayer',
                        'source_provider': '',
                        'releaseGroup': release_group,
                        'size': ''
                    },
                    'source_provider': '',
                    'provider_id': 'vaplayer'
                })
                
        return results
    except Exception as e:
        log(f"[VAPLAYER] Error: {e}")
        return None


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
    
    # --- CITIM SETAREA UTILIZATORULUI ---
    filter_duplicates = ADDON.getSetting('filter_duplicate_urls') == 'true'

    # 1. EXTRAGERE TITLU ȘI AN DIN TMDB (Necesar și foarte robust)
    extra_title = ""
    extra_year = ""
    
    title_based_scrapers = ['hdhub4u', 'mkvcinemas', 'vixsrc', 'moviesdrive', 'dooflix', 'vidlink', 'vsembed', 'meowtv', 'hdhub', 'streamvix', 'videasy', 'netmirror', 'castle', 'vidmody', 'movieblast', 'moviebox', 'lamovie', 'onlykdrama', 'yflix', 'primesrc', 'primesrcme', 'vaplayer']
    needs_title = any(
        ADDON.getSetting(f'use_{scraper}') == 'true' 
        for scraper in title_based_scrapers
    )
    
    if needs_title:
        try:
            imdb_str = str(imdb_id)
            if imdb_str.startswith('tt'):
                url = f"{BASE_URL}/find/{imdb_str}?api_key={API_KEY}&external_source=imdb_id"
                data = get_json(url)
                res = data.get('movie_results', []) or data.get('tv_results', [])
                if res:
                    extra_title = res[0].get('title') or res[0].get('name')
                    dt = res[0].get('release_date') or res[0].get('first_air_date')
                    extra_year = dt[:4] if dt else ""
            
            # Fallback 100% sigur: Dacă IMDB a eșuat sau ID-ul trimis era de fapt TMDB (tmdb:1234)
            if not extra_title:
                clean_id = imdb_str.replace('tmdb:', '')
                url = f"{BASE_URL}/{'tv' if content_type == 'tv' else 'movie'}/{clean_id}?api_key={API_KEY}"
                data = get_json(url)
                if data:
                    extra_title = data.get('title') or data.get('name')
                    dt = data.get('release_date') or data.get('first_air_date')
                    extra_year = dt[:4] if dt else ""
                    
            log(f"[SCRAPER] Title resolved safely: '{extra_title}' ({extra_year})")
        except Exception as e:
            log(f"[SCRAPER] Could not resolve title from TMDB: {e}")

    # 2. DEFINIRE PROVIDERI (ORDINEA CERUTĂ)
    providers_map = {
        'sooti': ('Sootio', lambda: scrape_sooti(imdb_id, content_type, season, episode)),
        'nuvio': ('Nuvio', lambda: _scrape_json_provider("https://nuviostreams.hayd.uk", 'stream', 'Nuvio', imdb_id, content_type, season, episode)),
        'webstreamr': ('Webstreamr', lambda: _scrape_json_provider("https://87d6a6ef6b58-webstreamrmbg.baby-beamup.club", 'stream', 'Webstreamr', imdb_id, content_type, season, episode)),
        'streamvix': ('StreamVix', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamVix', imdb_id, content_type, season, episode)),
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'meowtv': ('MeowTV', lambda: _scrape_json_provider("https://meowtv.vflix.shop", 'stream', 'MeowTV', imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'dooflix': ('DooFlix', lambda: scrape_dooflix(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vidlink': ('VidLink', lambda: scrape_vidlink(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vaplayer': ('VAPlayer', lambda: scrape_vaplayer(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vsembed': ('VSEmbed', lambda: scrape_vsembed(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'videasy': ('VidEasy', lambda: scrape_videasy(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'netmirror': ('NetMirror', lambda: scrape_netmirror(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'castle': ('Castle', lambda: scrape_castle(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vidmody': ('Vidmody', lambda: scrape_vidmody(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'movieblast': ('MovieBlast', lambda: scrape_movieblast(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'moviebox': ('MovieBox', lambda: scrape_moviebox(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'lamovie': ('LaMovie', lambda: scrape_lamovie(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'onlykdrama': ('OnlyKDrama', lambda: scrape_onlykdrama(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'yflix': ('YFlix', lambda: scrape_yflix(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'primesrc': ('PrimeSrc', lambda: scrape_primesrc(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'primesrcme': ('PrimeSrc.me', lambda: scrape_primesrcme(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        
        'hdhub4u': ('HDHub4u', lambda: scrape_hdhub4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'mkvcinemas': ('MKVCinemas', lambda: scrape_mkvcinemas(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'moviesdrive': ('MoviesDrive', lambda: scrape_moviesdrive(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'hdhub': ('HDHub', lambda: _scrape_json_provider("https://hdhub.thevolecitor.qzz.io/eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9", 'stream', 'HDHub', imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        
        # PROVIDERI DEBRID (IGNORĂ SWITCH-UL GLOBAL HTTP)
        'aiostreams': ('AIO Streams', lambda: scrape_aiostreams(imdb_id, content_type, season, episode)),
        'torrentio': ('Torrentio', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'torrentio', 'Torrentio')),
        'mediafusion': ('Mediafusion', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'mediafusion', 'Mediafusion')),
        'comet': ('Comet', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'comet', 'Comet')),
        'meteor': ('Meteor', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'meteor', 'Meteor')),
    }

    # 3. SELECȚIE PROVIDERI ACTIVI (CU LOGICĂ MASTER SWITCH)
    to_run = []
    http_master_enabled = ADDON.getSetting('enable_http_scrapers') == 'true'
    debrid_providers = ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor']

    if target_providers is not None:
        for pid in target_providers:
            if pid in providers_map:
                setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
                # Executăm dacă (e Debrid) SAU (Master HTTP e On și setarea individuală e On)
                if pid in debrid_providers or (http_master_enabled and ADDON.getSetting(setting_id) == 'true'):
                    to_run.append((pid, providers_map[pid][0], providers_map[pid][1]))
    else:
        for pid, (pname, pfunc) in providers_map.items():
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if pid in debrid_providers or (http_master_enabled and ADDON.getSetting(setting_id) == 'true'):
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

    # 5. EXECUȚIE PARALELĂ - OPTIMIZATĂ CU STATUS ÎN TIMP REAL
    try: MAX_TIMEOUT = int(ADDON.getSetting('scraper_timeout'))
    except: MAX_TIMEOUT = 25
    
    MAX_WORKERS = 15  # Crescut pentru mai multă paralelizare
    
    import time
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        future_to_provider = {executor.submit(run_provider, p): p for p in to_run}
        
        futures_list = list(future_to_provider.keys())
        finished_futures = set()
        start_time = time.time()
        
        try:
            # Loop cu polling non-blocant (0.25 secunde) pentru actualizare GUI cursivă
            while len(finished_futures) < len(futures_list):
                elapsed = time.time() - start_time
                if elapsed > MAX_TIMEOUT:
                    log(f"[SCRAPER] Global timeout forțat ({MAX_TIMEOUT}s)")
                    break
                    
                # Așteptăm 0.25 sec pentru a nu bloca interfața Kodi
                done, not_done = concurrent.futures.wait(
                    futures_list, 
                    timeout=0.25, 
                    return_when=concurrent.futures.FIRST_COMPLETED
                )
                
                # --- 1. ACTUALIZARE UI (Trimitem variante pentru ambele skin-uri) ---
                if progress_callback:
                    percent = int((len(finished_futures) / total_providers) * 100)
                    
                    pending_names = [future_to_provider[f][1] for f in not_done]
                    
                    # LOGICA PENTRU ESTUARY (Lista completă)
                    if pending_names:
                        formatted_names = [f"[B][COLOR FFFF69B4]{pending_names[0]}[/COLOR][/B]"]
                        for name in pending_names[1:3]:
                            formatted_names.append(f"[B][COLOR white]{name}[/COLOR][/B]")
                            
                        if len(pending_names) > 3:
                            display_pending = ", ".join(formatted_names) + f" [COLOR gray][I](+{len(pending_names)-3})[/I][/COLOR]"
                        else:
                            display_pending = ", ".join(formatted_names)
                    else:
                        display_pending = "[B][COLOR lime]Finalizare...[/COLOR][/B]"

                    msg_estuary = (
                        f"[COLOR gray]Se scanează:[/COLOR] {display_pending}\n"
                        f"[COLOR gray]Scanați:[/COLOR] [B][COLOR cyan]{len(finished_futures)}/{total_providers}[/COLOR][/B] [COLOR gray]| Surse găsite:[/COLOR] [B][COLOR FF00FA9A]{len(all_streams)}[/COLOR][/B]"
                    )
                    
                    # LOGICA PENTRU AF3 (Versiunea scurtă pe un rând)
                    active_prov = pending_names[0] if pending_names else "Finalizare..."
                    msg_af3 = f"Scănăm: [B][COLOR FFFF69B4]{active_prov}[/COLOR][/B] | Surse găsite: [B]{len(all_streams)}[/B]"
                    
                    # Trimitem ambele mesaje la pachet
                    status_data = {
                        'estuary': msg_estuary,
                        'af3': msg_af3
                    }
                    
                    keep_going = progress_callback(percent, status_data)
                    if keep_going is False:
                        was_canceled = True
                        break
                # --------------------------------------------------------------
                
                # --- 2. PROCESARE REZULTATE TERMINATE ---
                newly_done = done - finished_futures
                for future in newly_done:
                    finished_futures.add(future)
                    try:
                        pid, pname, result, success = future.result()
                        
                        if not success:
                            failed_providers.append(pid)
                            log(f"[SCRAPER] ✗ {pname}: eșuat sau fără rezultate")
                            continue
                        
                        if result:
                            items_to_add = []
                            if isinstance(result, dict):
                                items_to_add = [result]
                            elif isinstance(result, list):
                                items_to_add = result
                            
                            added_count = 0
                            for item in items_to_add:
                                if not isinstance(item, dict): continue
                                url = item.get('url', '')
                                if not url or not isinstance(url, str): continue
                                
                                clean_url = url.split('|')[0]
                                if filter_duplicates:
                                    if clean_url in seen_urls: continue
                                    seen_urls.add(clean_url)
                                
                                item.setdefault('name', pname)
                                item.setdefault('quality', 'SD')
                                item.setdefault('title', '')
                                
                                orig_info = item.get('info')
                                if not isinstance(orig_info, dict):
                                    item['info'] = {'original_info_str': str(orig_info) if orig_info else ''}
                                    
                                item['provider_id'] = pid
                                all_streams.append(item)
                                added_count += 1
                            
                            if added_count > 0:
                                log(f"[SCRAPER] ✓ {pname}: {added_count} surse adăugate")
                            else:
                                failed_providers.append(pid)

                    except Exception as exc:
                        log(f"[SCRAPER] Thread exception: {exc}")
                        try:
                            failed_pid = future_to_provider[future][0]
                            if failed_pid not in failed_providers:
                                failed_providers.append(failed_pid)
                        except: pass

        except Exception as e:
            log(f"[SCRAPER] Fatal error in execution loop: {e}")

        # La final, dacă au rămas unii blocați după Timeout, îi marcăm ca eșuați
        for future in futures_list:
            if not future.done():
                pid = future_to_provider[future][0]
                pname = future_to_provider[future][1]
                if pid not in failed_providers:
                    failed_providers.append(pid)
                    log(f"[SCRAPER] ✗ {pname}: Timeout!")
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            executor.shutdown(wait=False)

    log(f"[SCRAPER] Finalizat: {len(all_streams)} surse, {len(failed_providers)} provideri eșuați")
    return all_streams, failed_providers, was_canceled