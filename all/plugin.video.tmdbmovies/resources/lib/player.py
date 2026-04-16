import os
import re
import sys
import xbmc
import xbmcgui
import xbmcplugin
import threading
import time
import requests
import urllib.parse
from urllib.parse import urlparse
import json
from resources.lib.config import get_headers, BASE_URL, API_KEY, IMG_BASE, HANDLE, ADDON
from resources.lib.utils import log, get_json, extract_details, get_language, clean_text
from resources.lib.scraper import get_external_ids, get_stream_data, filter_streams_for_display
from resources.lib.tmdb_api import set_metadata
from resources.lib.trakt_sync import mark_as_watched_internal
from resources.lib import subtitles
from resources.lib import trakt_sync
from resources.lib.cache import MainCache
from resources.lib.subtitles import run_wyzie_service

LANG = get_language()

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# =============================================================================
# CONFIGURĂRI PLAYER - MODIFICĂ AICI
# =============================================================================
PLAYER_CHECK_TIMEOUT = 10  # Secunde pentru verificare sursă (mărește dacă surse mari)
PLAYER_AUDIO_CHECK_ONLY_SD = True  # True = verifică audio-only doar pe SD/720p, False = verifică toate
# PLAYER_KEEP_DUPLICATES = True  # True = păstrează surse duplicate, False = elimină duplicate
# =============================================================================
_active_player = None


# =============================================================================
# DEDUPLICARE STREAMS (FILTRARE URL-URI IDENTICE)
# =============================================================================
def deduplicate_streams(streams):
    """
    Elimină stream-urile duplicate bazat pe URL-ul de bază.
    Păstrează prima apariție pentru fiecare URL unic.
    """
    log(f"[DEDUP] === STARTING DEDUPLICATION ===")
    
    if not streams:
        log(f"[DEDUP] Empty streams list, returning")
        return streams
    
    # Verifică dacă filtrarea e activată
    try:
        filter_enabled = ADDON.getSetting('filter_duplicate_urls') == 'true'
    except Exception as e:
        log(f"[DEDUP] Error reading setting: {e}, defaulting to True")
        filter_enabled = True
    
    log(f"[DEDUP] filter_enabled = {filter_enabled}, streams count = {len(streams)}")
    
    if not filter_enabled:
        log(f"[DEDUP] Filtering DISABLED, keeping all {len(streams)} streams")
        return streams
    
    seen_urls = set()
    unique_streams = []
    duplicates_removed = 0
    
    for stream in streams:
        url = stream.get('url', '')
        if not url:
            unique_streams.append(stream)
            continue
        
        # Extrage URL-ul de bază (fără headere |...)
        base_url = url.split('|')[0].strip()
        
        # Normalizare URL pentru comparație
        try:
            parsed = urlparse(base_url.lower())
            host = parsed.netloc
            if host.startswith('www.'):
                host = host[4:]
            normalized = f"{parsed.scheme}://{host}{parsed.path.rstrip('/')}"
            if parsed.query:
                normalized += f"?{parsed.query}"
        except:
            normalized = base_url.lower().rstrip('/')
        
        if normalized not in seen_urls:
            seen_urls.add(normalized)
            unique_streams.append(stream)
        else:
            duplicates_removed += 1
    
    log(f"[DEDUP] ✓ Result: {len(streams)} -> {len(unique_streams)} (removed {duplicates_removed} duplicates)")
    
    return unique_streams
    


def check_url_validity(url, headers=None, max_timeout=None):
    """Verifică dacă URL-ul este accesibil și NU e intermediar (adl.php, etc)."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT
    
    if not url:
        return False
    
    result = {'valid': False, 'done': False}
    
    def _check():
        try:
            clean_url = url.split('|')[0]
            
            if not clean_url.startswith(('http://', 'https://')):
                result['done'] = True
                return
            
            clean_url_lower = clean_url.lower()
            

            # =========================================================
            # BYPASS PENTRU WORKERS ȘI M3U8 (Evităm erorile 429)
            # Aceste fișiere vor fi redate/descărcate direct!
            # =========================================================
            if 'workers.dev' in clean_url_lower or '.m3u8' in clean_url_lower:
                log(f"[PLAYER-CHECK] M3U8 / Worker bypass - Assume VALID")
                result['valid'] = True
                result['done'] = True
                return
            # =========================================================

            # =========================================================
            # VERIFICARE URL-URI INTERMEDIARE (SKIP DIRECT!)
            # =========================================================
            intermediate_patterns = [
                'adl.php',
                'fdownload.php', 
                '/dl.php?',
                '/download.php?',
            ]
            
            if any(p in clean_url_lower for p in intermediate_patterns):
                log(f"[PLAYER-CHECK] Intermediate URL detected - SKIP: {clean_url[:50]}...")
                result['done'] = True
                return
            # =========================================================
            
            bad_domains = [
                'googleusercontent.com',
                'googlevideo.com', 
                'video-leech.pro',
                'video-seed.pro',
                'video-downloads.googleusercontent.com'
            ]
            
            for bad in bad_domains:
                if bad in clean_url_lower:
                    log(f"[PLAYER-CHECK] Bad domain ({bad}) - SKIP")
                    result['done'] = True
                    return
            
            custom_headers = headers if headers else {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            internal_timeout = max(1.5, max_timeout / 2)
            
            try:
                r = requests.head(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True)
                
                final_url = r.url.lower() if r.url else ''
                
                # Verifică dacă redirect-ul duce la bad domain
                for bad in bad_domains:
                    if bad in final_url:
                        log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
                        result['done'] = True
                        return
                
                # Verifică dacă redirect-ul duce la intermediar
                for p in intermediate_patterns:
                    if p in final_url:
                        log(f"[PLAYER-CHECK] Redirects to intermediate ({p}) - SKIP")
                        result['done'] = True
                        return
                
                if r.status_code < 400:
                    result['valid'] = True
                    result['done'] = True
                    return
                    
                if r.status_code in [405, 403]:
                    r2 = requests.get(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True, stream=True)
                    final_url2 = r2.url.lower() if r2.url else ''
                    r2.close()
                    
                    for bad in bad_domains:
                        if bad in final_url2:
                            log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
                            result['done'] = True
                            return
                    
                    for p in intermediate_patterns:
                        if p in final_url2:
                            log(f"[PLAYER-CHECK] Redirects to intermediate ({p}) - SKIP")
                            result['done'] = True
                            return
                    
                    if r2.status_code < 400:
                        result['valid'] = True
                        result['done'] = True
                        return
                
                log(f"[PLAYER-CHECK] FAIL ({r.status_code})")
                result['done'] = True
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, 
                    requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                log(f"[PLAYER-CHECK] Network error: {type(e).__name__}")
                result['done'] = True
            except Exception as e:
                log(f"[PLAYER-CHECK] Eroare: {type(e).__name__}")
                result['done'] = True

        except Exception as e:
            log(f"[PLAYER-CHECK] Outer error: {type(e).__name__}")
            result['done'] = True
    
    thread = threading.Thread(target=_check)
    thread.daemon = True
    thread.start()
    thread.join(timeout=max_timeout)
    
    if not result['done']:
        log(f"[PLAYER-CHECK] TIMEOUT FORȚAT ({max_timeout}s) - SKIP")
        return False
    
    return result['valid']


def check_sooti_audio_only(url, headers=None, max_timeout=None):
    """Verifică dacă sursa Sooti este audio-only. Returnează True dacă e AUDIO (adică invalidă)."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT  # <-- Folosește constanta globală
    
    result = {'is_audio': False, 'done': False}
    
    def _check():
        try:
            clean_url = url.split('|')[0]
            custom_headers = headers if headers else {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            internal_timeout = max(1.5, max_timeout / 2)
            
            r = requests.get(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True)
            
            if r.status_code >= 400:
                result['is_audio'] = True
                result['done'] = True
                return
            
            content_str = r.text[:4096]
            content_lower = content_str.lower()
            
            if '#extm3u' not in content_lower:
                result['done'] = True
                return
            
            if 'type=audio' in content_lower and 'type=video' not in content_lower:
                log(f"[SOOTI-CHECK] Audio-only (type=audio)")
                result['is_audio'] = True
                result['done'] = True
                return
            
            if 'codecs=' in content_lower:
                has_video_codec = any(x in content_lower for x in ['avc', 'hvc', 'hevc', 'vp9', 'av01'])
                has_audio_only = 'mp4a' in content_lower and not has_video_codec
                
                if has_audio_only:
                    log(f"[SOOTI-CHECK] Audio-only (codec)")
                    result['is_audio'] = True
                    result['done'] = True
                    return
            
            if '#ext-x-stream-inf' in content_lower and 'resolution=' not in content_lower:
                log(f"[SOOTI-CHECK] Audio-only (no resolution)")
                result['is_audio'] = True
                result['done'] = True
                return
            
            result['done'] = True
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            log(f"[SOOTI-CHECK] Network error: {type(e).__name__}")
            result['is_audio'] = True
            result['done'] = True
        except Exception as e:
            log(f"[SOOTI-CHECK] Error: {type(e).__name__}")
            result['is_audio'] = True
            result['done'] = True
    
    thread = threading.Thread(target=_check)
    thread.daemon = True
    thread.start()
    thread.join(timeout=max_timeout)
    
    if not result['done']:
        log(f"[SOOTI-CHECK] TIMEOUT FORȚAT ({max_timeout}s) - SKIP")
        return True
    
    return result['is_audio']


# =============================================================================
# SISTEM CACHE RAM COMPLET
# =============================================================================
def get_window():
    return xbmcgui.Window(10000)


def get_search_id(tmdb_id, content_type, season=None, episode=None):
    if content_type == 'movie':
        return f"movie_{tmdb_id}"
    else:
        return f"tv_{tmdb_id}_s{season}_e{episode}"


def save_sources_to_ram(streams, tmdb_id, content_type, season=None, episode=None):
    try:
        window = get_window()
        search_id = get_search_id(tmdb_id, content_type, season, episode)
        window.setProperty('tmdbmovies.src_id', search_id)
        window.setProperty('tmdbmovies.src_data', json.dumps(streams))
        log(f"[RAM-SRC] Salvat {len(streams)} surse pentru: {search_id}")
    except Exception as e:
        log(f"[RAM-SRC] Eroare salvare: {e}", xbmc.LOGERROR)


def load_sources_from_ram(tmdb_id, content_type, season=None, episode=None):
    try:
        window = get_window()
        current_id = get_search_id(tmdb_id, content_type, season, episode)
        cached_id = window.getProperty('tmdbmovies.src_id')
        
        if current_id == cached_id:
            data = window.getProperty('tmdbmovies.src_data')
            if data:
                streams = json.loads(data)
                if streams and len(streams) > 0:
                    log(f"[RAM-SRC] Încărcat {len(streams)} surse din cache")
                    return streams
    except Exception as e:
        log(f"[RAM-SRC] Eroare citire: {e}", xbmc.LOGERROR)
    return None


def clear_sources_cache():
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.src_id')
        window.clearProperty('tmdbmovies.src_data')
        log("[RAM-SRC] Cache curățat complet")
    except Exception as e:
        log(f"[RAM-SRC] Eroare cleanup: {e}", xbmc.LOGERROR)


def save_return_path():
    try:
        window = get_window()
        window.setProperty('tmdbmovies.need_fast_return', 'true')
        log("[RAM-NAV] Marcat pentru întoarcere rapidă")
    except Exception as e:
        log(f"[RAM-NAV] Eroare: {e}", xbmc.LOGERROR)


def check_fast_return():
    try:
        window = get_window()
        need_return = window.getProperty('tmdbmovies.need_fast_return')
        if need_return == 'true':
            window.clearProperty('tmdbmovies.need_fast_return')
            return True
    except:
        pass
    return False


def clear_fast_return():
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.need_fast_return')
    except:
        pass


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def get_poster_url(tmdb_id, content_type, season=None):
    poster_url = "DefaultVideo.png"
    
    cached_poster = trakt_sync.get_poster_from_db(tmdb_id, content_type)
    if cached_poster and cached_poster.startswith('http'):
        return cached_poster

    try:
        found_poster = None
        
        if content_type == 'tv' and season:
            try:
                meta_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}"
                data = get_json(meta_url)
                if data and data.get('poster_path'):
                    found_poster = IMG_BASE + data.get('poster_path')
            except: 
                pass
            
        if not found_poster:
            endpoint = 'movie' if content_type == 'movie' else 'tv'
            meta_url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
            data = get_json(meta_url)
            if data and data.get('poster_path'):
                found_poster = IMG_BASE + data.get('poster_path')
        
        if found_poster:
            poster_url = found_poster
            trakt_sync.set_poster_to_db(tmdb_id, content_type, poster_url)

    except Exception as e:
        log(f"[PLAYER] Poster Error: {e}", xbmc.LOGWARNING)
    
    return poster_url


