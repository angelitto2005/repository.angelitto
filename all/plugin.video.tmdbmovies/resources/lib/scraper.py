import requests
import xbmc
import xbmcvfs
import re
import json
import base64
import hashlib
import time
import random
import datetime
import threading
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
def build_stream_url(url, referer=None, origin=None, user_agent=None):
    if '|' in url:
        return url

    headers = {
        'User-Agent': user_agent if user_agent else get_random_ua(),
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
    Returns quality statistics for UI display.
    Useful for showing "4K: 5 | 1080p: 12 | 720p: 8 | SD: 3"
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
        log(f"[VIX-CONVERT] Error: {e}")
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

        # log(f"[VIXSRC] Interogare: {url}")
        
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
                # Remove type=video param (server returns no audio with it)
                from urllib.parse import urlparse as _up, urlencode as _ue, urlunparse as _uup, parse_qsl as _pqs
                _pu = _up(final_url)
                _pq = dict(_pqs(_pu.query))
                _pq.pop('type', None)
                _pl = list(_pu); _pl[4] = _ue(_pq)
                final_url = _uup(_pl)
                final_stream_url = f"{final_url}|Referer={url}&Origin={base_url}&User-Agent={headers['User-Agent']}"
        
        if not final_stream_url:
            raw_url = _extract_video_from_page_vixsrc(session, url, f'{base_url}/')
            if raw_url:
                final_stream_url = f"{raw_url}|Referer={url}&Origin={base_url}&User-Agent={headers['User-Agent']}"
                
        if final_stream_url:
            # Use master playlist URL directly (variant sub-playlists lose audio group)
            # Detect best quality from master for display
            custom_headers = {'Referer': url, 'User-Agent': headers['User-Agent']}
            variants = _parse_m3u8_variants(final_url, custom_headers=custom_headers)
            best_qual = '1080p'
            if variants:
                best_q = max(variants, key=lambda x: int(x.get('bandwidth', 0) or 0))
                best_res = best_q.get('resolution', '1080p')
                best_qual = _get_quality_from_res(best_res)
            
            result = {
                'name': f'VixSrc | {best_qual}',
                'url': final_stream_url,
                'title': display_name,
                'quality': best_qual,
                'info': '',
                'provider_id': 'vixsrc'
            }
            log(f"[VIXSRC] ✓ Stream (master playlist): {final_stream_url[:50]}...")
            return [result]
            
        return None
        
    except Exception as e:
        log(f"[VIXSRC] Error: {e}")
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

            # log(f"[SOOTI] Trying mirror: {base_sooti_url[:30]}...")

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
                                'size': size,  # Separate field for size
                                'source_provider': source_provider,  # UHDMovies, MoviesDrive, etc
                                'info': '',
                                'provider_id': 'sooti'
                            }
                            
                            found_streams.append(stream_obj)
                        
                        log(f"[SOOTI] ✓ Success! {len(found_streams)} surse găsite.")
                        return found_streams
                        
            except Exception as e:
                log(f"[SOOTI] Mirror failed ({e}). Moving to next...")
                continue

    except Exception as e:
        log(f"[SOOTI] Critical error: {e}", xbmc.LOGERROR)
    
    return None

# =============================================================================
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
        
        # log(f"[VSEMBED-DEBUG] 1. Start. URL: {play_url}")
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
                
        urls = []
        
        # Înceracă server hashes (encrypted, needs working API)
        import base64 as _b64
        server_hashes = re.findall(r'data-hash="([^"]+)"', html)
        for h in server_hashes:
            try:
                # data-hash e base64url(hex:base64_data), decodăm primul layer
                _raw = h.replace('-', '+').replace('_', '/')
                _pad = 4 - len(_raw) % 4
                if _pad != 4: _raw += '=' * _pad
                _inner = _b64.b64decode(_raw).decode('utf-8', errors='replace')
                if ':' in _inner:
                    _hex, _b64part = _inner.split(':', 1)
                    dec_res = s.post('https://enc-dec.app/api/dec-cloudnestra', json={'text': _b64part, 'div_id': _hex}, timeout=10)
                    if dec_res.status_code == 200:
                        _results = dec_res.json().get('result', [])
                        if _results:
                            # log(f"[VSEMBED-DEBUG] data-hash decrypted {len(_results)} URL-uri")
                            urls.extend(_results)
                    else:
                        pass
            except:
                pass
        
        # Iframe chain (rcp → prorcp) – currently blocked by Cloudflare Turnstile
        if not urls:
            current_url = target_url
            current_referer = f"{base_url}/"
            final_html = ""
            cloud_domain = ""
            
            for depth in range(6):
                try:
                    r = s.get(current_url, headers={'Referer': current_referer}, timeout=10, verify=False)
                    current_html = r.text
                    from urllib.parse import urlparse
                    cloud_domain = f"https://{urlparse(current_url).netloc}"
                except:
                    break
                    
                prorcp_match = re.search(r'["\'](\\?/prorcp\\?/[^"\']+)["\']', current_html)
                hidden_div_match = re.search(r'<div[^>]*id=["\']([^"\']+)["\'][^>]*style=["\']display\s*:\s*none;?["\'][^>]*>([a-zA-Z0-9:\/.,{}\-_=+ ]+)<\/div>', current_html, re.IGNORECASE)
                direct_m3u8 = re.search(r'file\s*:\s*["\'](https?://[^\s"\'<>)]+\.m3u8[^\s"\'<>)]*)["\']', current_html)
                
                if prorcp_match or hidden_div_match or direct_m3u8:
                    final_html = current_html
                    break
                    
                iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', current_html, re.IGNORECASE)
                if iframe_match:
                    next_url = iframe_match.group(1)
                    if next_url.startswith('//'): next_url = 'https:' + next_url
                    elif next_url.startswith('/'): next_url = cloud_domain + next_url
                    current_referer = current_url
                    current_url = next_url
                else:
                    break
            
            if direct_m3u8:
                urls.append(direct_m3u8.group(1))
            elif hidden_div_match:
                try:
                    dec_res = s.post('https://enc-dec.app/api/dec-cloudnestra', json={'text': hidden_div_match.group(2), 'div_id': hidden_div_match.group(1)}, timeout=10)
                    if dec_res.status_code == 200:
                        urls = dec_res.json().get('result', [])
                except:
                    pass
            elif prorcp_match:
                prorcp_url = cloud_domain + prorcp_match.group(1).replace('\\/', '/')
                try:
                    r_final = s.get(prorcp_url, headers={'Referer': current_url}, timeout=10, verify=False)
                    final_html = r_final.text
                except:
                    pass
                if final_html:
                    hidden_div = re.search(r'<div[^>]*id=["\']([^"\']+)["\'][^>]*style=["\']display\s*:\s*none;?["\'][^>]*>([a-zA-Z0-9:\/.,{}\-_=+ ]+)<\/div>', final_html, re.IGNORECASE)
                    if hidden_div:
                        try:
                            dec_res = s.post('https://enc-dec.app/api/dec-cloudnestra', json={'text': hidden_div.group(2), 'div_id': hidden_div.group(1)}, timeout=10)
                            if dec_res.status_code == 200:
                                urls = dec_res.json().get('result', [])
                        except:
                            pass
                    if not urls:
                        m3u8s = list(dict.fromkeys(re.findall(r'https?://[^\s"\'<>)]+\.m3u8[^\s"\'<>)]*', final_html)))
                        for u in m3u8s:
                            if '{v' not in u: urls.append(u)
                            
        # Thrax fallback
        _thrax_quality = {}
        tmdb_for_vs = _get_tmdb_id_internal(imdb_id)
        if not urls:
            try:
                if tmdb_for_vs:
                    if content_type == 'tv' and season and episode:
                        _vs_srv_url = f'https://primesrc.me/api/v1/s?type=tv&tmdb={tmdb_for_vs}&season={int(season)}&episode={int(episode)}'
                        # log(f"[VSEMBED-DEBUG] Thrax fallback (tv): {_vs_srv_url}")
                    else:
                        _vs_srv_url = f'https://primesrc.me/api/v1/s?type=movie&tmdb={tmdb_for_vs}'
                        # log(f"[VSEMBED-DEBUG] Thrax fallback (movie): {_vs_srv_url}")
                    _vs_r = s.get(_vs_srv_url, headers={'User-Agent': user_agent}, timeout=15)
                    if _vs_r.ok:
                        for _srv in _vs_r.json().get('servers', []):
                            _key = _srv.get('key', '')
                            _name = _srv.get('name') or ''
                            _quality = _srv.get('quality') or '1080p'
                            _size = _srv.get('file_size') or ''
                            _audio_type = _srv.get('audio_type') or ''
                            if _key:
                                _link = f'https://primesrc.me/api/v1/l?key={_key}'
                                _meta = {
                                    'quality': _quality,
                                    'name': _name,
                                    'size': _size,
                                    'audio_type': _audio_type,
                                }
                                urls.append(_link)
                                _thrax_quality[_link] = _meta
                                # log(f"[VSEMBED-DEBUG] Thrax server: {_name} | {_quality}")
            except Exception as e:
                pass
        
        # log(f"[VSEMBED-DEBUG] FINAL: Extracted {len(urls)} valid master links.")
        
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
                
                # Dacă URL-ul vine de la Thrax cu calitate cunoscută, sărim parsarea m3u8
                thrax_meta = _thrax_quality.get(master_url, '')
                if thrax_meta:
                    # Movie/TV Thrax: metadata e dict cu nume server, calitate, size, audio_type
                    if isinstance(thrax_meta, dict):
                        _name = thrax_meta.get('name', '')
                        _q = thrax_meta.get('quality') or '1080p'
                        _size = thrax_meta.get('size') or ''
                        _audio = thrax_meta.get('audio_type') or ''
                        _display_name = f"VSEmbed | {_name}"
                        if _audio:
                            _display_name += f" ({_audio})"
                        _q_norm = _q
                        if _q.lower() in ('4k', '2160p', '2160'): _q_norm = '4K'
                        elif _q.lower() in ('1080p', '1080', 'fhd'): _q_norm = '1080p'
                        elif _q.lower() in ('720p', '720', 'hd'): _q_norm = '720p'
                        elif _q.lower() in ('480p', '480', 'sd'): _q_norm = 'SD'
                        if content_type == 'tv' and season and episode:
                            _tmdb_id_str = f"{tmdb_for_vs}:tv:{season}:{episode}"
                        else:
                            _tmdb_id_str = f"{tmdb_for_vs}:movie"
                        streams.append({
                            'name': _display_name,
                            'url': master_url,
                            'quality': _q_norm,
                            'title': display_title,
                            'size': _size,
                            'info': f"PrimeSrc | {_name}",
                            'provider_id': 'primesrcme',
                            'tmdb_id': _tmdb_id_str,
                        })
                        continue
                    # TV Thrax: metadata e string (quality)
                    q = thrax_meta
                    if q.lower() in ('4k', '2160p', '2160'): quality = '4K'
                    elif q.lower() in ('1080p', '1080', 'fhd'): quality = '1080p'
                    elif q.lower() in ('720p', '720', 'hd'): quality = '720p'
                    elif q.lower() in ('480p', '480', 'sd'): quality = 'SD'
                    else: quality = '1080p'
                    streams.append({
                        'name': f"VSEmbed [{lang}] | {q}",
                        'url': build_stream_url(master_url, referer="https://cloudnestra.com/"),
                        'quality': quality,
                        'title': display_title,
                        'size': '',
                        'info': f"Thrax | {q}",
                        'provider_id': 'vsembed'
                    })
                    continue
                
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
        log(f"[VSEMBED-DEBUG] CRITICAL PYTHON ERROR: {e}\n{traceback.format_exc()}")
        
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
            # log(f"[VIDEASY] Skipping {srv['name']} (movies only)")
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
            # log(f"[VIDEASY] Querying {srv['name']} ({srv['path']})...")
            
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

            # log(f"[VIDEASY] {srv['name']} returned {len(sources)} sources")

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
# SCRAPER CINEBY (Videasy network extended servers)
# =============================================================================
def scrape_cineby(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_cineby') == 'false':
        log(f"[CINEBY] Disabled in settings")
        return None

    # log(f"[CINEBY] scrape_cineby(imdb={imdb_id}, type={content_type}, s={season}, e={episode}, title={title_query}, year={year_query})")

    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id:
        log(f"[CINEBY] No tmdb_id from {imdb_id}")
        return None

    s = get_shared_session()
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    backend = 'http://145.241.158.129:3113'
    videasy_api = 'https://api.videasy.net'

    media_type = 'movie' if content_type == 'movie' else 'tv'
    season_id = str(int(season)) if season else '1'
    episode_id = str(int(episode)) if episode else '1'

    # log(f"[CINEBY] tmdb_id={tmdb_id}, media_type={media_type}, season_id={season_id}, episode_id={episode_id}")

    display_title = title_query or "Cineby"
    if year_query and content_type == 'movie':
        display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode:
        display_title += f" S{season_id}E{episode_id}"

    servers = [
        {'name': 'Oxygen', 'endpoint': 'myflixerzupcloud/sources-with-title'},
        {'name': 'Hydrogen', 'endpoint': 'cdn/sources-with-title'},
        {'name': 'Lithium', 'endpoint': 'moviebox/sources-with-title'},
        {'name': 'Helium', 'endpoint': '1movies/sources-with-title'},
        {'name': 'Titanium', 'endpoint': 'primesrcme/sources-with-title'},
    ]

    def _fetch_encrypted(endpoint):
        import time as _tmod
        params = {
            'title': title_query,
            'mediaType': media_type,
            'year': str(year_query or ''),
            'episodeId': episode_id,
            'seasonId': season_id,
            'tmdbId': tmdb_id,
            'imdbId': str(imdb_id) if str(imdb_id).startswith('tt') else '',
            '_t': str(int(_tmod.time() * 1000)),
        }
        hdrs = {
            'User-Agent': UA,
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://www.vidking.net',
            'Referer': 'https://www.vidking.net/',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
        }
        url = f'{videasy_api}/{endpoint}'
        # log(f"[CINEBY] GET {url}")
        try:
            r = s.get(url, params=params, headers=hdrs, timeout=15, verify=False)
            # log(f"[CINEBY] Response {r.status_code} ({len(r.text)}b): {r.text[:200]}")
            if r.status_code != 200 or len(r.text) < 50 or r.text.startswith('<!'):
                return None
            return r.text
        except Exception as e:
            log(f"[CINEBY] Request error: {e}")
            return None

    def _decrypt_items(encrypted_list, cache_key):
        try:
            url = f'{backend}/decrypt-batch'
            # log(f"[CINEBY] Decrypt via backend: {url}")
            r = s.post(url,
                       json={'items': encrypted_list, 'tmdbId': str(tmdb_id), 'cacheKey': cache_key},
                       headers={'Content-Type': 'application/json', 'User-Agent': UA},
                       timeout=10, verify=False)
            # log(f"[CINEBY] Backend decrypt response: {r.status_code} ({len(r.text)}b)")
            if r.status_code == 200:
                data = r.json()
                # log(f"[CINEBY] Backend decrypt data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                return data
        except Exception as e:
            log(f"[CINEBY] Backend decrypt error: {e}")
        try:
            text = encrypted_list[0] if encrypted_list else ''
            # log(f"[CINEBY] Decrypt via enc-dec.app ({len(text)}b)")
            r = s.post('https://enc-dec.app/api/dec-videasy',
                       json={'text': text, 'id': str(tmdb_id)},
                       timeout=15)
            # log(f"[CINEBY] enc-dec.app response: {r.status_code} ({len(r.text)}b)")
            if r.status_code == 200:
                data = r.json()
                # log(f"[CINEBY] enc-dec.app data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                if isinstance(data, dict):
                    result_obj = data.get('result', data)
                    if isinstance(result_obj, dict) and result_obj.get('sources'):
                        return result_obj
                    if data.get('sources'):
                        return data
                    # log(f"[CINEBY] enc-dec.app missing sources field, has: {list(data.keys())}")
        except Exception as e:
            log(f"[CINEBY] enc-dec.app error: {e}")
        return None

    def _format_streams(decrypted, server_name=''):
        if not isinstance(decrypted, dict):
            log(f"[CINEBY] _format_streams: decrypted is {type(decrypted)}, not dict")
            return []
        sources = decrypted.get('sources', [])
        if not isinstance(sources, list):
            log(f"[CINEBY] _format_streams: sources is {type(sources)}, not list")
            return []
        # log(f"[CINEBY] _format_streams: {len(sources)} sources")
        out = []
        for src in sources:
            if not isinstance(src, dict) or not src.get('url'):
                continue
            s_url = src['url']
            q = src.get('quality', 'auto')
            q_str = q.lower()
            if '2160' in q_str or '4k' in q_str:
                quality = '4K'
            elif '1080' in q_str:
                quality = '1080p'
            elif '720' in q_str:
                quality = '720p'
            elif '480' in q_str:
                quality = 'SD'
            else:
                quality = q or 'Auto'
            srv_name = src.get('server', server_name) or server_name
            label = f"Cineby {srv_name}" if srv_name else 'Cineby'
            out.append({
                'name': label,
                'url': build_stream_url(s_url, referer='https://www.vidking.net/',
                                        origin='https://www.vidking.net'),
                'quality': quality,
                'title': f"{display_title} [{srv_name}]" if srv_name else display_title,
                'size': '',
                'info': f"HLS | {q}",
                'provider_id': 'cineby',
            })
        return out

    # log(f"[CINEBY] Searching {title_query} ({media_type})")
    streams = []

    # Step 1: Try real backend directly
    try:
        real_url = f'{backend}/real-streams?title={title_query}&mediaType={media_type}&year={year_query or ""}&episodeId={episode_id}&seasonId={season_id}&tmdbId={tmdb_id}&imdbId={imdb_id if str(imdb_id).startswith("tt") else ""}'
        # log(f"[CINEBY] Step1: real backend {real_url}")
        r = s.get(real_url, headers={'User-Agent': UA}, timeout=8, verify=False)
        # log(f"[CINEBY] Step1: {r.status_code} ({len(r.text)}b)")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get('sources'):
                # log(f"[CINEBY] Step1: real backend returned {len(data['sources'])} sources")
                streams = _format_streams(data)
                if streams:
                    log(f"[CINEBY] Total: {len(streams)} streams")
                    return streams
            else:
                pass
    except Exception as e:
        log(f"[CINEBY] Step1 error: {e}")

    # Step 2: Try encrypted fetch from primary server (Hydrogen = cdn/sources-with-title)
    primary = servers[1]
    # log(f"[CINEBY] Step2: primary server {primary['name']} ({primary['endpoint']})")
    encrypted = _fetch_encrypted(primary['endpoint'])
    if encrypted:
        cache_key = f"{media_type}:{tmdb_id}:{season_id}:{episode_id}:{primary['name']}"
        decrypted = _decrypt_items([{'server': primary['name'], 'encrypted': encrypted}], cache_key)
        if decrypted:
            streams = _format_streams(decrypted, primary['name'])
            if streams:
                log(f"[CINEBY] Step2: {len(streams)} streams from primary")
                return streams
            else:
                pass
        else:
            log(f"[CINEBY] Step2: decrypt failed")
    else:
        log(f"[CINEBY] Step2: no encrypted data from primary")

    # Step 3: Try remaining servers (all except Hydrogen)
    # log(f"[CINEBY] Step3: trying backup servers")
    backup_results = []
    for srv in [s for s in servers if s['name'] != 'Hydrogen']:
        encrypted = _fetch_encrypted(srv['endpoint'])
        if encrypted:
            backup_results.append({'server': srv['name'], 'encrypted': encrypted})
    # log(f"[CINEBY] Step3: {len(backup_results)} backup servers returned data")
    if backup_results:
        cache_key = f"{media_type}:{tmdb_id}:{season_id}:{episode_id}:backups"
        decrypted = _decrypt_items(backup_results, cache_key)
        if decrypted:
            streams = _format_streams(decrypted, 'backup')
            if streams:
                log(f"[CINEBY] Step3: {len(streams)} streams from backups")
                return streams

    # Step 4: Try vidlink fallback
    try:
        vl_url = f'{backend}/vidlink-streams?tmdbId={tmdb_id}&mediaType={media_type}&season={season_id}&episode={episode_id}'
        # log(f"[CINEBY] Step4: vidlink fallback {vl_url}")
        r = s.get(vl_url, headers={'User-Agent': UA}, timeout=8, verify=False)
        # log(f"[CINEBY] Step4: {r.status_code} ({len(r.text)}b) {r.text[:200]}")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get('sources'):
                streams = _format_streams(data, 'Vidlink')
                log(f"[CINEBY] Step4: {len(streams)} streams from vidlink")
    except Exception as e:
        log(f"[CINEBY] Step4 error: {e}")

    log(f"[CINEBY] Final: {len(streams)} streams")
    return streams if streams else None


# =============================================================================
# SCRAPER PEACHIFY was removed — replaced by CineFreak
# SCRAPER FIBWATCH was removed — replaced by CineFreak
# =============================================================================
# =============================================================================
# SCRAPER NETMIRROR (Fixed API Headers)
# =============================================================================
def scrape_netmirror(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_netmirror') == 'false': return None
    if not title_query: return None

    s = get_shared_session()

    api_base = "https://tv.imgcdn.kim/newtv"

    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rv:136.0) Gecko/20100101 Firefox/136.0 /OS.GatuNewTV v1.0"

    platforms = [
        {'name': 'Netflix', 'ott': 'nf'},
        {'name': 'PrimeVideo', 'ott': 'pv'},
        {'name': 'Hotstar', 'ott': 'hs'}
    ]

    def fetch_json(url, ott):
        hdrs = {
            'ott': ott,
            'User-Agent': UA,
            'x-requested-with': 'NetmirrorNewTV v1.0'
        }
        try:
            resp = s.get(url, headers=hdrs, timeout=10, verify=False)
            if resp.status_code != 200: return None
            return resp.json()
        except:
            return None

    try:
        streams = []
        for plat in platforms:
            ott = plat['ott']
            search_url = f"{api_base}/search.php?s={quote(title_query)}"
            search_data = fetch_json(search_url, ott)
            if not search_data: continue

            results = search_data.get('searchResult', [])
            if not results: continue

            best = None
            tq_lower = title_query.strip().lower()
            for r in results:
                rt = r.get('t', '').strip().lower()
                if rt == tq_lower:
                    best = r
                    break
            if not best:
                for r in results:
                    rt = r.get('t', '').strip().lower()
                    if tq_lower in rt or rt in tq_lower:
                        best = r
                        break
            if not best:
                best = results[0]

            target_id = best.get('id')
            if not target_id: continue

            if content_type == 'tv':
                post_data = fetch_json(f"{api_base}/post.php?id={target_id}", ott)
                if not post_data: continue

                seasons = post_data.get('season', [])
                season_id = None
                for se in seasons:
                    s_str = str(se.get('s', ''))
                    if f"Season {int(season)}" in s_str or s_str == str(season):
                        season_id = se.get('id')
                        break

                if not season_id:
                    for se in seasons:
                        s_str = str(se.get('s', ''))
                        if str(season) in s_str:
                            season_id = se.get('id')
                            break
                if not season_id:
                    if seasons:
                        season_id = seasons[0].get('id')

                if not season_id: continue

                ep_id = None
                page = 1
                while not ep_id and page < 10:
                    ep_data = fetch_json(f"{api_base}/episodes.php?id={season_id}&p={page}", ott)
                    if not ep_data: break
                    episodes = ep_data.get('episodes', [])
                    for ep in episodes:
                        if str(ep.get('ep', '')).strip() == str(episode).strip():
                            ep_id = ep.get('id')
                            break
                    if ep_data.get('nextPageShow') != 1:
                        break
                    page += 1

                if not ep_id: continue
                target_id = ep_id

            player_data = fetch_json(f"{api_base}/player.php?id={target_id}", ott)
            if not player_data: continue

            video_link = player_data.get('video_link', '')
            referer = player_data.get('referer', 'https://net52.cc')
            if not video_link: continue

            if video_link.endswith('.m3u8') or '.m3u8' in video_link:
                m3u8_url = video_link
                resolved_variants = []
                try:
                    resp = s.get(m3u8_url, headers={'User-Agent': UA}, timeout=10, verify=False)
                    if resp.status_code == 200:
                        content = resp.text
                        lines = content.splitlines()
                        has_variants = any('#EXT-X-STREAM-INF' in l for l in lines)
                        if has_variants:
                            for i, line in enumerate(lines):
                                if '#EXT-X-STREAM-INF' in line:
                                    resolution = 'UNKNOWN'
                                    if 'RESOLUTION=' in line:
                                        try:
                                            resolution = line.split('RESOLUTION=')[1].split(',')[0]
                                        except: pass
                                    q = 'SD'
                                    if '2160' in resolution or '3840' in resolution: q = '4K'
                                    elif '1080' in resolution or '1920' in resolution: q = '1080p'
                                    elif '720' in resolution or '1280' in resolution: q = '720p'
                                    if q not in resolved_variants:
                                        resolved_variants.append(q)
                        else:
                            resolved_variants.append('Auto')
                except:
                    resolved_variants.append('Auto')

                if not resolved_variants:
                    resolved_variants.append('Auto')

                for q in resolved_variants:
                    streams.append({
                        'name': f"NetMirror | {plat['name']}",
                        'url': build_stream_url(video_link, referer=referer, user_agent=UA),
                        'quality': q,
                        'title': display_title,
                        'size': '',
                        'info': 'Direct HLS',
                        'provider_id': 'netmirror'
                    })
            else:
                q = 'SD'
                if '_2160' in video_link or '2160' in video_link: q = '4K'
                elif '_1080' in video_link or '1080' in video_link: q = '1080p'
                elif '_720' in video_link or '720' in video_link: q = '720p'
                elif '_480' in video_link or '480' in video_link: q = '480p'
                streams.append({
                    'name': f"NetMirror | {plat['name']}",
                    'url': build_stream_url(video_link, referer=referer, user_agent=UA),
                    'quality': q,
                    'title': display_title,
                    'size': '',
                    'info': 'Direct',
                    'provider_id': 'netmirror'
                })

            if streams:
                break

        return streams if streams else None
    except Exception as e:
        log(f"[NETMIRROR] Error: {e}")
        return None


# =============================================================================
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
                # log(f"[MOVIEBOX] Resolving redirect for: {proxy_url}")
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
                        # log(f"[HDHUB-DOM] API Successs: {final_url}")
                        return final_url
            except:
                continue

    except Exception as e:
        pass

    # 2. Fallback HARDCODED — new1.hdhub4u.cl e domeniul curent care funcționează
    # log("[HDHUB-DOM] Using fallback domain.")
    return "https://new2.hdhub4u.cl" 


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

    
    # === Detectare Multi-Rezoluție: alege cea mai înaltă ===
    clean_t = t.replace('ds4k', '').replace('4kds', '').replace('hdr4k', '').replace('sdr4k', '').replace('4khdhub', '')
    found_res = [r for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in t]
    if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_t) and '2160p' not in t: 
        found_res.append('4k_text')
    if len(found_res) >= 2:
        if '2160p' in found_res: return '4K'
        if '1080p' in found_res: return '1080p'
        if '720p' in found_res: return '720p'
        if '480p' in found_res: return '480p'
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
    # METODA 2 (FALLBACK): Caută oriunde în text — ordine descrescătoare
    # =================================================================
    
    if '2160p' in t:
        return '4K'
    
    if '1080p' in t:
        return '1080p'
    
    if '720p' in t:
        return '720p'
    
    if '480p' in t:
        # log(f"[QUALITY] Fallback: found 480p in text")
        return '480p'
    
    if '360p' in t:
        # log(f"[QUALITY] Fallback: found 360p in text")
        return '360p'
    
    # 4K DOAR dacă nu e precedat de literă (evită DS4K, HDR4K, SDR4K)
    # Pattern: spațiu/punct/început + 4k + non-literă
    if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_t):
        return '4K'
    
    # UHD = 4K
    if 'uhd' in t or 'ultrahd' in t:
        # log(f"[QUALITY] Fallback: found UHD -> 4K")r
        return '4K'
    
    # log(f"[QUALITY] No quality found in: {t[:50]}")
    return None


