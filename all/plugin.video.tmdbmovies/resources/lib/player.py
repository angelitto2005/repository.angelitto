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
import json
from resources.lib.config import get_headers, BASE_URL, API_KEY, IMG_BASE, HANDLE, ADDON
from resources.lib.utils import log, get_json, extract_details, get_language, clean_text
from resources.lib.scraper import get_external_ids, get_stream_data
from resources.lib.tmdb_api import set_metadata
from resources.lib.trakt_api import mark_as_watched_internal
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
    """Verifică DOAR dacă URL-ul este accesibil. RAPID cu timeout forțat."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT  # <-- Folosește constanta globală
    
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
            
            # Timeout intern = jumătate din max_timeout
            internal_timeout = max(1.5, max_timeout / 2)
            
            try:
                r = requests.head(clean_url, headers=custom_headers, timeout=internal_timeout, verify=False, allow_redirects=True)
                
                final_url = r.url.lower() if r.url else ''
                for bad in bad_domains:
                    if bad in final_url:
                        log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
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
# EXTRACTOR INFORMAȚII STREAM - V3 (WebStreamr FIX)
# =============================================================================
def extract_stream_info(stream):
    """
    Extrage informații detaliate (Undercover Mode).
    """
    raw_name = stream.get('name', '')
    raw_title = stream.get('title', '')
    provider_id = stream.get('provider_id', '')
    url = stream.get('url', '').lower()
    
    binge_group = ''
    behavior_hints = stream.get('behaviorHints', {})
    if isinstance(behavior_hints, dict):
        binge_group = behavior_hints.get('bingeGroup', '')
    if not binge_group:
        binge_group = stream.get('bingeGroup', '')
    
    full_info = (raw_name + ' ' + raw_title).lower()
    
    # 1. DETECTARE PROVIDER - SUPORTĂ ALIASURI
    provider = ""
    
    if provider_id:
        provider_map = {
            'sooti': 'SlowNow',
            'nuvio': 'NotNow',
            'webstreamr': 'WebNow',
            'vixsrc': 'VixSrc',
            'rogflix': 'Rogflix',
            'vega': 'Vega',
            'streamvix': 'StreamNow',
            'vidzee': 'Vidzee',
            'hdhub4u': 'HDHub4u',
            'mkvcinemas': 'MKVCinemas',
            'xdmovies': 'SmileNow',
            'moviesdrive': 'MoviesDrive'
        }
        provider = provider_map.get(provider_id.lower(), provider_id)
    
    # Fallback detectare din nume
    if not provider:
        name_lower = raw_name.lower()
        if 'slownow' in name_lower or 'sooti' in name_lower or '[hs+]' in name_lower: provider = 'SlowNow'
        elif 'webnow' in name_lower or 'webstreamr' in name_lower: provider = 'WebNow'
        elif 'notnow' in name_lower or 'nuvio' in name_lower: provider = 'NotNow'
        elif 'vix' in name_lower: provider = 'VixSrc'
        elif 'rogflix' in name_lower: provider = 'Rogflix'
        elif 'vega' in name_lower: provider = 'Vega'
        elif 'vidzee' in name_lower: provider = 'Vidzee'
        elif 'streamnow' in name_lower or 'streamvix' in name_lower: provider = 'StreamNow'
        elif 'mkv |' in name_lower or 'mkvcinemas' in name_lower: provider = 'MKVCinemas'
        elif 'hdhub' in name_lower: provider = 'HDHub4u'
        elif 'moviesdrive' in name_lower: provider = 'MoviesDrive'
        elif 'smilenow' in name_lower or 'xdm' in name_lower: provider = 'SmileNow'
        else: provider = 'Unknown'
    
    # 2. SERVER
    server = ""
    if provider == 'WebNow' or 'webstreamr' in raw_name.lower():
        webstr_server_match = re.search(r'🔗\s*(.+?)(?:\n|$)', raw_title)
        if webstr_server_match: server = webstr_server_match.group(1).strip()
        elif binge_group:
            if 'fsl' in binge_group.lower(): server = 'HubCloud (FSL)'
            elif 'pixel' in binge_group.lower(): server = 'HubCloud (Pixel)'

    if not server:
        if 'pixeldrain' in url: server = 'PixelDrain'
        elif 'r2.dev' in url or 'pub-' in url: server = 'Flash'
        elif 'fsl-lover' in url or 'fsl.gdboka' in url: server = 'FSL'
        elif 'fsl-buckets' in url: server = 'CDN'
        elif 'fsl' in url: server = 'Flash'
        elif 'polgen.buzz' in url: server = 'Flash'
        elif 'pixel.hubcdn' in url: server = 'HubPixel'
        elif 'workers.dev' in url: server = 'Worker'
        elif 'googleusercontent' in url: server = 'Google'

    if not server and 'nuvio' in provider_id:
        if '[PIX]' in raw_name: server = 'PixelDrain'
        elif '[FSL]' in raw_name: server = 'Flash'
        elif '[GD]' in raw_name: server = 'GDrive'

    if not server and '|' in raw_name and provider not in ['WebNow']:
        parts = raw_name.split('|')
        if len(parts) >= 2:
            potential = parts[1].strip().lower()
            if 'fast' in potential: server = 'FastServer'
            elif 'pixel' in potential: server = 'PixelDrain'
            elif 'flash' in potential: server = 'Flash'
            elif 'cdn' in potential: server = 'CDN'
            elif 'direct' in potential: server = 'Direct'
            elif len(potential) < 15: server = parts[1].strip()

    # 3. GROUP (Curățare)
    group = ""
    group_match = re.search(r'\|\s*([A-Za-z0-9]+(?:Hub|hub|HUB)?)\s*$', raw_title)
    if group_match: group = group_match.group(1)
    if group and server and group.lower() == server.lower(): group = ""

    # 4. SIZE
    size = ""
    size_patterns = [r'💾\s*([\d.]+)\s*(GB|MB|gb|mb)', r'\[([\d.]+)\s*(GB|MB|gb|mb)\]', r'([\d.]+)\s*(GB|MB|gb|mb)(?!\w)']
    for text in [raw_title, raw_name]:
        for pattern in size_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                size = f"{match.group(1)}{match.group(2).upper()}"
                break
        if size: break

# =========================================================
    # 5. DETECTARE QUALITY (FIX DS4K)
    # =========================================================
    quality = "SD"
    
    # PRIORITATE 1: Calitatea din scraper
    stream_quality = stream.get('quality', '')
    if stream_quality:
        quality = stream_quality
    else:
        # PRIORITATE 2: Detectare inteligentă
        # Ordinea contează: 2160p bate tot, 1080p bate 4k-ul fals (DS4K)
        
        if '2160p' in full_info:
            quality = "4K"
        elif '1080p' in full_info:
            quality = "1080p"
        elif '720p' in full_info:
            quality = "720p"
        elif '480p' in full_info:
            quality = "480p"
        else:
            # Verificăm "4k" doar dacă nu am găsit 1080p/720p
            # Și ne asigurăm că nu e DS4K (DownScaled 4K)
            if '4k' in full_info and 'ds4k' not in full_info:
                quality = "4K"

    # 6. TAGS
    tags = []
    if 'dolby vision' in full_info or '.dv.' in full_info: tags.append("DV")
    if 'hdr' in full_info: tags.append("HDR")
    if 'atmos' in full_info: tags.append("Atmos")
    if 'remux' in full_info: tags.append("REMUX")
    
    return {'provider': provider, 'group': group, 'server': server, 'size': size, 'quality': quality, 'tags': tags}


def build_display_items(streams, poster_url):
    """
    Construiește lista de ListItem-uri pentru dialog.
    Format: [B]{idx}. {quality} {provider} {size} {server} {tags}[/B]
    """
    display_items = []
    
    for idx, s in enumerate(streams, 1):
        # Extragem informațiile
        info = extract_stream_info(s)
        
        quality = info['quality']
        provider = info['provider']
        group = info['group']
        server = info['server']
        size = info['size']
        tags = info['tags']
        
        # =========================================================
        # CULORI PENTRU CALITATE
        # =========================================================
        c_qual = "FF00BFFF"  # Default albastru
        if quality == "4K": 
            c_qual = "FF00FFFF"  # Cyan
        elif quality == "1080p": 
            c_qual = "FF00FF7F"  # Verde
        elif quality == "720p": 
            c_qual = "FFFFD700"  # Galben/Auriu
        # SD rămâne albastru
        
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
        # Format: [B]01. 4K Sooti 24.35GB Flash 4KHDHub HDR DV Atmos 5.1[/B]
        # =========================================================
        parts = []
        
        # Index (alb)
        parts.append(f"[COLOR FFFFFFFF]{idx:02d}.[/COLOR]")
        
        # Quality (colorat)
        parts.append(f"[COLOR {c_qual}]{quality}[/COLOR]")
        
        # Provider (roz)
        if provider:
            parts.append(f"[COLOR FFFF69B4]{provider}[/COLOR]")
        
        # Size (galben) - IMEDIAT DUPĂ PROVIDER!
        if size:
            parts.append(f"[COLOR FFFFEA00]{size}[/COLOR]")
        
        # Server (verde-cyan)
        if server:
            parts.append(f"[COLOR FF20B2AA]{server}[/COLOR]")
        
        # Group (portocaliu) - doar dacă e diferit de server și provider
        if group and group.lower() != server.lower() and group.lower() != provider.lower():
            parts.append(f"[COLOR FFFFA500]{group}[/COLOR]")
        
        # Tags (la final)
        if tags_str:
            parts.append(tags_str)
        
        # Înconjurăm TOT label-ul cu [B][/B] pentru BOLD
        label = "[B]" + "  ".join(parts) + "[/B]"
        
        # =========================================================
        # LABEL2 (titlul fișierului - pentru linia a doua)
        # =========================================================
        raw_title = s.get('title', '')
        raw_name = s.get('name', '')
        
        # Curățăm titlul pentru label2
        label2 = raw_title if raw_title else raw_name
        # Eliminăm emoji și linii noi
        label2 = re.sub(r'[💾🔗🇬🇧🇺🇸🇮🇳]', '', label2)
        label2 = label2.replace('\n', ' ').strip()
        # Eliminăm informații redundante
        label2 = re.sub(r'\s*\|\s*[A-Za-z0-9]+Hub\s*$', '', label2)
        label2 = re.sub(r'\s*🔗\s*\w+\s*\(\w+\)\s*$', '', label2)
        # Limităm lungimea
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
    from resources.lib.utils import extract_details
    import re

    def get_sort_key(s):
        _, _, quality = extract_details(s.get('title', ''), s.get('name', ''))
        
        if quality == "4K": 
            q_score = 3
        elif quality == "1080p": 
            q_score = 2
        elif quality == "720p": 
            q_score = 1
        else: 
            q_score = 0
            
        size_mb = 0.0
        text = (s.get('name', '') + " " + s.get('title', '')).lower()
        match = re.search(r'(\d+(?:\.\d+)?)\s*(gb|gib|mb|mib)', text)
        if match:
            val = float(match.group(1))
            unit = match.group(2)
            size_mb = val * 1024 if 'g' in unit else val
        
        return (q_score, size_mb)

    streams.sort(key=get_sort_key, reverse=True)
    return streams


def is_link_playable(url):
    try:
        clean_url = url.split('|')[0]
        r = requests.head(clean_url, headers=get_headers(), timeout=3, allow_redirects=True, verify=False)
        
        if r.status_code in [200, 206]:
            return True
        elif r.status_code in [405, 403]: 
            r2 = requests.get(clean_url, headers=get_headers(), stream=True, timeout=3, verify=False)
            r2.close()
            if r2.status_code in [200, 206]:
                return True
                
        log(f"[PLAYER-CHECK] Link Dead ({r.status_code}): {clean_url}")
    except Exception as e:
        log(f"[PLAYER-CHECK] Error checking link: {e}")
        
    return False


def handle_resume_dialog(title):
    try:
        if len(sys.argv) > 3:
            resume_arg = sys.argv[3] if len(sys.argv) > 3 else ''
            if 'resume:false' in resume_arg:
                return False
            elif 'resume:true' in resume_arg:
                return True
    except:
        pass
    
    return False


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
                
                # Scrobble periodic la Trakt
                if total > 0 and curr > 300:
                    progress = (curr / total) * 100
                    
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
        # PLAYERUL S-A OPRIT - Salvăm PROCENTUL
        # ============================================================
        log("[PLAYER-MONITOR] Player stopped, saving progress...")
        
        if last_known_progress <= 0 or last_known_total <= 0:
            log(f"[PLAYER-MONITOR] No valid progress saved, skipping")
            # ✅ REFRESH CHIAR DACĂ NU SALVĂM (pentru cazul când se oprește rapid)
            xbmc.sleep(1000)
            xbmc.executebuiltin('Container.Refresh')
            # -----------------------------------
            return
        
        mins = int(last_known_position) // 60
        secs = int(last_known_position) % 60
        log(f"[PLAYER-MONITOR] ✓ Final: {mins}m {secs}s ({last_known_progress:.2f}%)")
        
        # ============================================================
        # SALVARE
        # ============================================================
        watched_duration = 0
        if player_instance.playback_start_time > 0:
            watched_duration = time.time() - player_instance.playback_start_time
        
        log(f"[PLAYER-MONITOR] Watched duration: {int(watched_duration)}s")
        
        try:
            from resources.lib import trakt_api
            from resources.lib import trakt_sync

            if player_instance.watched_marked or last_known_progress >= 85:
                log(f"[PLAYER-MONITOR] Marking as WATCHED ({last_known_progress:.2f}%)")
                
                trakt_api.mark_as_watched_internal(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    notify=True, sync_trakt=True
                )
                
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    100, player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('stop', 100)
                
            elif watched_duration > 180:  # 3 minute
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    last_known_progress,
                    player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('stop', last_known_progress)
                
                log(f"[PLAYER-MONITOR] ✓ Resume saved: {last_known_progress:.2f}%")
                
            else:
                log(f"[PLAYER-MONITOR] Watched <3min ({int(watched_duration)}s). Resume NOT saved.")
                
        except Exception as e:
            log(f"[PLAYER-MONITOR] Error saving progress: {e}", xbmc.LOGERROR)
        
        # ============================================================
        # ✅ CONTAINER REFRESH DUPĂ SALVARE (cu delay pentru siguranță)
        # ============================================================
        log("[PLAYER-MONITOR] Refreshing container in 1 second...")
        xbmc.sleep(1000)  # Așteaptă 1 secundă
        xbmc.executebuiltin('Container.Refresh')
        log("[PLAYER-MONITOR] Container refreshed!")
        # ============================================================
        
        log("[PLAYER-MONITOR] Monitor thread finished")
    
    _player_monitor = threading.Thread(target=monitor_loop, daemon=True)
    _player_monitor.start()


def is_sd_or_720p(stream):
    """Verifică dacă sursa este SD sau 720p (sub 1080p)."""
    full_info = (stream.get('name', '') + stream.get('title', '')).lower()
    
    # Dacă are 1080p sau 4K, NU e SD/720p
    if '1080' in full_info or '2160' in full_info or '4k' in full_info:
        return False
    
    # Dacă are 720p sau rezoluție mai mică, E SD/720p
    if '720' in full_info or '480' in full_info or '360' in full_info:
        return True
    
    # Dacă nu are nicio rezoluție specificată, considerăm SD
    has_quality = any(x in full_info for x in ['1080', '720', '480', '360', '2160', '4k'])
    if not has_quality:
        return True  # Fără calitate = probabil SD
    
    return False

# =============================================================================
# PLAY WITH ROLLOVER - VERSIUNE FINALĂ (FĂRĂ BUFFERING DUPLICAT)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties, resume_time=0, from_resolve=False):
    
    log("[PLAYER] === PLAY_WITH_ROLLOVER START ===")
    
    # ===========================================================================
    # FIX: CURĂȚĂM ȘI SETĂM WINDOW PROPERTIES LA ÎNCEPUT
    # ===========================================================================
    win = xbmcgui.Window(10000)
    
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'mrsp.tmdb_id', 'mrsp.imdb_id'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[PLAYER] Window Properties curățate la început')
    
    # SETĂM ID-URILE CORECTE IMEDIAT
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
        log(f'[PLAYER] Window Property TMDb setat: {tmdb_id}')
    
    # Extragem IMDb din unique_ids (care vine ca parametru)
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
        try:
            current_handle = int(sys.argv[1])
            xbmcplugin.setResolvedUrl(current_handle, False, xbmcgui.ListItem())
        except:
            pass
    
    if xbmc.Player().isPlaying():
        xbmc.Player().stop()
        xbmc.sleep(300)

    total_streams = len(streams)
    log(f"[PLAYER] Total surse: {total_streams}")
    
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Initializare...")
    
    p_title = info_tag.get('title', 'Unknown')
    p_year = info_tag.get('year', '')

    from resources.lib.utils import clean_text
    
    bad_domains = [
        'googleusercontent.com',
        'googlevideo.com',
        'video-leech.pro',
        'video-seed.pro',
    ]
    
    valid_url = None
    valid_index = -1

# Înlocuiește bucla FOR din play_with_rollover cu aceasta:
    for i in range(start_index, total_streams):
        try:
            stream = streams[i]
            url = stream.get('url', '')
            
            if not url or not url.startswith(('http://', 'https://')):
                continue
            
            # Verificare domenii blocate
            base_url_check = url.split('|')[0].lower()
            if any(bad in base_url_check for bad in bad_domains):
                continue
            
            # --- DETECȚIE SOOTI (LOGICĂ INTERNĂ) ---
            # Verificăm atât ID-ul cât și numele pentru a ști dacă aplicăm verificarea audio
            raw_name = stream.get('name', '').lower()
            provider_id = stream.get('provider_id', '').lower()
            is_sooti = 'sooti' in raw_name or 'sooti' in provider_id or 'slownow' in raw_name or 'sooti' in url.lower()
            
            if is_sooti:
                log(f"[PLAYER] Provider detectat: SOOTI/SlowNow (Index {i+1})")
                                    
            # --- AFIȘARE NOTIFICARE (UNDERCOVER) ---
            raw_n = stream.get('name', 'Unknown')
            # Forțăm înlocuirea numelor interzise DOAR PENTRU AFIȘARE
            display_name = clean_text(raw_n).replace('\n', ' ')
            display_name = display_name.replace('Sooti', 'SlowNow')
            display_name = display_name.replace('Nuvio', 'NotNow')
            display_name = display_name.replace('WebStreamr', 'WebNow')
            display_name = display_name.replace('XDMovies', 'SmileNow')
            display_name = display_name.replace('XDM', 'SmileNow')
            display_name = display_name[:50] # Tăiem dacă e prea lung

            full_info = (raw_n + stream.get('title', '')).lower()
            c_qual = "FF00BFFF" # Albastru (SD)
            qual_txt = "SD"
            # LOGICĂ STRICTĂ PENTRU DS4K
            if '2160p' in full_info:
                qual_txt = "4K"; c_qual = "FF00FFFF" # Cyan
            elif '1080p' in full_info:
                qual_txt = "1080p"; c_qual = "FF00FF7F" # Verde
            elif '720p' in full_info:
                qual_txt = "720p"; c_qual = "FFFFD700" # Galben
            elif '480p' in full_info:
                qual_txt = "480p"
            elif '4k' in full_info and 'ds4k' not in full_info:
                # 4K valid doar dacă nu e DS4K și nu am găsit altceva mai sus
                qual_txt = "4K"; c_qual = "FF00FFFF"
                
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            p_dialog.update(int(((i - start_index + 1) / max(1, total_streams - start_index)) * 100), message=msg)
            
            # --- VERIFICARE URL ---
            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except: pass
                
                is_valid = check_url_validity(base_url, headers=check_headers)
                
                # Verificare specifică Sooti (Audio Only check)
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
    
    p_dialog.close()
    
    if valid_url:
        log(f"[PLAYER] === PORNIRE REDARE SURSA {valid_index + 1} ===")
        
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        # ============================================================
        # PĂSTRĂM REFERINȚA LA PLAYER GLOBAL (pentru callback-uri!)
        # ============================================================
        global _active_player
        # ============================================================
        
        # ============================================================
        # THREAD PERMANENT (Cât timp merge playerul)
        # ============================================================
        stop_cleaner = threading.Event()
        
        def playlist_cleaner():
            log("[PLAYER] Cleaner thread pornit")
            
            # Așteptăm să pornească playerul
            for _ in range(20):
                if xbmc.Player().isPlaying():
                    break
                xbmc.sleep(500)
                
            # Ciclăm cât timp playerul merge SAU până trec 30 secunde
            # Dacă playerul se oprește, oprim și cleaner-ul
            start_time = time.time()
            while not stop_cleaner.is_set():
                # Verificăm dacă playerul s-a oprit
                if not xbmc.Player().isPlaying() and (time.time() - start_time > 5):
                    log("[PLAYER] Player oprit, opresc cleaner")
                    break
                
                # Curățăm și închidem
                xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
                
                if xbmc.getCondVisibility('Window.IsVisible(okdialog)'):
                    xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                    
                if xbmc.getCondVisibility('Window.IsVisible(progressdialog)'):
                    xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                
                xbmc.sleep(500)
                
            log("[PLAYER] Cleaner thread oprit")
        
        cleaner_thread = threading.Thread(target=playlist_cleaner, daemon=True)
        cleaner_thread.start()
        # ============================================================
        
        # ============================================================
        # SALVĂM REFERINȚA GLOBAL (altfel se pierde și callback-urile nu merg!)
        # ============================================================
        _active_player = TMDbPlayer(tmdb_id, c_type, season, episode, title=p_title, year=str(p_year))
        player = _active_player
        
        li = xbmcgui.ListItem(label=info_tag['title'], path=valid_url)
        li.setInfo('video', info_tag)
        if unique_ids:
            li.setUniqueIDs(unique_ids)
        if art:
            li.setArt(art)
        for k, v in properties.items():
            li.setProperty(k, str(v))
        
        player.play(valid_url, li)
        
        xbmc.executebuiltin('Dialog.Close(busydialog)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        log(f"[PLAYER] player.play() OK")
        
        # ============================================================
        # PORNEȘTE MONITORUL CARE SALVEAZĂ PROGRESUL
        # ============================================================
        start_playback_monitor(player)
        # ============================================================
        
        if resume_time > 0:
            def do_resume():
                log(f"[PLAYER] Resume requested: {resume_time} seconds")
                
                # 1. Așteptăm să pornească playerul
                for _ in range(30):
                    if player.isPlaying():
                        break
                    xbmc.sleep(500)
                else:
                    log("[PLAYER] Player did not start, cancelling resume")
                    return
                
                # 2. Așteptăm încă 3 secunde pentru HLS/stream-uri
                log("[PLAYER] Player started, waiting 3s for stream to stabilize...")
                xbmc.sleep(3000)
                
                # 3. Încercăm seek de 5 ori
                target_pos = float(resume_time)
                for attempt in range(5):
                    if not player.isPlaying():
                        log("[PLAYER] Player stopped, cancelling resume")
                        return
                    
                    try:
                        current_pos = player.getTime()
                        
                        # Dacă suntem deja aproape de target (±30s), e OK
                        if abs(current_pos - target_pos) < 30:
                            log(f"[PLAYER] Already at correct position: {int(current_pos)}s")
                            return
                        
                        log(f"[PLAYER] Seek attempt {attempt+1}: {int(current_pos)}s -> {int(target_pos)}s")
                        player.seekTime(target_pos)
                        
                        # Așteptăm 2 secunde pentru seek
                        xbmc.sleep(2000)
                        
                        # Verificăm dacă a funcționat
                        new_pos = player.getTime()
                        if abs(new_pos - target_pos) < 60:  # Toleranță 1 minut
                            log(f"[PLAYER] Seek SUCCESS! Position: {int(new_pos)}s")
                            return
                        else:
                            log(f"[PLAYER] Seek failed, got {int(new_pos)}s instead of {int(target_pos)}s")
                            
                    except Exception as e:
                        log(f"[PLAYER] Seek error: {e}")
                    
                    xbmc.sleep(1000)
                
                log("[PLAYER] All seek attempts failed")
                    
            threading.Thread(target=do_resume, daemon=True).start()
        
        if unique_ids.get('imdb'):
            threading.Thread(target=subtitles.run_wyzie_service, args=(unique_ids['imdb'], season, episode)).start()
            
        # Oprim manual cleaner-ul când funcția se termină (deși e daemon)
        # Dar el va rula în background cât timp playerul merge datorită logicii interne
            
    else:
        log(f"[PLAYER] FAIL - Nicio sursă validă din {total_streams}")
        xbmcgui.Dialog().notification("TMDb Movies", "Nicio sursă nu a putut fi redată", TMDbmovies_ICON)
    
    log("[PLAYER] === END ===")

# =============================================================================
# LIST SOURCES - VERSIUNE CORECTATĂ
# =============================================================================
def list_sources(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    
    # ===========================================================================
    # FIX: CURĂȚĂM WINDOW PROPERTIES LA ÎNCEPUT
    # ===========================================================================
    win = xbmcgui.Window(10000)
    
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'mrsp.tmdb_id', 'mrsp.imdb_id'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[LIST-SOURCES] Window Properties curățate la început')
    
    # Setăm TMDb imediat
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
        log(f'[LIST-SOURCES] Window Property TMDb setat: {tmdb_id}')
    # ===========================================================================
    
    ids = {}
    
    # ============================================================
    # CITIM PROCENTUL DIN DB și calculăm poziția din runtime
    # ============================================================
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
    
    resume_time = 0
    
    if progress_value > 0 and progress_value < 90:
        log(f"[LIST-SOURCES] Progress from DB: {progress_value:.2f}%")
        
        # Obținem runtime-ul pentru a calcula poziția
        duration_secs = 0
        try:
            if c_type == 'movie':
                url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                runtime = data.get('runtime', 0) if data else 0
                if runtime:
                    duration_secs = int(runtime) * 60
            else:
                url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US"
                data = get_json(url)
                if data:
                    runtimes = data.get('episode_run_time', [])
                    if runtimes:
                        duration_secs = int(runtimes[0]) * 60
                    else:
                        duration_secs = 2700  # 45 min default pentru seriale
        except Exception as e:
            log(f"[LIST-SOURCES] Error getting runtime: {e}")
        
        if duration_secs <= 0:
            duration_secs = 7200  # 2 ore default
        
        resume_time = int((progress_value / 100.0) * duration_secs)
        log(f"[LIST-SOURCES] Calculated resume: {resume_time}s ({resume_time//60}m {resume_time%60}s) from {progress_value:.2f}% of {duration_secs}s")
    
    elif progress_value >= 1000000:
        # Format vechi cu marker (pentru backwards compatibility)
        resume_time = int(progress_value - 1000000)
        log(f"[LIST-SOURCES] Legacy position from DB: {resume_time}s")
    # ============================================================

    # Meniu resume
    if resume_time > 180:
        m, s = divmod(resume_time, 60)
        h, m = divmod(m, 60)
        if h > 0: 
            time_str = f"{h}h {m}m"
        else: 
            time_str = f"{m}m {s}s"
        
        log(f"[LIST-SOURCES] Showing resume dialog for {resume_time} seconds")
        
        choice = xbmcgui.Dialog().contextmenu([f"Resume from {time_str}", "Play from beginning"])
        if choice == 1: 
            resume_time = 0
        elif choice == -1:
            try:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except:
                pass
            return

    # --- 2. CAUTARE / CACHE ---
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid!="nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: 
        cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: 
        cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': 
        search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: 
        scanned_providers_history = []
    if failed_providers_history is None: 
        failed_providers_history = []

    streams = []
    providers_to_scan = [] 
    
    if cached_streams is not None:
        log(f"[SMART-CACHE] Found {len(cached_streams)} cached streams.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name: 
                    s_pid = 'webstreamr'
                elif 'nuvio' in raw_name: 
                    s_pid = 'nuvio'
                elif 'vix' in raw_name: 
                    s_pid = 'vixsrc'
                elif 'sooti' in raw_name: 
                    s_pid = 'sooti'
                elif 'vega' in raw_name: 
                    s_pid = 'vega'
                elif 'vidzee' in raw_name: 
                    s_pid = 'vidzee'
                elif 'rogflix' in raw_name: 
                    s_pid = 'rogflix'
                elif 'streamvix' in raw_name: 
                    s_pid = 'streamvix'
                elif 'hdhub' in raw_name: s_pid = 'hdhub4u'
                elif 'mkvcinemas' in raw_name: s_pid = 'mkvcinemas'
                elif 'xdmovies' in raw_name: s_pid = 'xdmovies'
                elif 'moviesdrive' in raw_name: s_pid = 'moviesdrive'
            
            if s_pid and s_pid not in active_providers:
                continue 
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id')
        if not imdb_id: 
            imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if p_dialog.iscanceled():
                return False  # <--- Returnăm False pentru a semnala oprirea
            msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
            p_dialog.update(percent, msg)
            return True   # <--- Totul e OK

        target_list = providers_to_scan if cached_streams is not None else None
        
        # Filtrare finală: doar provideri activi
        if target_list:
            final_target = [p for p in target_list if p in active_providers]
        else:
            final_target = active_providers  # <-- CRUCIAL!

        # MODIFICARE: Primim si was_canceled
        new_streams, new_failed, was_canceled = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target
        )
        
        p_dialog.close()
        
        # --- FIX: DACĂ S-A DAT CANCEL, OPRIM TOT ---
        if was_canceled:
            log("[LIST-SOURCES] User cancelled scanning. Aborting without saving cache.")
            # Important: Nu salvăm cache-ul, pentru ca data viitoare să încerce din nou providerii săriți
            try:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except:
                pass
            return
        # --------------------------------------------
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
                
        final_failed = new_failed

        if cached_streams is not None:
            # Adaugă toate sursele noi - deduplicarea se face la final
            streams.extend(new_streams)
            log(f"[SMART-CACHE] Adăugate {len(new_streams)} surse noi")
        else:
            streams = new_streams
            
        if streams or final_scanned:
            # TREBUIE SĂ EXISTE ACESTE DOUĂ LINII:
            streams = deduplicate_streams(streams)  # <-- VERIFICĂ!
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)

    if not streams:
        xbmcgui.Dialog().notification("TMDb Movies", "Nu s-au găsit surse", TMDbmovies_ICON)
        try:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except:
            pass
        return

    # --- 4. AFIȘARE ---
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    dlg_title = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if cached_streams is not None: 
        dlg_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        # Preluare metadate
        eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
        
        if not ids: 
            try: 
                ids = get_external_ids(c_type, tmdb_id)
            except: 
                ids = {}

        final_imdb_id = None
        if c_type == 'tv':
            final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else ids.get('imdb_id')
        else:
            final_imdb_id = extra_imdb_id if extra_imdb_id else ids.get('imdb_id')

        final_title = eng_title if eng_title else title
        final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
        
        properties = {'tmdb_id': str(tmdb_id)}
        if final_imdb_id:
            if c_type == 'tv': 
                properties['tvshow.imdb_id'] = final_imdb_id
            properties['imdb_id'] = final_imdb_id
            properties['ImdbNumber'] = final_imdb_id

        info_tag = {
            'title': final_title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'year': int(year) if year else 0
        }
        if final_imdb_id: 
            info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: 
                info_tag['season'] = int(season)
            if episode: 
                info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id: 
            unique_ids['imdb'] = final_imdb_id
            
        # Pornește playerul - play_with_rollover se ocupă de setResolvedUrl
        play_with_rollover(
            streams, ret, tmdb_id, c_type, season, episode,
            info_tag, unique_ids, {'poster': poster_url}, properties, resume_time
        )
        
        if final_imdb_id:
            threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode)).start()
            
    else:
        # User cancelled dialog
        try:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        except:
            pass


# =============================================================================
# RESOLVE DIALOG - VERSIUNE CORECTATĂ
# =============================================================================
def tmdb_resolve_dialog(params):
    """
    Funcție pentru TMDbHelper - rezolvă și redă direct.
    """
    
    log("[RESOLVE] === TMDB_RESOLVE_DIALOG START ===")
    
    # ===========================================================================
    # FIX: CURĂȚĂM WINDOW PROPERTIES LA ÎNCEPUT
    # ===========================================================================
    win = xbmcgui.Window(10000)
    
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'mrsp.tmdb_id', 'mrsp.imdb_id'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[RESOLVE] Window Properties curățate la început')
    # ===========================================================================
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title', '')
    year = params.get('year', '')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = params.get('imdb_id')
    
    log(f"[RESOLVE] TMDb ID: {tmdb_id}, Type: {c_type}, Title: {title}")
    
    # =========================================================================
    # DEFINIRE BAD DOMAINS
    # =========================================================================
    bad_domains = [
        'googleusercontent.com',
        'googlevideo.com',
        'video-leech.pro',
        'video-seed.pro',
    ]
    
    # =========================================================================
    # 1. VERIFICĂM SMART CACHE ÎNTÂI
    # =========================================================================
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive']
    active_providers = []
    for pid in all_known_providers:
        setting_id = f'use_{pid if pid != "nuvio" else "nuviostreams"}'
        if ADDON.getSetting(setting_id) == 'true':
            active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try:
        cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except:
        cache_duration = 24
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv':
        search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, failed_providers_history, scanned_providers_history = None, [], []
    
    if use_cache:
        cached_streams, failed_providers_history, scanned_providers_history = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None:
        scanned_providers_history = []
    if failed_providers_history is None:
        failed_providers_history = []

    streams = []
    providers_to_scan = []
    from_cache = False
    
    if cached_streams is not None:
        log(f"[RESOLVE] [SMART-CACHE] Found {len(cached_streams)} cached streams.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                raw_name = s.get('name', '').lower()
                if 'webstreamr' in raw_name:
                    s_pid = 'webstreamr'
                elif 'nuvio' in raw_name:
                    s_pid = 'nuvio'
                elif 'vix' in raw_name:
                    s_pid = 'vixsrc'
                elif 'sooti' in raw_name:
                    s_pid = 'sooti'
                elif 'vega' in raw_name:
                    s_pid = 'vega'
                elif 'vidzee' in raw_name:
                    s_pid = 'vidzee'
                elif 'rogflix' in raw_name:
                    s_pid = 'rogflix'
                elif 'streamvix' in raw_name:
                    s_pid = 'streamvix'
                elif 'hdhub' in raw_name: s_pid = 'hdhub4u' # Adaugat detectie
                elif 'mkvcinemas' in raw_name: s_pid = 'mkvcinemas' # Adaugat detectie
                elif 'xdmovies' in raw_name: s_pid = 'xdmovies' # Adaugat detectie
                elif 'moviesdrive' in raw_name: s_pid = 'moviesdrive' # Adaugat detectie
            
            if s_pid and s_pid not in active_providers:
                continue
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        from_cache = True
        retry_list = [p for p in failed_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in failed_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))

    # =========================================================================
    # 2. CĂUTARE NET
    # =========================================================================
    if cached_streams is None or providers_to_scan:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Se inițializează căutarea...")
        
        if not imdb_id:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        
        if not imdb_id:
            imdb_id = f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if p_dialog.iscanceled():
                return False  # <--- Returnăm False
            msg = f"Se caută surse pentru: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
            p_dialog.update(percent, msg)
            return True   # <--- Totul e OK

        target_list = providers_to_scan if cached_streams is not None else None
        
        # Filtrare finală: doar provideri activi
        if target_list:
            final_target = [p for p in target_list if p in active_providers]
        else:
            final_target = active_providers  # <-- CRUCIAL!

        # MODIFICARE: Primim si was_canceled
        new_streams, new_failed, was_canceled = get_stream_data(
            imdb_id, c_type, season, episode, 
            progress_callback=update_progress,
            target_providers=final_target
        )
        
        p_dialog.close()
        
        # --- FIX: DACĂ S-A DAT CANCEL, OPRIM TOT ---
        if was_canceled:
            log("[RESOLVE] User cancelled scanning. Aborting.")
            try:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            except:
                pass
            return
        # --------------------------------------------
        
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                final_scanned.append(p)
        
        final_failed = new_failed

        if cached_streams is not None:
            # Adaugă toate sursele noi - deduplicarea se face la final
            streams.extend(new_streams)
            log(f"[SMART-CACHE] Adăugate {len(new_streams)} surse noi")
        else:
            streams = new_streams
        
        if streams or final_scanned:
            # Deduplicare și sortare
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_failed, final_scanned, cache_duration)
    
    # =========================================================================
    # 3. VERIFICĂM DACĂ AVEM SURSE
    # =========================================================================
    if not streams:
        log("[RESOLVE] Nicio sursă găsită")
        xbmcgui.Dialog().notification("TMDb Movies", "Nu s-au găsit surse", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 4. AFIȘARE DIALOG CU SURSE
    # =========================================================================
    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    header = f"{title} ({year})" if c_type == 'movie' and year else title
    dlg_title = f"[B][COLOR FFFDBD01]{header} - [COLOR FF6AFB92]{len(streams)} Surse[/COLOR][/B]"
    if from_cache:
        dlg_title += " [COLOR lime][CACHE][/COLOR]"
    
    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret < 0:
        log("[RESOLVE] User cancelled")
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 5. GĂSEȘTE PRIMA SURSĂ VALIDĂ (cu verificare) - CU MESAJE FRUMOASE
    # =========================================================================
    from resources.lib.utils import clean_text
    
    selected_url = None
    total_streams = len(streams)
    
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Inițializare...")
    
    try:  # <-- IMPORTANT: Try-finally pentru a asigura închiderea dialogului
        for i in range(ret, total_streams):
            stream = streams[i]
            url = stream.get('url', '')
            
            if not url or not url.startswith(('http://', 'https://')):
                continue
            
            # Verificare domenii rele
            base_url_check = url.split('|')[0].lower()
            if any(bad in base_url_check for bad in bad_domains):
                continue
            
            # ============================================================
            # DETECȚIE SOOTI (PENTRU LOGICA AUDIO - INTERN)
            # ============================================================
            raw_name = stream.get('name', 'Unknown')
            provider_id = stream.get('provider_id', '').lower()
            # Verificăm toate variațiile pentru a ști dacă aplicăm check-ul audio
            is_sooti = 'sooti' in raw_name.lower() or 'sooti' in provider_id or 'slownow' in raw_name.lower() or 'sooti' in url.lower()
            
            if is_sooti:
                log(f"[RESOLVE] Provider detectat: SOOTI/SlowNow (Index {i+1})")

            # ============================================================
            # PREGĂTIRE NUME PENTRU AFIȘARE (DREAPTA SUS) - UNDERCOVER
            # ============================================================
            # Aici forțăm înlocuirea vizuală, indiferent de ce vine din scraper
            display_name = clean_text(raw_name).replace('\n', ' ')
            
            # LISTA NEAGRĂ DE NUME REALE -> ALIASURI
            display_name = display_name.replace('Sooti', 'SlowNow')
            display_name = display_name.replace('Nuvio', 'NotNow')
            display_name = display_name.replace('WebStreamr', 'WebNow')
            display_name = display_name.replace('StreamVix', 'StreamNow')
            display_name = display_name.replace('XDMovies', 'SmileNow')
            display_name = display_name.replace('XDM', 'SmileNow')
            
            # Scurtare pentru estetică
            display_name = display_name[:50]

            full_info = (raw_name + stream.get('title', '')).lower()
            c_qual = "FF00BFFF"
            qual_txt = "SD"
            if '2160' in full_info or '4k' in full_info:
                qual_txt = "4K"; c_qual = "FF00FFFF"
            elif '1080' in full_info:
                qual_txt = "1080p"; c_qual = "FF00FF7F"
            elif '720' in full_info:
                qual_txt = "720p"; c_qual = "FFFFD700"
                
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            msg = f"Verific sursa {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR] • [B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            p_dialog.update(int(((i - ret + 1) / max(1, total_streams - ret)) * 100), message=msg)
            # ============================================================
            
            # Verificare validitate URL
            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except: pass
                
                is_valid = check_url_validity(base_url, headers=check_headers)
                
                # Verificare specifică Sooti (Audio Only check)
                if is_valid and is_sooti:
                    if PLAYER_AUDIO_CHECK_ONLY_SD:
                        if is_sd_or_720p(stream):
                            if check_sooti_audio_only(base_url, headers=check_headers):
                                is_valid = False
                    else:
                        if check_sooti_audio_only(base_url, headers=check_headers):
                            is_valid = False
                
                if is_valid:
                    selected_url = url
                    log(f"[RESOLVE] Sursă validă găsită: {i+1}/{total_streams}")
                    break
            except Exception as e:
                log(f"[RESOLVE] Eroare verificare sursa {i+1}: {e}")
                continue
    
    finally:  # <-- ASIGURĂ ÎNCHIDEREA DIALOGULUI ÎNTOTDEAUNA
        p_dialog.close()
    
    if not selected_url:
        log("[RESOLVE] Nicio sursă validă")
        xbmcgui.Dialog().notification("TMDb Movies", "Nicio sursă validă", TMDbmovies_ICON)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    
    # =========================================================================
    # 6. CONSTRUIEȘTE LISTITEM ȘI RETURNEAZĂ PRIN setResolvedUrl
    # =========================================================================
    eng_title, eng_tvshowtitle, extra_imdb_id, tv_show_parent_imdb_id = get_english_metadata(tmdb_id, c_type, season, episode)
    
    if not imdb_id:
        try:
            ids = get_external_ids(c_type, tmdb_id)
            imdb_id = ids.get('imdb_id')
        except:
            pass

    final_imdb_id = None
    if c_type == 'tv':
        final_imdb_id = tv_show_parent_imdb_id if tv_show_parent_imdb_id else imdb_id
    else:
        final_imdb_id = extra_imdb_id if extra_imdb_id else imdb_id

    final_title = eng_title if eng_title else title
    final_show_title = eng_tvshowtitle if eng_tvshowtitle else params.get('tv_show_title', '')
    
    properties = {'tmdb_id': str(tmdb_id)}
    if final_imdb_id:
        if c_type == 'tv':
            properties['tvshow.imdb_id'] = final_imdb_id
        properties['imdb_id'] = final_imdb_id
        properties['ImdbNumber'] = final_imdb_id

    info_tag = {
        'title': final_title,
        'mediatype': 'movie' if c_type == 'movie' else 'episode',
        'year': int(year) if year else 0
    }
    if final_imdb_id:
        info_tag['imdbnumber'] = final_imdb_id
    if c_type == 'tv':
        info_tag['tvshowtitle'] = final_show_title
        if season:
            info_tag['season'] = int(season)
        if episode:
            info_tag['episode'] = int(episode)

    unique_ids = {'tmdb': str(tmdb_id)}
    if final_imdb_id:
        unique_ids['imdb'] = final_imdb_id
    
    art = {'poster': poster_url, 'thumb': poster_url}
    
    # Construiește ListItem final
    li = xbmcgui.ListItem(label=final_title, path=selected_url)
    li.setInfo('video', info_tag)
    li.setUniqueIDs(unique_ids)
    li.setArt(art)
    for k, v in properties.items():
        li.setProperty(k, str(v))
    
    # --- FIX: Setare Window Properties pentru Subs.ro ---
    try:
        win = xbmcgui.Window(10000)
        win.setProperty('tmdb_id', str(tmdb_id))
        if final_imdb_id:
            win.setProperty('imdb_id', str(final_imdb_id))
        else:
            win.clearProperty('imdb_id')
    except: pass
    # ---------------------------------------------------
    
    # =========================================================================
    # RETURNEAZĂ URL-UL REZOLVAT CĂTRE TMDb Helper
    # =========================================================================
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    log("[RESOLVE] setResolvedUrl(True) trimis cu succes")
    
    # Pornește subtitle service în background
    if final_imdb_id:
        threading.Thread(target=subtitles.run_wyzie_service, args=(final_imdb_id, season, episode), daemon=True).start()
    
    log("[RESOLVE] === END ===")
   
   
# =============================================================================
# DOWNLOAD INITIATOR (UPDATED)
# =============================================================================
def initiate_download(params):
    from resources.lib.downloader import start_download_thread
    from resources.lib.cache import MainCache
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    season = params.get('season')
    episode = params.get('episode')
    year = params.get('year', '')
    
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
    all_known_providers = ['sooti', 'nuvio', 'webstreamr', 'vixsrc', 'rogflix', 'vega', 'streamvix', 'vidzee', 'hdhub4u', 'mkvcinemas', 'xdmovies', 'moviesdrive']
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
                elif 'rogflix' in raw: s_pid='rogflix'
                elif 'streamvix' in raw: s_pid='streamvix'
                elif 'hdhub' in raw: s_pid = 'hdhub4u'
                elif 'mkvcinemas' in raw: s_pid = 'mkvcinemas'
                elif 'xdmovies' in raw: s_pid = 'xdmovies'
                elif 'moviesdrive' in raw: s_pid = 'moviesdrive'
            
            if s_pid and s_pid in active_providers:
                valid_cached_streams.append(s)
            elif not s_pid:
                valid_cached_streams.append(s)
        streams = valid_cached_streams

    # 3. Scrape
    if not streams:
        p_dialog = xbmcgui.DialogProgress()
        p_dialog.create("Download Manager", "Inițializare...")
        
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id') or f"tmdb:{tmdb_id}"

        def update_progress(percent, provider_name):
            if p_dialog.iscanceled(): return False
            msg = f"Se caută surse download: [B][COLOR FF6AFB92]{title}[/COLOR][/B]\nProvider: [B][COLOR FFFF00FF]{provider_name}[/COLOR][/B]"
            p_dialog.update(percent, msg)
            return True

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
    streams = deduplicate_streams(streams)  # <-- VERIFICĂ!
    streams = sort_streams_by_quality(streams)
    clean_title_backup = title
    if c_type == 'tv':
        st = params.get('tv_show_title', '')
        if st: clean_title_backup = st 

    poster_url = get_poster_url(tmdb_id, c_type, season)
    display_items = build_display_items(streams, poster_url)
    
    dlg_title = f"[DOWNLOAD] Selectează sursa:"
    if cached_streams: dlg_title += " [COLOR lime][CACHE][/COLOR]"

    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        selected_stream = streams[ret]
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
        import xbmc
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