# =============================================================================
# EXTRACTOR INFORMAȚII STREAM - V4 (FIX SERVER EXTRACTION)
# =============================================================================
def extract_stream_info(stream):
    """
    Extrage informații detaliate (Undercover Mode).
    V4 - FIX: Extragere corectă server din MKV | Server | Size format.
    """
    raw_name = stream.get('name', '')
    raw_title = stream.get('title', '')
    provider_id = stream.get('provider_id', '')
    url = stream.get('url', '').lower()
    
    # Câmpuri noi pentru Sooti
    source_provider = stream.get('source_provider', '')
    stream_size = stream.get('size', '')
    
    binge_group = ''
    behavior_hints = stream.get('behaviorHints', {})
    if isinstance(behavior_hints, dict):
        binge_group = behavior_hints.get('bingeGroup', '')
    if not binge_group:
        binge_group = stream.get('bingeGroup', '')
    
    full_info = (raw_name + ' ' + raw_title).lower()
    
    # 1. DETECTARE PROVIDER PRINCIPAL
    provider = ""
    
    if provider_id:
        provider_map = {
            'sooti': 'Sootio',
            'nuvio': 'Nuvio',
            'webstreamr': 'Webstreamr',
            'vixsrc': 'VixSrc',
            'rogflix': 'Rogflix',
            'vega': 'Vega',
            'streamvix': 'StreamVix',
            'vidzee': 'Vidzee',
            'meowtv': 'MeowTV',
            'hdhub4u': 'HDHub4u',
            'mkvcinemas': 'MKVCinemas',
            'xdmovies': 'XDMovies',
            'moviesdrive': 'MoviesDrive',
            'hdhub': 'HDHub'
        }
        provider = provider_map.get(provider_id.lower(), provider_id)
    
    if not provider:
        name_lower = raw_name.lower()
        if 'sootio' in name_lower or 'sooti' in name_lower or '[hs+]' in name_lower: 
            provider = 'Sootio'
        elif 'webstreamr' in name_lower: 
            provider = 'Webstreamr'
        elif 'nuvio' in name_lower: 
            provider = 'Nuvio'
        elif 'vix' in name_lower: 
            provider = 'VixSrc'
        elif 'rogflix' in name_lower: 
            provider = 'Rogflix'
        elif 'vega' in name_lower: 
            provider = 'Vega'
        elif 'vidzee' in name_lower: 
            provider = 'Vidzee'
        elif 'meow' in name_lower: 
            provider = 'MeowTV'
        elif 'streamvix' in name_lower: 
            provider = 'StreamVix'
        elif 'mkv |' in name_lower or 'mkvcinemas' in name_lower: 
            provider = 'MKVCinemas'
        elif 'hdhub' in name_lower: 
            provider = 'HDHub4u'
        elif 'moviesdrive' in name_lower or 'mdrive' in name_lower: 
            provider = 'MoviesDrive'
        elif 'XDMovies' in name_lower or 'xdm' in name_lower: 
            provider = 'XDMovies'
        elif 'hdhub' in name_lower: 
            provider = 'HDHub'
        else: 
            provider = 'Unknown'
    
    # 2. SERVER (din URL sau din name)
    server = ""
    
    # 2a. Extragere din URL (prioritate maximă)
    if 'pixeldrain' in url: 
        server = 'PixelDrain'
    elif 'trashbytes' in url:
        server = 'TrashBytes'
    elif 'awsdllaaa' in url or 'aws-storage' in url:
        server = 'FastCloud'
    elif 'instant.busycdn' in url or 'busycdn' in url:
        server = 'InstantDL'
    elif 'r2.dev' in url or 'pub-' in url: 
        server = 'CloudR2'
    elif 'fsl-lover' in url or 'fsl.gdboka' in url: 
        server = 'FSL'
    elif 'fsl-buckets' in url: 
        server = 'CDN'
    elif 'fsl' in url and 'filesdl' not in url: 
        server = 'Flash'
    elif 'polgen.buzz' in url: 
        server = 'Flash'
    elif 'pixel.hubcdn' in url: 
        server = 'HubPixel'
    elif 'workers.dev' in url: 
        server = 'CFWorker'
    elif 'hubcloud' in url: 
        server = 'HubCloud'
    elif 'hubcdn' in url: 
        server = 'HubCDN'
    elif 'gofile' in url: 
        server = 'GoFile'
    elif 'filesdl' in url and 'bbdownload' not in url: 
        server = 'FilesDL'
    elif 'bbdownload' in url:
        if 'adl.php' in url:
            server = 'FastCloud-02'
        elif 'fdownload.php' in url:
            server = 'DirectDL'
    
    # 2b. Extragere din name pentru WebStreamr
    if not server and (provider == 'Webstreamr' or 'webstreamr' in raw_name.lower()):
        webstr_server_match = re.search(r'🔗\s*(.+?)(?:\n|$)', raw_title)
        if webstr_server_match: 
            server = webstr_server_match.group(1).strip()
        elif binge_group:
            if 'fsl' in binge_group.lower(): 
                server = 'HubCloud (FSL)'
            elif 'pixel' in binge_group.lower(): 
                server = 'HubCloud (Pixel)'

    # 2c. Extragere din name pentru Nuvio
    if not server and 'nuvio' in provider_id.lower():
        if '[PIX]' in raw_name: 
            server = 'PixelDrain'
        elif '[FSL]' in raw_name: 
            server = 'Flash'
        elif '[GD]' in raw_name: 
            server = 'GDrive'

    # 2d. Extragere din name pentru MKVCinemas/HDHub4u/MoviesDrive (format: MKV | Server | Size)
    if not server and '|' in raw_name and provider in ['MKVCinemas', 'HDHub4u', 'MoviesDrive', 'Unknown']:
        parts = [p.strip() for p in raw_name.split('|')]
        
        for part in parts:
            part_lower = part.lower()
            
            # Skip "MKV" sau nume provider
            if part_lower in ['mkv', 'mkvcinemas', 'hdhub4u', 'moviesdrive', 'hdhub', '']:
                continue
            
            # Skip dacă e mărime (ex: "5.28 GB", "707.78 MB")
            if re.search(r'^[\d.,]+\s*(gb|mb|tb|gib|mib)$', part_lower):
                continue
            
            # Skip dacă e doar numere cu punct
            if re.match(r'^[\d.,]+$', part_lower):
                continue
            
            # Am găsit un candidat valid - verifică pattern-uri cunoscute
            if 'fastcloud-02' in part_lower:
                server = 'FastCloud-02'
                break
            elif 'fastcloud' in part_lower:
                server = 'FastCloud'
                break
            elif 'pixel' in part_lower:
                server = 'PixelDrain'
                break
            elif 'instantdl' in part_lower or 'instant' in part_lower:
                server = 'InstantDL'
                break
            elif 'cloudr2' in part_lower:
                server = 'CloudR2'
                break
            elif 'trashbytes' in part_lower:
                server = 'TrashBytes'
                break
            elif 'directdl' in part_lower:
                server = 'DirectDL'
                break
            elif 'cfworker' in part_lower or 'worker' in part_lower:
                server = 'CFWorker'
                break
            elif 'hubcdn' in part_lower:
                server = 'HubCDN'
                break
            elif 'flash' in part_lower:
                server = 'Flash'
                break
            elif 'cdn' in part_lower and len(part_lower) <= 5:
                server = 'CDN'
                break
            elif 'direct' in part_lower:
                server = 'Direct'
                break
            elif 'gofile' in part_lower:
                server = 'GoFile'
                break
            elif 'cloud' in part_lower and 'fastcloud' not in part_lower:
                server = 'Cloud'
                break
            elif len(part) >= 2 and len(part) <= 25:
                # Folosește partea ca server name direct (capitalizat)
                # Doar dacă nu conține cifre la început
                if not re.match(r'^\d', part):
                    server = part
                    break
    
    # 2e. Fallback final - identifică din URL
    if not server:
        # Încearcă să extragă domeniul din URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url.split('|')[0])
            domain = parsed.netloc.lower().replace('www.', '')
            domain_parts = domain.split('.')
            if domain_parts and len(domain_parts[0]) >= 2:
                potential_server = domain_parts[0].title()
                if potential_server not in ['Http', 'Https', 'Www', '']:
                    server = potential_server
        except:
            pass
    
    # 3. GROUP (doar dacă nu avem source_provider)
    group = ""
    if not source_provider:
        group_match = re.search(r'\|\s*([A-Za-z0-9]+(?:Hub|hub|HUB)?)\s*$', raw_title)
        if group_match: 
            group = group_match.group(1)
        if group and server and group.lower() == server.lower(): 
            group = ""

    # 4. SIZE - Prioritate: câmpul 'size' din stream, apoi extragere din text
    size = stream_size if stream_size else ""
    
    if not size:
        # --- PROTECȚIE TYPEERROR (Dacă info e dict, regex va crăpa) ---
        info_val = stream.get('info', '')
        if isinstance(info_val, dict):
            info_str = str(info_val.get('original_info_str', '')) + " " + str(info_val.get('size', ''))
        else:
            info_str = str(info_val)
            
        search_texts =[raw_name, raw_title, info_str]
        # -------------------------------------------------------------
        
        size_patterns = [
            r'💾\s*([\d.]+)\s*(GB|MB|TB)',                    # Emoji format
            r'\[([\d.]+)\s*(GB|MB|TB)\]',                     # [5.28 GB]
            r'\|\s*([\d.]+)\s*(GB|MB|TB)\s*(?:\||$)',         # | 5.28 GB |
            r'Size\s*:\s*([\d.]+)\s*(GB|MB|TB)',              # Size: 5.28 GB
            r'Size\s*:\s*([\d.]+)(GB|MB|TB)',                 # Size: 5.28GB (no space)
            r'[\(\[]([\d.]+)\s*(GB|MB|TB)[\)\]]',             # (5.28 GB) or [5.28GB]
            r'([\d.]+)\s*(GB|MB|TB)(?:\s*\||$|<)',            # 5.28 GB| or end
            r'-([\d.]+)(GB|MB|TB)-',                          # -5.28GB-
            r'\s([\d.]+)(GB|MB|TB)\.',                        # space5.28GB.
        ]
        
        for text in search_texts:
            if not text:
                continue
            for pattern in size_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    val = match.group(1)
                    unit = match.group(2).upper()
                    # Validare: mărimea trebuie să fie rezonabilă (0.1 - 100 GB/MB)
                    try:
                        num = float(val)
                        if 0.1 <= num <= 100:
                            size = f"{val} {unit}"
                            break
                    except:
                        pass
            if size:
                break

    # 5. QUALITY
    quality = stream.get('quality', '')
    
    if not quality or quality.upper() == 'SD':
        clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
        res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in full_info)
        if '4k' in clean_info and '2160p' not in full_info: res_count += 1
        
        if res_count >= 2:
            quality = "SD"
        elif '2160p' in full_info or '4k' in clean_info:
            quality = "4K"
        elif '1080p' in full_info:
            quality = "1080p"
        elif '720p' in full_info:
            quality = "720p"
        elif '480p' in full_info:
            quality = "480p"
    
    if not quality:
        quality = "SD"

    # 6. TAGS
    tags = []
    if 'dolby vision' in full_info or '.dv.' in full_info: 
        tags.append("DV")
    if 'hdr' in full_info: 
        tags.append("HDR")
    if 'hlg' in full_info:
        tags.append("HLG")
    if 'atmos' in full_info: 
        tags.append("Atmos")
    if 'remux' in full_info: 
        tags.append("REMUX")
    
    return {
        'provider': provider, 
        'source_provider': source_provider,
        'group': group, 
        'server': server, 
        'size': size, 
        'quality': quality, 
        'tags': tags
    }

def build_display_items(streams, poster_url):
    """
    Construiește lista de ListItem-uri pentru dialog.
    Format: [B]{idx}. {quality} {provider} {size} {source_provider} {server} {tags}[/B]
    """
    display_items = []
    
    for idx, s in enumerate(streams, 1):
        info = extract_stream_info(s)
        
        quality = info['quality']
        provider = info['provider']
        source_provider = info['source_provider']  # NOU! UHDMovies, etc
        group = info['group']
        server = info['server']
        size = info['size']
        tags = info['tags']
        
        # =========================================================
        # CULORI PENTRU CALITATE
        # =========================================================
        c_qual = "FF00BFFF"
        if quality == "4K": 
            c_qual = "FF00FFFF"
        elif quality == "1080p": 
            c_qual = "FF00FF7F"
        elif quality == "720p": 
            c_qual = "FFFFD700"
        
        # =========================================================
        # CONSTRUIRE TAGS STRING
        # =========================================================
        tags_parts = []
        for tag in tags:
            if tag == "DV":
                tags_parts.append("[COLOR FFDA70D6]DV[/COLOR]")
            elif tag in ["HDR", "HDR10", "HDR10+"]:
                tags_parts.append(f"[COLOR FFADFF2F]{tag}[/COLOR]")
            elif tag == "REMUX":
                tags_parts.append("[COLOR FFFF0000]REMUX[/COLOR]")
            elif tag == "Atmos":
                tags_parts.append("[COLOR FF87CEEB]Atmos[/COLOR]")
            elif tag in ["DTS", "DTS-HD", "TrueHD"]:
                tags_parts.append(f"[COLOR FF98FB98]{tag}[/COLOR]")
            elif tag in ["5.1", "7.1"]:
                tags_parts.append(f"[COLOR FFFAFAD2]{tag}[/COLOR]")
            elif tag == "HEVC":
                tags_parts.append("[COLOR FFADD8E6]HEVC[/COLOR]")
            elif tag in ["BluRay", "WEB-DL", "WEBRip"]:
                tags_parts.append(f"[COLOR FFB0C4DE]{tag}[/COLOR]")
            else:
                tags_parts.append(f"[COLOR FFDDDDDD]{tag}[/COLOR]")
        
        tags_str = " ".join(tags_parts)
        
        # =========================================================
        # CONSTRUIRE LABEL PRINCIPAL
        # Format: 01. 4K Sootio 24.35GB UHDMovies PixelDrain HDR DV
        # =========================================================
        parts = []
        
        # Index (alb)
        parts.append(f"[COLOR FFFFFFFF]{idx:02d}.[/COLOR]")
        
        # Quality (colorat)
        parts.append(f"[COLOR {c_qual}]{quality}[/COLOR]")
        
        # Provider principal (roz) - Sootio, Nuvio, etc
        if provider:
            parts.append(f"[COLOR FFFF69B4]{provider}[/COLOR]")
        
        # Size (galben)
        if size:
            parts.append(f"[COLOR FFFFEA00]{size}[/COLOR]")
        
        # Source Provider (portocaliu) - UHDMovies, MoviesDrive, MKVCinemas
        # DOAR dacă există și e diferit de provider principal
        if source_provider and source_provider.lower() not in [provider.lower(), server.lower() if server else '']:
            parts.append(f"[COLOR FFFFA500]{source_provider}[/COLOR]")
        
        # Server (verde-cyan) - PixelDrain, Worker, Flash, etc
        if server:
            # Nu afișa server-ul dacă e identic cu source_provider
            if not source_provider or server.lower() != source_provider.lower():
                parts.append(f"[COLOR FF20B2AA]{server}[/COLOR]")
        
        # Group (mov) - doar dacă nu avem source_provider și e diferit
        if group and not source_provider:
            if group.lower() != server.lower() and group.lower() != provider.lower():
                parts.append(f"[COLOR FFBA55D3]{group}[/COLOR]")
        
        # Tags (la final)
        if tags_str:
            parts.append(tags_str)
        
        label = "[B]" + "  ".join(parts) + "[/B]"
        
        # =========================================================
        # LABEL2 (titlul fișierului)
        # =========================================================
        raw_title = s.get('title', '')
        raw_name = s.get('name', '')
        
        label2 = raw_title if raw_title else raw_name
        label2 = re.sub(r'[💾🔗🇬🇧🇺🇸🇮🇳]', '', label2)
        label2 = label2.replace('\n', ' ').strip()
        label2 = re.sub(r'\s*\|\s*[A-Za-z0-9]+Hub\s*$', '', label2)
        label2 = re.sub(r'\s*🔗\s*\w+\s*\(\w+\)\s*$', '', label2)
        
        if len(label2) > 110:
            label2 = label2[:107] + "..."
        
        # =========================================================
        # CREARE LISTITEM
        # =========================================================
        li = xbmcgui.ListItem(label=label)
        li.setLabel2(label2)
        li.setArt({'icon': poster_url, 'thumb': poster_url})
        display_items.append(li)
    
    return display_items