def _is_web_source(text):
    """
    Filtrează dacă textul conține: 
    - webrip, bdrip, hdrip, dvdrip
    - web-dl, web dl, web.dl (including with rip at the end)
    - bluray.x264, hdtv.x264, hdtv.xvid, web.x264, web.h264
    
    Completely ignores single words (e.g. just 'bluray', just 'x264', just 'web').
    """
    if not text:
        return False
    
    # Am adăugat noile combinații folosind \. pentru a reprezenta exact punctul.
    pattern = (
        r'webrip|bdrip|hdrip|dvdrip|web[- .]dl(rip)?|'
        r'bluray\.x264|hdtv\.x264|hdtv\.xvid|web\.x264|web\.h264'
    )
    
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
    elif 'bzzhr' in url_lower:
        return 'BuzzShort'
    elif 'buzzserver' in url_lower:
        return 'BuzzServer'
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
        'googlevideo.com',       # <--- ADĂUGAT
        'buzzheavie',            # BuzzHeavie direct
        'buzzserver',            # BuzzServer redirect
        'polgen.buzz',           # Polgen Buzz
        'pixel.hubcdn',          # HubPixel 10Gbps
        'gpdl',                  # GPDL direct
        'yummy.monster',         # FSL Server
        'gdboka',                # GDBoka
        'fsl-buckets',           # FSL buckets
        'fsl-lover',             # FSL lover
        'trashbytes.net',        # TrashBytes
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
                # log(f"[RESOLVE-URL] ✓ HEAD: {url[:40]}... -> {final_url[:60]}...")
                return final_url
        except:
            pass
        
        # Fallback: GET request
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True, stream=True)
            final_url = r.url
            r.close()
            
            if r.status_code == 200:
                # log(f"[RESOLVE-URL] ✓ GET: {url[:40]}... -> {final_url[:60]}...")
                return final_url
        except:
            pass
        
        # log(f"[RESOLVE-URL] ✗ Failed: {url[:50]}...")
        return None
        
    except Exception as e:
        # log(f"[RESOLVE-URL] ✗ Error: {e}")
        return None


# =============================================================================
# REZOLVARE BUZZSERVER (redirect cu ?download=1)
# =============================================================================

def _resolve_buzzserver_url(url, timeout=10):
    """
    Rezolvă URL-urile BuzzServer/BuzzHeavie făcând fetch cu ?download=1
    și urmărind redirect-ul până la URL-ul video final.
    Returnează URL-ul final sau None dacă eșuează.
    """
    if not url:
        return None
    
    try:
        # log(f"[BUZZSERVER] Resolving: {url[:50]}...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': url,
            'Accept': '*/*',
        }
        
        # La fel ca în Nuvio JS: fetch cu ?download=1 și urmărește redirect-ul
        download_url = url + ('&' if '?' in url else '?') + 'download=1'
        r = requests.get(download_url, headers=headers, timeout=timeout, verify=False, allow_redirects=True, stream=True)
        final_url = r.url
        r.close()
        
        if final_url and final_url != url and _is_direct_video_url(final_url):
            # log(f"[BUZZSERVER] ✓ Resolved: {url[:40]}... -> {final_url[:60]}...")
            return final_url
        
        # Fallback: încearcă direct URL-ul fără ?download=1
        r = requests.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True, stream=True)
        final_url = r.url
        r.close()
        
        if final_url and final_url != url:
            # log(f"[BUZZSERVER] ✓ Resolved (direct): {url[:40]}... -> {final_url[:60]}...")
            return final_url
            
        # log(f"[BUZZSERVER] ✗ No redirect for: {url[:50]}...")
        return url  # return original if can't resolve, might still work
        
    except Exception as e:
        # log(f"[BUZZSERVER] ✗ Error: {e}")
        return url  # return original on error


# =============================================================================
# PROCESOR GDFLIX PAGES
# =============================================================================