def sort_streams_by_quality(streams):
    """Sortează aplicând noile opțiuni din setări, calitate, mărime și seederi."""
    import re
    try: sort_opt = int(ADDON.getSetting('source_sorting') or '0')
    except: sort_opt = 0

    def get_sort_key(s):
        quality_field = s.get('quality', '').lower()
        name_lower = s.get('name', '').lower()
        title_lower = s.get('title', '').lower()
        text_combined = f"{name_lower} {title_lower} {quality_field}"
        
        # Scor Calitate
        q_score = 0
        clean_text = text_combined.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
        
        res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in text_combined)
        if '4k' in clean_text and '2160p' not in text_combined: res_count += 1
        
        if res_count >= 2:
            q_score = 0  # Multi-rezoluție generică -> La coada listei absolute
        elif '2160p' in text_combined or quality_field == '4k' or '4k' in clean_text:
            q_score = 4
        elif '1080p' in text_combined or quality_field == '1080p':
            q_score = 3
        elif '720p' in text_combined or quality_field == '720p':
            q_score = 2
        elif '480p' in text_combined or '360p' in text_combined:
            q_score = 1
        
        # Mărime MB
        size_mb = 0.0
        size_field = s.get('size', '')
        if size_field and isinstance(size_field, str):
            match = re.search(r'([\d.,]+)\s*(TB|GB|GIB|MB|MIB)', size_field, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace(',', '.'))
                    unit = match.group(2).upper()
                    if 'TB' in unit: size_mb = val * 1024 * 1024
                    elif 'GB' in unit or 'GIB' in unit: size_mb = val * 1024
                    else: size_mb = val
                except: pass
        
        if size_mb == 0:
            for pattern in [r'\|\s*([\d.,]+)\s*(tb|gb|gib|mb|mib)', r'\[([\d.,]+)\s*(tb|gb|gib|mb|mib)\]', r'([\d.,]+)\s*(tb|gb|gib|mb|mib)(?:\s|$|\|)']:
                match = re.search(pattern, name_lower)
                if match:
                    try:
                        val = float(match.group(1).replace(',', '.'))
                        unit = match.group(2).upper()
                        if 'TB' in unit: size_mb = val * 1024 * 1024
                        elif 'G' in unit: size_mb = val * 1024
                        else: size_mb = val
                        break
                    except: continue
        
        # Seeders extraction
        seeders = 0
        info_dict = s.get('info', {})
        if isinstance(info_dict, dict):
            try: seeders = int(info_dict.get('seeders', 0))
            except: pass
        if seeders == 0:
            m = re.search(r'(?:👤|👥|S:)\s*(\d+)', name_lower + ' ' + title_lower)
            if m: seeders = int(m.group(1))

        # Group Score pt Setări
        is_aio = (s.get('provider_id') == 'aiostreams')
        is_cached = isinstance(info_dict, dict) and info_dict.get('is_cached', False)
        is_http = not is_aio
        
        group_score = 0
        if sort_opt == 1:
            # AIO Cached(2) -> HTTP(1) -> AIO Uncached(0)
            if is_aio and is_cached: group_score = 2
            elif is_http: group_score = 1
            else: group_score = 0
        elif sort_opt == 2:
            # AIO Cached + HTTP(2) -> AIO Uncached(1)
            if (is_aio and is_cached) or is_http: group_score = 2
            else: group_score = 1
        elif sort_opt == 3:
            # AIO Original -> HTTP Sortat
            # Prin returnarea unei valori statice pentru AIO (2, 0, 0, 0), Python 
            # va păstra exact ordinea originală din listă. HTTP va fi sortat mai jos (1)
            if is_aio: return (2, 0, 0.0, 0)
            else: return (1, q_score, size_mb, seeders)
        
        return (group_score, q_score, size_mb, seeders)

    streams.sort(key=get_sort_key, reverse=True)
    return streams


# =============================================================================
# GET ENGLISH METADATA
# =============================================================================
def get_english_metadata(tmdb_id, content_type, season=None, episode=None):
    eng_title = ""
    eng_tvshowtitle = ""
    found_imdb_id = ""
    show_parent_imdb_id = ""
    
    try:
        if content_type == 'movie':
            url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data = get_json(url)
            eng_title = data.get('title', '')
            found_imdb_id = data.get('imdb_id') or data.get('external_ids', {}).get('imdb_id', '')
        else:
            url_show = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
            data_show = get_json(url_show)
            eng_tvshowtitle = data_show.get('name', '')
            show_parent_imdb_id = data_show.get('external_ids', {}).get('imdb_id', '')
            
            if season and episode:
                url_ep = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=en-US&append_to_response=external_ids"
                data_ep = get_json(url_ep)
                eng_title = data_ep.get('name', '')
                ep_imdb = data_ep.get('external_ids', {}).get('imdb_id')
                if ep_imdb:
                    found_imdb_id = ep_imdb
                else:
                    if not found_imdb_id: 
                        found_imdb_id = show_parent_imdb_id

    except Exception as e:
        log(f"[PLAYER] Error fetching metadata: {e}", xbmc.LOGERROR)
        
    return eng_title, eng_tvshowtitle, found_imdb_id, show_parent_imdb_id


def get_filename_from_url(url, stream_title=''):
    try:
        if stream_title and len(stream_title) > 5 and '.' in stream_title:
            return stream_title
        
        clean = url.split('|')[0].split('?')[0]
        filename = urllib.parse.unquote(clean.split('/')[-1])
        return filename
    except:
        return ""


# =============================================================================
# CLASA PLAYER + MONITOR THREAD
# =============================================================================
_active_player = None
_player_monitor = None

class TMDbPlayer(xbmc.Player):
    def __init__(self, tmdb_id, content_type, season=None, episode=None, title='', year=''):
        super().__init__()
        self.tmdb_id = str(tmdb_id)
        self.content_type = content_type
        
        try: 
            self.season = int(season) if season else None
        except: 
            self.season = None
            
        try: 
            self.episode = int(episode) if episode else None
        except: 
            self.episode = None
        
        self.title = title
        self.year = str(year)
        
        self.playback_started = False
        self.watched_marked = False
        self.playback_start_time = 0
        self.last_progress_sent = 0
        self.scrobble_threshold = 5.0
        
        # ============================================================
        # Variabile pentru a păstra ULTIMA poziție cunoscută
        # (actualizate în fiecare iterație a monitorului)
        # ============================================================
        self.last_known_position = 0
        self.last_known_total = 0

    def onAVStarted(self):
        log("[PLAYER-CLASS] onAVStarted: Stream is playing stable.")
        self.playback_started = True
        self.playback_start_time = time.time()
        
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        def close_error_dialogs():
            for _ in range(30):
                xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
                xbmc.sleep(100)
        threading.Thread(target=close_error_dialogs, daemon=True).start()
        
        self._send_trakt_scrobble('start', 0)

    def onPlayBackStopped(self):
        log(f"[PLAYER-CLASS] onPlayBackStopped called")
        # Nu facem nimic aici - monitorul se ocupă

    def onPlayBackEnded(self):
        log("[PLAYER-CLASS] onPlayBackEnded called")
        self.watched_marked = True
        # Nu facem nimic aici - monitorul se ocupă

    def _send_trakt_scrobble(self, action, progress):
        try:
            from resources.lib.trakt_api import send_trakt_scrobble
            send_trakt_scrobble(action, self.tmdb_id, self.content_type, self.season, self.episode, progress)
        except: 
            pass


def _silent_scrape_next_episode(player):
    """
    Background worker invizibil. Caută sezonul/episodul următor și face 
    scrape la surse fără a deschide nicio fereastră pe ecran.
    """
    try:
        from resources.lib.tmdb_api import get_smart_season_details, get_tmdb_item_details
        from resources.lib.cache import MainCache
        from resources.lib.scraper import get_stream_data
        
        tmdb_id = player.tmdb_id
        curr_s = player.season
        curr_e = player.episode
        
        show_details = get_tmdb_item_details(tmdb_id, 'tv')
        if not show_details: return
        
        show_title = show_details.get('name', 'Unknown')
        imdb_id = show_details.get('external_ids', {}).get('imdb_id', f"tmdb:{tmdb_id}")
        from resources.lib.config import BACKDROP_BASE, IMG_BASE
        show_fanart = f"{BACKDROP_BASE}{show_details.get('backdrop_path', '')}" if show_details.get('backdrop_path') else ''
        # Construim link-ul complet pentru logo
        show_logo = f"{IMG_BASE}{show_details.get('clearlogo', '')}" if show_details.get('clearlogo') else ''
        
        # 1. Căutăm episodul următor logic
        season_data = get_smart_season_details(tmdb_id, curr_s)
        next_s = curr_s
        next_e = curr_e + 1
        next_title = ""
        found = False
        
        import datetime
        today = datetime.date.today()
        
        if season_data:
            for ep in season_data.get('episodes', []):
                if int(ep.get('episode_number', 0)) == next_e:
                    air_date_str = ep.get('air_date', '')
                    if air_date_str:
                        try:
                            parts = str(air_date_str).split('-')
                            if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                                log(f"[AUTO-SCRAPE] Episodul S{next_s:02d}E{next_e:02d} NU e lansat încă. Abort.")
                                return # Ne oprim complet, fereastra YES/NO nu va mai apărea
                        except: pass
                    else:
                        log(f"[AUTO-SCRAPE] Episodul S{next_s:02d}E{next_e:02d} nu are dată (TBA). Abort.")
                        return

                    next_title = ep.get('name', f"Episode {next_e}")
                    found = True
                    break
                    
        # Dacă nu e în sezonul curent, verificăm sezonul următor, episodul 1
        if not found:
            next_s = curr_s + 1
            next_e = 1
            next_season_data = get_smart_season_details(tmdb_id, next_s)
            if next_season_data:
                for ep in next_season_data.get('episodes', []):
                    if int(ep.get('episode_number', 0)) == next_e:
                        air_date_str = ep.get('air_date', '')
                        if air_date_str:
                            try:
                                parts = str(air_date_str).split('-')
                                if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                                    log(f"[AUTO-SCRAPE] Sezonul următor NU e lansat încă. Abort.")
                                    return
                            except: pass
                        else:
                            return

                        next_title = ep.get('name', f"Episode 1")
                        found = True
                        break
                        
        if not found:
            log("[AUTO-SCRAPE] Niciun episod următor găsit (Final de serial).")
            return
            
        log(f"[AUTO-SCRAPE] Detectat Următorul: S{next_s:02d}E{next_e:02d} - {next_title}")
        # Salvăm info în player ca să știe dialogul de la final ce să afișeze
        player.next_ep_info = {
            'season': next_s, 'episode': next_e, 'title': next_title, 
            'show_title': show_title, 'fanart': show_fanart, 'clearlogo': show_logo
        }
        
        # 2. Verificăm dacă nu a fost deja dat scrape manual înainte
        search_id = f"src_{tmdb_id}_tv_s{next_s}e{next_e}"
        cache_db = MainCache()
        cached_streams, _, _ = cache_db.get_source_cache(search_id)
        
        if cached_streams:
            log("[AUTO-SCRAPE] Sursele sunt deja în cache. Ne oprim aici.")
            return
            
        # 3. Aflăm providerii activi
        active_providers = []
        all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'meowtv', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive', 'aiostreams', 'hdhub']
        for pid in all_known_providers:
            if pid == 'aiostreams':
                if ADDON.getSetting('use_aiostreams') == 'true' or ADDON.getSetting('aiostreams') == 'true':
                    active_providers.append(pid)
            else:
                if ADDON.getSetting(f'use_{pid if pid!="nuvio" else "nuviostreams"}') == 'true':
                    active_providers.append(pid)

        # Funcție fantomă (Mock) pentru a bloca deschiderea dialogului de progres!
        def dummy_progress(percent, text): return True
            
        log("[AUTO-SCRAPE] Începe Scraping-ul Invizibil în Background...")
        streams, new_failed, canceled = get_stream_data(
            imdb_id, 'tv', next_s, next_e, 
            progress_callback=dummy_progress, 
            target_providers=active_providers
        )
        
        if streams:
            # Formatăm, sortăm și stocăm pentru când utilizatorul dă "DA"
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            try: dur = int(ADDON.getSetting('cache_sources_duration'))
            except: dur = 24
            cache_db.set_source_cache(search_id, streams, new_failed, active_providers, dur)
            log(f"[AUTO-SCRAPE] Gata! Am stocat {len(streams)} surse pentru vizionare instantanee.")
        else:
            log("[AUTO-SCRAPE] Nicio sursă găsită în background.")
            
    except Exception as e:
        log(f"[AUTO-SCRAPE] Eroare Fatală: {e}", xbmc.LOGERROR)


class AutoPlayWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.n_info = kwargs.get('n_info', {})
        self.action_result = 0 # 0 = Not Now, 1 = Auto-Play, 2 = Choose Source
        self.timer = 60 # De la câte secunde să înceapă
        self.is_closed = False

    def onInit(self):
        # Transmitem datele către XML
        self.setProperty('tmdbmovies.show_title', self.n_info.get('show_title', ''))
        self.setProperty('tmdbmovies.ep_label', f"S{self.n_info.get('season', 1):02d}E{self.n_info.get('episode', 1):02d} - {self.n_info.get('title', '')}")
        self.setProperty('tmdbmovies.fanart', self.n_info.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.n_info.get('clearlogo', ''))
        self.setProperty('tmdbmovies.next_ep_countdown', str(self.timer))
        
        # Start Countdown într-un thread separat
        threading.Thread(target=self._start_countdown, daemon=True).start()

    def _start_countdown(self):
        while self.timer > 0 and not self.is_closed:
            self.setProperty('tmdbmovies.next_ep_countdown', str(self.timer))
            xbmc.sleep(1000)
            self.timer -= 1
            
        if not self.is_closed and self.timer <= 0:
            # MODIFICAT: Acum rezultatul este 0 (Nu Acum / Închide), nu 1 (Auto-Play)
            self.action_result = 0 
            self.close()

    def onClick(self, controlId):
        if controlId == 3021:   # Auto-Play
            self.action_result = 1
            self.close()
        elif controlId == 3022: # Not Now
            self.action_result = 0
            self.close()
        elif controlId == 3023: # Choose Source
            self.action_result = 2
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110): # Apăsare pe butonul Back
            self.action_result = 0
            self.close()

    def close(self):
        self.is_closed = True
        super(AutoPlayWindow, self).close()


def start_playback_monitor(player_instance):
    """Monitor thread care verifică periodic și salvează la oprire."""
    global _player_monitor
    
    if _player_monitor and _player_monitor.is_alive():
        return
    
    def monitor_loop():
        log("[PLAYER-MONITOR] Monitor thread started")
        
        # Așteptăm să pornească playerul
        for _ in range(30):
            if player_instance.isPlaying():
                break
            xbmc.sleep(500)
        else:
            log("[PLAYER-MONITOR] Player did not start, exiting monitor")
            try: xbmcgui.Window(10000).clearProperty('tmdbmovies.release_name')
            except: pass
            return
        
        log("[PLAYER-MONITOR] Player is playing, monitoring...")
        player_instance.playback_start_time = time.time()
        
        last_known_progress = 0
        last_known_position = 0
        last_known_total = 0
        
        while player_instance.isPlaying():
            try:
                curr = player_instance.getTime()
                total = player_instance.getTotalTime()
                
                if curr > 0 and total > 0:
                    last_known_position = curr
                    last_known_total = total
                    last_known_progress = (curr / total) * 100
                
                # Scrobble periodic la Trakt și Auto-Scrape
                if total > 0 and curr > 60: # Scădem limita la 60 secunde pentru episoade mai scurte
                    progress = (curr / total) * 100
                    
                    # --- START INVISIBLE AUTO SCRAPE (Declanșat la 80% ca să aibă timp să caute) ---
                    is_ep = (player_instance.content_type in ['tv', 'episode']) and (player_instance.season is not None) and (player_instance.episode is not None)
                    if is_ep and progress >= 80:
                        if not getattr(player_instance, 'next_episode_scraped', False):
                            if ADDON.getSetting('auto_scrape_next_episode') != 'false':
                                player_instance.next_episode_scraped = True
                                log("[PLAYER-MONITOR] 80% reached. Triggering Ghost Scraper.")
                                threading.Thread(target=_silent_scrape_next_episode, args=(player_instance,), daemon=True).start()
                    # ------------------------------------------------------------------------------

                    if not player_instance.watched_marked and progress >= 85:
                        log(f"[PLAYER-MONITOR] 85% reached. Will mark on stop.")
                        player_instance.watched_marked = True
                    
                    if abs(progress - player_instance.last_progress_sent) >= player_instance.scrobble_threshold:
                        player_instance._send_trakt_scrobble('scrobble', progress)
                        player_instance.last_progress_sent = progress
                        
            except Exception as e:
                log(f"[PLAYER-MONITOR] Loop error: {e}")
            
            xbmc.sleep(250)
        
        # ============================================================
        # PLAYERUL S-A OPRIT
        # ============================================================
        watched_duration = 0
        if player_instance.playback_start_time > 0:
            watched_duration = time.time() - player_instance.playback_start_time
        
        log(f"[PLAYER-MONITOR] Player stopped after {int(watched_duration)}s")
        
        # Optimizare masivă: Kodi are nevoie doar de max 300ms să se stabilizeze, indiferent de durata redării
        xbmc.sleep(300)
        
        # CURĂȚĂM PROPRIETĂȚILE
        log("[PLAYER-MONITOR] Clearing Window Properties.")
        try:
            win = xbmcgui.Window(10000)
            props_to_clear = ['tmdb_id', 'TMDb_ID', 'imdb_id', 'IMDb_ID', 'tmdbmovies.release_name']
            for prop in props_to_clear: win.clearProperty(prop)
        except Exception as e:
            log(f"[PLAYER-MONITOR] Error clearing properties: {e}")
        
        # VALIDARE DATE PENTRU SALVARE
        if last_known_progress <= 0 or last_known_total <= 0:
            log(f"[PLAYER-MONITOR] No valid progress ({last_known_progress:.2f}%), skipping save")
            if watched_duration < 30:
                log(f"[PLAYER-MONITOR] Very short playback. Skipping refresh.")
                return
            xbmc.sleep(1500)
            xbmc.executebuiltin('Container.Refresh')
            return
        
        mins = int(last_known_position) // 60
        secs = int(last_known_position) % 60
        log(f"[PLAYER-MONITOR] ✓ Final position: {mins}m {secs}s ({last_known_progress:.2f}%)")
        
        # SALVARE PROGRES (LOGICA NOUĂ)
        try:
            from resources.lib import trakt_sync

            if player_instance.watched_marked or last_known_progress >= 85:
                log(f"[PLAYER-MONITOR] Marking as WATCHED ({last_known_progress:.2f}%)")
                trakt_sync.mark_as_watched_internal(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    notify=True, sync_trakt=True
                )
                # Ștergem punctul de resume
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    100, player_instance.title, player_instance.year
                )
                player_instance._send_trakt_scrobble('stop', 100)
                
                # BIFĂM CĂ E ELIGIBIL PENTRU RATING LA FINAL
                player_instance.should_prompt_rating = True
                
            elif watched_duration > 180:  # Minim 3 minute de vizionare pentru a salva resume
                # <<-- MODIFICARE CHEIE: Folosim numărul magic -->>
                # Adăugăm 1.000.000 la secunde pentru a le diferenția de procente
                exact_seconds_value = last_known_position + 1000000

                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    exact_seconds_value,  # Trimitem numărul magic la DB
                    player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('stop', last_known_progress)
                log(f"[PLAYER-MONITOR] ✓ Resume saved locally (Exact Seconds stored as {exact_seconds_value})")
                
            else:
                log(f"[PLAYER-MONITOR] Watched <3min ({int(watched_duration)}s). Deleting ghost session.")
                # 1. Trimitem STOP la Trakt cu progres 0 ca să anuleze sesiunea "watching now"
                player_instance._send_trakt_scrobble('stop', 0)
                
                # 2. Ștergem proactiv din baza de date locală orice urmă
                try:
                    from resources.lib import trakt_sync
                    conn = trakt_sync.get_connection()
                    conn.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", 
                                 (str(player_instance.tmdb_id), player_instance.season or 0, player_instance.episode or 0))
                    if player_instance.content_type == 'movie':
                        conn.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(player_instance.tmdb_id),))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    log(f"[PLAYER-MONITOR] Eroare stergere resume scurt: {e}")
                
        except Exception as e:
            log(f"[PLAYER-MONITOR] Error saving progress: {e}", xbmc.LOGERROR)
        
        # REFRESH CONTAINER
        is_fully_watched = player_instance.watched_marked or last_known_progress >= 85
        
        if not is_fully_watched and watched_duration < 30:
            log(f"[PLAYER-MONITOR] Short playback (<30s). Skipping refresh and dialogs.")
            return
        
        # ==============================================================
        # POST-PLAYBACK: DIALOG NEXT EPISODE (BINGE WATCHING SMART)
        # ==============================================================
        prompted_next = False
        is_ep = (player_instance.content_type in ['tv', 'episode']) and (player_instance.season is not None) and (player_instance.episode is not None)
        if is_ep and hasattr(player_instance, 'next_ep_info') and player_instance.next_ep_info:
            if ADDON.getSetting('auto_scrape_next_episode') != 'false' and (player_instance.watched_marked or last_known_progress >= 85):
                n_info = player_instance.next_ep_info
                
                # Închidem orice dialog vechi
                xbmc.executebuiltin('Dialog.Close(all,true)')
                
                # Lansăm Fereastra XML Custom
                win = AutoPlayWindow('autoplay_dialog.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', n_info=n_info)
                win.doModal()
                ret = win.action_result
                del win
                
                log(f"[BINGE-WATCH] Buton apăsat: {ret}")
                
                # În Kodi yesnocustom: 1 = Yes(Auto-Play), 2 = Custom(Alege Sursa), 0 = No, -1 = Timeout
                if ret == 1 or ret == 2:
                    prompted_next = True
                    url_params = {
                        'mode': 'sources', 
                        'tmdb_id': player_instance.tmdb_id, 
                        'type': 'tv',
                        'season': str(n_info['season']), 
                        'episode': str(n_info['episode']),
                        'title': n_info['title'], 
                        'tv_show_title': n_info['show_title']
                    }
                    
                    if ret == 1:
                        log("[BINGE-WATCH] Utilizatorul a ales AUTO-PLAY")
                        url_params['auto_play_next'] = 'true'
                        url_params['prev_quality'] = getattr(player_instance, 'prev_quality', '')
                        url_params['prev_group'] = getattr(player_instance, 'prev_group', '')
                        url_params['prev_is_sdr'] = 'true' if getattr(player_instance, 'prev_is_sdr', True) else 'false'
                    else:
                        log("[BINGE-WATCH] Utilizatorul a ales ALEGE SURSA (Manual)")
                        
                    import urllib.parse
                    plugin_url = f"{sys.argv[0]}?{urllib.parse.urlencode(url_params)}"
                    
                    # Oprim forțat player-ul vechi dacă a rămas blocat
                    if xbmc.Player().isPlaying():
                        xbmc.Player().stop()
                        xbmc.sleep(500)
                        
                    xbmc.executebuiltin(f"RunPlugin({plugin_url})")
        # ==============================================================

        # ==============================================================
        # POST-PLAYBACK: DIALOG RATING TRAKT (Doar dacă playerul s-a oprit definitiv)
        # ==============================================================
        if getattr(player_instance, 'should_prompt_rating', False) and not prompted_next:
            try:
                rate_movies = ADDON.getSetting('trakt_rate_movies') == 'true'
                rate_eps = ADDON.getSetting('trakt_rate_episodes') == 'true'
                
                if (player_instance.content_type == 'movie' and rate_movies) or (is_ep and rate_eps):
                    _prompt_trakt_rating(
                        player_instance.tmdb_id, 
                        player_instance.content_type, 
                        player_instance.season, 
                        player_instance.episode, 
                        player_instance.title
                    )
            except Exception as e:
                log(f"[PLAYER-MONITOR] Error prompting rating: {e}")

        # Dacă utilizatorul a refuzat sau funcția e dezactivată, facem refresh standard la listă
        if not prompted_next:
            try:
                container_path = xbmc.getInfoLabel('Container.FolderPath')
                if container_path and 'plugin://' in container_path.lower() and 'plugin.video.tmdbmovies' not in container_path.lower():
                    log(f"[PLAYER-MONITOR] Not in our container. Skipping refresh.")
                    return
            except:
                pass
            
            # Optimizare: Am scos sleep-ul uriaș de 1500ms
            log("[PLAYER-MONITOR] Refreshing container immediately...")
            xbmc.executebuiltin('Container.Refresh')
            log("[PLAYER-MONITOR] Container refreshed!")
            
        log("[PLAYER-MONITOR] Monitor thread finished")
    
    _player_monitor = threading.Thread(target=monitor_loop, daemon=True)
    _player_monitor.start()


def is_sd_or_720p(stream):
    """Verifică dacă sursa este SD sau 720p (sub 1080p)."""
    full_info = (stream.get('name', '') + stream.get('title', '')).lower()
    
    # Eliminăm fals-pozitivele pentru verificare 4K pur
    clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
    
    # Dacă are mai multe rezoluții, e link generic, deci îl tratăm ca SD/720p
    res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in full_info)
    if '4k' in clean_info and '2160p' not in full_info: res_count += 1
    if res_count >= 2:
        return True
    
    # Dacă are 1080p sau 4K pur, NU e SD/720p
    if '1080' in full_info or '2160' in full_info or '4k' in clean_info:
        return False
    
    # Dacă are 720p sau rezoluție mai mică
    if '720' in full_info or '480' in full_info or '360' in full_info:
        return True
    
    # Dacă nu are nicio rezoluție specificată
    has_quality = any(x in full_info for x in['1080', '720', '480', '360', '2160', '4k'])
    if not has_quality:
        return True  
    
    return False