def _process_gdflix_page(url, quality_label, title_label, branch_label):
    """
    Procesează paginile GDFlix și extrage link-uri directe.
    V2 - Cu server names corecte.
    """
    streams = []
    # log(f"[GDFLIX-PAGE] Processing: {url}")
    
    try:
        headers = get_headers()
        r = requests.get(url, headers=headers, timeout=12, verify=False, allow_redirects=True)
        
        if r.status_code != 200:
            log(f"[GDFLIX-PAGE] Error: Status {r.status_code}")
            return []
        
        html = r.text
        final_url = r.url
        # log(f"[GDFLIX-PAGE] Final URL: {final_url}")
        
        # === NOU: Extragere Nume Real Fișier ===
        name_match = re.search(r'Name\s*:\s*([^<]+)', html, re.I)
        filename = name_match.group(1).strip() if name_match else title_label
        # log(f"[DEBUG-MKV] GDFlix filename match: {filename}")
        # ======================================
        
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
            # log(f"[GDFLIX-PAGE] Size P1 (list-item no-space): {page_size}")
        
        # Pattern 2: >Size : 872.27MB (FĂRĂ spațiu, general)
        if not page_size:
            size_match = re.search(r'>Size\s*:\s*([\d.,]+)(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                # log(f"[GDFLIX-PAGE] Size P2 (no-space): {page_size}")
        
        # Pattern 3: >Size : 9.24 GB (CU spațiu)
        if not page_size:
            size_match = re.search(r'>Size\s*:\s*([\d.,]+)\s+(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                # log(f"[GDFLIX-PAGE] Size P3 (with-space): {page_size}")
        
        # Pattern 4: "Size : 872.27MB" oriunde în text
        if not page_size:
            size_match = re.search(r'Size\s*:\s*([\d.,]+)\s*(GB|MB|TB)', html, re.IGNORECASE)
            if size_match:
                page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                # log(f"[GDFLIX-PAGE] Size P4 (anywhere): {page_size}")
        
        # Pattern 5: Căutare brută pentru (număr)(GB|MB)
        if not page_size:
            list_items = re.findall(r'<li[^>]*list-group-item[^>]*>([^<]+)</li>', html, re.IGNORECASE)
            for item in list_items:
                if 'size' in item.lower():
                    size_match = re.search(r'([\d.,]+)\s*(GB|MB|TB)', item, re.IGNORECASE)
                    if size_match:
                        page_size = f"{size_match.group(1)} {size_match.group(2).upper()}"
                        # log(f"[GDFLIX-PAGE] Size P5 (list-item extract): {page_size}")
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
        
        # 1. CLOUD DOWNLOAD R2 (pub-*.r2.dev)
        r2_pattern = r'href=["\']?(https://pub-[a-z0-9]+\.r2\.dev/[^"\'>\s]+)["\']?'
        r2_matches = re.findall(r2_pattern, html, re.IGNORECASE)
        
        for r2_url in r2_matches:
            if r2_url in seen_urls:
                continue
            if any(g in r2_url.lower() for g in google_patterns):
                continue
            seen_urls.add(r2_url)
            
            # Determinăm calitatea din filename pentru sortare
            actual_q = _extract_quality_from_string(filename) or quality_label

            streams.append({
                'name': filename,
                'url': build_stream_url(r2_url),
                'quality': actual_q,
                'title': filename,
                'size': page_size,
                'info': "GDFlix | R2"
            })
            log(f"[GDFLIX-PAGE] ✓ R2: {r2_url[:60]}...")
        
        # 2. INSTANT DL
        instant_matches = re.findall(r'href=["\']?(https://instant\.busycdn\.xyz/[^"\'>\s]+)["\']?', html, re.IGNORECASE)
        for instant_url in instant_matches:
            if instant_url in seen_urls:
                continue
            seen_urls.add(instant_url) # <--- FIX: Asigură-te că aici scrie instant_url
            
            # Determinăm calitatea din filename pentru sortare
            actual_q = _extract_quality_from_string(filename) or quality_label

            streams.append({
                'name': filename,
                'url': build_stream_url(instant_url),
                'quality': actual_q,
                'title': filename,
                'size': page_size,
                'info': "GDFlix | Instant"
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
                
                # Determinăm calitatea reală din numele fișierului pentru sortare
                actual_q = _extract_quality_from_string(filename) or quality_label

                streams.append({
                    'name': filename,
                    'url': build_stream_url(api_url),
                    'quality': actual_q,
                    'title': filename,
                    'size': page_size,
                    'info': "GDFlix | PixelDrain"
                })
                log(f"[GDFLIX-PAGE] ✓ PixelDrain: {api_url}")
        
        # Pattern pentru href (backup)
        pd_href = re.search(r'href=["\']https://pixeldrain\.dev/u/([a-zA-Z0-9]+)["\']', html, re.IGNORECASE)
        if pd_href:
            pd_id = pd_href.group(1)
            api_url = f"https://pixeldrain.dev/api/file/{pd_id}"
            if api_url not in seen_urls:
                seen_urls.add(api_url)
                
                # Determinăm calitatea reală din numele fișierului pentru sortare
                actual_q = _extract_quality_from_string(filename) or quality_label

                streams.append({
                    'name': filename,
                    'url': build_stream_url(api_url),
                    'quality': actual_q,
                    'title': filename,
                    'size': page_size,
                    'info': "GDFlix | PixelDrain"
                })
                log(f"[GDFLIX-PAGE] ✓ PixelDrain (href): {api_url}")
        
        # =========================================================
        # 4. EXTRACTOR GENERIC PENTRU ALTE TIPURI DE SERVER
        # =========================================================
        all_gd_links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
        generic_hosts = [
            'fsl-buckets', 'fsl-lover', 'fsl.gdboka', 'gdboka',
            'yummy.monster', 'polgen.buzz', 'workers.dev',
            'gpdl', 'hubcdn', 'aws-storage', 'awsdllaaa',
            'bbdownload.filesdl', 'busycdn.xyz', 'buzzserver', 'buzzheavie',
            'r2.cloudflarestorage.com',
        ]
        for gd_link in all_gd_links:
            if gd_link in seen_urls:
                continue
            gd_lower = gd_link.lower()
            if any(g in gd_lower for g in google_patterns):
                continue
            
            if any(h in gd_lower for h in generic_hosts):
                # BuzzServer/BuzzHeavie needs redirect resolution
                if 'buzzserver' in gd_lower or 'buzzheavie' in gd_lower:
                    resolved = _resolve_buzzserver_url(gd_link)
                    if resolved:
                        gd_link = resolved
                
                seen_urls.add(gd_link)
                actual_q = _extract_quality_from_string(filename) or quality_label
                server_name = _identify_host_from_url(gd_link)
                
                streams.append({
                    'name': filename,
                    'url': build_stream_url(gd_link),
                    'quality': actual_q,
                    'title': filename,
                    'size': page_size,
                    'info': f"GDFlix | {server_name}"
                })
                log(f"[GDFLIX-PAGE] ✓ {server_name}: {gd_link[:60]}...")
        
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
        '/tg/go',                  # HubCloud Telegram gateway
        '/dl.php',                 # HubCloud PHP download page
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
        '//ads.', '//ad.', 'adserver', 'adservice',
        'tracker.', 'tracking.', 'pixel.facebook', 'pixel.ads',
        'gtag/js', 'gtm.js', 'ga.js',
        'bit.ly', 'megaup.net', 'megaup'
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
        'googleusercontent.com', 'googlevideo.com',
        'buzzheavie',                 # BuzzHeavie direct
        'buzzserver',                 # BuzzServer (redirect handler)
        'trashbytes.net',             # TrashBytes
        'hubcdn.fans/file/',          # HubCDN file pages (redirect)
        'cdn.telesco.pe',            # Telegram CDN (direct video)
        'fafda.to',                  # bzzhr.co CDN (direct video)
        'ts.bzzhr.co',              # bzzhr.co streaming CDN
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
        'megaup.net', 'megaup',
        '/admin',
    ]
    
    if any(blocked in url_lower for blocked in blocked_domains):
        # log(f"[HDHUB-RES] Skipping blocked domain: {url[:60]}...")
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
        
        # Excepții: linkuri directe CDN care coincid cu indicatori wrapper
        if is_wrapper and 'gpdl.hubcloud.cx' in url_lower:
            is_wrapper = False
        
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
        'hubfiles', 'carnewz', 'bzzhr',
        'vcloud.zip',  # VCloud
        '/tg/go', '/dl.php',
    ]
    
    found_urls = []
    seen_urls = set()
    current_title = parent_title
    current_branch = branch_label

    if any(x in url_lower for x in wrapper_domains):
        try:
            # log(f"[HDHUB-RES] Step {depth} Processing: {url}")
            
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
            
            # === NOU: Extragere Filename din card-header HubCloud ===
            h_match = re.search(r"<div[^>]*class=['\"]card-header[^>]*>\s*(.*?)\s*</div>", content, re.I | re.S)
            if h_match:
                raw_fn = h_match.group(1).strip()
                if len(raw_fn) > 10: current_title = raw_fn
            # =======================================================
            
            # =================================================================
            # VCLOUD SPECIAL: Extrage URL din JavaScript "var url = '...'"
            # =================================================================
            if 'vcloud.zip' in url_lower or 'vcloud.zip' in final_url.lower():
                js_url_match = re.search(r"var\s+url\s*=\s*['\"]([^'\"]+)['\"]", content)
                if js_url_match:
                    extracted_url = js_url_match.group(1)
                    # log(f"[HDHUB-RES] ✓ VCloud extracted URL: {extracted_url[:60]}...")
                    
                    # Urmează acest URL (de obicei gamerxyt.com)
                    if extracted_url not in seen_urls:
                        seen_urls.add(extracted_url)
                        sub_results = _resolve_hdhub_redirect(extracted_url, depth + 1, current_title, current_branch)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
                else:
                    pass
            
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
                    # log(f"[HDHUB-RES] Bypassing Cookie: {c_n}={c_v}")
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
                    'bit.ly', 't.me', 'telegram', 'megaup.net', 'megaup'
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
                            # log(f"[HDHUB-RES] ✓ Found: PixelDrain -> {api_link[:60]}...")
                    return
                
                found_urls.append((host, link, current_title, q, current_branch))
                seen_urls.add(link)
                # log(f"[HDHUB-RES] ✓ Found: {host} -> {link[:60]}...")

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
            # log(f"[HDHUB-RES] Error on {url}: {e}")
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
    # log(f"[CLOUD] Processing URL: {url}")
    
    try:
        headers = get_headers()
        domain_netloc = urlparse(url).netloc
        headers['Referer'] = f'https://{domain_netloc}/'
        
        r = requests.get(url, headers=headers, timeout=12, verify=False)
        if r.status_code != 200:
            return []
            
        html = r.text
        
        # === NOU: Extragere Nume Real Fișier din title ===
        name_match = re.search(r"<div[^>]*class=['\"]title['\"][^>]*>(.*?)</div>", html, re.I | re.S)
        filename = name_match.group(1).strip() if name_match else title_label
        # log(f"[DEBUG-MKV] FilesDL filename match: {filename}")
        # ===============================================
        
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
            elif 'buzzserver' in link_lower or 'buzzheavie' in link_lower:
                resolved = _resolve_buzzserver_url(link_url)
                if resolved:
                    stream_url = resolved
                    server_name = 'BuzzServer'
            elif 'workers.dev' in link_lower:
                server_name = 'CFWorker'
            else:
                server_name = _identify_host_from_url(link_url)

            if stream_url and server_name:
                if needs_resolve:
                    pending_resolves.append((link_url, server_name, quality_label, filename, page_size))
                else:
                    # Determinăm calitatea reală din numele fișierului
                    actual_q = _extract_quality_from_string(filename) or quality_label

                    streams.append({
                        'name': filename,
                        'url': build_stream_url(stream_url, referer=f'https://{domain_netloc}/'),
                        'quality': actual_q,
                        'title': filename,
                        'size': page_size,
                        'info': f"MKV | {server_name}"
                    })

        if pending_resolves:
            def resolve_task(args):
                raw_url, srv_name, qual, title, size = args
                resolved_url = _resolve_intermediate_url(raw_url)
                if resolved_url:
                    # display = f"MKV | {srv_name}"
                    # if size: display += f" | {size}"
                    
                    if 'googleusercontent' in resolved_url.lower() or 'googlevideo' in resolved_url.lower() or 'pixel.hubcdn' in resolved_url.lower():
                        safe_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        final_url = f"{resolved_url}|User-Agent={safe_ua}&seekable=0"
                    else:
                        final_url = build_stream_url(resolved_url, referer=f'https://{domain_netloc}/')
                        
                    return {
                        'name': title, # <--- AICI (title este de fapt filename-ul lung trimis ca argument)
                        'url': final_url,
                        'quality': qual,
                        'title': title,
                        'size': size,
                        'info': info_label or ""
                    }
                return None
            
            _thrs = []
            _tlock_p = threading.Lock()
            def _tworker(args):
                try:
                    r = resolve_task(args)
                    if r:
                        with _tlock_p:
                            uc = r['url'].split('|')[0]
                            if uc not in seen_urls: streams.append(r); seen_urls.add(uc)
                except: pass
            for args in pending_resolves:
                th = threading.Thread(target=_tworker, args=(args,), daemon=True)
                th.start(); _thrs.append(th)
            _tstart = time.time()
            while _thrs and (time.time() - _tstart) < 17:
                _thrs = [th for th in _thrs if th.is_alive()]
                if not _thrs: break
                time.sleep(0.1)

    except Exception as e:
        log(f"[CLOUD] Critical Error: {e}", xbmc.LOGERROR)

    return streams


# =============================================================================
# _resolve_hdhub_redirect_parallel - FIX pentru GDFlix, HubCDN si Referer
# =============================================================================

def _resolve_hdhub_redirect_parallel(url, depth=0, parent_title=None, branch_label=None, executor=None):
    """
    Resolves HDHub4u/MKVCinemas chain WITH PARALLELIZATION.
    V6 - FIX: Support for relative token links (href="/drive/..." or var url = "/drive/...")
    """
    if not url or depth > 8: 
        return []
    
    url_lower = url.lower()
    
    # EXCLUDERE DOMENII PROBLEMATICE
    blocked_domains = [
        'googletagmanager', 'google-analytics', 'facebook.com', 
        'twitter.com', 'instagram.com', 'yandex', 'arc.io', '//ads.', 
        'recaptcha', 'captcha', 'disqus', 'gravatar', 'filepress',
        'bit.ly', 'telegram', 't.me',
        'gofile.io/d/',
        'megaup.net', 'megaup',
        'gadgetsweb', 'hubcloud.fans', '4khdhub.one',
        'gpdl.hubcloud.cx',
        '/admin',
    ]
    
    if any(blocked in url_lower for blocked in blocked_domains):
        return []
    
    # Exclude fișiere non-video (verifică doar PATH, nu domeniul)
    parsed_path = urlparse(url_lower).path
    if any(parsed_path.endswith(ext) for ext in ['.zip', '.rar', '.css', '.js', '.png', '.jpg', '.gif', '.ico']):
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
    
    # BuzzServer/BuzzHeavie - rezolvare redirect
    if 'buzzserver' in url_lower or 'buzzheavie' in url_lower:
        resolved = _resolve_buzzserver_url(url)
        if resolved and resolved != url:
            host = _identify_host_from_url(resolved)
            q = _extract_quality_from_string(parent_title) or _extract_quality_from_string(branch_label)
            return [(host, resolved, parent_title, q, branch_label)]
        # fallback: continuă ca link direct
    
    # Verifică dacă e link video final direct
    if _is_video_url(url):
        wrapper_indicators = ['hubcloud', 'gamerxyt', 'cryptoinsights', 'carnewz', 
                              'hblinks', 'inventoryidea', 'hubdrive', 'hubstream', 
                              '/drive/', '/file/', 'vcloud.zip', 'buzzserver', 'buzzheavie']
        
        is_wrapper = any(w in url_lower for w in wrapper_indicators)
        
        # Excepții: linkuri directe CDN care coincid cu indicatori wrapper
        if is_wrapper and 'gpdl.hubcloud.cx' in url_lower:
            is_wrapper = False
        
        if not is_wrapper:
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
        'hubfiles', 'carnewz', 'vcloud.zip', 'fastdl.zip', 'nexdrive.pro', 'nexdrive', 'filebee.xyz',
        'buzzserver', 'buzzheavie', 'bzzhr', 'hdstream4u',
        '/tg/go', '/dl.php',
    ]
    
    found_urls = []
    seen_urls = set()
    seen_urls.add(url)
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
            js_url_match = re.search(r"var\s+(?:re)?url\s*=\s*['\"]([^'\"]+)['\"]", content)
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
                
                # BuzzServer/BuzzHeavie - rezolvare redirect
                if 'buzzserver' in link_lower or 'buzzheavie' in link_lower:
                    resolved = _resolve_buzzserver_url(link)
                    if resolved and resolved != link:
                        q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                        host = _identify_host_from_url(resolved)
                        if resolved not in seen_urls:
                            found_urls.append((host, resolved, current_title, q, current_branch))
                            seen_urls.add(resolved)
                    return
                
                # WRAPPER CHECK - procesare recursivă doar pentru pagini cu fișiere
                if 'hubcloud' in link_lower and '/drive/' in link_lower:
                    sub_results = _resolve_hdhub_redirect_parallel(link, depth + 1, current_title, current_branch, executor)
                    for res in sub_results:
                        if res[1] not in seen_urls:
                            found_urls.append(res)
                            seen_urls.add(res[1])
                    return
                
                # Telegram gateway - resolve redirect to CDN (cdn.telesco.pe)
                if '/tg/go' in link_lower:
                    try:
                        sub_results = _resolve_hdhub_redirect_parallel(link, depth + 1, current_title, current_branch, executor)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
                    except: pass
                    return
                
                # PHP download page (dl.php) - resolve stck + var url
                if '/dl.php' in link_lower:
                    try:
                        sub_results = _resolve_hdhub_redirect_parallel(link, depth + 1, current_title, current_branch, executor)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
                    except: pass
                    return
                
                # Buzz shortener (bzzhr.co) - fetch hx-get links, follow redirect chain
                if 'bzzhr' in link_lower:
                    try:
                        sub_results = _resolve_hdhub_redirect_parallel(link, depth + 1, current_title, current_branch, executor)
                        for res in sub_results:
                            if res[1] not in seen_urls:
                                found_urls.append(res)
                                seen_urls.add(res[1])
                    except: pass
                    return
                
                blocked = ['googletagmanager', 'facebook', 'twitter', 'yandex', 'gadgetsweb',
                          'disqus', 'gravatar', 'recaptcha', '.css', '.js', '.png', '.jpg', 
                          'filepress', 'bit.ly', 't.me', 'telegram', 'megaup.net', 'megaup',
                          '/admin', 'gpdl.hubcloud.cx']
                if any(b in link_lower for b in blocked): return
                
                # PixelDrain - rezolvare înainte de _is_video_url
                if 'pixeldrain' in link_lower:
                    pd_id = re.search(r'/u/([a-zA-Z0-9]+)', link)
                    if pd_id:
                        api_link = f"https://pixeldrain.dev/api/file/{pd_id.group(1)}?download"
                        if api_link not in seen_urls:
                            q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                            found_urls.append(('PixelDrain', api_link, current_title, q, current_branch))
                            seen_urls.add(api_link)
                    return
                    
                if not _is_video_url(link): return
                
                host = _identify_host_from_url(link)
                q = _extract_quality_from_string(current_title) or _extract_quality_from_string(current_branch)
                
                found_urls.append((host, link, current_title, q, current_branch))
                seen_urls.add(link)

            # Acum transformăm și href-urile relative în absolute!
            # Include și hx-get (folosit de bzzhr.co și alte site-uri HTMX)
            all_hrefs = re.findall(r'(?:href|hx-get)=["\']([^"\']+)["\']', content)
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
                r'["\'](https?://[^"\']*buzzserver[^"\']*)["\']',
                r'["\'](https?://[^"\']*buzzheavie[^"\']*)["\']',
            ]
            
            for pattern in js_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches: add_direct_link(match)

            next_hop_patterns = [
                r'href=["\'](https?://[^"\']*hubcloud[^"\']*/drive/[^"\']*)["\']',
                r'href=["\'](/drive/[^"\']*\?token=[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*vcloud\.zip[^"\']+)["\']',
                r'href=["\'](https?://[^"\']*fastdl\.zip[^"\']+)["\']',
                r'href=["\'](https?://[^"\']*gamerxyt\.com[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hblinks[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*inventoryidea[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubcdn\.fans/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubdrive[^"\']*/file/[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*hubstream[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*carnewz\.site[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*cryptoinsights\.site[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*buzzserver[^"\']*)["\']',
                r'href=["\'](https?://[^"\']*buzzheavie[^"\']*)["\']',
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
                
                _nh_thrs = []
                _nh_lock = threading.Lock()
                def _nh_worker(nh):
                    try:
                        sub = resolve_next_hop(nh)
                        with _nh_lock:
                            for res in sub:
                                if res[1] not in seen_urls:
                                    found_urls.append(res); seen_urls.add(res[1])
                    except: pass
                for nh in next_hops[:10]:
                    th = threading.Thread(target=_nh_worker, args=(nh,), daemon=True)
                    th.start(); _nh_thrs.append(th)
                _nh_start = time.time()
                while _nh_thrs and (time.time() - _nh_start) < 17:
                    _nh_thrs = [th for th in _nh_thrs if th.is_alive()]
                    if not _nh_thrs: break
                    time.sleep(0.1)

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
            pass
            
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
        
        # Extrage mărimea din branch
        extracted_size = ""
        if returned_branch:
            size_match = re.search(r'\[([\d.]+\s*(?:GB|MB|TB))\]', returned_branch, re.IGNORECASE)
            if size_match:
                extracted_size = size_match.group(1)

        # 1. Cloud Page - procesare specială
        if host_name == 'CloudPage':
            # log(f"[PROCESS] Processing Cloud Page: {final_url[:50]}...")
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
            # log(f"[PROCESS] Processing GDFlix Page: {final_url[:50]}...")
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
            
            # Construiește display name - Prioritate pe titlul extras (.mkv)
            if file_title and len(file_title) > 10:
                display_name = file_title
            elif extracted_size:
                display_name = f"{host_name} | {extracted_size}"
            else:
                display_name = host_name

            # Forțăm calitatea corectă din display_name pentru a nu pica la fundul listei
            actual_q = _extract_quality_from_string(display_name) or final_quality

            streams_list.append({
                'name': display_name,
                'url': build_stream_url(final_url),
                'quality': actual_q,
                'title': display_title,
                'size': extracted_size,
                'info': f"{host_name} | {returned_branch or ''}"
            })
            seen_urls.add(url_check)


# =============================================================================
# SCRAPER HDHUB4U (V24 - WORKING VERSION + 4K PRIORITIZATION)
# =============================================================================

def scrape_hdhub4u(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_hdhub4u') == 'false':
        return None

    try:
        base_url = _get_hdhub_base_url()
        session = get_shared_session()
        
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        bad_qualities = ['hdtc', 'hdts', 'hdcam', 'camrip', 'predvd', 'pre-dvd', 'telesync', 'telecine']
        movie_url = None

        # 1. CĂUTARE (JSON API) — site-ul a schimbat domeniul, API-ul vechi e mort
        try:
            api_url = "https://search.hdhub4u.glass/collections/post/documents/search"
            r = session.get(api_url, params={'q': clean_search, 'query_by': 'post_title,imdb_id', 'limit': 15}, timeout=10)
            if r.status_code == 200:
                hits = r.json().get('hits', [])
                for hit in hits:
                    doc = hit.get('document', {})
                    link = doc.get('permalink', '')
                    title = doc.get('post_title', '').lower()
                    if not link or any(bad in title for bad in bad_qualities): continue
                    
                    if (imdb_id and imdb_id in str(doc.get('imdb_id', ''))) or (clean_search.lower() in title):
                        movie_url = f"{base_url.rstrip('/')}{link}" if link.startswith('/') else link
                        break
        except: pass

        # 2. CONSTRUIRE SLUG DIRECT (fallback principal — site-ul nu mai returnează RSS/JSON)
        if not movie_url and title_query:
            try:
                slug = re.sub(r'[^\w\s-]', '', title_query.lower().strip())
                slug = re.sub(r'\s+', '-', slug).strip('-')
                slug_patterns = [
                    f"{slug}-{year_query}-webrip-hindi-full-movie",
                    f"{slug}-{year_query}-hindi-webrip-full-movie",
                    f"{slug}-{year_query}-hindi-bluray-full-movie",
                    f"{slug}-{year_query}-web-dl-hindi-full-movie",
                    f"{slug}-{year_query}-hindi-web-dl-full-movie",
                    f"{slug}-{year_query}-hindi-720p-bluray",
                    f"{slug}-{year_query}-hindi-bluray-720p",
                    f"{slug}-{year_query}-hindi-1080p-bluray",
                    f"{slug}-{year_query}-bluray-hindi-720p",
                    f"{slug}-{year_query}-webrip-hindi",
                    f"{slug}-{year_query}-hindi-webrip",
                    f"{slug}-{year_query}-hindi-full-movie",
                    f"{slug}-{year_query}-full-movie",
                ]
                for sp in slug_patterns:
                    try:
                        r = session.head(f"{base_url}/{sp}/", timeout=5)
                        if r.status_code == 200:
                            movie_url = f"{base_url}/{sp}/"
                            # log(f"[HDHUB] Slug match: {movie_url}")
                            break
                    except: pass
            except: pass

        # 3. SCANARE SITEMAP (fallback cand slug-urile nu se potrivesc)
        if not movie_url and title_query:
            try:
                slug = re.sub(r'[^\w\s-]', '', title_query.lower().strip())
                slug = re.sub(r'\s+', '-', slug).strip('-')
                sm_r = session.get(f"{base_url}/sitemap.xml", timeout=10)
                if sm_r.status_code == 200:
                    post_sms = re.findall(r"<loc>(https?://[^/]+/post-sitemap\d*\.xml)</loc>", sm_r.text)
                    for sm_url in post_sms[:5]:
                        sm_r2 = session.get(sm_url, timeout=10)
                        if sm_r2.status_code != 200:
                            continue
                        matches = re.findall(rf"<loc>([^<]*{re.escape(slug)}[^<]*)</loc>", sm_r2.text, re.I)
                        if matches:
                            movie_url = matches[0]
                            # log(f"[HDHUB] Sitemap match: {movie_url}")
                            break
            except: pass

        # 4. FALLBACK RSS (possible future fix)
        if not movie_url:
            try:
                rss_url = f"{base_url}/?s={quote(clean_search)}&feed=rss2"
                r = session.get(rss_url, timeout=10)
                if r.status_code == 200:
                    items = r.text.split('<item>')
                    for item in items[1:]:
                        l_m = re.search(r'<link>(.*?)</link>', item)
                        t_m = re.search(r'<title>(.*?)</title>', item)
                        if l_m and t_m:
                            if any(bad in t_m.group(1).lower() for bad in bad_qualities): continue
                            movie_url = l_m.group(1).strip()
                            break
            except: pass

        if not movie_url: return None

        # 3. EXTRAGERE LINK-URI
        r_movie = session.get(movie_url, timeout=12)
        movie_html = r_movie.text
        title_m = re.search(r'<h1[^>]*>.*?<span[^>]*>(.*?)</span>', movie_html, re.DOTALL)
        fallback_title = title_m.group(1).strip() if title_m else title_query

        all_links = re.findall(r'<a\s+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', movie_html)
        
        valid_domains = ['hubdrive', 'hubcloud', 'hubcdn', 'hubstream', 'gamerxyt', 'vcloud', 'hblinks', 'search-recover.php',
                         'buzzserver', 'buzzheavie', 'hubcdn.fans', 'filesdl', 'gdflix', 'pixeldrain']
        hdhub_tasks = []
        
        for link, text in all_links:
            link = link.replace('&amp;', '&')
            txt_low = text.lower()
            if any(bad in txt_low for bad in bad_qualities): continue
            if not any(d in link.lower() for d in valid_domains): continue
            
            # PRIORITIZARE (nu mai sărim peste SD/480p!)
            q_label, weight = None, 0
            if '2160' in txt_low or '4k' in txt_low: q_label, weight = "4K", 3
            elif '1080' in txt_low: q_label, weight = "1080p", 2
            elif '720' in txt_low: q_label, weight = "720p", 1
            else: q_label, weight = "SD", 0  # Păstrăm și SD/480p!
            
            hdhub_tasks.append({'link': link, 'branch': text.strip(), 'quality': q_label, 'w': weight})

        # SORTARE: 4K primele pe țeavă
        hdhub_tasks.sort(key=lambda x: x['w'], reverse=True)

        streams = []
        seen = set()
        lock = threading.Lock()
        
        def process_task(t):
            res_list = []
            try:
                if 'search-recover.php' in t['link'].lower():
                    res_list = _process_hubcloud_search_recover(t['link'], t['quality'], fallback_title, t['branch'], session)
                else:
                    resolved = _resolve_hdhub_redirect_parallel(t['link'], 0, fallback_title, t['branch'], None)
                    if resolved:
                        _process_resolved_results(resolved, t['quality'], fallback_title, t['branch'], res_list, set())
            except: pass
            return res_list

        # EXECUȚIE PARALELĂ CU DAEMON THREADS (Kodi-safe)
        _hdhub_thrs = []
        _hdhub_lock = threading.Lock()
        _hdhub_out = []
        def _hdhub_worker(t):
            try:
                r = process_task(t)
                if r:
                    with _hdhub_lock:
                        for s in r:
                            if any(bad in str(s.get('title','')).lower() for bad in bad_qualities): continue
                            uc = s['url'].split('|')[0]
                            if uc not in seen: streams.append(s); seen.add(uc)
            except: pass
        for t in hdhub_tasks:
            th = threading.Thread(target=_hdhub_worker, args=(t,), daemon=True)
            th.start()
            _hdhub_thrs.append(th)
        _hdhub_start = time.time()
        while _hdhub_thrs and (time.time() - _hdhub_start) < 20:
            _hdhub_thrs = [th for th in _hdhub_thrs if th.is_alive()]
            if not _hdhub_thrs: break
            time.sleep(0.1)

        return streams if streams else None
    except: return None


# =============================================================================
# SCRAPER MKVCINEMAS (V14 - CLEAN RESOLUTION & CLOUD ROUTING)
# =============================================================================

def scrape_mkvcinemas(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_mkvcinemas') == 'false':
        return None

    try:
        base_url = "https://mkvcinemas.sc"
        session = get_shared_session()
        
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        bad_qualities = ['hdtc', 'hdts', 'hdcam', 'camrip', 'predvd', 'pre-dvd', 'telesync', 'telecine']
        
        # 1. CĂUTARE RSS (Bypass JS)
        movie_url = None
        try:
            rss_url = f"{base_url}/?s={quote(clean_search)}&feed=rss2"
            r = session.get(rss_url, timeout=12, verify=False)
            if r.status_code == 200:
                items = r.text.split('<item>')
                for item in items[1:]:
                    l_m = re.search(r'<link>(.*?)</link>', item)
                    t_m = re.search(r'<title>(.*?)</title>', item)
                    if l_m and t_m:
                        p_t, p_l = t_m.group(1).lower(), l_m.group(1).strip()
                        if any(bad in p_t for bad in bad_qualities): continue
                        if clean_search.lower() in p_t or clean_search.lower().replace(' ', '-') in p_l:
                            if year_query and str(year_query) in p_l: movie_url = p_l; break
                            if not movie_url: movie_url = p_l
        except: pass

        if not movie_url: return None

        # 2. EXTRAGERE LINK-URI FILESDL
        r_post = session.get(movie_url, timeout=12, verify=False)
        post_html = r_post.text
        filesdl_links = re.findall(r'href=["\'](https?://filesdl\.[a-z]+/(?:view/)?(\d+))["\']', post_html, re.I)
        
        if not filesdl_links: return None
        
        mkv_tasks = []
        seen_ids = set()

        # 3. PROCESARE PAGINI INTERMEDIARE (FilesDL)
        for f_url, f_id in filesdl_links:
            if f_id in seen_ids: continue
            seen_ids.add(f_id)
            
            try:
                # Bypass Cloudflare via WP-API pentru a lua butoanele de download
                api_url = f"https://filesdl.live/wp-json/wp/v2/posts/{f_id}"
                r_api = session.get(api_url, timeout=8, verify=False)
                
                content_html = ""
                if r_api.status_code == 200:
                    content_html = r_api.json().get('content', {}).get('rendered', '')
                else:
                    r_f = session.get(f_url, headers={'Referer': movie_url}, timeout=8, verify=False)
                    content_html = r_f.text

                # "Săpăm" după Download Boxes (4K, 1080p, 720p)
                boxes = content_html.split('download-box')
                for box in boxes[1:]:
                    q_low = box.lower()
                    
                    quality, weight = None, 0
                    if '2160' in q_low or '4k' in q_low: quality, weight = "4K", 3
                    elif '1080' in q_low: quality, weight = "1080p", 2
                    elif '720' in q_low: quality, weight = "720p", 1
                    else: continue # Sărim peste 480p/SD
                    
                    # Extragem link-urile butoanelor din fiecare box
                    btns = re.findall(r'href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', box, re.I)
                    for b_url, b_text in btns:
                        b_text_clean = re.sub(r'<[^>]+>', '', b_text).strip()
                        # Nu adăugăm direct în listă! Le punem ca sarcini de rezolvat.
                        mkv_tasks.append({
                            'url': b_url, 
                            'quality': quality, 
                            'weight': weight, 
                            'info': b_text_clean
                        })
            except: continue

        if not mkv_tasks: return None
        # Sortăm: 4K primele
        mkv_tasks.sort(key=lambda x: x['weight'], reverse=True)

        streams = []
        seen_urls = set()
        lock = threading.Lock()

        # 4. RESOLVER FINAL (Curățenie & Routing)
        def work(t):
            local_found = []
            u = t['url'].replace('&amp;', '&')
            u_low = u.lower()
            try:
                # Rutăm fiecare link către procesorul lui specific
                if 'search-recover' in u_low:
                    return _process_hubcloud_search_recover(u, t['quality'], title_query, t['info'], session)
                
                elif any(x in u_low for x in ['hubcloud', 'vcloud']):
                    resolved = _resolve_hdhub_redirect_parallel(u, 0, title_query, t['info'], None)
                    if resolved:
                        _process_resolved_results(resolved, t['quality'], title_query, t['info'], local_found, set())
                    return local_found

                elif 'gdflix' in u_low:
                    # Folosim procesorul de pagini GDFlix existent
                    return _process_gdflix_page(u, t['quality'], title_query, t['info'])

                elif 'filesdl' in u_low and ('/cloud/' in u_low or '/drive/' in u_low):
                    # Folosim procesorul de pagini Cloud existent (REZOLVĂ EROAREA TA DIN LOG)
                    return _process_filesdl_cloud_page(u, t['quality'], title_query, t['info'])

                # Fallback doar dacă e link video direct verificat
                elif _is_direct_video_url(u):
                    h = _identify_host_from_url(u)
                    local_found.append({
                        'name': f"MKV | {h}", 
                        'url': build_stream_url(u), 
                        'quality': t['quality'], 
                        'title': title_query, 
                        'info': t['info'], 
                        'provider_id': 'mkvcinemas'
                    })
            except: pass
            return local_found

        _mkv_thrs = []
        _mkv_lock = threading.Lock()
        def _mkv_worker(t):
            try:
                r = work(t)
                if r:
                    with _mkv_lock:
                        for s in r:
                            if any(bad in str(s.get('title','')).lower() for bad in bad_qualities): continue
                            uc = s['url'].split('|')[0]
                            if uc not in seen_urls: streams.append(s); seen_urls.add(uc)
            except: pass
        for t in mkv_tasks:
            th = threading.Thread(target=_mkv_worker, args=(t,), daemon=True)
            th.start()
            _mkv_thrs.append(th)
        _mkv_start = time.time()
        while _mkv_thrs and (time.time() - _mkv_start) < 20:
            _mkv_thrs = [th for th in _mkv_thrs if th.is_alive()]
            if not _mkv_thrs: break
            time.sleep(0.1)

        return streams if streams else None
    except Exception as e:
        log(f"[MKV] Critical error: {e}")
        return None


# =============================================================================
# HELPER NOU: API HubCloud (search-recover.php) - V2 (SORTARE & FILTRARE JSON)
# =============================================================================
def _process_hubcloud_search_recover(url, quality, title, branch_info, session, target_episode=None):
    """
    Rezolvă noul sistem MoviesDrive/HubCloud (search-recover.php).
    V2: Sortează hit-urile din JSON pentru a prioritiza 4K/1080p.
    """
    streams = []
    bad_qualities = ['hdtc', 'hdts', 'hdcam', 'camrip', 'predvd', 'pre-dvd', 'telesync', 'telecine']
    
    try:
        url = url.replace('&amp;', '&').replace('&#038;', '&')
        parsed = urlparse(url)
        qs = dict(parse_qsl(parsed.query))
        
        from_ac = qs.get('from_ac', '')
        q_b64 = qs.get('q', '')
        if not from_ac or not q_b64: return streams

        q_b64 = q_b64.replace('-', '+').replace('_', '/')
        q_b64 += "=" * ((4 - len(q_b64) % 4) % 4)
        decoded_q = base64.b64decode(q_b64).decode('utf-8')

        api_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        params = {'api': 'search', 'q': decoded_q, 'page': '1', 'from_ac': from_ac}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json', 'Referer': url, 'X-Requested-With': 'XMLHttpRequest'
        }

        r = session.get(api_url, params=params, headers=headers, timeout=10, verify=False)
        if r.status_code == 200:
            hits = r.json().get('hits', [])
            
            # --- PASUL 1: FILTRARE ȘI ATRIBUIRE GREUTATE ---
            valid_hits = []
            for hit in hits:
                fn = hit.get('file_name', '').lower()
                # 1. Filtru bad quality
                if any(bad in fn for bad in bad_qualities): continue
                # 2. Filtru episod
                if target_episode:
                    if not re.search(rf'(?i)(?:E|Ep|Episode)[\s0]*{int(target_episode)}\b', fn): continue
                
                # 3. Calcul greutate (4K=3, 1080=2, 720=1, Restul=0)
                weight = 0
                hit_q = "SD"
                if '2160' in fn or '4k' in fn: hit_q, weight = "4K", 3
                elif '1080' in fn: hit_q, weight = "1080p", 2
                elif '720' in fn: hit_q, weight = "720p", 1
                
                if weight >= 0: # Includem SD/480p
                    hit['w'] = weight
                    hit['q_label'] = hit_q
                    valid_hits.append(hit)

            # --- PASUL 2: SORTARE HIT-URI (4K PRIMELE) ---
            valid_hits.sort(key=lambda x: x['w'], reverse=True)

            # --- PASUL 3: REZOLVARE ÎN ORDINEA PRIORITĂȚII ---
            for hit in valid_hits:
                file_url = hit.get('url', '')
                if not file_url: continue
                
                # Rezolvăm link-ul HubCloud (de obicei PixelDrain/R2)
                resolved = _resolve_hdhub_redirect_parallel(file_url, 0, title, branch_info, None)
                if resolved:
                    temp_streams = []
                    _process_resolved_results(resolved, hit['q_label'], title, branch_info, temp_streams, set())
                    for s in temp_streams:
                        if hit.get('size'): s['size'] = hit['size']
                        # Verificare finală nume fișier
                        if not any(bad in s['title'].lower() for bad in bad_qualities):
                            streams.append(s)
                            
    except Exception as e:
        log(f"[MDRIVE-RECOVER] Error: {e}")
    return streams


# =============================================================================
# SCRAPER MOVIESDRIVE (V16 - ULTRA FAST & 4K PRIORITIZED)
# =============================================================================

def scrape_moviesdrive(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_moviesdrive') == 'false': return None
    try:
        base_url = _get_moviesdrive_base()
        session = get_shared_session()
        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        
        # 1. CĂUTARE JSON
        search_api_url = f"{base_url}/search.php"
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        r = session.get(search_api_url, params={'q': clean_search, 'page': '1'}, headers=headers, timeout=12, verify=False)
        if r.status_code != 200: return None
        hits = r.json().get('hits', [])
        if not hits: return None

        # 2. GĂSIRE PAGINĂ (Match slug/an)
        movie_url = None
        search_slug = clean_search.lower().replace(' ', '-')
        bad_qualities = ['hdtc', 'hdts', 'hdcam', 'camrip', 'predvd', 'telesync']
        
        for hit in hits:
            doc = hit.get('document', {})
            raw_link = doc.get('permalink', '')
            raw_title = doc.get('post_title', '').lower()
            if not raw_link or any(bad in raw_title for bad in bad_qualities): continue
            
            full_link = raw_link if raw_link.startswith('http') else f"{base_url.rstrip('/')}/{raw_link.lstrip('/')}"
            if search_slug in full_link.lower() or clean_search.lower() in raw_title:
                if year_query and str(year_query) in full_link: movie_url = full_link; break
                if not movie_url: movie_url = full_link
        
        if not movie_url: movie_url = hits[0].get('document', {}).get('permalink', '')
        if not movie_url: return None

        # 3. ACCESARE PAGINĂ & EXTRAGERE BUTOANE
        r_page = session.get(movie_url, timeout=10, verify=False)
        target_html = r_page.text
        title_match = re.search(r'<title>([^<]+)</title>', target_html)
        target_title = title_match.group(1).split('|')[0].strip().replace('– MoviesDrive', '') if title_match else title_query

        # Dacă e TV, mergem la pagina sezonului
        if content_type == 'tv' and season:
            sn = int(season)
            s_link = None
            for p in [rf'href=["\']([^"\']*season[- ]?{sn}[^"\']*)["\']', rf'href=["\']([^"\']*s{sn:02d}[^"\']*)["\']']:
                m = re.search(p, target_html, re.I)
                if m: s_link = base_url + m.group(1) if m.group(1).startswith('/') else m.group(1); break
            if s_link: target_html = session.get(s_link, timeout=10).text

        # 4. PROCESARE BUTOANE (SORTATE DUPĂ CALITATE)
        btn_links = []
        all_a = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', target_html, re.I)
        for url, text in all_a:
            txt = text.lower()
            if any(key in url.lower() for key in ['search-recover.php', 'hubcloud', 'mdrive.lol']):
                w = 3 if ('2160' in txt or '4k' in txt) else 2 if '1080' in txt else 1 if '720' in txt else 0
                if w > 0 and not any(bad in txt for bad in bad_qualities):
                    btn_links.append({'url': url, 'text': text, 'w': w})
        
        btn_links.sort(key=lambda x: x['w'], reverse=True)
        
        streams = []
        seen_urls = set()
        lock = threading.Lock()
        
        def work(item):
            q = "4K" if item['w'] == 3 else "1080p" if item['w'] == 2 else "720p"
            u = item['url'].replace('&amp;', '&')
            res_streams = []
            if 'search-recover.php' in u.lower():
                res_streams = _process_hubcloud_search_recover(u, q, target_title, item['text'], session, episode if content_type=='tv' else None)
            elif 'mdrive.lol' in u.lower():
                # Pentru mdrive.lol trebuie sa intram o data
                try:
                    inner = session.get(u, timeout=8).text
                    m = re.search(r'href=["\'](https?://[^"\']*search-recover\.php[^"\']+)["\']', inner, re.I)
                    if m: res_streams = _process_hubcloud_search_recover(m.group(1), q, target_title, item['text'], session, episode if content_type=='tv' else None)
                except: pass
            return res_streams

        _hc_thrs = []
        _hc_lock = threading.Lock()
        def _hc_worker(b):
            try:
                r = work(b)
                if r:
                    with _hc_lock:
                        for s in r:
                            uc = s['url'].split('|')[0]
                            if uc not in seen_urls: streams.append(s); seen_urls.add(uc)
            except: pass
        for b in btn_links[:10]:
            th = threading.Thread(target=_hc_worker, args=(b,), daemon=True)
            th.start()
            _hc_thrs.append(th)
        _hc_start = time.time()
        while _hc_thrs and (time.time() - _hc_start) < 22:
            _hc_thrs = [th for th in _hc_thrs if th.is_alive()]
            if not _hc_thrs: break
            time.sleep(0.1)
        
        return streams if streams else None
    except Exception as e:
        log(f"[MDRIVE] Error: {e}")
        return None


def scrape_moviesdrive(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_moviesdrive') == 'false':
        return None

    try:
        base_url = _get_moviesdrive_base()
        session = get_shared_session()
        
        # --- PASUL 0: SESIUNE PRE-WARMUP (Anti-Bot Bypass) ---
        try:
            session.get(f"{base_url}/", timeout=5, verify=False)
        except: pass

        search_query = title_query if title_query else imdb_id
        clean_search = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_query).strip()
        clean_search = re.sub(r'\s+', ' ', clean_search)
        
        bad_qualities = ['hdtc', 'hdts', 'hdcam', 'camrip', 'predvd', 'pre-dvd', 'telesync', 'telecine']
        movie_url = None
        search_slug = clean_search.lower().replace(' ', '-')
        import html as html_lib

        # =========================================================
        # 1. CĂUTARE HYBRIDĂ (JSON + FALLBACK HTML)
        # =========================================================
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f"{base_url}/"
        }

        # Încercăm JSON prima dată
        try:
            r = session.get(f"{base_url}/search.php", params={'q': clean_search, 'page': '1'}, headers=headers, timeout=10, verify=False)
            if r.status_code == 200:
                hits = r.json().get('hits', [])
                for hit in hits:
                    doc = hit.get('document', {})
                    raw_link = doc.get('permalink', '')
                    raw_title = html_lib.unescape(doc.get('post_title', ''))
                    if not raw_link: continue
                    full_link = raw_link if raw_link.startswith('http') else f"{base_url.rstrip('/')}/{raw_link.lstrip('/')}"
                    
                    if any(bad in full_link.lower() or bad in raw_title.lower() for bad in bad_qualities): continue
                    
                    if (imdb_id and imdb_id in full_link) or (search_slug in full_link.lower()):
                        movie_url = full_link
                        if year_query and str(year_query) in full_link.lower(): break
        except: pass

        # Fallback la HTML Search dacă JSON a eșuat
        if not movie_url:
            try:
                r_html = session.get(f"{base_url}/", params={'s': clean_search}, headers={'User-Agent': headers['User-Agent']}, timeout=10, verify=False)
                res_links = re.findall(r'<h2[^>]*><a href=["\']([^"\']+)["\']', r_html.text, re.IGNORECASE)
                for lnk in res_links:
                    if any(bad in lnk.lower() for bad in bad_qualities): continue
                    if search_slug in lnk.lower():
                        movie_url = lnk
                        break
            except: pass

        if not movie_url: return None

        # =========================================================
        # 2. PROCESARE PAGINĂ (FILM SAU SERIAL)
        # =========================================================
        r_page = session.get(movie_url, timeout=10, verify=False)
        target_html = r_page.text
        
        # Dacă este serial, căutăm pagina sezonului
        if content_type == 'tv' and season:
            season_num = int(season)
            season_link = None
            for pattern in [rf'href=["\']([^"\']*season[- ]?{season_num}[^"\']*)["\']', rf'href=["\']([^"\']*s{season_num:02d}[^"\']*)["\']']:
                match = re.search(pattern, target_html, re.IGNORECASE)
                if match:
                    season_link = base_url + match.group(1) if match.group(1).startswith('/') else match.group(1)
                    break
            if season_link:
                target_html = session.get(season_link, timeout=10, verify=False).text

        title_match = re.search(r'<title>([^<]+)</title>', target_html)
        target_title = html_lib.unescape(title_match.group(1).split('|')[0].strip().replace('– MoviesDrive', '')) if title_match else title_query

        # =========================================================
        # 3. COLECTARE ȘI PRIORITIZARE LINK-URI (4K -> 1080 -> 720)
        # =========================================================
        # Restrângem căutarea la secțiunea de download
        start_search = target_html.find("DOWNLOAD LINKS")
        html_section = target_html[start_search:] if start_search != -1 else target_html
        
        raw_found = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_section, re.IGNORECASE)
        
        mdrive_tasks = []
        seen_urls = set()

        for l_url, l_text in raw_found:
            text_clean = html_lib.unescape(re.sub(r'<[^>]+>', '', l_text).strip())
            text_lower = text_clean.lower()
            
            # Filtru ANTI-HDTC / CAM
            if any(bad in text_lower for bad in bad_qualities): continue
            
            # Filtru PRIORITATE și EXCLUDERE SD/480p
            quality, weight = None, 0
            if '2160' in text_lower or '4k' in text_lower: quality, weight = "4K", 3
            elif '1080' in text_lower: quality, weight = "1080p", 2
            elif '720' in text_lower: quality, weight = "720p", 1
            else: continue # Skip SD/480p/360p
            
            if any(key in l_url.lower() for key in ['search-recover.php', 'hubcloud', 'gdflix', 'vcloud', 'mdrive.lol']):
                mdrive_tasks.append({
                    'url': l_url.replace('&amp;', '&'),
                    'text': text_clean,
                    'quality': quality,
                    'weight': weight
                })

        if not mdrive_tasks: return None
        
        # --- SORTARE: 4K ÎNCEPE PRIMUL PE REȚEA ---
        mdrive_tasks.sort(key=lambda x: x['weight'], reverse=True)

        streams = []
        final_seen_urls = set()
        streams_lock = threading.Lock()
        episode_num = int(episode) if episode else 1

        def process_node(item):
            local_res = []
            try:
                d_url = item['url']
                # Dacă suntem la seriale, filtrăm blocul de episoade înainte
                if content_type == 'tv' and 'search-recover.php' not in d_url:
                    # Request rapid pentru a vedea dacă episodul există în mdrive.lol
                    r_node = session.get(d_url, timeout=7, verify=False)
                    node_html = r_node.text
                    if f"Ep{episode_num:02d}" not in node_html and f"Episode {episode_num}" not in node_html:
                        return [] # Skip dacă nu e episodul nostru
                    
                if 'search-recover.php' in d_url.lower():
                    local_res.extend(_process_hubcloud_search_recover(d_url, item['quality'], target_title, item['text'], session, target_episode=(episode if content_type=='tv' else None)))
                else:
                    # Rezolvăm mdrive.lol sau hubcloud direct
                    resolved = _resolve_hdhub_redirect_parallel(d_url, 0, target_title, item['text'], None)
                    if resolved:
                        _process_resolved_results(resolved, item['quality'], target_title, item['text'], local_res, set())
            except: pass
            return local_res

        # EXECUȚIE PARALELĂ CU DAEMON THREADS (Kodi-safe)
        _md_thrs = []
        _md_lock = threading.Lock()
        def _md_worker(t):
            try:
                r = process_node(t)
                if r:
                    with _md_lock:
                        for s in r:
                            if any(bad in s.get('title', '').lower() for bad in bad_qualities): continue
                            uc = s['url'].split('|')[0]
                            if uc not in final_seen_urls: streams.append(s); final_seen_urls.add(uc)
            except: pass
        for t in mdrive_tasks:
            th = threading.Thread(target=_md_worker, args=(t,), daemon=True)
            th.start()
            _md_thrs.append(th)
        _md_start = time.time()
        while _md_thrs and (time.time() - _md_start) < 22:
            _md_thrs = [th for th in _md_thrs if th.is_alive()]
            if not _md_thrs: break
            time.sleep(0.1)

        return streams if streams else None

    except Exception as e:
        log(f"[MDRIVE] Critical error: {e}", xbmc.LOGERROR)
        return None

# =============================================================================
# HELPER PROVIDERI JSON (StreamVix, Vidzee, Webstreamr)
# =============================================================================
def _scrape_json_provider(base_url, pattern, label, imdb_id, content_type, season, episode, title_query=None, year_query=None):
    """
    Helper pentru providerii JSON (StreamVix, Vidzee, Webstreamr).
    FIX: Extrage calitatea din name/title/description și folosește titlul fallback.
    """
    local_streams = []
    
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
                        if content_type == 'tv' and season and episode:
                            raw_title = f"{title_query} S{int(season):02d}E{int(episode):02d}"
                        else:
                            raw_title = title_query

                    try: clean_name = raw_name.encode('ascii', 'ignore').decode('ascii')
                    except: clean_name = raw_name

                    # Eliminare nume provider din afișare
                    banned_names = ['WebStreamr', 'StreamVix', 'Vidzee', 'Sooti', 'Sootio', 'HDHub']
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
    if not url:
        info_hash = s.get('infoHash')
        if not info_hash:
            return None
        trackers = s.get('sources', [])
        url = "magnet:?xt=urn:btih:%s" % info_hash
        for tr in trackers:
            url += "&tr=%s" % tr
        # Magnet URLs from non-P2P providers (custom1-5 etc.) are blocked — P2P only
        if not provider_id.startswith('p2p_'):
            return None
    
    raw_name = s.get('name', '')
    raw_title = (s.get('title', '') + '\n' + s.get('description', '')).strip()
    name_upper = raw_name.upper()
    url_lower = url.lower()
    
    # 1. Debrid & Cached Status
    is_cached = False
    debrid_service = ""

    # Map debrid initials to full names (TB=torbox, RD=realdebrid, AD=alldebrid, PM=premiumize, EN=easynews)
    DEBRID_INITIALS = {
        'TB': 'torbox', 'RD': 'realdebrid', 'AD': 'alldebrid',
        'PM': 'premiumize', 'EN': 'easynews',
    }

    # Priority 1: Name-based — matches [TB+], [TB⚡], [TB🌩️] (Torrentio/Comet/Meteor)
    for initial, service in DEBRID_INITIALS.items():
        if f'[{initial}' in name_upper:
            debrid_service = service
            is_cached = f'[{initial}+]' in name_upper
            break
    if not debrid_service:
        # MediaFusion pattern: 🧲 CODE ⚡️ (e.g. 🧲 TRB ⚡️ for TorBox)
        mf_match = re.search(r'🧲\s*(\w+)\s*⚡', raw_name)
        if mf_match:
            mf_code = mf_match.group(1).upper()
            mf_map = {'TRB': 'torbox', 'RD': 'realdebrid', 'AD': 'alldebrid', 'PM': 'premiumize', 'EN': 'easynews'}
            if mf_code in mf_map:
                debrid_service = mf_map[mf_code]
                is_cached = True

    # Priority 2: URL path patterns
    if not debrid_service:
        url_checks = {
            '/realdebrid/': 'realdebrid', '/rd/': 'realdebrid',
            '/alldebrid/': 'alldebrid', '/ad/': 'alldebrid',
            '/premiumize/': 'premiumize', '/pm/': 'premiumize',
            '/torbox/': 'torbox', '/tb/': 'torbox',
            '/easynews/': 'easynews', '/en/': 'easynews',
        }
        for pattern, service in url_checks.items():
            if pattern in url_lower:
                debrid_service = service
                break

    # Priority 3: Description/title patterns (Comet puts "DebridAccount|torbox" in description)
    if not debrid_service:
        title_lower = raw_title.lower()
        for initial, service in DEBRID_INITIALS.items():
            if f'|{service}' in title_lower or service in title_lower:
                debrid_service = service
                break

    # Priority 4: behaviorHints.cached — set is_cached if not already set
    if not is_cached and debrid_service:
        is_cached = s.get('behaviorHints', {}).get('cached', False)

    # 2. Extragem numele fișierului din title / behaviorHints
    raw_title_unquoted = full_unquote(raw_title)
    lines = [line.strip() for line in raw_title_unquoted.split('\n') if line.strip()]
    filename = ""
    info_line = ""
    
    # Prioritate 1: behaviorHints.filename (Meteor pune numele real aici)
    try:
        bh_filename = s.get('behaviorHints', {}).get('filename', '')
        if bh_filename and len(bh_filename) > 5:
            filename = bh_filename
    except:
        pass
    
    # Prioritate 2: Linia cu 📄 sau 📂 din title (Meteor / Mediafusion)
    if not filename:
        for line in lines:
            if '📄' in line or '📂' in line:
                potential = line.replace('📄', '').replace('📂', '').strip()
                if potential and len(potential) > 5:
                    filename = potential
                    break
    
    # Prioritate 3: Prima linie non-info (TorrentIO / Comet / Mediafusion)
    # Only treat seeders/size/indexer lines as "skip" -- quality/audio/language lines
    # are valid fallback filenames when the real name is unavailable
    if not filename:
        for line in lines:
            if not any(e in line for e in ('👤', '👥', '💾', '⚙️', '🇵🇱')) and 'GB' not in line.upper() and 'MB' not in line.upper() and 'TB' not in line.upper() and ' peers ' not in line.lower() and 'multi audio' not in line.lower():
                filename = line
                break
    
    if not filename:
        filename = raw_title_unquoted.replace('\n', ' ')
    
    # Identificăm linia de info (mărime, seederi, indexer)
    for line in lines:
        if any(e in line for e in ('👤', '💾', '⚙️', '🇵🇱')) or 'GB' in line.upper() or 'MB' in line.upper() or ' peers ' in line.lower() or 'multi audio' in line.lower():
            info_line = line

    # 3. EXTRAȚIE NUME FIȘIER DIN URL (Pentru Comet / Fallback)
    def is_valid_filename(fname):
        return bool(re.search(r'\.(mkv|mp4|avi|ts|webm|m4v)', fname, re.IGNORECASE))
        
    # Dacă numele e gol, e un hash random, sau n-are extensie (skip pentru magnet URLs)
    if not url.startswith('magnet:') and (not is_valid_filename(filename) or len(filename) < 5 or (' ' not in filename and '.' not in filename)):
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
                # Nu are parametri, încercăm din Path (Torrentio / Meteor)
                url_name = ""
                if '/null/0/' in clean_url: url_name = clean_url.split('/null/0/')[-1]
                elif '/null/undefined/' in clean_url: url_name = clean_url.split('/null/undefined/')[-1]
                else: url_name = clean_url.split('/')[-1]
                
                url_name = url_name.split('?')[0]
                
                # Evităm nume care par ID-uri (numere, hash-uri hex) în loc de nume de fișiere
                if url_name and len(url_name) > 5 and not url_name.isdigit() and not re.match(r'^[a-f0-9]{32,40}$', url_name, re.I):
                    filename = url_name
        except:
            pass

    filename = full_unquote(filename).strip(' |-,')
    
    # 3.5 FILTRU CAM/TS/SAMPLE — aceleași reguli ca în scrape_aiostreams
    if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync)\b', filename):
        return None
    
    # 3.6 BLOCARE FIȘIERE GUNOI / MALWARE / NON-VIDEO / AUDIO
    bad_extensions = [
        '.iso', '.zip', '.rar', '.7z', '.tar', '.gz', '.zipx', '.arj',
        '.txt', '.nfo', '.jpg', '.png', '.pdf',
        '.exe', '.bat', '.cmd', '.scr', '.msi', '.ps1', '.vbs', '.js', '.jar', '.com', '.pif', '.reg', '.dll', '.sys', '.lnk',
        '.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.wma', '.ape', '.alac'
    ]
    filename_lower = filename.lower()
    if any(filename_lower.endswith(ext) for ext in bad_extensions) or any(f"{ext} " in filename_lower for ext in bad_extensions):
        return None

    # 3.6 FILTRU WEB (Opțional din setări) - DOAR PENTRU RD
    try:
        if ADDON.getSetting('filter_web_sources') == 'true' and debrid_service == 'realdebrid':
            if _is_web_source(filename) or _is_web_source(raw_title) or _is_web_source(raw_name):
                # log(f"[FILTER-WEB] Excluding WEB RD source: {filename[:50]}...")
                return None
    except:
        pass

    # 4. Mărime și Seederi
    size_match = re.search(r'([\d.,]+\s*(?:GB|MB|TB))', raw_title_unquoted, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else ""
    
    seeders = 0
    seed_match = re.search(r'(?:👤|👥|S:|P:|Peers:)\s*(\d+)', raw_title_unquoted, re.IGNORECASE)
    if seed_match: seeders = int(seed_match.group(1))
    
    # 5. Indexer — prioritate 1: decodează `t` din URL (cel mai autoritar, suprascrie AIO)
    indexer = ""
    if url and '?t=' in url:
        try:
            import base64, json as _json
            _t = url.split('?t=')[1].split('|')[0].split('&')[0]
            _t = _t + '=='
            _decoded = _json.loads(base64.urlsafe_b64decode(_t).decode('utf-8'))
            _t_idxer = str(_decoded.get('indexer', '')).strip()
        except:
            _t_idxer = ''
        if _t_idxer:
            indexer = _t_idxer
    # Prioritate 2: 🗂️ (Usenet), apoi 🔗, apoi ⚙️ (codec fallback)
    if not indexer:
        idx_match = re.search(r'🗂️\s*([^\n📅🏴]+)', raw_title_unquoted)
        if idx_match:
            indexer = idx_match.group(1).strip()
    if not indexer:
        link_match = re.search(r'🔗\s*(.*)', raw_title_unquoted)
        if link_match:
            indexer = link_match.group(1).strip()
    if not indexer:
        gear_match = re.search(r'⚙️\s*([^\n💾]+)', raw_title_unquoted)
        if gear_match:
            indexer = gear_match.group(1).strip()
    if not indexer and info_line:
        clean = re.sub(r'[\d.,]+\s*(?:GB|MB|TB)', '', info_line, flags=re.IGNORECASE)
        clean = re.sub(r'(?:👤|👥|S:|P:|Peers:)\s*\d+', '', clean, flags=re.IGNORECASE)
        clean = clean.replace('👤', '').replace('💾', '').replace('⚙️', '').replace('📦', '').replace('🔗', '').strip(' |-,')
        if clean and not is_valid_filename(clean): indexer = clean
    # Garbage validation: none, emoji, codec terms, GB/MB
    if indexer and (indexer.lower() == 'none' or re.search(r'[🗂️⚙️💾📅🏴]', indexer)):
        indexer = ''
            
    # 6. Calitate
    quality = _extract_quality_from_string(raw_name)
    if not quality or quality == 'SD':
        quality = _extract_quality_from_string(filename) or 'SD'
        
    stream_obj = {
        'name': filename, 
        'url': url if url.startswith('magnet:') else build_stream_url(url),
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
            'provider': addon_name,
            'indexer': indexer,
            'seeders': seeders,
            'releaseGroup': _extract_release_group(filename),
            'quality': quality,
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
        log(f"[{addon_name.upper()}] Error: {e}", xbmc.LOGERROR)
        
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
            
            # log(f"[AIO] Cerere API: {search_link} | type: {m_type} | id: {st_id} | timeout: {req_timeout}s")
            
            r = get_shared_session().get(
                search_link, params={'type': m_type, 'id': st_id},
                auth=aio_auth, headers=headers, timeout=req_timeout, verify=False
            )
            if r.status_code == 200: 
                res = r.json().get('data', {}).get('results', [])
                log(f"[AIO] ✓ Success! Am primit {len(res)} surse de la server.")
                return res
            else:
                log(f"[AIO] Error HTTP {r.status_code}: {r.text[:100]}", xbmc.LOGWARNING)
        except Exception as e: 
            log(f"[AIO] Error conexiune: {e}", xbmc.LOGERROR)
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
                
            # BLOCARE FIȘIERE GUNOI / MALWARE / NON-VIDEO / AUDIO
            bad_extensions = [
                '.iso', '.zip', '.rar', '.7z', '.tar', '.gz', '.zipx', '.arj',
                '.txt', '.nfo', '.jpg', '.png', '.pdf',
                '.exe', '.bat', '.cmd', '.scr', '.msi', '.ps1', '.vbs', '.js', '.jar', '.com', '.pif', '.reg', '.dll', '.sys', '.lnk',
                '.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.wma', '.ape', '.alac'
            ]
            title_lower = title.lower()
            if any(title_lower.endswith(ext) for ext in bad_extensions) or any(f"{ext} " in title_lower for ext in bad_extensions):
                continue

            # FILTRU WEB (Opțional din setări) - DOAR PENTRU RD
            try:
                if ADDON.getSetting('filter_web_sources') == 'true':
                    # Extragem service-ul mai devreme pentru a filtra doar RD
                    aio_service = str(item.get('service', '')).strip().lower()
                    if aio_service == 'realdebrid' or aio_service == 'rd':
                        if _is_web_source(title) or _is_web_source(full_title_raw):
                            # log(f"[FILTER-WEB] Excluding WEB RD AIO source: {title[:50]}...")
                            continue
            except:
                pass

            res_tag = "SD"
            check_text = (str(parsed.get('resolution', '')) + ' ' + full_title_raw + ' ' + title).upper()
            
            # --- FIX: Multi-rezoluție și izolare grupuri (inclusiv 4KHDHUB) ---
            clean_text = check_text.replace('DS4K', '').replace('4KDS', '').replace('SDR4K', '').replace('HDR4K', '').replace('4KHDHUB', '')
            
            res_count = sum(1 for r in ['2160P', '1080P', '720P', '480P', '360P'] if r in check_text)
            if '4K' in clean_text and '2160P' not in check_text: res_count += 1
            
            if res_count >= 2: res_tag = 'SD'
            elif any(x in check_text for x in['720P', '720I']): res_tag = '720p'
            elif any(x in check_text for x in ['1080P', '1080I', 'FHD']): res_tag = '1080p'
            elif any(x in check_text for x in['2160P', '2160', 'UHD']) or '4K' in clean_text: res_tag = '4K'
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
            # Indexer — prioritate 1: decodează `t` din URL (cel mai autoritar, suprascrie AIO)
            indexer = ''
            if '?t=' in play_url:
                try:
                    import base64, json as _json
                    _t = play_url.split('?t=')[1].split('|')[0].split('&')[0]
                    _t = _t + '=='
                    _decoded = _json.loads(base64.urlsafe_b64decode(_t).decode('utf-8'))
                    _t_idxer = str(_decoded.get('indexer', '')).strip()
                except:
                    _t_idxer = ''
                if _t_idxer:
                    indexer = _t_idxer
            # Prioritate 2: din AIO server
            if not indexer:
                indexer = str(item.get('indexer', '')).strip()
            # Garbage validation: none, emoji, GB/MB
            if indexer and (indexer.lower() == 'none' or re.search(r'[🗂️⚙️💾📅🏴]', indexer) or re.search(r'\d+(\.\d+)?\s*(GB|MB|TB)', indexer, re.I)):
                indexer = ''
            # Prioritate 3: din titlu (🗂️ altHUB)
            if not indexer:
                _idx_m = re.search(r'🗂️\s*([^\n📅🏴]+)', full_title_raw)
                if _idx_m:
                    indexer = _idx_m.group(1).strip()
            # Fallback 3: extrage addonul din description după ⛉
            if not source_addon:
                _a_m = re.search(r'⛉\s*([^·\n]+)', str(item.get('description', '')))
                if _a_m:
                    source_addon = _a_m.group(1).strip()
            
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
                    'releaseGroup': release_group,
                    'quality': res_tag,
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

        # log(f"[TORRENTIO] Caut pe: {api_url[:80]}...")
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
                    'title': filename, # Saved here to be found by Wyzie (Subtitles)
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
                        'releaseGroup': _extract_release_group(filename),
                        'quality': quality,
                    }
                }
                found_streams.append(stream_obj)

            log(f"[TORRENTIO] Found: {len(found_streams)} sources.")
            return found_streams
    except Exception as e:
        log(f"[TORRENTIO] Error: {e}", xbmc.LOGERROR)

    return None