# =============================================================================
# FORMATTER PENTRU NOUA FEREASTRA POV (RESULTS WINDOW)
# =============================================================================
def format_for_results_window(streams, poster_url):
    window_results =[]
    for s in streams:
        info_extr = extract_stream_info(s)
        
        raw_name = s.get('title', '')
        if not raw_name or len(raw_name) < 5:
            raw_name = s.get('name', '')
            
        # --- PROTECȚIE STRICTĂ PENTRU 'info' ---
        original_info = s.get('info')
        stream_info = {}
        
        # Dacă este deja dicționar (ex: din AIO Streams), copiem datele.
        # Dacă este text (ex: din cache-ul vechi), îl salvăm izolat ca să nu mai dea eroare la .get()
        if isinstance(original_info, dict):
            stream_info = original_info.copy()
        elif isinstance(original_info, str):
            stream_info['original_info_str'] = original_info
            
        stream_info['quality'] = info_extr['quality']
        stream_info['size'] = info_extr['size']
        stream_info['provider'] = info_extr['provider']
        stream_info['source_provider'] = info_extr['source_provider']
        stream_info['server'] = info_extr['server']
        stream_info['tags'] = info_extr['tags']
        
        # Acum folosim get pe stream_info (care e GARANTAT dicționar), evitând AttributeError
        stream_info['debrid_service'] = stream_info.get('debrid_service', '')
        stream_info['is_cached'] = stream_info.get('is_cached', False)
        stream_info['is_cloud'] = stream_info.get('is_cloud', False)
        stream_info['addon'] = stream_info.get('addon', '')
        stream_info['indexer'] = stream_info.get('indexer', '')
        stream_info['seeders'] = stream_info.get('seeders', 0) # <--- ADĂUGAT AICI PENTRU POV
        stream_info['releaseGroup'] = stream_info.get('releaseGroup', '')
        
        window_results.append({
            'name': raw_name,
            'url': s.get('url', ''),
            'info': stream_info,
            'raw_stream_data': s 
        })
    return window_results


# =============================================================================
# PLAY WITH ROLLOVER - VERSIUNE FINALĂ (FĂRĂ BUFFERING DUPLICAT)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties, resume_time=0, from_resolve=False):
    
    log("[PLAYER] === PLAY_WITH_ROLLOVER START ===")
    
    # ===========================================================================
    # CURĂȚĂM WINDOW PROPERTIES LA ÎNCEPUT (FĂRĂ URME DE ALTE ADDONURI)
    # ===========================================================================
    win = xbmcgui.Window(10000)
    
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'tmdbmovies.release_name',
        'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
        'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
        'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
        'tmdbmovies.has_ro_sub'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[PLAYER] Window Properties curățate la început')
    
    # SETĂM ID-URILE CORECTE IMEDIAT
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
        log(f'[PLAYER] Window Property TMDb setat: {tmdb_id}')
    
    final_imdb_id = unique_ids.get('imdb') if unique_ids else None
    if final_imdb_id:
        win.setProperty('imdb_id', str(final_imdb_id))
        win.setProperty('IMDb_ID', str(final_imdb_id))
        log(f'[PLAYER] Window Property IMDb setat: {final_imdb_id}')
    # ===========================================================================
    
    xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
    xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()
    xbmc.executebuiltin('Playlist.Clear')
    
    if not from_resolve:
        xbmc.executebuiltin('Dialog.Close(busydialog)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    
    if xbmc.Player().isPlaying():
        xbmc.Player().stop()
        xbmc.sleep(300)

    total_streams = len(streams)
    log(f"[PLAYER] Total surse: {total_streams}")
    
    p_title = info_tag.get('title', 'Unknown')
    p_year = info_tag.get('year', '')

    from resources.lib.utils import clean_text
    
    bad_domains =[
        'googleusercontent.com', 'googlevideo.com', 'video-leech.pro', 'video-seed.pro',
    ]
    
    valid_url = None
    valid_index = -1
    p_dialog = None

    for i in range(start_index, total_streams):
        try:
            stream = streams[i]
            url = stream.get('url', '')

            is_aio = stream.get('provider_id') == 'aiostreams'
            
            if not url or not url.startswith(('http://', 'https://')):
                continue
            
            base_url_check = url.split('|')[0].lower()
            if any(bad in base_url_check for bad in bad_domains):
                continue
            
            raw_name = stream.get('name', '').lower()
            provider_id = stream.get('provider_id', '').lower()
            is_sooti = 'sooti' in raw_name or 'sooti' in provider_id or 'sootio' in raw_name or 'sooti' in url.lower()
            
            raw_n = stream.get('name', 'Unknown')
            display_name = clean_text(raw_n).replace('\n', ' ')
            display_name = display_name.replace('Sooti', 'Sootio').replace('XDM', 'XDMovies')
            display_name = display_name[:50] 

            full_info = (raw_n + stream.get('title', '')).lower()
            c_qual = "FF1E90FF"
            qual_txt = "SD"
            
            clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
            res_count = sum(1 for r in['2160p', '1080p', '720p', '480p', '360p'] if r in full_info)
            if '4k' in clean_info and '2160p' not in full_info: res_count += 1
            
            if res_count >= 2:
                qual_txt = "SD"; c_qual = "FF1E90FF"
            elif '2160' in clean_info or '4k' in clean_info:
                qual_txt = "4K"; c_qual = "FFFF00FF" 
            elif '1080' in clean_info:
                qual_txt = "1080p"; c_qual = "FF7CFC00" 
            elif '720' in clean_info:
                qual_txt = "720p"; c_qual = "FFBA55D3" 
            elif '480' in clean_info:
                qual_txt = "480p"
            
            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except: pass
                
                is_valid = False
                if is_aio or any(x in base_url.lower() for x in['real-debrid.com', 'alldebrid', 'premiumize', 'torbox', 'debrid']):
                    is_valid = True
                    log(f"[PLAYER] Sursă AIO/Debrid detectată -> Bypass verificare.")
                else:
                    # Afișăm caseta DOAR dacă trebuie să facem request pe bune
                    if p_dialog is None:
                        p_dialog = xbmcgui.DialogProgressBG()
                        p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Verificare sursă...")
                        
                    counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
                    msg = f"Aștept răspuns de la {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR] •[B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
                    p_dialog.update(int(((i - start_index + 1) / max(1, total_streams - start_index)) * 100), message=msg)
                    
                    is_valid = check_url_validity(base_url, headers=check_headers)

                if is_valid and is_sooti:
                    if PLAYER_AUDIO_CHECK_ONLY_SD:
                        if is_sd_or_720p(stream):
                            if check_sooti_audio_only(base_url, headers=check_headers):
                                is_valid = False
                    else:
                        if check_sooti_audio_only(base_url, headers=check_headers):
                            is_valid = False
                
                if is_valid:
                    valid_url = url
                    valid_index = i
                    log(f"[PLAYER] ✓ SURSĂ VALIDĂ: {i+1}")
                    break
            except Exception as e:
                log(f"[PLAYER] Eroare verificare: {e}")
                continue
                
        except Exception as e:
            log(f"[PLAYER] Eroare sursa {i+1}: {e}", xbmc.LOGERROR)
            continue
    
    if p_dialog:
        p_dialog.close()
    
    if valid_url:
        log(f"[PLAYER] === PORNIRE REDARE SURSA {valid_index + 1} ===")
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        global _active_player
        
        stop_cleaner = threading.Event() 
        def playlist_cleaner():
            for _ in range(20):
                if xbmc.Player().isPlaying(): break
                xbmc.sleep(500)
            start_time = time.time()
            while not stop_cleaner.is_set():
                if not xbmc.Player().isPlaying() and (time.time() - start_time > 5): break
                xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
                if xbmc.getCondVisibility('Window.IsVisible(okdialog)'): xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                if xbmc.getCondVisibility('Window.IsVisible(progressdialog)'): xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                xbmc.sleep(500)
        
        cleaner_thread = threading.Thread(target=playlist_cleaner, daemon=True)
        cleaner_thread.start()
        
        _active_player = TMDbPlayer(tmdb_id, c_type, season, episode, title=p_title, year=str(p_year))
        player = _active_player
        
        current_stream = streams[valid_index]
        
        # ==============================================================
        # FIX EASYNEWS: NO SEEK (Prevenire erori conexiune)
        # ==============================================================
        try:
            if ADDON.getSetting('easynews_noseek') != 'false':
                info_dict = current_stream.get('info', {})
                is_en = False
                if isinstance(info_dict, dict):
                    if 'easynews' in str(info_dict.get('addon', '')).lower() or 'easynews' in str(info_dict.get('debrid_service', '')).lower():
                        is_en = True
                if not is_en and ('easynews' in current_stream.get('name', '').lower() or 'easynews' in valid_url.lower()):
                    is_en = True
                    
                if is_en:
                    if '|' in valid_url:
                        valid_url += '&seekable=0'
                    else:
                        valid_url += '|seekable=0'
                    log(f"[PLAYER] EasyNews detectat -> Adăugat seekable=0 la URL pentru a preveni erorile.")
        except: pass
        # ==============================================================
        
        # --- SALVARE METADATE PENTRU NEXT EPISODE ---
        info_extr = extract_stream_info(current_stream)
        player.prev_quality = info_extr.get('quality', '')
        player.prev_group = info_extr.get('group', '').lower() or current_stream.get('info', {}).get('releaseGroup', '').lower()
        player.prev_is_sdr = not any(t in info_extr.get('tags', []) for t in ['HDR', 'HDR10', 'HDR10+', 'DV'])
        # --------------------------------------------
        
        # --- LOGARE STREAM DATA  AIO ---
        
        # --- LOGARE STREAM DATA  AIO ---
        try:
            stream_dump = json.dumps(current_stream, indent=2, ensure_ascii=False)
            xbmc.log(f"[TMDb Movies] 🧲 STREAM DATA 🧲:\n{stream_dump}", xbmc.LOGINFO)
        except:
            pass
        # --------------------------
        
        release_name_for_subs = current_stream.get('title', '')
        if not release_name_for_subs or len(release_name_for_subs) < 10:
             release_name_for_subs = current_stream.get('name', '')
             
        try:
            win = xbmcgui.Window(10000)
            win.setProperty('tmdbmovies.release_name', str(release_name_for_subs))
        except: pass
        
        li = xbmcgui.ListItem(label=info_tag['title'], path=valid_url)
        from resources.lib.tmdb_api import set_metadata
        set_metadata(li, info_tag, unique_ids)
        if art: li.setArt(art)
        for k, v in properties.items(): li.setProperty(k, str(v))
        
        player.play(valid_url, li)
        
        xbmc.executebuiltin('Dialog.Close(busydialog)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        start_playback_monitor(player)
        
        if resume_time > 0:
            def do_resume():
                for _ in range(30):
                    if player.isPlaying(): break
                    xbmc.sleep(500)
                else: return
                xbmc.sleep(3000)
                target_pos = float(resume_time)
                for attempt in range(5):
                    if not player.isPlaying(): return
                    try:
                        current_pos = player.getTime()
                        if abs(current_pos - target_pos) < 30: return
                        player.seekTime(target_pos)
                        xbmc.sleep(2000)
                        new_pos = player.getTime()
                        if abs(new_pos - target_pos) < 60: return
                    except Exception as e: pass
                    xbmc.sleep(1000)
            threading.Thread(target=do_resume, daemon=True).start()
        
        if unique_ids.get('imdb'):
            threading.Thread(target=subtitles.run_wyzie_service, args=(unique_ids['imdb'], season, episode)).start()
            
    else:
        log(f"[PLAYER] FAIL - Nicio sursă validă din {total_streams}")
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Nicio sursă nu a putut fi redată", TMDbmovies_ICON)
    
    log("[PLAYER] === END ===")

# =============================================================================
# LOGICA AUTO PLAY (Windows/Android)
# =============================================================================
def sort_streams_for_autoplay(streams, profile_idx):
    """
    profile_idx: 0 = Windows 1080p, 1 = Android 4K, 2 = Android 1080p
    """
    log(f"[AUTOPLAY] Processing profile index: {profile_idx}")
    
    # Exclude 4K dacă profilul e 1080p (Windows sau Android 1080p)
    if profile_idx == 0 or profile_idx == 2:
        streams = [s for s in streams if '4k' not in s.get('quality', '').lower() and '2160' not in s.get('name', '')]
    
    # 1. Android 4K sau Android 1080p -> Sortare standard (Vix primul > Calitate > Mărime)
    if profile_idx == 1 or profile_idx == 2:
        return sort_streams_by_quality(streams)
    
# 2. Windows 1080p -> Logică specială 
    if profile_idx == 0:
        
        # ✨ LINIA MAGICĂ: Scrie 'meow' sau 'vix' pentru a alege cine are prioritate absolută la Autoplay!
        KING_PROVIDER = 'meow'
        
        top_streams = []
        priority_streams = [] # Pixel + CloudR2
        other_streams = []
        
        for s in streams:
            raw_name = s.get('name', '').lower()
            provider_id = s.get('provider_id', '').lower()
            url = s.get('url', '').lower()
            
            is_vix = 'vixsrc' in provider_id or 'vix' in raw_name
            is_meow = 'meowtv' in provider_id or 'meow' in raw_name
            
            # Detectare Pixel & CloudR2 (Prioritate 2 - merg bine pe Windows)
            is_good_windows = False
            if 'pixel' in raw_name or 'pix' in raw_name or 'hubpix' in raw_name:
                is_good_windows = True
            elif 'pixeldrain' in url or 'pixel' in url:
                is_good_windows = True
            elif 'cloudr2' in raw_name:
                is_good_windows = True
            elif 'pub-' in url or 'r2.dev' in url: 
                is_good_windows = True
                
            # Distribuire
            if is_meow or is_vix:
                top_streams.append(s)
            elif is_good_windows:
                priority_streams.append(s)
            else:
                other_streams.append(s)
        
        # Sortăm standard pe calitate/mărime
        top_streams = sort_streams_by_quality(top_streams)
        priority_streams = sort_streams_by_quality(priority_streams)
        other_streams = sort_streams_by_quality(other_streams)
        
        # ✨ APLICĂ MAGIA: Sortează lista "top_streams" astfel încât Regele ales să fie primul
        top_streams.sort(key=lambda x: KING_PROVIDER in x.get('provider_id', '').lower() or KING_PROVIDER in x.get('name', '').lower(), reverse=True)
        
        final_list = top_streams + priority_streams + other_streams
        log(f"[AUTOPLAY] Windows Logic: {len(top_streams)} Top (King: {KING_PROVIDER}), {len(priority_streams)} Pixel/Cloud")
        return final_list


def find_best_stream_index(streams, prev_quality, prev_group, prev_is_sdr):
    """Găsește cel mai bun stream pentru Auto-Play. Cu fallback garantat."""
    best_idx = -1
    best_score = -1
    
    qual_scores = {'4K': 40, '1080p': 30, '720p': 20, '480p': 10, 'SD': 10}
    prev_q_val = qual_scores.get(prev_quality, 0)
    
    log(f"[BINGE-WATCH] Căutăm: Qual={prev_quality}, Group={prev_group}, SDR={prev_is_sdr}")
    
    for i, s in enumerate(streams):
        info = extract_stream_info(s)
        s_qual = info.get('quality', '')
        s_q_val = qual_scores.get(s_qual, 0)
        s_group = info.get('group', '').lower() or s.get('info', {}).get('releaseGroup', '').lower()
        s_tags = info.get('tags', [])
        
        s_has_hdr = any(t in s_tags for t in ['HDR', 'HDR10', 'HDR10+', 'DV'])
        s_is_sdr = not s_has_hdr
        
        s_is_cached = s.get('info', {}).get('is_cached', False)
        if s.get('provider_id') != 'aiostreams':
            s_is_cached = True # Sursele HTTP directe
            
        score = 0
        
        # 1. PROTECȚIE SDR / HDR
        if prev_is_sdr:
            if not s_is_sdr: continue # Dacă te uitai la Normal, evită HDR/DV
        else:
            if not s_is_sdr: score += 500 # Dacă te uitai la HDR, preferă HDR
                
        # 2. CACHED
        if s_is_cached: score += 10000
            
        # 3. REZOLUȚIE
        if s_qual == prev_quality: score += 5000
        elif s_q_val <= prev_q_val: score += 2000 + s_q_val
        else: score += s_q_val
            
        # 4. GRUP (Ex: FLUX)
        if prev_group and s_group and prev_group == s_group:
            score += 1000
            
        if score > best_score:
            best_score = score
            best_idx = i
            
    # FALLBACK GARANTAT: Dacă tot nu găsim potrivire perfectă, luăm primul Cached 1080p sau efectiv prima sursă!
    if best_idx == -1 and len(streams) > 0:
        log("[BINGE-WATCH] Nu s-a găsit match exact. Fallback la prima sursă validă.")
        for i, s in enumerate(streams):
            if s.get('info', {}).get('is_cached', False) and '1080p' in extract_stream_info(s).get('quality', ''):
                return i
        return 0
        
    return best_idx

# =============================================================================
# LIST SOURCES - VERSIUNE CORECTATĂ PENTRU RESULTS WINDOW (Fără fallback)
# =============================================================================
def list_sources(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    
    # CURĂȚĂM WINDOW PROPERTIES LA ÎNCEPUT
    win = xbmcgui.Window(10000)
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'tmdbmovies.release_name',
        'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
        'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
        'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
        'tmdbmovies.has_ro_sub'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[LIST-SOURCES] Window Properties curățate la început')
    
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
    
    ids = {}
    
    # CALCULARE POZIȚIE RESUME
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
    resume_time = 0
    
    if progress_value > 0 and progress_value < 90:
        duration_secs = 0
        try:
            if c_type == 'movie':
                url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                runtime = data.get('runtime', 0) if data else 0
                if runtime: duration_secs = int(runtime) * 60
            else:
                url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                if data:
                    runtimes = data.get('episode_run_time', [])
                    if runtimes: duration_secs = int(runtimes[0]) * 60
                    else: duration_secs = 2700
        except: pass
        if duration_secs <= 0: duration_secs = 7200
        resume_time = int((progress_value / 100.0) * duration_secs)
    elif progress_value >= 1000000:
        resume_time = int(progress_value - 1000000)

    # Meniu resume
    if resume_time > 180:
        m, s = divmod(resume_time, 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
        
        choice = xbmcgui.Dialog().contextmenu([f"Resume from {time_str}", "Play from beginning"])
        if choice == 1: resume_time = 0
        elif choice == -1:
            try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except: pass
            return

    # CAUTARE / CACHE
    all_known_providers =['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'meowtv', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive', 'aiostreams', 'hdhub']
    active_providers =[]
    for pid in all_known_providers:
        if pid == 'aiostreams':
            # Suportă ambele variante de ID din settings.xml pentru AIO
            if ADDON.getSetting('use_aiostreams') == 'true' or ADDON.getSetting('aiostreams') == 'true':
                active_providers.append(pid)
        else:
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if ADDON.getSetting(setting_id) == 'true':
                active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: scanned_providers_history = []
    if failed_providers_history is None: failed_providers_history = []

    streams = []
    providers_to_scan = [] 
    
    if cached_streams is not None:
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: s_pid = 'nuvio'
                elif 'vix' in raw_name: s_pid = 'vixsrc'
                elif 'sooti' in raw_name: s_pid = 'sooti'
                elif 'vega' in raw_name: s_pid = 'vega'
                elif 'vidzee' in raw_name: s_pid = 'vidzee'
                elif 'meow' in raw_name: s_pid = 'meowtv'
                elif 'rogflix' in raw_name: s_pid = 'rogflix'
                elif 'streamvix' in raw_name: s_pid = 'streamvix'
                elif 'hdhub' in raw_name: s_pid = 'hdhub4u'
                elif 'mkvcinemas' in raw_name: s_pid = 'mkvcinemas'
                elif 'xdmovies' in raw_name: s_pid = 'xdmovies'
                elif 'moviesdrive' in raw_name: s_pid = 'moviesdrive'
                elif 'hdhub' in raw_name: s_pid = 'hdhub'
                elif 'aio' in raw_name or 'comet' in raw_name or 'torrentio' in raw_name: s_pid = 'aiostreams' # <--- NOU
            
            if s_pid and s_pid not in active_providers:
                continue 
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Se caută surse...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id')
        if not imdb_id: imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            msg = f"[COLOR FF6AFB92]{title}[/COLOR] • [COLOR FFFF00FF]{provider_name}[/COLOR]"
            p_dialog.update(percent, message=msg)
            return True

        target_list = providers_to_scan if cached_streams is not None else None
        final_target = [p for p in target_list if p in active_providers] if target_list else active_providers

        new_streams, new_failed, was_canceled = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target
        )
        
        p_dialog.close()
        
        if was_canceled:
            log("[LIST-SOURCES] User cancelled scanning. Aborting without saving cache.")
            try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except: pass
            return
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
                
        final_failed = new_failed

        if cached_streams is not None:
            streams.extend(new_streams)
        else:
            streams = new_streams
            
        if streams or final_scanned:
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)

    if not streams:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Nu s-au găsit surse", TMDbmovies_ICON)
        try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except: pass
        return

    # FILTRARE PENTRU AFIȘARE
    all_streams_count = len(streams)
    filtered_streams, quality_stats = filter_streams_for_display(streams)
    
    if not filtered_streams:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", f"Toate cele {all_streams_count} surse sunt filtrate!", TMDbmovies_ICON, 3000)
        try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except: pass
        return
    
    # === PREGĂTIRE METADATA PENTRU FEREASTRA POV ===
    poster_url = get_poster_url(tmdb_id, c_type, season)
    eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
    
    if not ids: 
        try: ids = get_external_ids(c_type, tmdb_id)
        except: ids = {}

    final_imdb_id = tv_show_parent_imdb_id if c_type == 'tv' else (extra_imdb_id or imdb_id)
    final_title = eng_title if eng_title else title
    final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')

    meta_dict = {
        'title': final_title,
        'tvshowtitle': final_show_title,
        'year': year,
        'poster': poster_url,
        'fanart': '',
        'plot': '',
        'imdb_id': final_imdb_id,
        'tmdb_id': tmdb_id,
        'season': season,
        'episode': episode,
        'clearlogo': '' 
    }
    
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        details = get_tmdb_item_details(str(tmdb_id), c_type)
        if details:
            meta_dict['plot'] = details.get('overview', '')
            meta_dict['rating'] = details.get('vote_average', 0.0)
            meta_dict['votes'] = details.get('vote_count', 0)
            
            if details.get('genres'):
                meta_dict['genre'] = [g['name'] for g in details['genres']]
            
            if c_type == 'movie' and details.get('production_companies'):
                meta_dict['studio'] = [c['name'] for c in details['production_companies']]
            elif c_type in ['tv', 'episode'] and details.get('networks'):
                meta_dict['studio'] = [n['name'] for n in details['networks']]
                
            cast = []
            for p in details.get('credits', {}).get('cast', [])[:15]:
                if p.get('name'):
                    thumb = f"https://image.tmdb.org/t/p/w500{p['profile_path']}" if p.get('profile_path') else ''
                    cast.append({"name": p['name'], "role": p.get('character', ''), "thumbnail": thumb})
            if cast: meta_dict['cast'] = cast
            
            if details.get('poster_path'):
                meta_dict['poster'] = f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
                poster_url = meta_dict['poster']
                
            if c_type == 'movie' and details.get('title'):
                final_title = details['title']
                meta_dict['title'] = final_title
                
            if c_type == 'tv' and season and episode:
                from resources.lib.tmdb_api import get_smart_season_details
                season_data = get_smart_season_details(tmdb_id, season)
                if season_data:
                    for ep in season_data.get('episodes',[]):
                        if int(ep.get('episode_number', -1)) == int(episode):
                            if ep.get('overview'):
                                meta_dict['plot'] = ep['overview']
                            if ep.get('name'):
                                final_title = ep['name']
                                meta_dict['title'] = final_title
                            if ep.get('vote_average'):
                                meta_dict['rating'] = ep.get('vote_average')
                            break
                            
            if details.get('backdrop_path'):
                meta_dict['fanart'] = f"https://image.tmdb.org/t/p/original{details['backdrop_path']}"
            if details.get('clearlogo'):
                meta_dict['clearlogo'] = f"https://image.tmdb.org/t/p/w500{details['clearlogo']}"
    except: pass

    # Fetch direct titlu episod RO (sigur, bypass cache)
    if ADDON.getSetting('plot_language') == '1' and c_type == 'tv' and season and episode:
        try:
            url_ep_ro = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=ro-RO"
            data_ep_ro = get_json(url_ep_ro)
            if data_ep_ro and data_ep_ro.get('name', '').strip():
                ro_name = data_ep_ro['name'].strip()
                if not (ro_name.lower().startswith("episodul ") and ro_name.split(" ")[-1].isdigit()):
                    meta_dict['title'] = ro_name
        except:
            pass

    auto_play = ADDON.getSetting('auto_play') == 'true'
    ret = -1

    # =========================================================
    # --- START BINGE WATCHING (SMART AUTO-PLAY) ---
    # =========================================================
    auto_play_next = params.get('auto_play_next') == 'true'
    log(f"[BINGE-WATCH] list_sources a primit auto_play_next={auto_play_next}")
    
    if auto_play_next:
        prev_quality = params.get('prev_quality', '')
        prev_group = params.get('prev_group', '')
        prev_is_sdr = params.get('prev_is_sdr') == 'true'
        
        best_idx = find_best_stream_index(filtered_streams, prev_quality, prev_group, prev_is_sdr)
        log(f"[BINGE-WATCH] Sursa aleasă index={best_idx} din {len(filtered_streams)}")
        
        if best_idx >= 0:
            ret = best_idx
            xbmcgui.Dialog().notification("Binge Watching", "Se redă automat episodul următor...", TMDbmovies_ICON, 3000, False)
    # =========================================================

    # Autoplay-ul standard (Dacă NU suntem în Binge Watching Next)
    if ret < 0 and auto_play and not auto_play_next:
        try:
            profile_idx = int(ADDON.getSetting('autoplay_profile'))
            filtered_streams = sort_streams_for_autoplay(filtered_streams, profile_idx)
            if filtered_streams:
                xbmcgui.Dialog().notification("Auto Play", "Se selectează sursa optimă...", TMDbmovies_ICON, 3000, False)
                ret = 0 
        except: pass

    if ret < 0:
        from resources.lib.results_window import ResultsWindow
        window_items = format_for_results_window(filtered_streams, poster_url)
        win = ResultsWindow('results.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', results=window_items, meta=meta_dict)
        win.doModal()
        selected_data = win.selected
        del win
        
        if selected_data:
            try:
                import json
                sel_dict = json.loads(selected_data)
                selected_url = sel_dict.get('url')
                for i, s in enumerate(filtered_streams):
                    if s['url'] == selected_url:
                        ret = i
                        break
            except: pass

    if ret >= 0:
        selected_streams = filtered_streams  
        properties = {'tmdb_id': str(tmdb_id)}
        if final_imdb_id:
            if c_type == 'tv': properties['tvshow.imdb_id'] = final_imdb_id
            properties['imdb_id'] = final_imdb_id
            properties['ImdbNumber'] = final_imdb_id

        # Extragem titlul curat (Garantat RO dacă a fost găsit)
        safe_osd_title = meta_dict.get('title', final_title)

        info_tag = {
            'title': safe_osd_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0,
            'plot': meta_dict.get('plot', ''),
            'rating': float(meta_dict.get('rating', 0.0)),
            'votes': int(meta_dict.get('votes', 0))
        }
        
        if meta_dict.get('genre'): info_tag['genre'] = meta_dict['genre']
        if meta_dict.get('studio'): info_tag['studio'] = meta_dict['studio']
        if meta_dict.get('cast'): info_tag['cast'] = meta_dict['cast']

        if final_imdb_id: info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: info_tag['season'] = int(season)
            if episode: info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id: unique_ids['imdb'] = final_imdb_id
            
        art = {'poster': poster_url, 'thumb': poster_url}
        
        # --- FIX KODI OSD CLEARLOGO ---
        if meta_dict.get('clearlogo'):
            art['clearlogo'] = meta_dict['clearlogo']
            art['tvshow.clearlogo'] = meta_dict['clearlogo'] # Obligatoriu pentru seriale în Kodi!
        # ------------------------------
        
        # Trimitem Clearlogo către OSD Kodi
        if meta_dict.get('clearlogo'):
            art['clearlogo'] = meta_dict['clearlogo']
            art['tvshow.clearlogo'] = meta_dict['clearlogo']

        play_with_rollover(
            selected_streams, ret, tmdb_id, c_type, season, episode, 
            info_tag, unique_ids, art, properties, resume_time
        )
        
        if final_imdb_id:
            import threading
            from resources.lib import subtitles
            threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode)).start()
            
    else:
        try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except: pass