# =============================================================================
# =============================================================================
# SCRAPER PRIMESRC.ME ([PSM])
# =============================================================================
THRAX_KEY = "7d9f4987bcd1a2026e6a422931bd7dbff0060977d189f37fa5727d9288b4abbb"
THRAX_HEADERS = {"X-Thrax-Key": THRAX_KEY}



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
    If tmdb_id is specified, it is passed to Thrax for automatic caching."""
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
        
    try:
        api_url = "https://streamdata.vaplayer.ru/api.php"
        params = {
            "imdb": imdb_id,
            "type": "movie" if content_type == 'movie' else 'tv'
        }
        if content_type == 'tv':
            params['season'] = season
            params['episode'] = episode

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://nextgencloudfabric.com/",
            "Origin": "https://nextgencloudfabric.com",
            "Accept": "*/*",
            "Accept-Language": "ro-RO,ro-GB;q=0.9,en;q=0.8"
        }
        
        session = get_shared_session()
        resp = session.get(api_url, params=params, headers=headers, timeout=10, verify=False)
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        if not data or data.get('status_code') != '200':
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
                    'url': build_stream_url(master_url, referer="https://nextgencloudfabric.com/"),
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
                    'url': build_stream_url(v['url'], referer="https://nextgencloudfabric.com/"),
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
# SCRAPER FLIXER (MULTI-SERVER FIXED - KODI HLS BYPASS + TV SHOWS)
# =============================================================================
def scrape_flixer(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_flixer') == 'false': return None
    tmdb_id = _get_tmdb_id_internal(imdb_id)
    if not tmdb_id: return None
    
    from urllib.parse import quote
    
    try:
        session = get_shared_session()
        _UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0'
        headers = {
            'User-Agent': _UA,
            'Referer': 'https://movie-scraper-theta-11.vercel.app/',
            'Origin': 'https://movie-scraper-theta-11.vercel.app'
        }
        
        flixer_type = 'tv' if content_type in ('tv', 'show', 'episode', 'tvshow') else 'movie'
        streams = []
        
        display_title = title_query if title_query else "Flixer Stream"
        if year_query and flixer_type == 'movie': display_title += f" ({year_query})"
        if flixer_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"
        
        # --- PARTEA 1: Vynx API (currently broken - missing WASM + API key) ---
        try:
            health = session.get("https://media-proxy.vynx-3b3.workers.dev/flixer/health", timeout=5, verify=False)
            if health.status_code == 200:
                h_data = health.json()
                if h_data.get('wasmLoaded') and h_data.get('hasApiKey'):
                    url = f"https://media-proxy.vynx-3b3.workers.dev/flixer/extract?tmdbId={tmdb_id}&type={flixer_type}"
                    if flixer_type == 'tv' and season and episode:
                        url += f"&season={int(season)}&episode={int(episode)}"
                    r = session.get(url, headers=headers, timeout=10, verify=False)
                    if r.status_code == 200:
                        data = r.json()
                        if data.get('success') and data.get('sources'):
                            for source in data['sources']:
                                source_url = source.get('url')
                                if not source_url: continue
                                referer = source.get('referer', 'https://hexa.su/')
                                stream_referer = referer if referer else "https://hexa.su/"
                                source_type = source.get('type', 'hls')
                                if source_type == 'hls' or '.m3u8' in source_url:
                                    custom_headers = {'Referer': stream_referer, 'User-Agent': _UA, 'Origin': 'https://hexa.su'}
                                    variants = _parse_m3u8_variants(source_url, custom_headers=custom_headers)
                                    if variants:
                                        for var in variants:
                                            res_val = var.get('resolution', 'UNKNOWN')
                                            quality = _get_quality_from_res(res_val)
                                            var_kodi_url = f"{var['url']}|User-Agent={quote(_UA)}&Referer={quote(stream_referer)}&Origin=https://hexa.su&Connection=keep-alive"
                                            streams.append({
                                                'name': f"Flixer | {source.get('server', 'Auto')} ({res_val})",
                                                'url': var_kodi_url,
                                                'quality': quality,
                                                'title': display_title,
                                                'size': '',
                                                'info': f"{source.get('server', 'Auto')} | {res_val}",
                                                'provider_id': 'flixer'
                                            })
                                        continue
                                quality = '1080p' if source.get('quality') == '1080p' else '720p' if source.get('quality') == '720p' else 'SD'
                                if source.get('quality') == 'auto': quality = '1080p'
                                kodi_url = f"{source_url}|User-Agent={quote(_UA)}&Referer={quote(stream_referer)}&Origin=https://hexa.su&Connection=keep-alive"
                                streams.append({
                                    'name': f"Flixer | {source.get('server', 'Auto')}",
                                    'url': kodi_url,
                                    'quality': quality,
                                    'title': display_title,
                                    'size': '',
                                    'info': source.get('server', 'Auto'),
                                    'provider_id': 'flixer'
                                })
        except Exception as e:
            log(f"[FLIXER-VYNX] API broken (missing WASM/key), skipping: {e}")

        # --- PARTEA 2: SERVER SECUNDAR (VideoDB) - Filme + Seriale ---
        try:
            if flixer_type == 'movie':
                vdb_embed = f"https://videodb.cloud/embed/player.php?type=movie&id={tmdb_id}"
                api_url = f"https://videodb.stream/file/play?type=movie&id={tmdb_id}&name=slug&lang=ru&p=l.playlist"
            else:
                s_num = int(season)
                e_num = int(episode)
                vdb_embed = f"https://videodb.cloud/embed/splayer.php?type=serial&id={tmdb_id}&season={s_num}&episode={e_num}"
                api_url = f"https://videodb.stream/file/play?type=serial&id={tmdb_id}&name=serial&season={s_num}&episode={e_num}&lang=ru&p=l.playlist"
                
            r_vdb = session.get(vdb_embed, headers={'Referer': 'https://www.tenies.site/', 'User-Agent': _UA}, timeout=8, verify=False)
            
            if r_vdb.status_code == 200:
                iframe_match = re.search(r'<iframe[^>]+src=["\'](https://videodb\.stream/play/[^"\']+)["\']', r_vdb.text)
                if iframe_match:
                    iframe_url = iframe_match.group(1)
                    
                    v_headers = {
                        'User-Agent': _UA,
                        'Referer': iframe_url,
                        'Accept': 'application/json, text/javascript, */*; q=0.01'
                    }
                    
                    r_api = session.get(api_url, headers=v_headers, timeout=8, verify=False)
                    if r_api.status_code == 200:
                        v_data = r_api.json()
                        target_files = []
                        
                        if flixer_type == 'movie':
                            if isinstance(v_data, list) and len(v_data) > 0:
                                f_url = v_data[0].get('file')
                                if f_url: target_files.append((f_url, '1080p'))
                        else:
                            # Traversare JSON pentru seriale (Sezoane -> Episoade)
                            if isinstance(v_data, list):
                                target_id = f"{s_num}-{e_num}"
                                for s_data in v_data:
                                    for ep_data in s_data.get('folder', []):
                                        if str(ep_data.get('id')) == target_id:
                                            f_str = ep_data.get('file', '')
                                            if f_str:
                                                # Extrage MP4 Direct (SD/HD separate prin virgulă)
                                                if ',' in f_str or '[HD]' in f_str or '[SD]' in f_str:
                                                    for part in f_str.split(','):
                                                        url_match = re.search(r'(https?://[^;]+)', part)
                                                        if url_match:
                                                            target_files.append((url_match.group(1), '1080p' if '[HD]' in part else 'SD'))
                                                else:
                                                    # Master HLS (multi-rezoluție)
                                                    target_files.append((f_str, '1080p'))
                                            break
                        
                        # Generăm linkurile pentru Kodi
                        for file_url, q_label in target_files:
                            if file_url.endswith('.txt') or 'master' in file_url:
                                if '?' in file_url:
                                    file_url += "&dummy=.m3u8"
                                else:
                                    file_url += "?dummy=.m3u8"
                                    
                                kodi_vdb_url = f"{file_url}|User-Agent={quote(_UA)}&Referer={quote(iframe_url)}&Origin=https://videodb.stream&Connection=keep-alive"
                                streams.append({
                                    'name': f"Flixer (VideoDB) | Multi-Rezolutie",
                                    'url': kodi_vdb_url,
                                    'quality': '1080p',
                                    'title': display_title,
                                    'size': '',
                                    'info': "Choose quality in Kodi video settings",
                                    'provider_id': 'flixer'
                                })
                            else:
                                kodi_vdb_url = f"{file_url}|User-Agent={quote(_UA)}&Referer={quote(iframe_url)}&Origin=https://videodb.stream&Connection=keep-alive"
                                streams.append({
                                    'name': f"Flixer (VideoDB) | {q_label}",
                                    'url': kodi_vdb_url,
                                    'quality': q_label,
                                    'title': display_title,
                                    'size': '',
                                    'info': f"VideoDB | {q_label}",
                                    'provider_id': 'flixer'
                                })
        except Exception as e:
            log(f"[FLIXER-VIDEODB] Error: {e}")

        return streams if streams else None
    except Exception as e:
        log(f"[FLIXER] Fatal Error: {e}")
        return None


# =============================================================================
# SCRAPER CINEFREAK (cinefreak.nl - Direct MKV/MP4 Streams via CineCloud)
# =============================================================================
CINEFREAK_BASE = 'https://cinefreak.nl'
CINECLOUD_BASE = 'https://new5.cinecloud.site'

def _cinefreak_fetch_text(url, timeout=15):
    try:
        hdrs = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        r = get_shared_session().get(url, headers=hdrs, timeout=timeout, verify=False)
        if r.status_code == 200:
            return r.text
    except: pass
    return None

def _cinefreak_fetch_json(url, timeout=15):
    try:
        text = _cinefreak_fetch_text(url, timeout)
        if text:
            return json.loads(text)
    except: pass
    return None

def _cinefreak_parse_quality(label):
    if not label: return 'HD'
    s = str(label).lower()
    if '2160' in s or '4k' in s: return '4K'
    if '1080' in s: return '1080p'
    if '720' in s: return '720p'
    if '480' in s: return '480p'
    return 'HD'

def _cinefreak_decode_generate_id(encoded):
    try:
        raw = base64.b64decode(encoded).decode('utf-8', errors='replace')
        if raw.endswith('newgo32'):
            raw = raw[:-7]
        return raw
    except: return None

def _cinefreak_extract_fsl_url(html):
    idx = html.find('href="https://pub-')
    if idx == -1: return None
    start = idx + 6
    end = html.find('"', start)
    if end == -1: return None
    url = html[start:end]
    url = url.replace('&amp;', '&')
    return url

def _cinefreak_resolve_fsl(decoded_url):
    if not decoded_url: return None
    hash_part = None
    f_idx = decoded_url.find('/f/')
    x_idx = decoded_url.find('/x/')
    if f_idx >= 0: hash_part = decoded_url[f_idx + 3:]
    elif x_idx >= 0: hash_part = decoded_url[x_idx + 3:]
    if not hash_part: return None
    fsl_url = f'{CINECLOUD_BASE}/f/{hash_part}'
    html = _cinefreak_fetch_text(fsl_url, timeout=10)
    if not html: return None
    return _cinefreak_extract_fsl_url(html)

def _cinefreak_extract_movie_qualities(html):
    if not html: return []
    parts = html.split('dlbtn-container')
    results = []
    for i in range(1, len(parts)):
        prev_part = parts[i - 1]
        current = parts[i]
        m = re.search(r'href="(?:https?://[^"]*?)?/generate\.php\?id=([a-zA-Z0-9+/=]+)"', current)
        if not m: continue
        enc_id = m.group(1)
        dec_url = _cinefreak_decode_generate_id(enc_id)
        if not dec_url or dec_url.find('/f/') == -1: continue
        label = ''
        qm = re.search(r'</span>\s*([^<]*?(?:2160|1080|720|480|4K)[^<]*?)\s*\[', prev_part, re.IGNORECASE)
        if qm: label = qm.group(1).strip()
        if not label:
            qm = re.search(r'\b(?:4K\s*2160p|UHD|2160p|1080p|720p|480p|SD|HD)\b', prev_part, re.IGNORECASE)
            if qm: label = qm.group(0)
        if not label: label = dec_url
        quality = _cinefreak_parse_quality(label)
        dup = False
        for r in results:
            if r['decodedUrl'] == dec_url: dup = True; break
        if dup: continue
        results.append({'encodedId': enc_id, 'decodedUrl': dec_url, 'label': label, 'quality': quality})
    return results

def _cinefreak_extract_episode_qualities(html, episode_num):
    if not html: return []
    cards = html.split('<div class="ep-card"')
    target_html = None
    for card in cards[1:]:
        m = re.search(r'episode-badge[^>]*>Episode\s*(\d+)', card, re.IGNORECASE)
        if m and int(m.group(1)) == episode_num:
            target_html = card
            break
    if not target_html: return []
    links = re.findall(r'<a[^>]*href="(?:https?://[^"]*?)?/generate\.php\?id=([a-zA-Z0-9+/=]+)"[^>]*>([^<]*)</a>', target_html)
    results = []
    for enc_id, link_label in links:
        dec_url = _cinefreak_decode_generate_id(enc_id)
        if not dec_url or dec_url.find('/f/') == -1: continue
        label = link_label.strip()
        quality = _cinefreak_parse_quality(label)
        dup = False
        for r in results:
            if r['decodedUrl'] == dec_url: dup = True; break
        if dup: continue
        results.append({'encodedId': enc_id, 'decodedUrl': dec_url, 'label': label or quality, 'quality': quality})
    return results

def _cinefreak_filter_qualities(qualities):
    filtered = []
    seen_q = set()
    for q in qualities:
        if q['quality'] in ('480p', 'SD'): continue
        if q['quality'] in seen_q: continue
        seen_q.add(q['quality'])
        filtered.append(q)
    priority = {'4K': 0, '1080p': 1, '720p': 2, 'HD': 3}
    filtered.sort(key=lambda x: priority.get(x['quality'], 99))
    return filtered

def _cinefreak_match_result(search_title, search_year, results, target_season=None):
    if not results: return None
    search_lower = str(search_title or '').lower().strip()
    search_year_str = str(search_year or '')

    def score_item(item):
        s = 0
        title = str(item.get('title', '')).lower().strip()
        url = str(item.get('url', ''))
        # titleStartsWith equivalent
        if title.startswith(search_lower) or title.startswith(search_lower + ' ') or ('(' + search_lower + ')') in title:
            s += 10
        # urlContains: count how many significant words from title appear in URL
        words = [w for w in re.sub(r'[^a-z0-9\s]', ' ', search_lower).split() if len(w) > 2]
        if words:
            url_lower = url.lower().replace(' ', '-')
            word_matches = sum(1 for w in words if w in url_lower)
            s += (word_matches / len(words)) * 5
        # wordMatchScore
        if words:
            word_hits = 0
            for w in words:
                if re.search(r'\b' + re.escape(w) + r'\b', title, re.IGNORECASE):
                    word_hits += 1
            s += word_hits / len(words)
        # year in title
        if search_year_str and search_year_str in title:
            s += 3
        return s

    # For TV with season, prefer results mentioning the season
    if target_season:
        season_pattern = rf'(?:season|s)\s*{target_season}\b'
        best = None
        best_score = -1
        for item in results:
            title = str(item.get('title', ''))
            if re.search(season_pattern, title, re.IGNORECASE):
                sc = score_item(item) + 10
                if sc > best_score:
                    best_score = sc
                    best = item
        if best:
            return best

    # Find best match overall
    best = None
    best_score = -1
    for item in results:
        sc = score_item(item)
        if sc > best_score:
            best_score = sc
            best = item
    if best and best_score >= 3:
        return best
    return None

def scrape_cinefreak(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_cinefreak') == 'false':
        return None
    if not title_query:
        return None

    display_title = title_query
    if year_query and content_type == 'movie':
        display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode:
        display_title += f" S{int(season):02d}E{int(episode):02d}"

    # log(f"[CINEFREAK] Searching: {title_query} ({year_query})")

    try:
        # Step 1: Search via WP JSON API
        search_url = f"{CINEFREAK_BASE}/wp-json/wp/v2/search?search={quote(title_query)}&per_page=10"
        results = _cinefreak_fetch_json(search_url)
        if not results:
            log(f"[CINEFREAK] No search results")
            return None

        search_items = []
        for r in results:
            r_title = str(r.get('title', '')).replace('Download ', '', 1).strip()
            r_url = str(r.get('url', ''))
            if not r_title or not r_url: continue
            search_items.append({'id': r.get('id'), 'title': r_title, 'url': r_url})

        if not search_items:
            log(f"[CINEFREAK] No valid search items")
            return None

        # If few results, retry with title + year
        if len(search_items) < 3:
            retry_url = f"{CINEFREAK_BASE}/wp-json/wp/v2/search?search={quote(title_query)} {quote(str(year_query or ''))}&per_page=10"
            retry_results = _cinefreak_fetch_json(retry_url)
            if retry_results:
                for r in retry_results:
                    r_title = str(r.get('title', '')).replace('Download ', '', 1).strip()
                    r_url = str(r.get('url', ''))
                    if not r_title or not r_url: continue
                    dup = any(s['url'] == r_url for s in search_items)
                    if not dup:
                        search_items.append({'id': r.get('id'), 'title': r_title, 'url': r_url})

        # Step 2: Match by title/year
        target_season = int(season) if content_type == 'tv' and season else None
        matched = _cinefreak_match_result(title_query, year_query, search_items, target_season)
        if not matched:
            log(f"[CINEFREAK] No match found for '{title_query}'")
            return None

        log(f"[CINEFREAK] Matched: {matched['title']} -> {matched['url']}")

        # Step 3: Fetch post page
        post_url = matched['url']
        if not post_url.startswith('http'):
            post_url = CINEFREAK_BASE + ('/' if not post_url.startswith('/') else '') + post_url
        html = _cinefreak_fetch_text(post_url)
        if not html:
            log(f"[CINEFREAK] Failed to fetch post page")
            return None

        # Step 4: Extract quality links
        if content_type == 'tv' and episode:
            ep_num = int(episode)
            qualities = _cinefreak_extract_episode_qualities(html, ep_num)
        else:
            qualities = _cinefreak_extract_movie_qualities(html)

        if not qualities:
            log(f"[CINEFREAK] No quality links found")
            return None

        # Step 5: Filter (remove 480p/SD) and sort
        filtered = _cinefreak_filter_qualities(qualities)
        if not filtered:
            log(f"[CINEFREAK] No usable qualities after filtering")
            return None

        log(f"[CINEFREAK] Qualities: {', '.join(q['quality'] for q in filtered)}")

        # Step 6: Resolve each quality's stream URL
        streams = []
        ep_label = ''
        if content_type == 'tv' and season and episode:
            sn = int(season); en = int(episode)
            ep_label = f"S{sn:02d}E{en:02d} "

        for q in filtered:
            final_url = _cinefreak_resolve_fsl(q['decodedUrl'])
            if not final_url:
                log(f"[CINEFREAK] Failed to resolve FSL for {q['quality']}")
                continue
            streams.append({
                'name': 'CineFreak',
                'url': final_url,
                'quality': q['quality'],
                'title': f"{display_title} [{q['quality']}]",
                'size': '',
                'info': f"{q['quality']} | FSL",
                'provider_id': 'cinefreak',
                'custom_headers': {'Referer': f'{CINECLOUD_BASE}/'}
            })

        log(f"[CINEFREAK] Total: {len(streams)} streams")
        return streams if streams else None

    except Exception as e:
        log(f"[CINEFREAK] Error: {e}")
        return None


# =============================================================================
# SCRAPER MOVIES4U (movies4u.finance - Wordpress + HubCloud/m4uplay streams)
# =============================================================================
M4U_DOMAINS_URL = 'https://raw.githubusercontent.com/phisher98/TVVVV/refs/heads/main/domains.json'
M4U_FALLBACK_URL = 'https://new1.movies4u.finance'
M4U_TMDB_KEY = '1865f43a0549ca50d341dd9ab8b29f49'
M4U_HUBCLOUD_API = 'https://hc-zf3c.vercel.app'

def _m4u_fetch_json(url, headers=None):
    try:
        r = get_shared_session().get(url, headers=headers or {}, timeout=15, verify=False)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"[M4U] fetch_json error: {e}")
    return None

def _m4u_fetch_text(url, headers=None):
    try:
        r = get_shared_session().get(url, headers=headers or {}, timeout=15, verify=False)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        log(f"[M4U] fetch_text error: {e}")
    return None

def _m4u_get_base_url():
    try:
        data = _m4u_fetch_json(M4U_DOMAINS_URL)
        if data:
            return data.get('domain') or data.get('url') or M4U_FALLBACK_URL
    except:
        pass
    return M4U_FALLBACK_URL

def _m4u_extract_quality(name):
    ql = (name or '').lower()
    if re.search(r'\b(2160p|4k|uhd)\b', ql): return '4K'
    if re.search(r'\b1080p\b', ql): return '1080p'
    if re.search(r'\b720p\b', ql): return '720p'
    if re.search(r'\b480p\b', ql): return '480p'
    if re.search(r'\b360p\b', ql): return '360p'
    return 'HD'

def _m4u_to_base(num, base):
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    if num == 0:
        return '0'
    result = ''
    n = num
    while n > 0:
        result = chars[n % base] + result
        n //= base
    return result

def _m4u_unpack_eval(script):
    m = re.search(r"\}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'\s*\.\s*split\s*\(\s*['\"]\|['\"]\s*\)", script, re.DOTALL)
    if not m:
        return None
    p_enc = m.group(1)
    radix = int(m.group(2))
    count = int(m.group(3))
    words = m.group(4).split('|')
    result = p_enc
    for i in range(min(count, len(words))):
        if words[i]:
            result = re.sub(r'\b' + re.escape(_m4u_to_base(i, radix)) + r'\b', words[i], result)
    return result

def _m4u_extract_m3u8(page_url, headers):
    html = _m4u_fetch_text(page_url, headers)
    if not html:
        return None
    m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html, re.I)
    if m:
        return m.group(0)
    m = re.search(r'https?://[^\s"\'<>]+master\.txt[^\s"\'<>]*', html, re.I)
    if m:
        return m.group(0).replace('master.txt', 'master.m3u8')
    m = re.search(r'/(?:3o|stream)/[^\s"\'<>]+(?:m3u8|txt)', html, re.I)
    if m:
        return 'https://m4uplay.store' + m.group(0)
    m4u_base = 'https://m4uplay.store'
    for m_src in re.finditer(r'https?://[^"\']*?morencius\.com/(?:file|embed|download)/[^"\'\s<>]+', html, re.I):
        morencius_url = m_src.group(0)
        morencius_html = _m4u_fetch_text(morencius_url, headers)
        if not morencius_html:
            continue
        for m_sc in re.finditer(r'<script[^>]*>(.*?)</script>', morencius_html, re.DOTALL | re.I):
            inner = m_sc.group(1)
            if 'eval(function(p,a,c,k,e,d)' not in inner:
                continue
            decoded = _m4u_unpack_eval(inner)
            if not decoded:
                continue
            if 'links.hls4' in decoded or 'links.hls3' in decoded or 'links.hls2' in decoded:
                m3u = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', decoded, re.I)
                if m3u:
                    return m3u.group(0)
                m3u = re.search(r'(https?://[^\s"\'<>]+master\.txt[^\s"\'<>]*)', decoded, re.I)
                if m3u:
                    return m3u.group(0).replace('master.txt', 'master.m3u8')
                m_rel = re.search(r'"(/[^\s"\'<>]*master\.m3u8[^\s"\'<>]*)"', decoded, re.I)
                if m_rel:
                    parsed = urlparse(morencius_url)
                    return f"{parsed.scheme}://{parsed.netloc}" + m_rel.group(1)
    return None

def _m4u_parse_article_links(html, base):
    links = []
    for m in re.finditer(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE):
        for a in re.finditer(r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', m.group(1), re.DOTALL | re.IGNORECASE):
            href = a.group(1).strip()
            text = re.sub(r'<[^>]+>', '', a.group(2)).strip()
            if href and text:
                if not href.startswith('http'):
                    href = base + ('/' if not href.startswith('/') else '') + href
                links.append({'href': href, 'text': text})
    return links

def _m4u_parse_heading_links(html, base):
    links = []
    for tag in ('h2', 'h3'):
        for m in re.finditer(r'<{0}[^>]*>(.*?)</{0}>'.format(tag), html, re.DOTALL | re.IGNORECASE):
            for a in re.finditer(r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', m.group(1), re.DOTALL | re.IGNORECASE):
                href = a.group(1).strip()
                text = re.sub(r'<[^>]+>', '', a.group(2)).strip()
                if href and text:
                    if not href.startswith('http'):
                        href = base + ('/' if not href.startswith('/') else '') + href
                    links.append({'href': href, 'text': text})
    for a in re.finditer(r'<a[^>]+rel=["\']bookmark["\'][^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        href = a.group(1).strip()
        text = re.sub(r'<[^>]+>', '', a.group(2)).strip()
        if href and text:
            if not href.startswith('http'):
                href = base + ('/' if not href.startswith('/') else '') + href
            links.append({'href': href, 'text': text})
    return links

def _m4u_parse_stream_links(html):
    links = []
    seen = set()
    keywords = ('hubcloud', 'gdrive', 'gdflix', 'pixeldrain', 'm4uplay.store', 'm4ulinks.com')

    # Method 1: parse h4 + download-buttons pairs (structured quality listing)
    for m_section in re.finditer(
        r'<h4[^>]*>(.*?)</h4>\s*<div[^>]*class=["\'][^"\']*downloads?[_-]?btns?[^"\']*["\'][^>]*>(.*?)</div>',
        html, re.DOTALL | re.IGNORECASE
    ):
        heading = re.sub(r'<[^>]+>', '', m_section.group(1)).strip()
        btns = m_section.group(2)
        quality = _m4u_extract_quality(heading)

        for a in re.finditer(r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>', btns, re.DOTALL | re.IGNORECASE):
            href = a.group(1).strip()
            if not href:
                continue
            if any(k in href.lower() for k in keywords):
                key = (href, quality)
                if key not in seen:
                    seen.add(key)
                    links.append({'href': href, 'text': heading, 'quality': quality})

    # Method 2: fallback — scan all <a> tags for keywords
    if not links:
        for a in re.finditer(r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            href = a.group(1).strip()
            text = re.sub(r'<[^>]+>', '', a.group(2)).strip()
            if not href or href in seen:
                continue
            if any(k in href.lower() for k in keywords):
                seen.add(href)
                links.append({'href': href, 'text': text, 'quality': _m4u_extract_quality(text)})

    return links

def scrape_movies4u(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_movies4u') == 'false':
        return None
    if not title_query:
        return None

    display_title = title_query
    if year_query and content_type == 'movie':
        display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode:
        display_title += f" S{int(season):02d}E{int(episode):02d}"

    # log(f"[MOVIES4U] Searching: {title_query} ({year_query})")

    try:
        base = _m4u_get_base_url()
        # log(f"[MOVIES4U] Using base: {base}")

        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        headers = {'User-Agent': ua, 'Referer': base + '/'}

        # Step 1: Search movies4u by title (site does NOT index by IMDb ID)
        search_url = f"{base}/?s={quote(title_query)}"
        html = _m4u_fetch_text(search_url, headers)
        if not html:
            log(f"[MOVIES4U] Search returned no HTML")
            return None

        # Parse article links
        links = _m4u_parse_article_links(html, base)
        if not links:
            links = _m4u_parse_heading_links(html, base)
        if not links:
            log(f"[MOVIES4U] No links found in search results")
            return None

        # Step 3: Find matching link
        target = None
        title_lower = title_query.lower()
        for link in links:
            if title_lower in link['text'].lower() or title_lower in link['href'].lower():
                target = link['href']
                break
        if not target:
            target = links[0]['href']

        log(f"[MOVIES4U] Matched: {target}")

        # Step 4: Fetch movie page and extract stream links
        page_html = _m4u_fetch_text(target, headers)
        if not page_html:
            return None

        stream_links = _m4u_parse_stream_links(page_html)

        if not stream_links:
            log(f"[MOVIES4U] No stream links found on page")
            return None

        log(f"[MOVIES4U] Found {len(stream_links)} stream links")

        # Step 4.5: Expand m4ulinks.com links into per-quality hubcloud sub-links
        before = len(stream_links)
        expanded = []
        expanded_m4u = set()
        for sl in stream_links:
            if 'm4ulinks.com' in sl['href']:
                m4u_key = sl['href'].rstrip('/')
                if m4u_key in expanded_m4u:
                    continue
                expanded_m4u.add(m4u_key)
                sub_html = _m4u_fetch_text(sl['href'], headers)
                if sub_html:
                    sub_links = _m4u_parse_stream_links(sub_html)
                    expanded.extend(sub_links)
            else:
                expanded.append(sl)
        stream_links = expanded
        if before != len(stream_links):
            log(f"[MOVIES4U] After m4ulinks expansion: {len(stream_links)} stream links (was {before})")

        # Step 5: Resolve each link
        streams = []
        ep_label = ''
        if content_type == 'tv' and season and episode:
            ep_label = f"S{int(season):02d}E{int(episode):02d} "

        for sl in stream_links:
            try:
                href = sl['href']
                text = sl['text']
                quality = sl.get('quality') or ''

                if 'm4uplay.store' in href:
                    stream_url = _m4u_extract_m3u8(href, headers)
                    if not stream_url:
                        continue
                    custom_hdrs = {'Referer': 'https://m4uplay.store/'}
                elif 'hubcloud' in href.lower():
                    api_url = f"{M4U_HUBCLOUD_API}/api/extract?url={quote(href)}"
                    api_data = _m4u_fetch_json(api_url)
                    if not api_data or not api_data.get('links'):
                        continue
                    best = api_data['links'][0]
                    stream_url = best.get('url', '')
                    if not stream_url:
                        continue
                    custom_hdrs = {'User-Agent': ua}
                elif 'gdflix' in href.lower():
                    gd_results = _process_gdflix_page(href, quality, display_title, 'Movies4U')
                    if not gd_results:
                        continue
                    for gd in gd_results:
                        gd['provider_id'] = 'movies4u'
                        label = quality
                        if text and quality in text:
                            extra = text.split(quality, 1)[1].strip().lstrip('-').strip()
                            if extra:
                                label = f"{quality} {extra}"
                        gd['title'] = f"{display_title} [{label}]"
                        gd['custom_headers'] = {'User-Agent': ua}
                        streams.append(gd)
                    continue
                else:
                    continue

                quality = quality or _m4u_extract_quality(text) or _m4u_extract_quality(stream_url) or 'HD'
                if quality in ('480p', '360p'):
                    continue

                # Use heading text for richer label: "1080p HEVC [1.8GB]"
                label = quality
                if text and quality in text:
                    extra = text.split(quality, 1)[1].strip().lstrip('-').strip()
                    if extra:
                        label = f"{quality} {extra}"

                streams.append({
                    'name': 'Movies4U',
                    'url': stream_url,
                    'quality': quality,
                    'title': f"{display_title} [{label}]",
                    'size': '',
                    'info': label,
                    'provider_id': 'movies4u',
                    'custom_headers': custom_hdrs
                })

            except Exception as e:
                log(f"[MOVIES4U] Error resolving link: {e}")

        log(f"[MOVIES4U] Total: {len(streams)} streams")
        return streams if streams else None

    except Exception as e:
        log(f"[MOVIES4U] Error: {e}")
        return None


# =============================================================================
# SCRAPER FSHD (filmeserialehd.net) — HTML + AJAX + HLS multi-server/variant
# =============================================================================
def _fshd_process_server(server_link, server_name, target_url, display_title):
    """Încearcă un server FSHD: extrage HLS, parsează variante. Returnează listă de streamuri."""
    results = []
    s = get_shared_session()
    try:
        r = s.get(server_link, headers={'User-Agent': get_random_ua(), 'Referer': target_url}, timeout=20, verify=False)
        html = r.text

        # Variabile JS posibile: var HLS, var videoUrl, var source, player.src
        master_url = None
        for pattern in [
            r'var\s+HLS\s*=\s*"([^"]+)"',
            r"var\s+HLS\s*=\s*'([^']+)'",
            r'var\s+hls\s*=\s*"([^"]+)"',
            r'source["\']*\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'src["\']*\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        ]:
            m = re.search(pattern, html, re.I)
            if m:
                master_url = m.group(1)
                break

        if not master_url:
            log(f"[FSHDNET] No HLS found in {server_name} page")
            return results

        # Încearcă variante multiple din master m3u8
        try:
            variants = _parse_m3u8_variants(master_url, custom_headers={
                'User-Agent': get_random_ua(), 'Referer': server_link
            })
            if variants:
                for v in variants:
                    v_res = v.get("resolution", "UNKNOWN")
                    q_label = _get_quality_from_res(v_res)
                    results.append({
                        'name': f"FSHD | {server_name} | {v_res}",
                        'url': build_stream_url(v['url'], referer=server_link),
                        'quality': q_label,
                        'title': display_title,
                        'size': '',
                        'info': f'HLS {v_res}',
                        'provider_id': 'fshdnet'
                    })
                return results
        except:
            pass

        # Fallback: un singur stream
        quality = '1080p'
        if '2160' in master_url or '4k' in master_url.lower(): quality = '4K'
        elif '1080' in master_url: quality = '1080p'
        elif '720' in master_url: quality = '720p'
        results.append({
            'name': f"FSHD | {server_name}",
            'url': build_stream_url(master_url, referer=server_link),
            'quality': quality,
            'title': display_title,
            'size': '',
            'info': 'HLS Stream',
            'provider_id': 'fshdnet'
        })
    except Exception as e:
        log(f"[FSHDNET] Server {server_name} failed: {e}")
    return results


def scrape_fshdnet(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    if ADDON.getSetting('use_fshdnet') == 'false': return None
    if not title_query: return None
    if content_type == 'tv' and (season is None or episode is None): return None

    base_url = "https://filmeserialehd.net"
    s = get_shared_session()

    display_title = title_query
    if year_query and content_type == 'movie': display_title += f" ({year_query})"
    if content_type == 'tv' and season and episode: display_title += f" S{int(season):02d}E{int(episode):02d}"

    bad_qualities = ['cam', 'camrip', 'hdts', 'hdtc', 'ts', 'telesync', 'telecine', 'trailer', 'sample']

    try:
        # 1. CĂUTARE
        r = s.get(f"{base_url}/search?keyword={quote(title_query)}", headers=get_headers(), timeout=15, verify=False)
        html = r.text

        path_prefix = 'vezi-filmul' if content_type == 'movie' else 'vezi-serialul'
        series_slug = None
        target_url = None

        chunks = html.split('<div class="flw-item">')
        for chunk in chunks[1:]:
            type_m = re.search(r'fdi-type">([^<]+)', chunk)
            item_type = type_m.group(1).strip().lower() if type_m else ''
            if content_type == 'movie' and 'serial' in item_type: continue
            if content_type == 'tv' and 'film' in item_type: continue

            title_m = re.search(r'<h3 class="film-name">.*?<a[^>]*>([^<]+)</a>', chunk, re.DOTALL)
            if not title_m: continue
            item_title = title_m.group(1).strip()

            qual_m = re.search(r'film-poster-quality">([^<]+)', chunk)
            if qual_m:
                q = qual_m.group(1).strip().lower()
                if any(bad in q for bad in bad_qualities): continue

            year_m = re.search(r'<span class="fdi-item">(\d{4})</span>', chunk)
            item_year = year_m.group(1) if year_m else ''

            link_m = re.search(r'href="([^"]*' + path_prefix + r'/([^"\']+))"', chunk)
            if not link_m: continue

            if title_query.lower() in item_title.lower():
                full_path = link_m.group(1)
                slug = link_m.group(2).rstrip('/')
                if year_query and str(year_query) == item_year:
                    series_slug = slug
                    break
                if not series_slug:
                    series_slug = slug

        if not series_slug: return None

        if content_type == 'movie':
            target_url = f"{base_url}/vezi-filmul/{series_slug}/"
        else:
            target_url = f"{base_url}/vezi-episodul/{series_slug}/s{int(season):02d}-e{int(episode):02d}/"

        # 2. PAGINA DETALIU (movie) / EPISOD (tv)
        r = s.get(target_url, headers=get_headers(), timeout=15, verify=False)
        page_html = r.text

        # Token extraction: #main-wrapper (movies) or #series-player (tv)
        token_m = re.search(r'<div[^>]*data-token="([^"]+)"', page_html)
        if not token_m: return None
        token = token_m.group(1)

        # 3. AJAX → SERVERE (field name differs: players vs players_show)
        ajax_field = 'players_show' if content_type == 'tv' else 'players'
        ajax_headers = {'User-Agent': get_random_ua(), 'Referer': target_url, 'X-Requested-With': 'XMLHttpRequest'}
        r_ajax = s.post(f"{base_url}/ajax/ajax.php", data={ajax_field: token}, headers=ajax_headers, timeout=15, verify=False)
        servers = r_ajax.json()
        if not servers or not isinstance(servers, list): return None

        streams = []
        for server in servers:
            server_link = server.get('link', '')
            server_name = server.get('name', 'Megacloud')
            if not server_link: continue
            results = _fshd_process_server(server_link, server_name, target_url, display_title)
            streams.extend(results)

        return streams if streams else None
    except Exception as e:
        log(f"[FSHDNET] Error: {e}")
        return None


# =============================================================================
# MAIN ORCHESTRATION FUNCTION (PARALLEL / MULTITHREADING)
# =============================================================================






# =============================================================================
# SCRAPER TORRENTIO P2P (Magnet links via Torrentio, no debrid)
# =============================================================================
def scrape_p2p_torrentio(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log("[TMDb Movies] [P2P Torrentio] called: imdb_id=%s content_type=%s" % (imdb_id, content_type), xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_torrentio') == 'false':
        return None

    custom_manifest = ADDON.getSetting('p2p_torrentio_manifest').strip()
    if custom_manifest:
        base_url = custom_manifest.split('/manifest.json')[0].rstrip('/')
    else:
        base_url = "https://torrentio.strem.fun/qualityfilter=cam,scr,threed,480p"

    try:
        if content_type == 'movie':
            api_url = "%s/stream/movie/%s.json" % (base_url, imdb_id)
        else:
            api_url = "%s/stream/series/%s:%s:%s.json" % (base_url, imdb_id, season or 1, episode or 1)

        r = get_shared_session().get(api_url, headers=get_headers(), timeout=15, verify=False)

        if r.status_code != 200:
            return None

        data = r.json()
        streams = []

        for s in data.get('streams', []):
            info_hash = s.get('infoHash')
            if not info_hash:
                continue

            magnet = "magnet:?xt=urn:btih:%s" % info_hash
            raw_name = s.get('name', '')
            raw_title = s.get('title', '')

            full_check = (raw_name + " " + raw_title).upper().replace('DS4K', '').replace('4KDS', '')
            q_label = '1080p'
            if '720P' in full_check:
                q_label = '720p'
            elif '1080P' in full_check:
                q_label = '1080p'
            elif any(x in full_check for x in ['2160P', '4K', 'UHD']):
                q_label = '4K'
            elif '480P' in full_check:
                q_label = 'SD'

            # Extract name: Torrentio puts filename in title first line or name second line
            title_parts = raw_title.split('\n')
            clean_title = title_parts[0].strip() if title_parts else ''
            if not clean_title or clean_title.lower() == 'torrentio':
                name_parts = raw_name.split('\n')
                if len(name_parts) > 1:
                    clean_title = name_parts[1].strip()
                else:
                    clean_title = name_parts[0].strip()

            for e in ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','⚙️']:
                clean_title = clean_title.replace(e, '')
            clean_title = clean_title.strip()

            if not clean_title:
                continue

            # Size from full title
            size_match = re.search(r'([\d.]+\s*(?:GB|MB|TB))', raw_title, re.IGNORECASE)
            size_str = size_match.group(1).upper() if size_match else ""

            # Seeders from full title
            seeders = 0
            seed_match = re.search(r'(?:👤|👥|S:)\s*(\d+)', raw_title)
            if seed_match:
                seeders = int(seed_match.group(1))

            streams.append({
                'url': magnet,
                'name': clean_title + " [S: %d]" % seeders,
                'title': clean_title,
                'quality': q_label,
                'size': size_str,
                'info': {
                    'seeders': seeders,
                    'peers': 0,
                    'indexer': 'Torrentio',
                    'freeleech': 0,
                    'doubleup': 0,
                    'internal': 0,
                    'quality': q_label,
                    'releaseGroup': _extract_release_group(clean_title),
                },
                'provider_id': 'p2p_torrentio'
            })

        if streams:
            xbmc.log("[TMDb Movies] [P2P Torrentio] %d streams returned" % len(streams), xbmc.LOGERROR)
        return streams if streams else None

    except Exception as e:
        xbmc.log("[TMDb Movies] [P2P Torrentio] error: %s" % str(e), xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER COMET P2P (Magnet links via Comet, no debrid)
# =============================================================================
def scrape_p2p_comet(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log("[TMDb Movies] [P2P Comet] called: imdb_id=%s content_type=%s" % (imdb_id, content_type), xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_comet') == 'false':
        return None

    custom_manifest = ADDON.getSetting('p2p_comet_manifest').strip()
    if custom_manifest:
        base_url = custom_manifest.split('/manifest.json')[0].rstrip('/')
    else:
        base_url = "https://cometfortheweebs.midnightignite.me/eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOltdLCJlbmFibGVUb3JyZW50Ijp0cnVlLCJkZWR1cGxpY2F0ZVN0cmVhbXMiOmZhbHNlLCJzY3JhcGVEZWJyaWRBY2NvdW50VG9ycmVudHMiOmZhbHNlLCJkZWJyaWRTdHJlYW1Qcm94eVBhc3N3b3JkIjoiIiwibGFuZ3VhZ2VzIjp7InJlcXVpcmVkIjpbXSwiYWxsb3dlZCI6W10sImV4Y2x1ZGUiOltdLCJwcmVmZXJyZWQiOltdfSwicmVzb2x1dGlvbnMiOnsicjU3NnAiOmZhbHNlLCJyNDgwcCI6ZmFsc2UsInIzNjBwIjpmYWxzZSwicjI0MHAiOmZhbHNlfSwib3B0aW9ucyI6eyJyZW1vdmVfcmFua3NfdW5kZXIiOi0xMDAwMDAwMDAwMCwiYWxsb3dfZW5nbGlzaF9pbl9sYW5ndWFnZXMiOmZhbHNlLCJyZW1vdmVfdW5rbm93bl9sYW5ndWFnZXMiOmZhbHNlfX0="

    try:
        if content_type == 'movie':
            api_url = "%s/stream/movie/%s.json" % (base_url, imdb_id)
        else:
            api_url = "%s/stream/series/%s:%s:%s.json" % (base_url, imdb_id, season or 1, episode or 1)

        r = get_shared_session().get(api_url, headers=get_headers(), timeout=15, verify=False)
        if r.status_code != 200:
            return None

        data = r.json()
        streams = []

        for s in data.get('streams', []):
            info_hash = s.get('infoHash')
            if not info_hash:
                continue

            trackers = s.get('sources', [])
            magnet = "magnet:?xt=urn:btih:%s" % info_hash
            for tr in trackers:
                magnet += "&tr=%s" % tr

            raw_name = s.get('name', '')
            description = s.get('description', '')
            bh = s.get('behaviorHints', {})

            filename = bh.get('filename', '')
            if not filename:
                fn_match = re.search(r'📄\s*(.+?)(?:\n|$)', description)
                if fn_match:
                    filename = fn_match.group(1).strip()

            if not filename:
                filename = raw_name

            display_name = filename
            for ext in ['.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.mov']:
                if display_name.lower().endswith(ext):
                    display_name = display_name[:-(len(ext))]
                    break

            full_check = (raw_name + " " + display_name + " " + description).upper().replace('DS4K', '').replace('4KDS', '')
            q_label = '1080p'
            if '720P' in full_check:
                q_label = '720p'
            elif '1080P' in full_check:
                q_label = '1080p'
            elif any(x in full_check for x in ['2160P', '4K', 'UHD']):
                q_label = '4K'
            elif '480P' in full_check:
                q_label = 'SD'

            size_str = ""
            size_match = re.search(r'💾\s*([\d.]+\s*(?:GB|MB|TB))', description, re.IGNORECASE)
            if size_match:
                size_str = size_match.group(1).upper()
            elif bh.get('videoSize'):
                vs = float(bh['videoSize'])
                if vs >= 1073741824:
                    size_str = "%.2f GB" % (vs / 1073741824)
                elif vs >= 1048576:
                    size_str = "%.0f MB" % (vs / 1048576)

            seeders = 0

            clean_title = display_name
            for e in ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','⚙️','🧲','▪️','▫️']:
                clean_title = clean_title.replace(e, '')
            clean_title = clean_title.strip()

            if not clean_title:
                continue

            streams.append({
                'url': magnet,
                'name': clean_title,
                'title': clean_title,
                'quality': q_label,
                'size': size_str,
                'info': {
                    'seeders': seeders,
                    'peers': 0,
                    'indexer': 'Comet',
                    'freeleech': 0,
                    'doubleup': 0,
                    'internal': 0,
                    'quality': q_label,
                    'releaseGroup': _extract_release_group(clean_title),
                },
                'provider_id': 'p2p_comet'
            })

        if streams:
            xbmc.log("[TMDb Movies] [P2P Comet] %d streams returned" % len(streams), xbmc.LOGERROR)
        return streams if streams else None

    except Exception as e:
        xbmc.log("[TMDb Movies] [P2P Comet] error: %s" % str(e), xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER MEDIAFUSION P2P (Magnet links via MediaFusion, no debrid)
# =============================================================================
def scrape_p2p_mediafusion(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log("[TMDb Movies] [P2P MediaFusion] called: imdb_id=%s content_type=%s" % (imdb_id, content_type), xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_mediafusion') == 'false':
        return None

    custom_manifest = ADDON.getSetting('p2p_mediafusion_manifest').strip()
    if custom_manifest:
        base_url = custom_manifest.split('/manifest.json')[0].rstrip('/')
    else:
        base_url = "https://mediafusionfortheweebs.midnightignite.me/D-MgIOYBm8hyaUIwwpw-vb7g1DkYuDWlVkR8yC2LTS3b7ejVz5s0yzfMZ1Gf5CxiqtreQCeRCfLfLhOWTFkTDsQL8ozlOF6Sig9mbbuqGnKCFO46BLz3EoWk2OGlL5oM7dpIsTJXVyJC7zWVlgRHXhPy8C-kzUcMHgCJwcFQ-p877sugPoevStrllmYQou9DPpyzbR87R58nJNFrrOj7AoAWK3EkJjAZrvA-t1JCXrrjKWJ-F5FBg4kP9NZ3-6kF8ukse-wG2rU1-xRrHa9r-oya4KwNbR7wYqc2RJVk8WZ5NlKl9SyhS-_FaCGLHinIvG_Spgi-_f9f1aEAVE6_f6rEF-23ajBhmoRu7E3-_F6Fzaahv5sXXG4PkOC62GE37K3OeWZf9X2x-zoIlvmDd6mQ6PAsbKrmhxZbe71uccjWeSjvAOd4iamk1dUiGZp_KPlgjFIEsp98dg7DDG_bXn2klWQuJspM_Pqnaa2T1v8VMuYkqEGcYfAlxYEDKwmB_FIGla9SB5eK2kxZ6NfY3eruKJZ-RDGll9oiTRql9boUeooCAIg839XoenYcHred5wx7r_j5Yx0yUAuC9gytKArPajtIc46TDa4bNsO3ugvJ8U2kKLkLcrCaDSyi3daFSS3Yw_zyv7OeNH2ZH-5UoGgiR49kxLUiGhhR0eM724890haspz40N1JyUeexC620OyAdYIm47hfshxAToEKnPL3fr3L9_HwjwAtxUTWTIO3mLc-RLUz_BDOxeSqKyW-ogq_iTYOVmKBrLVPuQhYIBTSHoZ9fwS4K6UalaQVSADTbun-Nw8xpW6uy9_pLXn-fzw0S-t7is3U63gAkET_f6y30LkWbkuCBF-haoyx7f8i6fMoDZ-i3JedLGw1ReXIK-SKUqo7a0OOWuZF97A-GPyYOu34TZTcGLL3YH-XbZm0kPMXUh9gIM5-vMbafSaZKobLIAg4LSHb0IQVmpQKUqiifXfjhQx7xdwgdTg0aZ-MUa1kZ__vAvWonmAlIXKoj3myCZ3CO4NhzMS90D4rcD7cMx5NGP5fG6EQVbnlyrfpqcT1bsuz1rk5QeIyhGGhRyivaJbJfCC9a5kGtiO9gFBkiDiRnq8Lmy_ADqcTnZYYc5vgbgCDHjZRW3uh2PT61UzN6oWnisSHMQUQWu_KwpAHQ"

    try:
        if content_type == 'movie':
            api_url = "%s/stream/movie/%s.json" % (base_url, imdb_id)
        else:
            api_url = "%s/stream/series/%s:%s:%s.json" % (base_url, imdb_id, season or 1, episode or 1)

        r = get_shared_session().get(api_url, headers=get_headers(), timeout=15, verify=False)
        if r.status_code != 200:
            return None

        data = r.json()
        streams = []

        for s in data.get('streams', []):
            info_hash = s.get('infoHash')
            if not info_hash:
                continue

            trackers = s.get('sources', [])
            magnet = "magnet:?xt=urn:btih:%s" % info_hash
            for tr in trackers:
                tr_url = tr.replace('tracker:', '', 1) if tr.startswith('tracker:') else tr
                magnet += "&tr=%s" % tr_url

            raw_name = s.get('name', '')
            description = s.get('description', '')
            bh = s.get('behaviorHints', {})

            filename = bh.get('filename', '')
            if not filename:
                fn_match = re.search(r'📄\s*(.+?)(?:\n|$)', description)
                if fn_match:
                    filename = fn_match.group(1).strip()

            if not filename:
                filename = raw_name

            display_name = filename
            for ext in ['.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.mov']:
                if display_name.lower().endswith(ext):
                    display_name = display_name[:-(len(ext))]
                    break

            full_check = (raw_name + " " + display_name + " " + description).upper().replace('DS4K', '').replace('4KDS', '')
            q_label = '1080p'
            if '720P' in full_check:
                q_label = '720p'
            elif '1080P' in full_check:
                q_label = '1080p'
            elif any(x in full_check for x in ['2160P', '4K', 'UHD']):
                q_label = '4K'
            elif '480P' in full_check:
                q_label = 'SD'

            size_str = ""
            size_match = re.search(r'[💾📦]\s*([\d.]+\s*(?:GB|MB|TB))', description, re.IGNORECASE)
            if size_match:
                size_str = size_match.group(1).upper()
            elif bh.get('videoSize'):
                vs = float(bh['videoSize'])
                if vs >= 1073741824:
                    size_str = "%.2f GB" % (vs / 1073741824)
                elif vs >= 1048576:
                    size_str = "%.0f MB" % (vs / 1048576)

            seeders = 0

            clean_title = display_name
            for e in ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','⚙️','🧲','▪️','▫️','📦']:
                clean_title = clean_title.replace(e, '')
            clean_title = clean_title.strip()

            if not clean_title:
                continue

            streams.append({
                'url': magnet,
                'name': clean_title,
                'title': clean_title,
                'quality': q_label,
                'size': size_str,
                'info': {
                    'seeders': seeders,
                    'peers': 0,
                    'indexer': 'MediaFusion',
                    'freeleech': 0,
                    'doubleup': 0,
                    'internal': 0,
                    'quality': q_label,
                    'releaseGroup': _extract_release_group(clean_title),
                },
                'provider_id': 'p2p_mediafusion'
            })

        if streams:
            xbmc.log("[TMDb Movies] [P2P MediaFusion] %d streams returned" % len(streams), xbmc.LOGERROR)
        return streams if streams else None

    except Exception as e:
        xbmc.log("[TMDb Movies] [P2P MediaFusion] error: %s" % str(e), xbmc.LOGERROR)
        return None


# =============================================================================
# SCRAPER YTS (P2P - Torrents via YTS API)
# =============================================================================
def scrape_yts(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log(f"[TMDb Movies] [YTS] scrape_yts called: imdb_id={imdb_id} content_type={content_type} title_query={title_query}", xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_yts') == 'false':
        xbmc.log(f"[TMDb Movies] [YTS] use_p2p_yts is false, skipping", xbmc.LOGERROR)
        return None
    if content_type != 'movie':
        xbmc.log(f"[TMDb Movies] [YTS] content_type={content_type} != movie, skipping", xbmc.LOGERROR)
        return None

    query_term = None
    if imdb_id and str(imdb_id).startswith('tt'):
        query_term = imdb_id
        xbmc.log(f"[TMDb Movies] [YTS] using IMDb ID: {query_term}", xbmc.LOGERROR)
    elif title_query:
        query_term = title_query
        if year_query:
            query_term += " " + year_query
        xbmc.log(f"[TMDb Movies] [YTS] using title query: {query_term}", xbmc.LOGERROR)
    else:
        xbmc.log(f"[TMDb Movies] [YTS] no valid query (imdb_id={imdb_id}, title={title_query}), skipping", xbmc.LOGERROR)
        return None

    custom_domain = ADDON.getSetting('yts_custom_domain').strip()
    if custom_domain:
        domains = [custom_domain]
    else:
        domains = ['yts.gg', 'yts.bz', 'yts.ag', 'yts.lt', 'yts.mx', 'yts.rs']
    last_error = None
    for domain in domains:
        try:
            session = get_shared_session()
            api_url = "https://%s/api/v2/list_movies.json?query_term=%s&limit=20" % (domain, quote(str(query_term)))
            resp = session.get(api_url, headers={'User-Agent': get_random_ua()}, timeout=10, verify=False)
            if resp.status_code != 200:
                last_error = "[YTS] %s returned %d" % (domain, resp.status_code)
                continue

            data = resp.json()
            if data.get('status') != 'ok':
                last_error = "[YTS] %s bad status: %s" % (domain, data.get('status'))
                continue

            movies = data.get('data', {}).get('movies', [])
            if not movies:
                last_error = "[YTS] %s no movies in response" % domain
                continue

            movie = movies[0]
            title = movie.get('title', 'Unknown')
            year = movie.get('year', '')
            display_title = "%s (%s)" % (title, year) if year else title

            torrents = movie.get('torrents', [])
            if not torrents:
                last_error = "[YTS] %s no torrents for %s" % (domain, query_term)
                continue

            streams = []
            for t in torrents:
                quality = t.get('quality', '1080p')
                if quality == '2160p':
                    q_label = '4K'
                elif quality == '1080p':
                    q_label = '1080p'
                elif quality == '720p':
                    q_label = '720p'
                else:
                    q_label = 'SD'

                size = t.get('size', '')
                seeders = t.get('seeds', 0)
                peers = t.get('peers', 0)

                hash_val = t.get('hash', '')
                if not hash_val:
                    continue

                type_val = t.get('type', '').upper()
                codec = t.get('video_codec', '')
                bit_depth = t.get('bit_depth', '')
                audio = t.get('audio_channels', '')
                parts = [title.replace(' ', '.'), str(year), quality, type_val, codec]
                if bit_depth:
                    parts.append(bit_depth + 'bit')
                if audio:
                    parts.append(audio.replace('.', ''))
                torrent_name = '.'.join(parts)
                display_name = "%s (%s) %s %s [S: %d P: %d] %s" % (title, year, quality, type_val, seeders, peers, size)

                magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (hash_val, quote(torrent_name))
                trackers = [
                    'udp://open.demonii.com:1337/announce',
                    'udp://tracker.openbittorrent.com:80',
                    'udp://tracker.coppersurfer.tk:6969',
                    'udp://glotorrents.pw:6969/announce',
                    'udp://tracker.opentrackr.org:1337/announce',
                    'udp://exodus.desync.com:6969/announce',
                    'udp://p4p.arenabg.com:1337/announce'
                ]
                for tr in trackers:
                    magnet += "&tr=" + quote(tr)

                streams.append({
                    'name': 'YTS | %s %s' % (quality, type_val),
                    'url': magnet,
                    'title': display_name,
                    'quality': q_label,
                    'size': size,
                    'info': {'seeders': seeders, 'peers': peers, 'quality': q_label},
                    'provider_id': 'p2p_yts'
                })

            if streams:
                log("[YTS] %d torrents found for %s via %s" % (len(streams), query_term, domain))
                return streams
            last_error = "[YTS] %s empty streams" % domain
        except Exception as e:
            last_error = "[YTS] %s error: %s" % (domain, str(e))

    log(last_error)
    return None


def _filter_tv_packs(streams, season, episode):
    if not streams or not season:
        return streams
    import re
    filtered = []
    is_episode_search = episode is not None
    season_int = int(season)
    episode_int = int(episode) if episode else None
    for s in streams:
        name = s.get('name', '') or s.get('title', '')
        s_match = re.search(r'(?i)S(\d+)', name)
        e_match = re.search(r'(?i)E(\d+)', name)
        item_season = int(s_match.group(1)) if s_match else -1
        item_episode = int(e_match.group(1)) if e_match else -1
        is_episode_item = (item_season != -1 and item_episode != -1)
        keep_item = True
        if is_episode_search:
            # Mode D1 - specific episode
            if item_season != -1 and item_season != season_int:
                keep_item = False
            elif is_episode_item and item_episode != episode_int:
                keep_item = False
        else:
            # Mode D2 - season only (reject individual episodes)
            if item_season != -1 and item_season != season_int:
                keep_item = False
            elif is_episode_item:
                keep_item = False
        if keep_item:
            filtered.append(s)
    return filtered if filtered else None


def scrape_filelist(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log("[TMDb Movies] [FileList] scrape_filelist called: imdb_id=%s content_type=%s season=%s episode=%s title_query=%s" % (imdb_id, content_type, season, episode, title_query), xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_filelist') == 'false':
        xbmc.log("[TMDb Movies] [FileList] use_p2p_filelist is false, skipping", xbmc.LOGERROR)
        return None

    username = ADDON.getSetting('filelist_username').strip()
    passkey = ADDON.getSetting('filelist_passkey').strip()
    fallback_enabled = ADDON.getSetting('filelist_fallback_name') == 'true'

    if not username or not passkey:
        xbmc.log("[TMDb Movies] [FileList] missing username or passkey", xbmc.LOGERROR)
        return None

    stream_map = {}
    session = get_shared_session()

    def fetch_and_parse(search_type, query_val):
        api_url = "https://filelist.io/api.php?username=%s&passkey=%s&action=search-torrents&type=%s&query=%s" % (
            username, passkey, search_type, quote(str(query_val)))
        xbmc.log("[TMDb Movies] [FileList] fetching: %s" % api_url.replace(passkey, '***'), xbmc.LOGERROR)
        try:
            resp = session.get(api_url, headers={'User-Agent': get_random_ua()}, timeout=15)
            if resp.status_code != 200:
                xbmc.log("[TMDb Movies] [FileList] HTTP %d" % resp.status_code, xbmc.LOGERROR)
                return False
            data = resp.json()
            if not isinstance(data, list):
                xbmc.log("[TMDb Movies] [FileList] unexpected response: %s" % str(data)[:200], xbmc.LOGERROR)
                return False
            for t in data:
                tid = t.get('id')
                if tid and tid not in stream_map:
                    stream_map[tid] = t
            xbmc.log("[TMDb Movies] [FileList] %d torrents from %s=%s" % (len(data), search_type, query_val), xbmc.LOGERROR)
            return True
        except Exception as e:
            xbmc.log("[TMDb Movies] [FileList] error: %s" % str(e), xbmc.LOGERROR)
            return False

    # 1. IMDb search
    if imdb_id and str(imdb_id).startswith('tt'):
        fetch_and_parse('imdb', imdb_id)

    # 2. Fallback name search
    if not stream_map and fallback_enabled and title_query:
        search_term = title_query
        if year_query:
            search_term += " " + year_query
        fetch_and_parse('name', search_term)

    if not stream_map:
        xbmc.log("[TMDb Movies] [FileList] no torrents found", xbmc.LOGERROR)
        return None

    streams = []
    for tid, t in stream_map.items():
        name = t.get('name', 'Unknown')
        size_bytes = t.get('size', 0)
        seeders = t.get('seeders', 0)
        leechers = t.get('leechers', 0)
        freeleech = t.get('freeleech', 0)
        doubleup = t.get('doubleup', 0)
        internal = t.get('internal', 0)
        category = t.get('category', '')
        download_link = t.get('download_link', '')

        if not download_link:
            continue

        # Build display name
        display_name = name
        display_name += " [S: %d P: %d]" % (seeders, leechers)

        # Size in human-readable
        try:
            size_gb = float(size_bytes) / (1024**3)
            if size_gb >= 1.0:
                size_str = "%.2f GB" % size_gb
            else:
                size_mb = float(size_bytes) / (1024**2)
                size_str = "%.0f MB" % size_mb
        except:
            size_str = ""

        # Quality extraction from name
        q_label = '1080p'
        name_upper = name.upper()
        if '720P' in name_upper:
            q_label = '720p'
        elif '1080P' in name_upper:
            q_label = '1080p'
        elif '2160P' in name_upper or '4K' in name_upper:
            q_label = '4K'
        elif '480P' in name_upper or 'SD' in name_upper:
            q_label = 'SD'

        streams.append({
            'url': download_link,
            'name': display_name,
            'title': display_name,
            'quality': q_label,
            'size': size_str,
            'info': {
                'seeders': seeders,
                'peers': leechers,
                'indexer': category,
                'freeleech': freeleech,
                'doubleup': doubleup,
                'internal': internal,
                'quality': q_label,
                'releaseGroup': _extract_release_group(name),
            },
            'provider_id': 'p2p_filelist'
        })

    if content_type == 'tv' and (season is not None) and streams:
        xbmc.log("[TMDb Movies] [FileList] applying tv pack filter: season=%s episode=%s" % (season, episode), xbmc.LOGERROR)
        streams = _filter_tv_packs(streams, season, episode)
        if streams:
            xbmc.log("[TMDb Movies] [FileList] %d streams after tv pack filter" % len(streams), xbmc.LOGERROR)
        else:
            xbmc.log("[TMDb Movies] [FileList] all streams filtered out by tv pack filter", xbmc.LOGERROR)
    if streams:
        xbmc.log("[TMDb Movies] [FileList] %d streams returned" % len(streams), xbmc.LOGERROR)
    return streams if streams else None


def scrape_speedapp(imdb_id, content_type, season=None, episode=None, title_query=None, year_query=None):
    xbmc.log("[TMDb Movies] [SpeedApp] scrape_speedapp called: imdb_id=%s content_type=%s" % (imdb_id, content_type), xbmc.LOGERROR)
    if ADDON.getSetting('use_p2p_speedapp') == 'false':
        return None

    username = ADDON.getSetting('speedapp_username').strip()
    password = ADDON.getSetting('speedapp_password').strip()
    passkey = ADDON.getSetting('speedapp_passkey').strip()
    fallback_enabled = ADDON.getSetting('speedapp_fallback_name') == 'true'

    if not username or not password:
        xbmc.log("[TMDb Movies] [SpeedApp] missing username or password", xbmc.LOGERROR)
        return None

    if not passkey:
        xbmc.log("[TMDb Movies] [SpeedApp] missing passkey", xbmc.LOGERROR)
        return None

    session = requests.Session()
    base_url = 'https://speedapp.io'
    ua = get_random_ua()

    # --- LOGIN via HTML form ---
    try:
        login_resp = session.get(base_url + '/login',
            headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.5"},
            timeout=15)
        token_match = re.search(r'_csrf_token.+?value="(.+?)"', login_resp.text)
        if not token_match:
            xbmc.log("[TMDb Movies] [SpeedApp] no CSRF token found", xbmc.LOGERROR)
            return None
        csrf_token = token_match.group(1)

        login_data = {
            'username': username,
            'password': password,
            '_remember_me': 'on',
            '_csrf_token': csrf_token
        }
        login_post = session.post(base_url + '/login', data=login_data,
            headers={
                "User-Agent": ua,
                "Accept-Language": "en-US,en;q=0.5",
                "Origin": base_url,
                "Referer": base_url + '/login',
            },
            timeout=15)

        if 'logout' not in login_post.text:
            xbmc.log("[TMDb Movies] [SpeedApp] login failed", xbmc.LOGERROR)
            return None
    except Exception as e:
        xbmc.log("[TMDb Movies] [SpeedApp] login error: %s" % str(e), xbmc.LOGERROR)
        return None

    # --- SEARCH via HTML browse page ---
    def fetch_page(search_url):
        try:
            resp = session.get(search_url, headers={"User-Agent": ua}, timeout=15)
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception as e:
            xbmc.log("[TMDb Movies] [SpeedApp] fetch error: %s" % str(e), xbmc.LOGERROR)
            return None

    def parse_html(html):
        streams = []
        blocks = html.split('<div class="row mr-0 ml-0 py-3">')
        if len(blocks) > 1:
            blocks = blocks[1:]

        for block in blocks:
            try:
                if 'href="/torrents/' not in block:
                    continue

                name_match = re.search(r'<a class="font-weight-bold" href="([^"]+)">(.+?)</a>', block, re.DOTALL)
                if not name_match:
                    continue
                raw_name = name_match.group(2)
                name = re.sub(r'</?mark>', '', raw_name).strip()
                if not name:
                    continue

                dl_match = re.search(r'href="(/torrents/([^/"]+)/[^"]+\.torrent)"', block)
                if not dl_match:
                    continue
                tid = dl_match.group(2)

                size_match = re.search(r'(\d+[\.,]?\d*\s*[KMGT]B)', block)
                size_str = size_match.group(1).strip() if size_match else ''

                seeds_match = re.search(r'text-success.*?>(\d+)<', block)
                seeders = int(seeds_match.group(1)) if seeds_match else 0

                leech_match = re.search(r'text-danger.*?>(\d+)<', block)
                leechers = int(leech_match.group(1)) if leech_match else 0

                freeleech = 1 if 'title="Descarcarea acestui torrent este gratuita' in block else 0
                doubleup = 1 if 'title="Uploadul pe acest torrent se va contoriza dublu."' in block else 0
                halfdw = 1 if 'title="Descarcarea acestui torrent este redusa la jumatate."' in block else 0
                is_internal = 1 if 'Intern' in block else 0

                cat_match = re.search(r'href="/(?:browse|adult)\?categories%5B0%5D=(\d+)"', block)
                cat_id = cat_match.group(1) if cat_match else ''
                cat_names = {
                    '3': 'Anime/Hentai', '43': 'Seriale HDTV', '44': 'Seriale HDTV-Ro',
                    '17': 'Filme BluRay', '24': 'Filme BluRay-Ro',
                    '7': 'Filme DVD', '2': 'Filme DVD-Ro',
                    '8': 'Filme HD', '29': 'Filme HD-Ro',
                    '61': 'Filme 4K(2160p)', '57': 'Filme 4K-RO(2160p)',
                    '10': 'Filme SD', '35': 'Filme SD-Ro',
                    '45': 'Seriale TV', '46': 'Seriale TV-Ro',
                    '9': 'Documentare', '63': 'Documentare-Ro',
                    '22': 'Sport', '58': 'Sport-Ro',
                    '38': 'Movies Packs', '41': 'TV Packs', '66': 'TV Packs-Ro',
                    '59': 'Filme Romanesti', '60': 'Seriale Romanesti',
                    '62': 'Desene Animate',
                    '64': 'Videoclipuri'
                }
                category_name = cat_names.get(cat_id, '')

                q_label = '1080p'
                name_upper = name.upper()
                if '720P' in name_upper:
                    q_label = '720p'
                elif '1080P' in name_upper:
                    q_label = '1080p'
                elif '2160P' in name_upper or '4K' in name_upper:
                    q_label = '4K'
                elif '480P' in name_upper or 'SD' in name_upper:
                    q_label = 'SD'

                download_link = "https://speedapp.io/rss/download/%s/%s.torrent?passkey=%s" % (tid, quote(name), passkey)

                streams.append({
                    'url': download_link,
                    'name': name + " [S: %d P: %d]" % (seeders, leechers),
                    'title': name,
                    'quality': q_label,
                    'size': size_str,
                    'info': {
                        'seeders': seeders,
                        'peers': leechers,
                        'indexer': category_name,
                        'freeleech': freeleech,
                        'doubleup': doubleup,
                        'halfdw': halfdw,
                        'internal': is_internal,
                        'quality': q_label,
                        'releaseGroup': _extract_release_group(name),
                    },
                    'provider_id': 'p2p_speedapp'
                })
            except:
                continue

        return streams

    all_streams = []

    # 1. Search by IMDb
    if imdb_id and str(imdb_id).startswith('tt'):
        for page in [1, 2]:
            url = base_url + "/browse?search=%s&submit=&sort=torrent.seeders&direction=desc&page=%d" % (imdb_id, page)
            html = fetch_page(url)
            if html:
                streams = parse_html(html)
                all_streams.extend(streams)
                if len(streams) < 50:
                    break
            else:
                break

    # 2. Fallback by name
    if not all_streams and fallback_enabled and title_query:
        search_term = title_query
        if year_query:
            search_term += " " + year_query
        for page in [1, 2]:
            url = base_url + "/browse?search=%s&submit=&sort=torrent.seeders&direction=desc&page=%d" % (quote(search_term), page)
            html = fetch_page(url)
            if html:
                streams = parse_html(html)
                all_streams.extend(streams)
                if len(streams) < 50:
                    break
            else:
                break

    if content_type == 'tv' and (season is not None) and all_streams:
        xbmc.log("[TMDb Movies] [SpeedApp] applying tv pack filter: season=%s episode=%s" % (season, episode), xbmc.LOGERROR)
        all_streams = _filter_tv_packs(all_streams, season, episode)
        if all_streams:
            xbmc.log("[TMDb Movies] [SpeedApp] %d streams after tv pack filter" % len(all_streams), xbmc.LOGERROR)
        else:
            xbmc.log("[TMDb Movies] [SpeedApp] all streams filtered out by tv pack filter", xbmc.LOGERROR)
    if all_streams:
        xbmc.log("[TMDb Movies] [SpeedApp] %d streams returned" % len(all_streams), xbmc.LOGERROR)

    return all_streams if all_streams else None


def get_stream_data(imdb_id, content_type, season=None, episode=None, progress_callback=None, target_providers=None, override_title=None, override_year=None):
    """
    Orchestrează scanarea PARALELĂ (Multithreading).
    override_title/override_year: forțează titlu/an personalizat (Scrape with Custom Values).
    """
    all_streams = []
    seen_urls = set()
    failed_providers = [] 
    empty_providers = []
    was_canceled = False
    
    # --- CITIM SETAREA UTILIZATORULUI ---
    filter_duplicates = ADDON.getSetting('filter_duplicate_urls') == 'true'

    # 1. EXTRAGERE TITLU ȘI AN DIN TMDB (Necesar și foarte robust)
    extra_title = ""
    extra_year = ""
    
    # Dacă avem override (Custom Values), le folosim direct
    if override_title:
        extra_title = override_title
        extra_year = override_year or ""
        log(f"[SCRAPER] Custom Values: '{extra_title}' ({extra_year})")
    else:
        title_based_scrapers = ['fshdnet', 'hdhub4u', 'mkvcinemas', 'vixsrc', 'moviesdrive', 'vidlink', 'vsembed', 'hdhub', 'streamvix', 'videasy', 'netmirror', 'vidmody', 'movieblast', 'moviebox', 'onlykdrama', 'primesrcme', 'vaplayer', 'flixer', 'cineby', 'cinefreak', 'movies4u']
        needs_title = any(
            ADDON.getSetting(f'use_{scraper}') == 'true' 
            for scraper in title_based_scrapers
        ) or ADDON.getSetting('use_p2p_yts') == 'true' or ADDON.getSetting('use_p2p_filelist') == 'true' or ADDON.getSetting('use_p2p_speedapp') == 'true' or ADDON.getSetting('use_p2p_torrentio') == 'true' or ADDON.getSetting('use_p2p_comet') == 'true' or ADDON.getSetting('use_p2p_mediafusion') == 'true'
        
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
        'moviesdrive': ('MoviesDrive', lambda: scrape_moviesdrive(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'webstreamr': ('Webstreamr', lambda: _scrape_json_provider("https://87d6a6ef6b58-webstreamrmbg.baby-beamup.club", 'stream', 'Webstreamr', imdb_id, content_type, season, episode)),
        'streamvix': ('StreamVix', lambda: _scrape_json_provider("https://streamvix.hayd.uk", 'stream', 'StreamVix', imdb_id, content_type, season, episode)),
        'vixsrc': ('VixSrc', lambda: scrape_vixsrc(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vidlink': ('VidLink', lambda: scrape_vidlink(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vaplayer': ('VAPlayer', lambda: scrape_vaplayer(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vsembed': ('VSEmbed', lambda: scrape_vsembed(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'videasy': ('VidEasy', lambda: scrape_videasy(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'netmirror': ('NetMirror', lambda: scrape_netmirror(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'vidmody': ('Vidmody', lambda: scrape_vidmody(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'movieblast': ('MovieBlast', lambda: scrape_movieblast(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'moviebox': ('MovieBox', lambda: scrape_moviebox(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'onlykdrama': ('OnlyKDrama', lambda: scrape_onlykdrama(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'primesrcme': ('PrimeSrc.me', lambda: scrape_primesrcme(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'flixer': ('Flixer', lambda: scrape_flixer(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        
        'cineby': ('Cineby', lambda: scrape_cineby(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'cinefreak': ('CineFreak', lambda: scrape_cinefreak(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'movies4u': ('Movies4U', lambda: scrape_movies4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        
        'fshdnet': ('FSHDnet', lambda: scrape_fshdnet(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'hdhub4u': ('HDHub4u', lambda: scrape_hdhub4u(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'mkvcinemas': ('MKVCinemas', lambda: scrape_mkvcinemas(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'hdhub': ('HDHub', lambda: _scrape_json_provider("https://hdhub.thevolecitor.qzz.io/eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9", 'stream', 'HDHub', imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        
        # PROVIDERI DEBRID (IGNORĂ SWITCH-UL GLOBAL HTTP)
        'aiostreams': ('AIO Streams', lambda: scrape_aiostreams(imdb_id, content_type, season, episode)),
        'torrentio': ('Torrentio', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'torrentio', 'Torrentio')),
        'mediafusion': ('Mediafusion', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'mediafusion', 'Mediafusion')),
        'comet': ('Comet', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'comet', 'Comet')),
        'meteor': ('Meteor', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'meteor', 'Meteor')),
        'custom1': ('Custom 1', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'custom1', ADDON.getSetting('custom1_name') or 'Custom 1')),
        'custom2': ('Custom 2', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'custom2', ADDON.getSetting('custom2_name') or 'Custom 2')),
        'custom3': ('Custom 3', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'custom3', ADDON.getSetting('custom3_name') or 'Custom 3')),
        'custom4': ('Custom 4', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'custom4', ADDON.getSetting('custom4_name') or 'Custom 4')),
        'custom5': ('Custom 5', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'custom5', ADDON.getSetting('custom5_name') or 'Custom 5')),
        'usenet': ('Usenet', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'usenet', 'Usenet')),

        # PROVIDERI P2P (IGNORĂ SWITCH-UL GLOBAL HTTP, RESPECTĂ P2P MASTER SWITCH)
        'p2p_yts': ('YTS', lambda: scrape_yts(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_filelist': ('FileList', lambda: scrape_filelist(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_torrentio': ('Torrentio P2P', lambda: scrape_p2p_torrentio(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_comet': ('Comet P2P', lambda: scrape_p2p_comet(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_mediafusion': ('MediaFusion P2P', lambda: scrape_p2p_mediafusion(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_speedapp': ('SpeedApp', lambda: scrape_speedapp(imdb_id, content_type, season, episode, title_query=extra_title, year_query=extra_year)),
        'p2p_custom1': ('P2P Custom 1', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'p2p_custom1', ADDON.getSetting('p2p_custom1_name') or 'P2P Custom 1')),
        'p2p_custom2': ('P2P Custom 2', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'p2p_custom2', ADDON.getSetting('p2p_custom2_name') or 'P2P Custom 2')),
        'p2p_custom3': ('P2P Custom 3', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'p2p_custom3', ADDON.getSetting('p2p_custom3_name') or 'P2P Custom 3')),
        'p2p_custom4': ('P2P Custom 4', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'p2p_custom4', ADDON.getSetting('p2p_custom4_name') or 'P2P Custom 4')),
        'p2p_custom5': ('P2P Custom 5', lambda: scrape_stremio_addon(imdb_id, content_type, season, episode, 'p2p_custom5', ADDON.getSetting('p2p_custom5_name') or 'P2P Custom 5')),
    }

    # 3. SELECȚIE PROVIDERI ACTIVI (CU LOGICĂ MASTER SWITCH)
    to_run = []
    http_master_enabled = ADDON.getSetting('enable_http_scrapers') == 'true'
    p2p_master_enabled = ADDON.getSetting('enable_p2p_providers') == 'true'
    debrid_providers = ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5']
    p2p_providers = ['p2p_yts', 'p2p_torrentio', 'p2p_comet', 'p2p_mediafusion', 'p2p_filelist', 'p2p_speedapp', 'p2p_custom1', 'p2p_custom2', 'p2p_custom3', 'p2p_custom4', 'p2p_custom5']

    if target_providers is not None:
        for pid in target_providers:
            if pid in providers_map:
                setting_id = f'use_{pid}'
                is_enabled = ADDON.getSetting(setting_id)
                if is_enabled == '' and pid == 'flixer': is_enabled = 'true'
                # Executăm dacă (e Debrid) SAU (Master HTTP e On și setarea individuală e On) SAU (P2P)
                if pid in debrid_providers or (http_master_enabled and pid not in p2p_providers and is_enabled == 'true') or (pid in p2p_providers and p2p_master_enabled and is_enabled == 'true'):
                    if pid.startswith('custom') or pid.startswith('p2p_custom'):
                        display_name = ADDON.getSetting(f'{pid}_name') or providers_map[pid][0]
                    else:
                        display_name = providers_map[pid][0]
                    to_run.append((pid, display_name, providers_map[pid][1]))
    else:
        for pid, (pname, pfunc) in providers_map.items():
            setting_id = f'use_{pid}'
            is_enabled = ADDON.getSetting(setting_id)
            if is_enabled == '' and pid == 'flixer': is_enabled = 'true'
            if pid in debrid_providers or (http_master_enabled and pid not in p2p_providers and is_enabled == 'true') or (pid in p2p_providers and p2p_master_enabled and is_enabled == 'true'):
                if pid.startswith('custom') or pid.startswith('p2p_custom'):
                    display_name = ADDON.getSetting(f'{pid}_name') or pname
                else:
                    display_name = pname
                to_run.append((pid, display_name, pfunc))
    
    total_providers = len(to_run)
    if total_providers == 0:
        return [], [], [], False

    # 4. FUNCȚIA WRAPPER PENTRU THREAD
    _scraper_results = []
    _scraper_lock = threading.Lock()

    def run_provider(provider_info):
        """
        Execută un provider și returnează rezultatele.
        Returnează: (pid, pname, result, status)
        status: 'success' = are rezultate, 'empty' = 0 rezultate, 'error' = excepție/timeout
        """
        pid, pname, pfunc = provider_info
        
        try:
            result = pfunc()
            if result:
                with _scraper_lock:
                    _scraper_results.append((pid, pname, result, 'success'))
            else:
                with _scraper_lock:
                    _scraper_results.append((pid, pname, None, 'empty'))
            
        except Exception as e:
            log(f"[THREAD] Error in {pname}: {e}")
            with _scraper_lock:
                _scraper_results.append((pid, pname, None, 'error'))

    # 5. EXECUȚIE PARALELĂ - DAEMON THREADS (Kodi nu așteaptă după ele)
    try: MAX_TIMEOUT = int(ADDON.getSetting('scraper_timeout'))
    except: MAX_TIMEOUT = 25
    
    MAX_WORKERS = 20  # Toți providerii pornesc simultan
    
    import time
    _scraper_threads = []
    for p in to_run:
        t = threading.Thread(target=run_provider, args=(p,), daemon=True)
        _scraper_threads.append(t)
        t.start()
    
    start_time = time.time()
    _all_done = False
    processed_count = 0
    try:
        while not _all_done:
            elapsed = time.time() - start_time
            if elapsed > MAX_TIMEOUT:
                log(f"[SCRAPER] Global timeout forced ({MAX_TIMEOUT}s)")
                break
            
            time.sleep(0.25)
            
            # Check if all threads finished
            _all_done = all(not t.is_alive() for t in _scraper_threads)
            
            # --- 1. ACTUALIZARE UI ---
            if progress_callback:
                with _scraper_lock:
                    finished_count = len(_scraper_results)
                percent = int((finished_count / total_providers) * 100)
                
                alive_names = []
                for i, p in enumerate(to_run):
                    if _scraper_threads[i].is_alive():
                        alive_names.append(p[1])
                
                if alive_names:
                    formatted_names = [f"[B][COLOR FFFF69B4]{alive_names[0]}[/COLOR][/B]"]
                    for name in alive_names[1:3]:
                        formatted_names.append(f"[B][COLOR white]{name}[/COLOR][/B]")
                    if len(alive_names) > 3:
                        display_pending = ", ".join(formatted_names) + f" [COLOR gray][I](+{len(alive_names)-3})[/I][/COLOR]"
                    else:
                        display_pending = ", ".join(formatted_names)
                else:
                    display_pending = "[B][COLOR lime]Finalizare...[/COLOR][/B]"

                msg_estuary = (
                    f"[COLOR gray]Scanning:[/COLOR] {display_pending}\n"
                    f"[COLOR gray]Scanned:[/COLOR] [B][COLOR cyan]{finished_count}/{total_providers}[/COLOR][/B] [COLOR gray]| Sources found:[/COLOR] [B][COLOR FF00FA9A]{len(all_streams)}[/COLOR][/B]"
                )
                active_prov = alive_names[0] if alive_names else "Finalizare..."
                msg_af3 = f"Scanning: [B][COLOR FFFF69B4]{active_prov}[/COLOR][/B] | Sources found: [B]{len(all_streams)}[/B]"
                status_data = {'estuary': msg_estuary, 'af3': msg_af3}
                
                keep_going = progress_callback(percent, status_data)
                if keep_going is False:
                    was_canceled = True
                    break
            
            # --- 2. PROCESARE REZULTATE NOI (în timp real) ---
            with _scraper_lock:
                new_results = _scraper_results[processed_count:]
                processed_count += len(new_results)
            
            for pid, pname, result, status in new_results:
                if status == 'error':
                    failed_providers.append(pid)
                    log(f"[SCRAPER] ✗ {pname}: error/timeout")
                    continue
                elif status == 'empty':
                    empty_providers.append(pid)
                    log(f"[SCRAPER] ✗ {pname}: no results")
                    continue
                
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
                    # Filtru centralizat gunoaie (telesync, cam, hdts etc.)
                    _garbage_text = str(item.get('title', '')) + ' ' + str(item.get('name', '')) + ' ' + str(item.get('info', ''))
                    if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|telecine|hdcam|predvd|pre-dvd)\b', _garbage_text):
                        log(f"[SCRAPER] ✗ Filtrat gunoi: {pname} | {str(item.get('title',''))[:60]}")
                        continue
                    all_streams.append(item)
                    added_count += 1
                
                if added_count > 0:
                    log(f"[SCRAPER] ✓ {pname}: {added_count} sources added")
                else:
                    empty_providers.append(pid)

        # Process any remaining results (e.g. after timeout break)
        with _scraper_lock:
            remaining_results = _scraper_results[processed_count:]
            processed_count += len(remaining_results)
        
        for pid, pname, result, status in remaining_results:
            if status == 'error':
                if pid not in failed_providers: failed_providers.append(pid)
            elif status == 'empty':
                if pid not in empty_providers: empty_providers.append(pid)
            else:
                items_to_add = []
                if isinstance(result, dict):
                    items_to_add = [result]
                elif isinstance(result, list):
                    items_to_add = result
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
                    _garbage_text = str(item.get('title', '')) + ' ' + str(item.get('name', '')) + ' ' + str(item.get('info', ''))
                    if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|telecine|hdcam|predvd|pre-dvd)\b', _garbage_text):
                        continue
                    all_streams.append(item)
        
        # Mark timed-out threads
        for i, p in enumerate(to_run):
            if _scraper_threads[i].is_alive():
                pid = p[0]
                pname = p[1]
                if pid not in failed_providers:
                    failed_providers.append(pid)
                    log(f"[SCRAPER] ✗ {pname}: Timeout!")

    except Exception as e:
        log(f"[SCRAPER] Fatal error in execution loop: {e}")

    log(f"[SCRAPER] Finalizat: {len(all_streams)} surse, {len(failed_providers)} erori, {len(empty_providers)} fara rezultate")
    return all_streams, failed_providers, empty_providers, was_canceled