# =============================================================================
# RESOLVE DIALOG - VERSIUNE FINALĂ (TMDb Helper)
# =============================================================================
def tmdb_resolve_dialog(params):
    log("[RESOLVE] === TMDB_RESOLVE_DIALOG START ===")
    
    win = xbmcgui.Window(10000)
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'tmdbmovies.release_name',
        'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
        'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
        'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
        'tmdbmovies.has_ro_sub'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title', '')
    year = params.get('year', '')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = params.get('imdb_id')
    
    bad_domains = ['googleusercontent.com', 'googlevideo.com', 'video-leech.pro', 'video-seed.pro']
    
    all_known_providers =['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'meowtv', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive', 'aiostreams', 'hdhub']
    active_providers =[]
    for pid in all_known_providers:
        if pid == 'aiostreams':
            # Suportă ambele variante de ID din settings.xml pentru AIO
            if ADDON.getSetting('use_aiostreams') == 'true' or ADDON.getSetting('aiostreams') == 'true':
                active_providers.append(pid)
        else:
            setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
            if ADDON.getSetting(setting_id) == 'true':
                active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: scanned_providers_history = []
    if failed_providers_history is None: failed_providers_history = []

    streams = []
    providers_to_scan = []
    from_cache = False
    
    if cached_streams is not None:
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: s_pid = 'nuvio'
                elif 'vix' in raw_name: s_pid = 'vixsrc'
                elif 'sooti' in raw_name: s_pid = 'sooti'
                elif 'vega' in raw_name: s_pid = 'vega'
                elif 'vidzee' in raw_name: s_pid = 'vidzee'
                elif 'meow' in raw_name: s_pid = 'meowtv'
                elif 'rogflix' in raw_name: s_pid = 'rogflix'
                elif 'streamvix' in raw_name: s_pid = 'streamvix'
                elif 'hdhub' in raw_name: s_pid = 'hdhub4u' 
                elif 'mkvcinemas' in raw_name: s_pid = 'mkvcinemas' 
                elif 'xdmovies' in raw_name: s_pid = 'xdmovies' 
                elif 'moviesdrive' in raw_name: s_pid = 'moviesdrive'
                elif 'hdhub' in raw_name: s_pid = 'hdhub'
                elif 'aio' in raw_name or 'comet' in raw_name or 'torrentio' in raw_name: s_pid = 'aiostreams' # <--- NOU
            
            if s_pid and s_pid not in active_providers: continue
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        from_cache = True
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Se caută surse...")
        
        if not imdb_id:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        if not imdb_id: imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            msg = f"[COLOR FF6AFB92]{title}[/COLOR] • [COLOR FFFF00FF]{provider_name}[/COLOR]"
            p_dialog.update(percent, message=msg)
            return True

        target_list = providers_to_scan if cached_streams is not None else None
        final_target = [p for p in target_list if p in active_providers] if target_list else active_providers

        new_streams, new_failed, was_canceled = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target
        )
        
        p_dialog.close()
        
        if was_canceled:
            log("[RESOLVE] User cancelled scanning. Aborting.")
            try: xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except: pass
            return
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
        
        final_failed = new_failed

        if cached_streams is not None:
            streams.extend(new_streams)
        else:
            streams = new_streams
        
        if streams or final_scanned:
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)
    
    if not streams:
        log("[RESOLVE] Nicio sursă găsită")
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Nu s-au găsit surse", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # FILTRARE
    all_streams_count = len(streams)
    filtered_streams, quality_stats = filter_streams_for_display(streams)
    
    if not filtered_streams:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", f"Toate cele {all_streams_count} surse sunt filtrate!", TMDbmovies_ICON, 3000)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # PREGĂTIRE FEREASTRĂ POV
    poster_url = get_poster_url(tmdb_id, c_type, season)
    eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
    
    if not imdb_id:
        try:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        except: pass

    final_imdb_id = tv_show_parent_imdb_id if c_type == 'tv' else (extra_imdb_id or imdb_id)
    final_title = eng_title if eng_title else title
    final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')

    meta_dict = {
        'title': final_title,
        'tvshowtitle': final_show_title,
        'year': year,
        'poster': poster_url,
        'fanart': '',
        'plot': '',
        'imdb_id': final_imdb_id,
        'tmdb_id': tmdb_id,
        'season': season,
        'episode': episode,
        'clearlogo': '' 
    }
    
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        details = get_tmdb_item_details(str(tmdb_id), c_type)
        if details:
            meta_dict['plot'] = details.get('overview', '')
            meta_dict['rating'] = details.get('vote_average', 0.0)
            meta_dict['votes'] = details.get('vote_count', 0)
            
            if details.get('genres'):
                meta_dict['genre'] = [g['name'] for g in details['genres']]
            
            if c_type == 'movie' and details.get('production_companies'):
                meta_dict['studio'] = [c['name'] for c in details['production_companies']]
            elif c_type in ['tv', 'episode'] and details.get('networks'):
                meta_dict['studio'] = [n['name'] for n in details['networks']]
                
            cast = []
            for p in details.get('credits', {}).get('cast', [])[:15]:
                if p.get('name'):
                    thumb = f"https://image.tmdb.org/t/p/w500{p['profile_path']}" if p.get('profile_path') else ''
                    cast.append({"name": p['name'], "role": p.get('character', ''), "thumbnail": thumb})
            if cast: meta_dict['cast'] = cast
            
            if details.get('poster_path'):
                meta_dict['poster'] = f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
                poster_url = meta_dict['poster']
                
            if c_type == 'movie' and details.get('title'):
                final_title = details['title']
                meta_dict['title'] = final_title
                
            if c_type == 'tv' and season and episode:
                from resources.lib.tmdb_api import get_smart_season_details
                season_data = get_smart_season_details(tmdb_id, season)
                if season_data:
                    for ep in season_data.get('episodes',[]):
                        if int(ep.get('episode_number', -1)) == int(episode):
                            if ep.get('overview'):
                                meta_dict['plot'] = ep['overview']
                            if ep.get('name'):
                                final_title = ep['name']
                                meta_dict['title'] = final_title
                            if ep.get('vote_average'):
                                meta_dict['rating'] = ep.get('vote_average')
                            break
                            
            if details.get('backdrop_path'):
                meta_dict['fanart'] = f"https://image.tmdb.org/t/p/original{details['backdrop_path']}"
            if details.get('clearlogo'):
                meta_dict['clearlogo'] = f"https://image.tmdb.org/t/p/w500{details['clearlogo']}"
    except: pass

    # Fetch direct titlu episod RO (sigur, bypass cache)
    if ADDON.getSetting('plot_language') == '1' and c_type == 'tv' and season and episode:
        try:
            url_ep_ro = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=ro-RO"
            data_ep_ro = get_json(url_ep_ro)
            if data_ep_ro and data_ep_ro.get('name', '').strip():
                ro_name = data_ep_ro['name'].strip()
                if not (ro_name.lower().startswith("episodul ") and ro_name.split(" ")[-1].isdigit()):
                    meta_dict['title'] = ro_name
        except:
            pass

    auto_play = ADDON.getSetting('auto_play') == 'true'
    ret = -1
    
    # --- START BINGE WATCHING (SMART AUTO-PLAY) ---
    auto_play_next = params.get('auto_play_next') == 'true'
    log(f"[BINGE-WATCH] list_sources a primit auto_play_next={auto_play_next}")
    
    if auto_play_next:
        prev_quality = params.get('prev_quality', '')
        prev_group = params.get('prev_group', '')
        prev_is_sdr = params.get('prev_is_sdr') == 'true'
        
        best_idx = find_best_stream_index(filtered_streams, prev_quality, prev_group, prev_is_sdr)
        log(f"[BINGE-WATCH] Sursa aleasă index={best_idx} din {len(filtered_streams)}")
        
        if best_idx >= 0:
            ret = best_idx
            xbmcgui.Dialog().notification("Binge Watching", "Se redă automat episodul următor...", TMDbmovies_ICON, 3000, False)
    # --- SFÂRȘIT BINGE WATCHING ---

    if ret < 0 and auto_play and not auto_play_next:
        try:
            profile_idx = int(ADDON.getSetting('autoplay_profile'))
            filtered_streams = sort_streams_for_autoplay(filtered_streams, profile_idx)
            if filtered_streams:
                xbmcgui.Dialog().notification("Auto Play", "Se selectează sursa optimă...", TMDbmovies_ICON, 3000, False)
                ret = 0 
        except: pass

    if ret < 0:
        from resources.lib.results_window import ResultsWindow
        window_items = format_for_results_window(filtered_streams, poster_url)
        win = ResultsWindow('results.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', results=window_items, meta=meta_dict)
        win.doModal()
        selected_data = win.selected
        del win
        
        if selected_data:
            try:
                import json
                sel_dict = json.loads(selected_data)
                selected_url = sel_dict.get('url')
                for i, s in enumerate(filtered_streams):
                    if s['url'] == selected_url:
                        ret = i
                        break
            except: pass

    if ret < 0:
        log("[RESOLVE] User cancelled")
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    from resources.lib.utils import clean_text
    
    selected_url = None
    total_filtered = len(filtered_streams)
    valid_stream_index = -1 
    p_dialog = None
    
    try:
        for i in range(ret, total_filtered):
            stream = filtered_streams[i]
            url = stream.get('url', '')
            
            is_aio = stream.get('provider_id') == 'aiostreams'
            
            if not url or not url.startswith(('http://', 'https://')): continue
            
            base_url_check = url.split('|')[0].lower()
            if any(bad in base_url_check for bad in bad_domains): continue
            
            raw_name = stream.get('name', 'Unknown')
            provider_id = stream.get('provider_id', '').lower()
            is_sooti = 'sooti' in raw_name.lower() or 'sooti' in provider_id or 'sootio' in raw_name.lower() or 'sooti' in url.lower()
            
            display_name = clean_text(raw_name).replace('\n', ' ')
            display_name = display_name.replace('Sooti', 'Sootio').replace('XDM', 'XDMovies')[:50]

            full_info = (raw_name + stream.get('title', '')).lower()
            c_qual = "FF1E90FF"
            qual_txt = "SD"
            
            clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
            
            if '2160' in clean_info: qual_txt = "4K"; c_qual = "FFFF00FF"
            elif '1080' in clean_info: qual_txt = "1080p"; c_qual = "FF7CFC00"
            elif '720' in clean_info: qual_txt = "720p"; c_qual = "FFBA55D3"
            elif '4k' in clean_info: qual_txt = "4K"; c_qual = "FFFF00FF"
                
            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except: pass
                
                is_valid = False
                if is_aio or any(x in base_url.lower() for x in['real-debrid.com', 'alldebrid', 'premiumize', 'torbox', 'debrid']):
                    is_valid = True
                    log(f"[PLAYER] Sursă AIO/Debrid detectată -> Bypass verificare.")
                else:
                    if p_dialog is None:
                        p_dialog = xbmcgui.DialogProgressBG()
                        p_dialog.create("[B][COLOR FF00CED1]TMDb[COLOR FFCCCCFF]Movies[/COLOR][/B]", "Verificare sursă...")
                        
                    counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_filtered}[/COLOR][/B]"
                    msg = f"Aștept răspuns de la {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
                    p_dialog.update(int(((i - ret + 1) / max(1, total_filtered - ret)) * 100), message=msg)
                    
                    is_valid = check_url_validity(base_url, headers=check_headers)

                if is_valid and is_sooti:
                    if PLAYER_AUDIO_CHECK_ONLY_SD:
                        if is_sd_or_720p(stream):
                            if check_sooti_audio_only(base_url, headers=check_headers): is_valid = False
                    else:
                        if check_sooti_audio_only(base_url, headers=check_headers): is_valid = False
                
                if is_valid:
                    selected_url = url
                    valid_stream_index = i 
                    break
            except Exception as e:
                continue
    finally:  
        if p_dialog:
            p_dialog.close()
    
    if not selected_url:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Nicio sursă validă", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    current_stream = filtered_streams[valid_stream_index]
    
    # ==============================================================
    # FIX EASYNEWS: NO SEEK (Prevenire erori conexiune)
    # ==============================================================
    try:
        if ADDON.getSetting('easynews_noseek') != 'false':
            info_dict = current_stream.get('info', {})
            is_en = False
            if isinstance(info_dict, dict):
                if 'easynews' in str(info_dict.get('addon', '')).lower() or 'easynews' in str(info_dict.get('debrid_service', '')).lower():
                    is_en = True
            if not is_en and ('easynews' in current_stream.get('name', '').lower() or 'easynews' in selected_url.lower()):
                is_en = True
                
            if is_en:
                if '|' in selected_url:
                    selected_url += '&seekable=0'
                else:
                    selected_url += '|seekable=0'
                log(f"[PLAYER] EasyNews detectat -> Adăugat seekable=0 la URL pentru a preveni erorile.")
    except: pass
    # ==============================================================
    
    # CONSTRUIEȘTE LISTITEM ȘI RETURNEAZĂ PRIN setResolvedUrl
    properties = {'tmdb_id': str(tmdb_id)}
    if final_imdb_id:
        if c_type == 'tv': properties['tvshow.imdb_id'] = final_imdb_id
        properties['imdb_id'] = final_imdb_id
        properties['ImdbNumber'] = final_imdb_id

    # Extragem titlul curat (Garantat RO dacă a fost găsit)
        safe_osd_title = meta_dict.get('title', final_title)

        info_tag = {
            'title': safe_osd_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0,
            'plot': meta_dict.get('plot', ''),
            'rating': float(meta_dict.get('rating', 0.0)),
            'votes': int(meta_dict.get('votes', 0))
        }
        
        if meta_dict.get('genre'): info_tag['genre'] = meta_dict['genre']
        if meta_dict.get('studio'): info_tag['studio'] = meta_dict['studio']
        if meta_dict.get('cast'): info_tag['cast'] = meta_dict['cast']

        if final_imdb_id: info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: info_tag['season'] = int(season)
            if episode: info_tag['episode'] = int(episode)

    unique_ids = {'tmdb': str(tmdb_id)}
    if final_imdb_id: unique_ids['imdb'] = final_imdb_id
    
    art = {'poster': poster_url, 'thumb': poster_url}
    
    # --- FIX KODI OSD CLEARLOGO ---
    if meta_dict.get('clearlogo'):
        art['clearlogo'] = meta_dict['clearlogo']
        art['tvshow.clearlogo'] = meta_dict['clearlogo']
    # ------------------------------
    
    # Adăugare Logo OSD
    if meta_dict.get('clearlogo'):
        art['clearlogo'] = meta_dict['clearlogo']
        art['tvshow.clearlogo'] = meta_dict['clearlogo']

    li = xbmcgui.ListItem(label=safe_osd_title, path=selected_url)
    from resources.lib.tmdb_api import set_metadata
    set_metadata(li, info_tag, unique_ids)
    li.setArt(art)  # <--- IATĂ-L, AICI ESTE MEREU OBLIGATORIU SĂ FIE CHEMAT!
    for k, v in properties.items(): li.setProperty(k, str(v))
    
    try:
        win = xbmcgui.Window(10000)
        win.setProperty('tmdb_id', str(tmdb_id))
        if final_imdb_id: win.setProperty('imdb_id', str(final_imdb_id))
        else: win.clearProperty('imdb_id')

        # Nume Release pentru Subs.ro folosind indexul salvat
        current_stream = filtered_streams[valid_stream_index] 
        
        # --- LOGARE STREAM DATA AIO ---
        try:
            stream_dump = json.dumps(current_stream, indent=2, ensure_ascii=False)
            xbmc.log(f"[TMDb Movies] 🧲 TMDB RESOLVE STREAM DATA 🧲:\n{stream_dump}", xbmc.LOGINFO)
        except:
            pass
        # --------------------------
        
        release_name_for_subs = current_stream.get('title', '')
        if not release_name_for_subs or len(release_name_for_subs) < 10:
             release_name_for_subs = current_stream.get('name', '')
        
        win.setProperty('tmdbmovies.release_name', str(release_name_for_subs))
    except: pass
        
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    
    if final_imdb_id:
        import threading
        from resources.lib import subtitles
        threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode), daemon=True).start()
   
# =============================================================================
# DOWNLOAD INITIATOR (UPDATED)
# =============================================================================
def initiate_download(params):
    from resources.lib.downloader import start_download_thread, get_dl_id
    from resources.lib.cache import MainCache
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    season = params.get('season')
    episode = params.get('episode')
    year = params.get('year', '')
    
    # =================================================================
    # FIX SMART TOGGLE: Dacă se descarcă deja, oferim opțiunea de STOP!
    # Chiar dacă meniul din Kodi a rămas vizual pe "Download", dând click va opri.
    # =================================================================
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    window = xbmcgui.Window(10000)
    
    if window.getProperty(unique_id) == 'active':
        if xbmcgui.Dialog().yesno("Download Activ", f"Titlul [COLOR cyan]{title}[/COLOR] se descarcă deja în fundal.\n\nVrei să OPREȘTI descărcarea?"):
            window.setProperty(f"{unique_id}_stop", "true")
            window.clearProperty(unique_id)
            xbmcgui.Dialog().notification("Download", "Se oprește...", TMDbmovies_ICON, 2000, False)
            xbmc.sleep(300)
            xbmc.executebuiltin("Container.Refresh")
        return
    # =================================================================
    
    # 1. Anul
    if not year and c_type == 'movie':
        from resources.lib.tmdb_api import get_tmdb_item_details
        details = get_tmdb_item_details(tmdb_id, 'movie')
        if details: year = str(details.get('release_date', ''))[:4]
    
    if c_type == 'tv' and not year:
         from resources.lib.tmdb_api import get_tmdb_item_details
         details = get_tmdb_item_details(tmdb_id, 'tv')
         if details: year = str(details.get('first_air_date', ''))[:4]

    streams = []
    
    # ID Cache
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
        
    cache_db = MainCache()
    cached_streams, failed_history, scanned_history = cache_db.get_source_cache(search_id)
    
    # 2. Cache + Filtrare
    active_providers = []
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'meowtv', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive', 'hdhub']
    for pid in all_known_providers:
        if ADDON.getSetting(f'use_{pid if pid!="nuvio" else "nuviostreams"}') == 'true':
            active_providers.append(pid)

    if cached_streams:
        log(f"[DOWNLOAD] Found {len(cached_streams)} streams in CACHE.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid: # fallback ident
                raw = s.get('name', '').lower()
                if 'webstreamr' in raw: s_pid='webstreamr'
                elif 'nuvio' in raw: s_pid='nuvio'
                elif 'vix' in raw: s_pid='vixsrc'
                elif 'sooti' in raw: s_pid='sooti'
                elif 'vega' in raw: s_pid='vega'
                elif 'vidzee' in raw: s_pid='vidzee'
                elif 'meow' in raw: s_pid='meowtv'
                elif 'rogflix' in raw: s_pid='rogflix'
                elif 'streamvix' in raw: s_pid='streamvix'
                elif 'hdhub' in raw: s_pid = 'hdhub4u'
                elif 'mkvcinemas' in raw: s_pid = 'mkvcinemas'
                elif 'xdmovies' in raw: s_pid = 'xdmovies'
                elif 'hdhub' in raw: s_pid = 'hdhub'
                elif 'moviesdrive' in raw: s_pid = 'moviesdrive'
            
            if s_pid and s_pid in active_providers:
                valid_cached_streams.append(s)
            elif not s_pid:
                valid_cached_streams.append(s)
        streams = valid_cached_streams

    # 3. Scrape
    if not streams:
        # --- MODIFICARE: Folosim DialogProgressBG (dreapta-sus) în loc de DialogProgress (mijloc) ---
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create("[B][COLOR FFFDBD01]Download Manager[/COLOR][/B]", "Inițializare...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id') or f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            # provider_name vine deja formatat din scraper cu culori si linii noi
            # Nu mai adaugam alte tag-uri peste el
            p_dialog.update(percent, message=provider_name)
            return True

        # Observatie: get_stream_data returneaza canceled=False daca folosim DialogProgressBG
        # deoarece acesta nu are buton de cancel explicit in interfata simpla
        streams, failed, canceled = get_stream_data(imdb_id, c_type, season, episode, update_progress, active_providers)
        p_dialog.close()
        
        if canceled: return
        
        if streams:
            streams = sort_streams_by_quality(streams)
            scanned_now = [p for p in active_providers if p not in failed]
            try: dur = int(ADDON.getSetting('cache_sources_duration'))
            except: dur = 24
            cache_db.set_source_cache(search_id, streams, failed, scanned_now, dur)

    if not streams:
        xbmcgui.Dialog().notification("Download", "Nu s-au găsit surse!", TMDbmovies_ICON)
        return

    # 4. Deduplicare și sortare
    streams = deduplicate_streams(streams)
    streams = sort_streams_by_quality(streams)
    
    # =========================================================
    # FILTRARE CALITATE PENTRU AFIȘARE
    # =========================================================
    all_streams_count = len(streams)
    filtered_streams, quality_stats = filter_streams_for_display(streams)
    
    if not filtered_streams:
        xbmcgui.Dialog().notification("Download", f"Toate cele {all_streams_count} surse sunt filtrate!", TMDbmovies_ICON, 3000)
        return
    # =========================================================
    
    clean_title_backup = title
    if c_type == 'tv':
        st = params.get('tv_show_title', '')
        if st: clean_title_backup = st 

    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(filtered_streams, poster_url)  # <- filtered_streams!
    
    if len(filtered_streams) < all_streams_count:
        dlg_title = f"[DOWNLOAD] {len(filtered_streams)}/{all_streams_count} surse:"
    else:
        dlg_title = f"[DOWNLOAD] Selectează sursa:"
    
    if cached_streams: 
        dlg_title += " [COLOR lime][CACHE][/COLOR]"

    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        selected_stream = filtered_streams[ret]  # <- filtered_streams, nu streams!
        url = selected_stream['url']
        
        # Nume fișier
        raw_release_name = selected_stream.get('name', '')
        extra_title = selected_stream.get('title', '')
        if len(extra_title) > len(raw_release_name):
            raw_release_name = extra_title
        if len(raw_release_name) < 5:
             raw_release_name = None

        # START DOWNLOAD
        start_download_thread(url, clean_title_backup, year, tmdb_id, c_type, season, episode, release_name=raw_release_name)
        
        # --- MODIFICARE: REFRESH AUTOMAT ---
        # Forțăm reîncărcarea listei pentru ca meniul contextual să vadă noul status (Stop)
        xbmc.sleep(200) # Pauză mică să apuce să seteze proprietatea
        xbmc.executebuiltin("Container.Refresh")
        # -----------------------------------

def stop_download_action(params):
    """Oprește download-ul curent pentru acest item."""
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    season = params.get('season')
    episode = params.get('episode')
    
    from resources.lib.downloader import get_dl_id
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    
    window = xbmcgui.Window(10000)
    
    # 1. Trimitem semnalul de STOP către thread-ul de download
    window.setProperty(f"{unique_id}_stop", "true")
    
    # 2. Ștergem IMEDIAT flag-ul de 'active', astfel încât meniul contextual
    # să revină la "Download" imediat ce dăm refresh, chiar dacă thread-ul
    # mai durează 1-2 secunde să șteargă fișierul.
    window.clearProperty(unique_id) 
    
    xbmcgui.Dialog().notification("Download", "Se oprește...", TMDbmovies_ICON, 1000, False)


class TraktRatingWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.meta = kwargs.get('meta', {})
        self.rating_val = -1

    def onInit(self):
        # Setăm proprietățile pentru XML, ca la Autoplay
        
        # 1. Background și Artă
        self.setProperty('tmdbmovies.fanart', self.meta.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.meta.get('clearlogo', ''))
        
        # 2. Titluri
        content_type = self.meta.get('content_type', 'movie')
        
        if content_type == 'movie':
            self.setProperty('tmdbmovies.show_title', self.meta.get('title', 'Unknown'))
            self.setProperty('tmdbmovies.ep_label', '')
        else:
            self.setProperty('tmdbmovies.show_title', self.meta.get('tvshowtitle', 'Unknown'))
            season = self.meta.get('season', 1)
            episode = self.meta.get('episode', 1)
            ep_title = self.meta.get('title', '')
            
            if ep_title:
                self.setProperty('tmdbmovies.ep_label', f"S{season:02d}E{episode:02d} - {ep_title}")
            else:
                self.setProperty('tmdbmovies.ep_label', f"S{season:02d}E{episode:02d}")
        
        # Focus default pe 10 stele (id 11039)
        try:
            self.setFocusId(11039)
        except:
            pass

    def onClick(self, controlId):
        if 11030 <= controlId <= 11039:
            # 11030 este 1 stea, 11039 este 10 stele
            self.rating_val = controlId - 11029 
            self.close()
        elif controlId == 1000:
            # Butonul close
            self.rating_val = -1
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110): # Back, escape, etc.
            self.rating_val = -1
            self.close()


def _prompt_trakt_rating(tmdb_id, content_type, season, episode, title):
    from resources.lib import trakt_api
    from resources.lib.config import ADDON, BACKDROP_BASE, IMG_BASE
    from resources.lib.tmdb_api import get_tmdb_item_details
    import os
    
    token = trakt_api.get_trakt_token()
    if not token: return
    
    # Adunăm detaliile pentru fereastră
    meta_info = {
        'content_type': content_type,
        'title': title,
        'season': season,
        'episode': episode,
        'fanart': '',
        'clearlogo': '',
        'tvshowtitle': ''
    }
    
    # Tragem fanart și clearlogo din TMDb cache pentru a arăta frumos
    try:
        if content_type == 'movie':
            details = get_tmdb_item_details(str(tmdb_id), 'movie')
        else:
            details = get_tmdb_item_details(str(tmdb_id), 'tv')
            
        if details:
            if details.get('backdrop_path'):
                meta_info['fanart'] = f"{BACKDROP_BASE}{details.get('backdrop_path')}"
            if details.get('clearlogo'):
                meta_info['clearlogo'] = f"{IMG_BASE}{details.get('clearlogo')}"
                
            if content_type != 'movie':
                meta_info['tvshowtitle'] = details.get('name', 'Unknown')
                
                # Căutăm titlul real al episodului dacă nu a fost dat
                if not title or title.startswith('Episode '):
                    from resources.lib.tmdb_api import get_smart_season_details
                    season_data = get_smart_season_details(str(tmdb_id), season)
                    if season_data:
                        for ep in season_data.get('episodes',[]):
                            if str(ep.get('episode_number')) == str(episode):
                                if ep.get('name'):
                                    meta_info['title'] = ep.get('name')
                                break
    except: pass
    
    # Deschidem fereastra custom XML
    win = TraktRatingWindow('TraktRating.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', meta=meta_info)
    win.doModal()
    
    rating_val = win.rating_val
    del win
    
    if rating_val > 0:
        if content_type == 'movie':
            data = {'movies':[{'ids': {'tmdb': int(tmdb_id)}, 'rating': rating_val}]}
        else:
            data = {'shows':[{'ids': {'tmdb': int(tmdb_id)}, 'seasons':[{'number': int(season), 'episodes':[{'number': int(episode), 'rating': rating_val}]}]}]}
            
        res = trakt_api.trakt_api_request("/sync/ratings", method='POST', data=data)
        
        # Forțăm afișarea notificării indiferent de tipul de răspuns (atâta timp cât nu e None/Eroare)
        if res is not None:
            icon_path = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'trakt.png')
            import xbmcgui
            xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", f"Ai acordat nota [B][COLOR lime]{rating_val}/10[/COLOR][/B]", icon_path, 3000, False)

