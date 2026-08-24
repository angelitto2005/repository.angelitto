import os
import re
import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs
import threading
import time
import requests
import urllib.parse
from urllib.parse import urlparse
import json
from resources.lib.config import get_headers, BASE_URL, API_KEY, IMG_BASE, ADDON
from resources.lib.utils import log, get_json, extract_details, get_language, clean_text
from resources.lib.scraper import get_external_ids, get_stream_data, filter_streams_for_display
from resources.lib.tmdb_api import set_metadata
from resources.lib.watched_provider import dispatch_mark_watched, dispatch_mark_unwatched, dispatch_scrobble
from resources.lib import subtitle as subtitles
from resources.lib import trakt_sync
from resources.lib.cache import MainCache


def _current_handle():
    """Get the current Kodi plugin handle dynamically (avoids stale HANDLE from config)."""
    try:
        return int(sys.argv[1])
    except Exception:
        return -1


def _current_win_id():
    try:
        return int(xbmcgui.getCurrentWindowId())
    except:
        return 0


def _kodi_resume_bookmark_exists(tmdb_id, c_type, season=None, episode=None):
    """Verifica daca baza video Kodi are bookmark de resume pentru acest episod/film.
    Kodi salveaza bookmark-urile keyed by plugin URL (original_listitem_url), deci un
    bookmark existent = dialogul NATIV de resume a aparut la click in ferestrele video
    (GUIWindowVideoBase::OnSelect -> OnResumeItem -> GetResumeString). La orice eroare
    returneaza False -> dialogul nostru ramane fallback (mai bine intrebam decat sa
    presupunem ca s-a raspuns deja)."""
    try:
        import glob
        import os
        import sqlite3
        c_type = 'tv' if c_type in ('tv', 'episode') else 'movie'
        db_dir = xbmcvfs.translatePath('special://userdata/Database/')
        dbs = glob.glob(os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            return False
        db_path = max(dbs, key=os.path.getmtime)
        conn = sqlite3.connect(db_path, timeout=2)
        cur = conn.cursor()
        params = ['%mode=sources%', f'%tmdb_id={tmdb_id}%', f'%type={c_type}%']
        query = ("SELECT 1 FROM bookmark b JOIN files f ON b.idFile=f.idFile "
                 "WHERE b.type=1 AND f.strFilename LIKE ? AND f.strFilename LIKE ? AND f.strFilename LIKE ?")
        if c_type == 'tv' and season is not None and episode is not None:
            params += [f'%season={season}%', f'%episode={episode}%']
            query += " AND f.strFilename LIKE ? AND f.strFilename LIKE ?"
        query += " LIMIT 1"
        cur.execute(query, params)
        found = cur.fetchone() is not None
        conn.close()
        log(f"[RESUME] Bookmark check (db={os.path.basename(db_path)}): {found}")
        return found
    except Exception as e:
        log(f"[RESUME] Bookmark check error: {e}")
        return False
from resources.lib.subtitle import run_wyzie_service
try: import resolveurl
except: resolveurl = None

_IS_ANDROID = xbmc.getCondVisibility('System.Platform.Android')
import pprint

LANG = get_language()

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# =============================================================================
# CONFIGURARI PLAYER - MODIFICA AICI
# =============================================================================
PLAYER_CHECK_TIMEOUT = 10  # Secunde pentru verificare sursa (mareste daca surse mari)
PLAYER_AUDIO_CHECK_ONLY_SD = True  # True = verifica audio-only doar pe SD/720p, False = verifica toate
# PLAYER_KEEP_DUPLICATES = True  # True = pastreaza surse duplicate, False = elimina duplicate
# =============================================================================
_active_player = None

# Globals for reopening sources window on P2P cancel
_saved_window_items = None
_saved_meta_dict = None
_saved_filtered_streams = None

# AIO/Stremio provider IDs for type grouping
_AIO_STREMIO_IDS = {'aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5'}


# =============================================================================
# CLASIFICARE SURSE PE 4 CATEGORII (HTTP / AIO / STREMIO / P2P)
# =============================================================================
def classify_stream_source(stream):
    """Returneaza categoria sursei: 'p2p' (p2p_*), 'aio' (aiostreams),
    'stremio' (torrentio/mediafusion/comet/meteor/usenet/custom1-5) sau 'http'."""
    pid = str(stream.get('provider_id', ''))
    if pid.startswith('p2p_'):
        return 'p2p'
    if pid == 'aiostreams':
        return 'aio'
    if pid in _AIO_STREMIO_IDS:
        return 'stremio'
    return 'http'


# Tabela de tier-uri pt fiecare optiune de Source Priority (sort_opt):
# prima pozitie = cel mai sus (score maxim), cached se consulta DOAR la aio/stremio.
# 'aio_orig' pastreaza ordinea originala din lista (cheie statica).
_SORT_TIERS = {
    1: ['aio_orig', 'stremio', 'http', 'p2p'],
    2: ['aio_orig', 'stremio', 'p2p', 'http'],
    3: ['aio_c', 'stremio_c', 'http', 'aio_u', 'stremio_u', 'p2p'],
    4: ['aio_stremio_c', 'p2p', 'http', 'aio_stremio_u'],
    5: ['aio_stremio_c', 'http', 'aio_stremio_u', 'p2p'],
    6: ['stremio_c', 'aio_c', 'http', 'aio_stremio_u', 'p2p'],
    7: ['http', 'aio_stremio_c', 'p2p', 'aio_stremio_u'],
    8: ['http', 'aio_stremio_c', 'aio_stremio_u', 'p2p'],
    9: ['p2p', 'aio_stremio_c', 'http', 'aio_stremio_u'],
}


def _tier_matches(tier, cat, is_cached):
    """Verifica daca un stream (categoria + cached) apartine tier-ului."""
    if tier in ('aio_orig', 'aio'):
        return cat == 'aio'
    if tier == 'stremio':
        return cat == 'stremio'
    if tier == 'http':
        return cat == 'http'
    if tier == 'p2p':
        return cat == 'p2p'
    if tier == 'aio_c':
        return cat == 'aio' and is_cached
    if tier == 'aio_u':
        return cat == 'aio' and not is_cached
    if tier == 'stremio_c':
        return cat == 'stremio' and is_cached
    if tier == 'stremio_u':
        return cat == 'stremio' and not is_cached
    if tier == 'aio_stremio_c':
        return cat in ('aio', 'stremio') and is_cached
    if tier == 'aio_stremio_u':
        return cat in ('aio', 'stremio') and not is_cached
    return False

ALL_KNOWN_PROVIDERS = ['sooti', 'webstreamr', 'streamvix', 'vidlink', 'vsembed', 'videasy', 'netmirror', 'vidmody', 'movieblast', 'moviebox', 'onlykdrama', 'primesrcme', 'vaplayer', 'flixer', 'cineby', 'cinefreak', 'fshdnet', 'hdhub4u', 'mkvcinemas', 'moviesdrive', 'hdhub', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5', 'aiostreams', 'p2p_yts', 'p2p_torrentio', 'p2p_comet', 'p2p_mediafusion', 'p2p_filelist', 'p2p_speedapp', 'p2p_seedpool', 'p2p_knaben', 'p2p_thepiratebay', 'p2p_custom1', 'p2p_custom2', 'p2p_custom3', 'p2p_custom4', 'p2p_custom5']

# =============================================================================
# HELPER GLOBAL PENTRU IDENTIFICAREA PROVIDERILOR (FALLBACK)
# =============================================================================
def get_fallback_provider_id(name_string):
    """Identifica provider-ul dintr-un string daca acesta lipseste din dictionar."""
    if not name_string:
        return None
        
    name_lower = name_string.lower()
    
    # ATENTIE LA ORDINE: Cele mai lungi/specifice primele (ex: hdhub4u inainte de hdhub)
    mapping = {
        'webstreamr': 'webstreamr', 'sooti': 'sooti',
        'vidlink': 'vidlink', 'vsembed': 'vsembed', 'videasy': 'videasy',
        'netmirror': 'netmirror', 'vidmody': 'vidmody', 'movieblast': 'movieblast',
        'moviebox': 'moviebox', 'onlykdrama': 'onlykdrama',
        'streamvix': 'streamvix', 'mkvcinemas': 'mkvcinemas', 'moviesdrive': 'moviesdrive',
        'hdhub4u': 'hdhub4u', 'hdhub': 'hdhub', 'primesrcme': 'primesrcme',
        'vaplayer': 'vaplayer', 'flixer': 'flixer', 'fshd': 'fshdnet',
        'torrentio': 'torrentio', 'mediafusion': 'mediafusion', 'comet': 'comet', 'meteor': 'meteor',
        'usenet': 'usenet', 'custom1': 'custom1', 'custom2': 'custom2', 'custom3': 'custom3', 'custom4': 'custom4', 'custom5': 'custom5',
        'aio': 'aiostreams',
        # Cache vechi / Istoric (sa nu se piarda daca exista deja stocate):
        'vidzee': 'vidzee', 'rogflix': 'rogflix', 'xdmovies': 'xdmovies'
    }
    
    for key, provider_id in mapping.items():
        if key in name_lower:
            return provider_id
            
    return None


# =============================================================================
# DEDUPLICARE STREAMS (FILTRARE URL-URI IDENTICE)
# =============================================================================
def deduplicate_streams(streams):
    """
    Elimina stream-urile duplicate bazat pe URL-ul de baza.
    Pastreaza prima aparitie pentru fiecare URL unic.
    """
    log(f"[DEDUP] === STARTING DEDUPLICATION ===")
    
    if not streams:
        log(f"[DEDUP] Empty streams list, returning")
        return streams
    
    # Verifica daca filtrarea e activata
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
        
        # Extrage URL-ul de baza (fara headere |...)
        base_url = url.split('|')[0].strip()
        
        # Normalizare URL pentru comparatie
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
    
    log(f"[DEDUP] âś“ Result: {len(streams)} -> {len(unique_streams)} (removed {duplicates_removed} duplicates)")
    
    return unique_streams
    


def check_url_validity(url, headers=None, max_timeout=None):
    """Verifica daca URL-ul este accesibil si NU e intermediar."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT
    
    if not url:
        return False
    
    result = {'valid': False, 'done': False}
    
    def _check():
        try:
            clean_url = url.split('|')[0]
            
            if not clean_url.startswith(('http://', 'https://')):
                if clean_url.startswith('file://'):
                    result['valid'] = True
                    result['done'] = True
                    return
                result['done'] = True
                return
            
            clean_url_lower = clean_url.lower()
            
            # =========================================================
            # BYPASS PENTRU WORKERS SI M3U8 SI GOOGLE SI CDN-URI SEMNATE
            # =========================================================
            if 'workers.dev' in clean_url_lower or '.m3u8' in clean_url_lower or 'googleusercontent.com' in clean_url_lower or 'googlevideo.com' in clean_url_lower or 'bcdnxw.hakunaymatata.com' in clean_url_lower or 'baby-beamup.club' in clean_url_lower:
                log(f"[PLAYER-CHECK] M3U8 / Worker / Google / Hakuna bypass - Assume VALID")
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
            
            # AM ELIMINAT COMPLET GOOGLE DE AICI!
            bad_domains = [
                'video-leech.pro',
                'video-seed.pro'
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
                
                log(f"[PLAYER-CHECK] Original: {clean_url[:80]}...")
                if final_url and final_url != clean_url.lower():
                    log(f"[PLAYER-CHECK] Redirect: {final_url[:80]}...")
                
                for bad in bad_domains:
                    if bad in final_url:
                        log(f"[PLAYER-CHECK] Redirects to bad domain ({bad}) - SKIP")
                        result['done'] = True
                        return
                
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
                
            except Exception as e:
                log(f"[PLAYER-CHECK] Network/Timeout error: {type(e).__name__}")
                result['done'] = True

        except Exception as e:
            log(f"[PLAYER-CHECK] Outer error: {type(e).__name__}")
            result['done'] = True
    
    thread = threading.Thread(target=_check)
    thread.daemon = True
    thread.start()
    thread.join(timeout=max_timeout)
    
    if not result['done']:
        log(f"[PLAYER-CHECK] TIMEOUT FORTAT ({max_timeout}s) - SKIP")
        return False
    
    return result['valid']


def _fast_aio_resolve_link(url, timeout=25):
    """Rezolva URL-uri AIO/Stremio la link-ul final (stil POV): 4xx/5xx/timeout = None, fara retry."""
    clean_url = url.split('|')[0]
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    if '|' in url:
        try: headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
        except: pass
    try:
        r = requests.get(clean_url, headers=headers, timeout=timeout, verify=False, allow_redirects=True, stream=True)
        code = r.status_code
        final = r.url
        r.close()
        if code >= 400:
            log(f"[PLAYER-AIOCHECK] FAIL ({code}): {clean_url[:60]}...")
            return None
        if headers and '|' not in final:
            final = f"{final}|" + urllib.parse.urlencode(headers)
        log(f"[PLAYER-AIOCHECK] OK ({code}) -> {final[:60]}...")
        return final
    except Exception as e:
        log(f"[PLAYER-AIOCHECK] ERROR {type(e).__name__}: {clean_url[:60]}...")
        return None


def check_sooti_audio_only(url, headers=None, max_timeout=None):
    """Verifica daca sursa Sooti este audio-only. Returneaza True daca e AUDIO (adica invalida)."""
    if max_timeout is None:
        max_timeout = PLAYER_CHECK_TIMEOUT  # <-- Foloseste constanta globala
    
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
        log(f"[SOOTI-CHECK] TIMEOUT FORTAT ({max_timeout}s) - SKIP")
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
        log(f"[RAM-SRC] Error salvare: {e}", xbmc.LOGERROR)


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
                    log(f"[RAM-SRC] Incarcat {len(streams)} surse din cache")
                    return streams
    except Exception as e:
        log(f"[RAM-SRC] Error citire: {e}", xbmc.LOGERROR)
    return None


def clear_sources_cache():
    try:
        window = get_window()
        window.clearProperty('tmdbmovies.src_id')
        window.clearProperty('tmdbmovies.src_data')
        log("[RAM-SRC] Cache curatat complet")
    except Exception as e:
        log(f"[RAM-SRC] Error cleanup: {e}", xbmc.LOGERROR)


def save_return_path():
    try:
        window = get_window()
        window.setProperty('tmdbmovies.need_fast_return', 'true')
        log("[RAM-NAV] Marcat pentru intoarcere rapida")
    except Exception as e:
        log(f"[RAM-NAV] Error: {e}", xbmc.LOGERROR)


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
# EXTRACTOR INFORMATII STREAM - V4 (FIX SERVER EXTRACTION)
# =============================================================================
def extract_stream_info(stream):
    """
    Extrage informatii detaliate (Undercover Mode).
    V4 - FIX: Extragere corecta server din MKV | Server | Size format.
    """
    raw_name = stream.get('name', '')
    raw_title = stream.get('title', '')
    provider_id = stream.get('provider_id', '')
    url = stream.get('url', '').lower()
    
    # Campuri noi pentru Sooti
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
            'webstreamr': 'Webstreamr',
            'streamvix': 'StreamVix',
            'vidlink': 'VidLink',
            'vsembed': 'VSEmbed',
            'videasy': 'VidEasy',
            'netmirror': 'NetMirror',
            'vidmody': 'Vidmody',
            'movieblast': 'MovieBlast',
            'moviebox': 'MovieBox',
            'onlykdrama': 'OnlyKDrama',
            'hdhub4u': 'HDHub4u',
            'mkvcinemas': 'MKVCinemas',
            'moviesdrive': 'MoviesDrive',
            'hdhub': 'HDHub',
            'torrentio': 'Torrentio',
            'primesrcme': 'PrimeSrc',
            'vaplayer': 'VAPlayer',
            'flixer': 'Flixer',
            'fshdnet': 'FSHDnet',
            'custom1': ADDON.getSetting('custom1_name') or 'Custom 1',
            'custom2': ADDON.getSetting('custom2_name') or 'Custom 2',
            'custom3': ADDON.getSetting('custom3_name') or 'Custom 3',
            'custom4': ADDON.getSetting('custom4_name') or 'Custom 4',
            'custom5': ADDON.getSetting('custom5_name') or 'Custom 5',
            'p2p_yts': 'YTS',
            'p2p_torrentio': 'Torrentio P2P',
            'p2p_comet': 'Comet P2P',
            'p2p_mediafusion': 'MediaFusion P2P',
            'p2p_filelist': 'FileList',
            'p2p_speedapp': 'SpeedApp',
            'p2p_seedpool': 'SeedPool',
            'p2p_knaben': 'Knaben',
            'p2p_thepiratebay': 'TPB',
            'p2p_custom1': ADDON.getSetting('p2p_custom1_name') or 'P2P Custom 1',
            'p2p_custom2': ADDON.getSetting('p2p_custom2_name') or 'P2P Custom 2',
            'p2p_custom3': ADDON.getSetting('p2p_custom3_name') or 'P2P Custom 3',
            'p2p_custom4': ADDON.getSetting('p2p_custom4_name') or 'P2P Custom 4',
            'p2p_custom5': ADDON.getSetting('p2p_custom5_name') or 'P2P Custom 5'
        }
        provider = provider_map.get(provider_id.lower(), provider_id)
    
    if not provider:
        name_lower = raw_name.lower()
        if 'sootio' in name_lower or 'sooti' in name_lower or '[hs+]' in name_lower: provider = 'Sootio'
        elif 'webstreamr' in name_lower: provider = 'Webstreamr'
        elif 'vidlink' in name_lower: provider = 'VidLink'
        elif 'vsembed' in name_lower: provider = 'VSEmbed'
        elif 'videasy' in name_lower: provider = 'VidEasy'
        elif 'netmirror' in name_lower: provider = 'NetMirror'
        elif 'vidmody' in name_lower: provider = 'Vidmody'
        elif 'movieblast' in name_lower: provider = 'MovieBlast'
        elif 'moviebox' in name_lower: provider = 'MovieBox'
        elif 'onlykdrama' in name_lower: provider = 'OnlyKDrama'
        elif 'streamvix' in name_lower: provider = 'StreamVix'
        elif 'mkv |' in name_lower or 'mkvcinemas' in name_lower: provider = 'MKVCinemas'
        elif 'hdhub' in name_lower: provider = 'HDHub4u'
        elif 'moviesdrive' in name_lower or 'mdrive' in name_lower: provider = 'MoviesDrive'
        elif 'torrentio' in name_lower: provider = 'Torrentio'
        elif 'flixer' in name_lower: provider = 'Flixer'
        elif 'fshdnet' in name_lower or 'fshd' in name_lower: provider = 'FSHDnet'
        elif 'yts' in name_lower or 'yify' in name_lower: provider = 'YTS'
        else: provider = 'Unknown'
    
    # 2. SERVER (din URL sau din name)
    server = ""
    
    # 2a. Extragere din URL (prioritate maxima)
    if 'pixeldrain' in url: 
        server = 'PixelDrain'
    elif 'trashbytes' in url:
        server = 'TrashBytes'
    elif 'awsdllaaa' in url or 'aws-storage' in url:
        server = 'FastCloud'
    elif 'instant.busycdn' in url or 'busycdn' in url:
        server = 'InstantDL'
    elif 'r2.cloudflarestorage.com' in url:
        server = 'FSL-V2'
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
        webstr_server_match = re.search(r'đź”—\s*(.+?)(?:\n|$)', raw_title)
        if webstr_server_match: 
            server = webstr_server_match.group(1).strip()
        elif binge_group:
            if 'fsl' in binge_group.lower(): 
                server = 'HubCloud (FSL)'
            elif 'pixel' in binge_group.lower(): 
                server = 'HubCloud (Pixel)'

    # 2c. Extragere din name pentru MKVCinemas/HDHub4u/MoviesDrive (format: MKV | Server | Size)
    if not server and '|' in raw_name and provider in ['MKVCinemas', 'HDHub4u', 'MoviesDrive', 'Unknown']:
        parts = [p.strip() for p in raw_name.split('|')]
        
        for part in parts:
            part_lower = part.lower()
            
            # Skip "MKV" sau nume provider
            if part_lower in ['mkv', 'mkvcinemas', 'hdhub4u', 'moviesdrive', 'hdhub', '']:
                continue
            
            # Skip daca e marime (ex: "5.28 GB", "707.78 MB")
            if re.search(r'^[\d.,]+\s*(gb|mb|tb|gib|mib)$', part_lower):
                continue
            
            # Skip daca e doar numere cu punct
            if re.match(r'^[\d.,]+$', part_lower):
                continue
            
            # Am gasit un candidat valid - verifica pattern-uri cunoscute
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
                # Foloseste partea ca server name direct (capitalizat)
                # Doar daca nu contine cifre la inceput
                if not re.match(r'^\d', part):
                    server = part
                    break
    
    # 2e. Fallback final - identifica din URL
    if not server:
        # Incearca sa extraga domeniul din URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url.split('|')[0])
            domain = parsed.netloc.lower().replace('www.', '')
            domain_parts = domain.split('.')
            if domain_parts and len(domain_parts[0]) >= 2:
                potential_server = domain_parts[0].title()
                # Filtram hash-urile lungi (MD5/UUID) ca sa nu apara ca nume de server
                if potential_server not in ['Http', 'Https', 'Www', ''] and len(potential_server) < 25:
                    server = potential_server
        except:
            pass
    
    # 3. GROUP (doar daca nu avem source_provider)
    group = ""
    if not source_provider:
        group_match = re.search(r'\|\s*([A-Za-z0-9]+(?:Hub|hub|HUB)?)\s*$', raw_title)
        if group_match: 
            group = group_match.group(1)
        if group and server and group.lower() == server.lower(): 
            group = ""

    # 4. SIZE - Prioritate: campul 'size' din stream, apoi extragere din text
    size = stream_size if stream_size else ""
    
    if not size:
        # --- PROTECTIE TYPEERROR (Daca info e dict, regex va crapa) ---
        info_val = stream.get('info', '')
        if isinstance(info_val, dict):
            info_str = str(info_val.get('original_info_str', '')) + " " + str(info_val.get('size', ''))
        else:
            info_str = str(info_val)
            
        search_texts =[raw_name, raw_title, info_str]
        # -------------------------------------------------------------
        
        size_patterns = [
            r'đź’ľ\s*([\d.]+)\s*(GB|MB|TB)',                    # Emoji format
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
                    # Validare: marimea trebuie sa fie rezonabila (0.1 - 100 GB/MB)
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
    
    if not quality or quality.upper() in ['SD', '480P', '360P', 'N/A', '']:
        clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
        res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in full_info)
        if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_info) and '2160p' not in full_info: res_count += 1
        
        if res_count >= 2:
            if '2160p' in full_info or re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_info):
                quality = "4K"
            elif '1080p' in full_info:
                quality = "1080p"
            elif '720p' in full_info:
                quality = "720p"
            else:
                quality = "SD"
        elif '2160p' in full_info or re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_info):
            quality = "4K"
        elif '1080p' in full_info:
            quality = "1080p"
        elif '720p' in full_info:
            quality = "720p"
        elif '480p' in full_info or '360p' in full_info or ' sd ' in full_info:
            quality = "SD"
    
    if not quality:
        quality = "SD"

    # 6. TAGS - Sistem de detectie extins
    tags = []
    
    # Video Codecs
    if any(x in full_info for x in ['hevc', 'x265', 'h.265', 'h265']): 
        tags.append("HEVC")
    elif any(x in full_info for x in ['x264', 'h.264', 'h264', 'avc']): 
        tags.append("x264")
    
    # Audio Codecs & Channels
    if 'atmos' in full_info: 
        tags.append("Atmos")
    if any(x in full_info for x in ['truehd', 'true.hd']): 
        tags.append("TrueHD")
    if 'dts-hd' in full_info or 'dtshd' in full_info: 
        tags.append("DTS-HD")
    elif 'dts' in full_info: 
        tags.append("DTS")
    if 'dd+' in full_info or 'eac3' in full_info or 'digital+' in full_info: 
        tags.append("DD+")
    elif 'ac3' in full_info or 'dd5' in full_info: 
        tags.append("DD")
    
    if '7.1' in full_info: 
        tags.append("7.1")
    elif '5.1' in full_info or '6ch' in full_info: 
        tags.append("5.1")
    
    # HDR / DV (Fix: Ignora HDRip)
    if 'dolby vision' in full_info or '.dv.' in full_info or ' dv ' in full_info: 
        tags.append("DV")
    
    # Verificare HDR curata (fara HDRip)
    if 'hdr' in full_info:
        if 'hdrip' not in full_info:
            tags.append("HDR")
    elif 'hdr10' in full_info:
        tags.append("HDR10")
        
    if 'hlg' in full_info: 
        tags.append("HLG")
    
    # Source Type
    if 'remux' in full_info: 
        tags.append("REMUX")
    if 'bluray' in full_info or 'bdrip' in full_info: 
        tags.append("BluRay")
    elif 'web-dl' in full_info or 'webdl' in full_info: 
        tags.append("WEB-DL")
    elif 'webrip' in full_info: 
        tags.append("WEBRip")
    elif 'hdtv' in full_info: 
        tags.append("HDTV")
    
    # Extra Tags
    if 'multi' in full_info: 
        tags.append("Multi")
    if any(x in full_info for x in ['ro-ro', 'romana', 'subs ro', 'sub ro']):
        tags.append("RO")
    if 'dual' in full_info and 'audio' in full_info:
        tags.append("Dual-Audio")
    
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
    Construieste lista de ListItem-uri pentru dialog.
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
        
        # Provider principal (roz)
        if provider:
            parts.append(f"[COLOR FFFF69B4]{provider}[/COLOR]")
        
        # Size (galben)
        if size:
            parts.append(f"[COLOR FFFFEA00]{size}[/COLOR]")
        
        # Source Provider (portocaliu) - UHDMovies, MoviesDrive, MKVCinemas
        # DOAR daca exista si e diferit de provider principal
        if source_provider and source_provider.lower() not in [provider.lower(), server.lower() if server else '']:
            parts.append(f"[COLOR FFFFA500]{source_provider}[/COLOR]")
        
        # Server (verde-cyan) - PixelDrain, Worker, Flash, etc
        if server:
            # Nu afisa server-ul daca e identic cu source_provider
            if not source_provider or server.lower() != source_provider.lower():
                parts.append(f"[COLOR FF20B2AA]{server}[/COLOR]")
        
        # Group (mov) - doar daca nu avem source_provider si e diferit
        if group and not source_provider:
            if group.lower() != server.lower() and group.lower() != provider.lower():
                parts.append(f"[COLOR FFBA55D3]{group}[/COLOR]")
        
        # Tags (la final)
        if tags_str:
            parts.append(tags_str)
        
        label = "[B]" + "  ".join(parts) + "[/B]"
        
        # =========================================================
        # LABEL2 (titlul fisierului)
        # =========================================================
        raw_title = s.get('title', '')
        raw_name = s.get('name', '')
        
        label2 = raw_title if raw_title else raw_name
        label2 = re.sub(r'[đź’ľđź”—đź‡¬đź‡§đź‡şđź‡¸đź‡®đź‡ł]', '', label2)
        label2 = label2.replace('\n', ' ').strip()
        label2 = re.sub(r'\s*\|\s*[A-Za-z0-9]+Hub\s*$', '', label2)
        label2 = re.sub(r'\s*đź”—\s*\w+\s*\(\w+\)\s*$', '', label2)
        
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
    """Sorteaza aplicand noile optiuni din setari, calitate, marime si seederi."""
    import re
    try: sort_opt = int(ADDON.getSetting('source_sorting') or '0')
    except: sort_opt = 0

    def get_sort_key(s):
        quality_field = s.get('quality', '').lower()
        name_lower = s.get('name', '').lower()
        title_lower = s.get('title', '').lower()
        text_combined = f"{name_lower} {title_lower} {quality_field}"
        
        # Scor Calitate â€” quality_field e sursa autoritara
        q_score = 0
        if quality_field == '4k' or quality_field == '2160p' or quality_field == 'uhd':
            q_score = 4
        elif quality_field == '1080p':
            q_score = 3
        elif quality_field == '720p':
            q_score = 2
        elif quality_field in ('480p', '360p', 'sd'):
            q_score = 1
        
        # Fallback: parseaza text doar daca quality_field nu a dat un scor
        if q_score == 0:
            clean_text = text_combined.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
            res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in text_combined)
            if re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_text) and '2160p' not in text_combined:
                res_count += 1
            if res_count >= 2:
                if '2160p' in text_combined or re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_text):
                    q_score = 4
                elif '1080p' in text_combined:
                    q_score = 3
                elif '720p' in text_combined:
                    q_score = 2
                else:
                    q_score = 1
            elif '2160p' in text_combined or re.search(r'(?:^|[\.\-\s_])4k(?:$|[\.\-\s_])', clean_text):
                q_score = 4
            elif '1080p' in text_combined:
                q_score = 3
            elif '720p' in text_combined:
                q_score = 2
            elif '480p' in text_combined or '360p' in text_combined:
                q_score = 1
        
        # Marime MB
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
            m = re.search(r'(?:đź‘¤|đź‘Ą|S:)\s*(\d+)', name_lower + ' ' + title_lower)
            if m: seeders = int(m.group(1))

        # Group Score pt Setari (4 categorii: HTTP / AIO / Stremio / P2P)
        cat = classify_stream_source(s)
        is_cached = isinstance(info_dict, dict) and info_dict.get('is_cached', False)

        tiers = _SORT_TIERS.get(sort_opt)
        if tiers:
            n = len(tiers)
            for ti, tier in enumerate(tiers):
                if _tier_matches(tier, cat, is_cached):
                    g_score = n - 1 - ti
                    # Tier-urile "Original" pastreaza ordinea originala din lista
                    if tier == 'aio_orig':
                        return (g_score, 0, 0.0, 0)
                    return (g_score, q_score, size_mb, seeders)
            return (0, q_score, size_mb, seeders)

        return (0, q_score, size_mb, seeders)

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
    def __init__(self, tmdb_id, content_type, season=None, episode=None, title='', year='', tvshowtitle=''):
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
        self.tvshowtitle = tvshowtitle  # <--- AM ADAUGAT ASTA AICI
        
        self.playback_started = False
        self.user_stopped = False
        self.watched_marked = False
        self.playback_start_time = 0
        self.last_progress_sent = 0
        self.scrobble_threshold = 5.0
        
        # ============================================================
        # Variabile pentru a pastra ULTIMA pozitie cunoscuta
        # (actualizate in fiecare iteratie a monitorului)
        # ============================================================
        self.last_known_position = 0
        self.last_known_total = 0
        
        # Data pentru Rollover Automat
        self.streams = None
        self.start_index = 0
        self.rollover_args = None
        self.rollover_triggered = False
        self.source_type = None

    def onAVStarted(self):
        log("[PLAYER-CLASS] onAVStarted: Stream is playing stable.")
        self.playback_started = True
        self.playback_start_time = time.time()
        
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmc.PlayList(xbmc.PLAYLIST_MUSIC).clear()
        xbmc.executebuiltin('Playlist.Clear')
        
        def close_error_dialogs():
            for _ in range(40):
                xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                xbmc.executebuiltin('Dialog.Close(progressdialog,true)')
                xbmc.executebuiltin('Dialog.Close(busydialog,true)')
                xbmc.executebuiltin('Dialog.Close(busydialognocancel,true)')
                xbmc.sleep(150)
        threading.Thread(target=close_error_dialogs, daemon=True).start()
        
        self._send_trakt_scrobble('start', 0)

    def onPlayBackError(self):
        log("[PLAYER-CLASS] onPlayBackError: Playback failed to start.")
        # Inchidem imediat dialogul de eroare Kodi INAINTE de rollover
        xbmc.executebuiltin('Dialog.Close(okdialog,true)')
        xbmc.executebuiltin('Dialog.Close(yesnodialog,true)')
        xbmc.executebuiltin('Dialog.Close(all,true)')
        self.trigger_rollover()

    def trigger_rollover(self):
        if self.playback_started or self.rollover_triggered: 
            return
        
        if not self.streams or self.rollover_args is None:
            return
        
        self.rollover_triggered = True
        
        source_prov = str(self.streams[self.start_index].get('provider_id', ''))
        is_p2p = source_prov.startswith('p2p_') or self.source_type == 'p2p'
        
        # P2P sources: no rollover, reopen sources window instead
        if is_p2p:
            log("[PLAYER-CLASS] P2P source blocked rollover, reopening sources window")
            xbmc.executebuiltin('Dialog.Close(all,true)')
            self._open_sources_window()
            return
        
        # Determine the current source's group type (same logic as play_with_rollover)
        current_is_aio = source_prov in _AIO_STREMIO_IDS
        current_group = 'aio_stremio' if current_is_aio else 'http'
        
        # Scan forward for next source of the SAME group
        next_idx = -1
        for i in range(self.start_index + 1, len(self.streams)):
            prov = str(self.streams[i].get('provider_id', ''))
            if prov.startswith('p2p_'):
                continue
            s_aio = prov in _AIO_STREMIO_IDS
            s_group = 'aio_stremio' if s_aio else 'http'
            if s_group == current_group:
                next_idx = i
                break
        
        if next_idx >= 0:
            log(f"[PLAYER-CLASS] Auto-Rollover triggered: trying source {next_idx + 1}")
            xbmc.executebuiltin('Dialog.Close(all,true)')
            
            t = threading.Thread(target=play_with_rollover, args=(
                self.streams, next_idx, self.tmdb_id, self.content_type, 
                self.season, self.episode, *self.rollover_args
            ), kwargs={'from_resolve': True})
            t.daemon = True
            t.start()
        else:
            log("[PLAYER-CLASS] Rollover failed: No more sources of the same type.")
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "No source could be played", TMDbmovies_ICON)
            xbmc.executebuiltin('Dialog.Close(all,true)')
    
    def _open_sources_window(self):
        """Reopen the sources window after P2P cancel"""
        global _saved_window_items, _saved_meta_dict, _saved_filtered_streams
        if not _saved_window_items or not _saved_filtered_streams:
            return
        try:
            from resources.lib.results_window import ResultsWindow
            win = ResultsWindow('results.xml', ADDON.getAddonInfo('path'), 'Default', '1080i',
                               results=_saved_window_items, meta=_saved_meta_dict)
            _show_modal_abortable(win)
            selected_data = win.selected
            del win
            
            if selected_data and self.rollover_args:
                import json
                sel_dict = json.loads(selected_data)
                selected_url = sel_dict.get('url')
                for i, s in enumerate(_saved_filtered_streams):
                    if s['url'] == selected_url:
                        self.rollover_triggered = False
                        info_tag, unique_ids, art, properties, resume_time = self.rollover_args
                        t = threading.Thread(target=play_with_rollover, args=(
                            _saved_filtered_streams, i, self.tmdb_id, self.content_type,
                            self.season, self.episode, info_tag, unique_ids, art, properties, resume_time
                        ), kwargs={'from_resolve': True})
                        t.daemon = True
                        t.start()
                        return
        except Exception as e:
            log(f"[PLAYER-CLASS] Error reopening sources window: {e}")

    def onPlayBackStopped(self):
        log(f"[PLAYER-CLASS] onPlayBackStopped called")
        self.user_stopped = True

    def onPlayBackEnded(self):
        log("[PLAYER-CLASS] onPlayBackEnded called")
        self.watched_marked = True
        # Nu facem nimic aici - monitorul se ocupa

    def _send_trakt_scrobble(self, action, progress):
        try:
            dispatch_scrobble(action, self.tmdb_id, self.content_type, self.season, self.episode, progress)
        except: 
            pass


def _silent_scrape_next_episode(player):
    """
    Background worker invizibil. Cauta sezonul/episodul urmator si face 
    scrape la surse fara a deschide nicio fereastra pe ecran.
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
        
        # 1. Cautam episodul urmator logic
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
                                log(f"[AUTO-SCRAPE] Episodul S{next_s:02d}E{next_e:02d} NU e lansat inca. Abort.")
                                return # Ne oprim complet, fereastra YES/NO nu va mai aparea
                        except: pass
                    else:
                        log(f"[AUTO-SCRAPE] Episodul S{next_s:02d}E{next_e:02d} nu are data (TBA). Abort.")
                        return

                    next_title = ep.get('name', f"Episode {next_e}")
                    found = True
                    break
                    
        # Daca nu e in sezonul curent, verificam sezonul urmator, episodul 1
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
                                    log(f"[AUTO-SCRAPE] Sezonul urmator NU e lansat inca. Abort.")
                                    return
                            except: pass
                        else:
                            return

                        next_title = ep.get('name', f"Episode 1")
                        found = True
                        break
                        
        if not found:
            log("[AUTO-SCRAPE] Niciun episod urmator gasit (Final de serial).")
            return
            
        log(f"[AUTO-SCRAPE] UP NEXT: S{next_s:02d}E{next_e:02d} - {next_title}")
        # Salvam info in player ca sa stie dialogul de la final ce sa afiseze
        player.next_ep_info = {
            'season': next_s, 'episode': next_e, 'title': next_title, 
            'show_title': show_title, 'fanart': show_fanart, 'clearlogo': show_logo
        }
        
        # 2. Verificam daca nu a fost deja dat scrape manual inainte
        search_id = f"src_{tmdb_id}_tv_s{next_s}e{next_e}"
        cache_db = MainCache()
        cached_streams, _, _, _, _ = cache_db.get_source_cache(search_id)
        
        if cached_streams:
            log("[AUTO-SCRAPE] Sursele sunt deja in cache. Ne oprim aici.")
            return
            
        # 3. Aflam providerii activi
        active_providers = []
        http_master_enabled = ADDON.getSetting('enable_http_scrapers') == 'true'
        p2p_master_enabled = ADDON.getSetting('enable_p2p_providers') == 'true'
        debrid_ids = ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5']
        p2p_ids = ['p2p_yts', 'p2p_torrentio', 'p2p_comet', 'p2p_mediafusion', 'p2p_filelist', 'p2p_speedapp', 'p2p_seedpool', 'p2p_knaben', 'p2p_thepiratebay', 'p2p_custom1', 'p2p_custom2', 'p2p_custom3', 'p2p_custom4', 'p2p_custom5']
        for pid in ALL_KNOWN_PROVIDERS:
            is_enabled = ADDON.getSetting(f'use_{pid}') == 'true' or (pid == 'aiostreams' and ADDON.getSetting('aiostreams') == 'true')
            if not is_enabled:
                continue
            if pid in debrid_ids:
                active_providers.append(pid)
            elif pid in p2p_ids:
                if p2p_master_enabled:
                    active_providers.append(pid)
            else:
                if http_master_enabled:
                    active_providers.append(pid)

        # Functie fantoma (Mock) pentru a bloca deschiderea dialogului de progres!
        def dummy_progress(percent, text): return True
            
        log("[AUTO-SCRAPE] Incepe Scraping-ul Invizibil in Background...")
        streams, new_error, new_empty, canceled = get_stream_data(
            imdb_id, 'tv', next_s, next_e, 
            progress_callback=dummy_progress, 
            target_providers=active_providers
        )
        
        if streams:
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            try: dur = int(ADDON.getSetting('cache_sources_duration'))
            except: dur = 24
            cache_db.set_source_cache(search_id, streams, new_error, new_empty, active_providers, dur)
            log(f"[AUTO-SCRAPE] Gata! Am stocat {len(streams)} surse pentru vizionare instantanee.")
        else:
            log("[AUTO-SCRAPE] Nicio sursa gasita in background.")
            
    except Exception as e:
        log(f"[AUTO-SCRAPE] Error Fatala: {e}", xbmc.LOGERROR)


class AutoPlayWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.n_info = kwargs.get('n_info', {})
        self.action_result = 0 # 0 = Not Now, 1 = Auto-Play, 2 = Choose Source
        self.timer = 60 # De la cate secunde sa inceapa
        self.is_closed = False

    def onInit(self):
        # Transmitem datele catre XML
        self.setProperty('tmdbmovies.show_title', self.n_info.get('show_title', ''))
        self.setProperty('tmdbmovies.ep_label', f"S{self.n_info.get('season', 1):02d}E{self.n_info.get('episode', 1):02d} - {self.n_info.get('title', '')}")
        self.setProperty('tmdbmovies.fanart', self.n_info.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.n_info.get('clearlogo', ''))
        self.setProperty('tmdbmovies.next_ep_countdown', str(self.timer))
        
        # Start Countdown intr-un thread separat
        threading.Thread(target=self._start_countdown, daemon=True).start()

    def _start_countdown(self):
        while self.timer > 0 and not self.is_closed:
            self.setProperty('tmdbmovies.next_ep_countdown', str(self.timer))
            xbmc.sleep(1000)
            self.timer -= 1
            
        if not self.is_closed and self.timer <= 0:
            # MODIFICAT: Acum rezultatul este 0 (Nu Acum / Inchide), nu 1 (Auto-Play)
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
        if action.getId() in (9, 10, 13, 92, 110): # Apasare pe butonul Back
            self.action_result = 0
            self.close()

    def close(self):
        self.is_closed = True
        super(AutoPlayWindow, self).close()


def start_playback_monitor(player_instance, dialog=None):
    """Monitor thread care verifica periodic si salveaza la oprire."""
    global _player_monitor
    
    if _player_monitor and _player_monitor.is_alive():
        return
    
    def monitor_loop():
        log("[PLAYER-MONITOR] Monitor thread started")
        
        # Asteptam sa porneasca playerul (30 secunde, cu inchidere agresiva a dialogurilor de eroare Kodi)
        # 30s: open-ul poate dura ~20s pe surse lente (Stat intern Kodi); abandonul la 15s
        # declansa rollover in mijlocul deschiderii -> sursa se juca oricum, dar "figuri".
        for attempt in range(120):  # 120 x 250ms = 30 secunde
            if player_instance.isPlaying():
                break
            xbmc.executebuiltin('Dialog.Close(okdialog,true)')
            xbmc.executebuiltin('Dialog.Close(yesnodialog,true)')
            xbmc.sleep(250)
        else:
            log("[PLAYER-MONITOR] Player did not start, exiting monitor")
            if dialog:
                try: dialog.close()
                except: pass
            xbmc.executebuiltin('Dialog.Close(all,true)')
            try: xbmcgui.Window(10000).clearProperty('tmdbmovies.release_name')
            except: pass
            
            if hasattr(player_instance, 'trigger_rollover') and getattr(player_instance, 'source_type', None) != 'p2p':
                player_instance.trigger_rollover()
            elif getattr(player_instance, 'source_type', None) == 'p2p':
                log("[PLAYER-MONITOR] P2P source timeout - not rolling over")
                if hasattr(player_instance, '_open_sources_window'):
                    player_instance._open_sources_window()
            return
        
        log("[PLAYER-MONITOR] Player is playing, monitoring...")
        if dialog:
            try: dialog.close()
            except: pass
        player_instance.playback_start_time = time.time()
        
        # ============================================================
        # SKIP INTRO (stil POV): fereastra mica in dreapta sus la generic
        # ============================================================
        is_episode_playback = (player_instance.content_type in ['tv', 'episode']) and (player_instance.season is not None) and (player_instance.episode is not None)
        if is_episode_playback and ADDON.getSetting('skip_intro.enable') != 'false':
            try:
                from resources.lib.skip_intro import execute_skip_intro
                threading.Thread(target=execute_skip_intro, args=(player_instance,), daemon=True).start()
            except Exception as e:
                log(f"[SKIP-INTRO] Trigger error: {e}", xbmc.LOGWARNING)
        # ============================================================

        if ADDON.getSetting('use_osv3_subs') == 'true':
            from resources.lib.subtitle.subtitles import _playback_imdb as subs_ctx
            if subs_ctx:
                log(f"[PLAYER-MONITOR] scheduling subs for {subs_ctx} in 10s")
                def _delayed_subs():
                    xbmc.sleep(10000)
                    run_wyzie_service(subs_ctx, player_instance.season, player_instance.episode)
                threading.Thread(target=_delayed_subs, daemon=True).start()
        
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
                
                # Scrobble periodic la Trakt si Auto-Scrape
                if total > 0 and curr > 60: # Scadem limita la 60 secunde pentru episoade mai scurte
                    progress = (curr / total) * 100
                    
                    # --- START INVISIBLE AUTO SCRAPE (Declansat la 80% ca sa aiba timp sa caute) ---
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
        
        # Inchidem dialogurile busy ca sa nu mai apara rotita
        xbmc.executebuiltin('Dialog.Close(busydialog,true)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel,true)')
        
        # CURATAM PROPRIETATILE
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
            return
        
        mins = int(last_known_position) // 60
        secs = int(last_known_position) % 60
        log(f"[PLAYER-MONITOR] âś“ Final position: {mins}m {secs}s ({last_known_progress:.2f}%)")
        
        mins = int(last_known_position) // 60
        secs = int(last_known_position) % 60
        log(f"[PLAYER-MONITOR] âś“ Final position: {mins}m {secs}s ({last_known_progress:.2f}%)")
        
        # ============================================================
        # FIX ANTI-DUMMY: STERGEM BIFA PUSA DE KODI DIN GRESEALA
        # ============================================================
        if last_known_total > 0 and last_known_total < 900:
            log(f"[PLAYER-MONITOR] Video scurt detectat ({last_known_total}s). Este un video DUMMY! Anulam marcarea automata Kodi.")
            try:
                import json
                if player_instance.content_type == 'movie':
                    q = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"properties": ["title", "year"], "filter": {"field": "title", "operator": "is", "value": player_instance.title}}, "id": 1}
                    res = json.loads(xbmc.executeJSONRPC(json.dumps(q)))
                    for m in res.get('result', {}).get('movies', []):
                        if str(m.get('year', '')) == str(player_instance.year) or not player_instance.year:
                            xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.SetMovieDetails", "params": {"movieid": m['movieid'], "playcount": 0}, "id": 1}))
                            log(f"[PLAYER-MONITOR] Success: Am sters bifa Kodi pentru filmul {player_instance.title}")
                            break
                else:
                    if player_instance.tvshowtitle:
                        q = {"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": {"properties": ["title"], "filter": {"field": "title", "operator": "is", "value": player_instance.tvshowtitle}}, "id": 1}
                        res = json.loads(xbmc.executeJSONRPC(json.dumps(q)))
                        shows = res.get('result', {}).get('tvshows', [])
                        if shows:
                            tvshowid = shows[0]['tvshowid']
                            q_ep = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": {"tvshowid": tvshowid, "season": player_instance.season, "properties": ["episode"], "filter": {"field": "episode", "operator": "is", "value": str(player_instance.episode)}}, "id": 1}
                            res_ep = json.loads(xbmc.executeJSONRPC(json.dumps(q_ep)))
                            eps = res_ep.get('result', {}).get('episodes', [])
                            if eps:
                                xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails", "params": {"episodeid": eps[0]['episodeid'], "playcount": 0}, "id": 1}))
                                log(f"[PLAYER-MONITOR] Success: Am sters bifa Kodi pentru episodul S{player_instance.season}E{player_instance.episode}")
            except Exception as e:
                log(f"[PLAYER-MONITOR] Delete errora bifei Kodi: {e}")
                
            # Fortam duratele la 0 ca sa fie considerata o vizionare fantoma si stearsa din baza de date locala
            watched_duration = 0
            last_known_position = 0
        # ============================================================

        # SALVARE PROGRES (LOGICA NOUA)
        try:
            from resources.lib import trakt_sync

            if (player_instance.watched_marked or last_known_progress >= 85) and last_known_total >= 900:
                log(f"[PLAYER-MONITOR] Marking as WATCHED ({last_known_progress:.2f}%)")
                dispatch_mark_watched(
                    player_instance.tmdb_id, player_instance.content_type,
                    player_instance.season, player_instance.episode,
                    notify=True, do_refresh=False
                )
                # Stergem punctul de resume
                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    100, player_instance.title, player_instance.year
                )
                player_instance._send_trakt_scrobble('stop', 100)
                
                # BIFAM CA E ELIGIBIL PENTRU RATING LA FINAL
                player_instance.should_prompt_rating = True
                
            elif watched_duration > 180 or last_known_position > 180:  # Salvam progresul daca vizionarea curenta > 3m SAU pozitia in film e deja avansata
                # <<-- MODIFICARE CHEIE: Folosim numarul magic -->>
                # Adaugam 1.000.000 la secunde pentru a le diferentia de procente
                exact_seconds_value = last_known_position + 1000000

                trakt_sync.update_local_playback_progress(
                    player_instance.tmdb_id, player_instance.content_type, 
                    player_instance.season, player_instance.episode, 
                    exact_seconds_value,  # Trimitem numarul magic la DB
                    player_instance.title, player_instance.year
                )
                
                player_instance._send_trakt_scrobble('pause', last_known_progress)
                log(f"[PLAYER-MONITOR] âś“ Resume saved locally (Exact Seconds stored as {exact_seconds_value})")
                
            else:
                # FIX RESUME: Verificam daca exista deja un resume valid (>3min) inainte de a-l sterge
                try:
                    from resources.lib import trakt_sync
                    conn = trakt_sync.get_connection()
                    c = conn.cursor()
                    c.execute("SELECT progress FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", 
                                 (str(player_instance.tmdb_id), player_instance.season or 0, player_instance.episode or 0))
                    row = c.fetchone()
                    
                    old_resume_seconds = 0
                    if row:
                        val = float(row[0])
                        if val >= 1000000:
                            old_resume_seconds = val - 1000000
                        elif val > 0 and val < 100 and last_known_total > 0:
                            old_resume_seconds = (val / 100.0) * last_known_total
                    
                    if old_resume_seconds > 180:
                        # Pastram resume-ul vechi valid - nu-l stergem!
                        log(f"[PLAYER-MONITOR] Watched <3min, dar exista resume vechi valid ({int(old_resume_seconds)}s). Il PASTRAM!")
                        old_pct = (old_resume_seconds / last_known_total * 100) if last_known_total > 0 else 0
                        player_instance._send_trakt_scrobble('pause', old_pct)
                    else:
                        # Nu exista resume valid sau era si el sub 3 min -> stergem tot
                        log(f"[PLAYER-MONITOR] Watched <3min and near start ({int(watched_duration)}s). Deleting ghost session.")
                        player_instance._send_trakt_scrobble('stop', 0)
                        conn.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", 
                                     (str(player_instance.tmdb_id), player_instance.season or 0, player_instance.episode or 0))
                        if player_instance.content_type == 'movie':
                            conn.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(player_instance.tmdb_id),))
                    
                    conn.commit()
                    conn.close()
                except Exception as e:
                    log(f"[PLAYER-MONITOR] Error procesare resume scurt: {e}")
                
        except Exception as e:
            log(f"[PLAYER-MONITOR] Error saving progress: {e}", xbmc.LOGERROR)
        
        # REFRESH CONTAINER
        
        # ==============================================================
        # POST-PLAYBACK: DIALOGURI + REFRESH (in thread separat)
        # ==============================================================
        def _post_playback_dialogs():
            is_ep = (player_instance.content_type in ['tv', 'episode']) and (player_instance.season is not None) and (player_instance.episode is not None)
            prompted_next = False
            
            # AutoPlayWindow (Binge Watching)
            if is_ep and hasattr(player_instance, 'next_ep_info') and player_instance.next_ep_info:
                if ADDON.getSetting('auto_scrape_next_episode') != 'false' and (player_instance.watched_marked or last_known_progress >= 85):
                    n_info = player_instance.next_ep_info
                    xbmc.executebuiltin('Dialog.Close(all,true)')
                    win = AutoPlayWindow('autoplay_dialog.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', n_info=n_info)
                    _show_modal_abortable(win)
                    ret = win.action_result
                    del win
                    log(f"[BINGE-WATCH] Buton apasat: {ret}")
                    if ret == 1 or ret == 2:
                        prompted_next = True
                        url_params = {
                            'mode': 'sources', 'tmdb_id': player_instance.tmdb_id, 'type': 'tv',
                            'season': str(n_info['season']), 'episode': str(n_info['episode']),
                            'title': n_info['title'], 'tv_show_title': n_info['show_title']
                        }
                        if ret == 1:
                            url_params.update({
                                'auto_play_next': 'true',
                                'prev_quality': getattr(player_instance, 'prev_quality', ''),
                                'prev_group': getattr(player_instance, 'prev_group', ''),
                                'prev_is_sdr': 'true' if getattr(player_instance, 'prev_is_sdr', True) else 'false',
                                'prev_debrid': getattr(player_instance, 'prev_debrid', ''),
                                'prev_provider': getattr(player_instance, 'prev_provider', ''),
                                'prev_codec': getattr(player_instance, 'prev_codec', ''),
                                'prev_source': getattr(player_instance, 'prev_source', ''),
                            })
                        import urllib.parse
                        plugin_url = f"{sys.argv[0]}?{urllib.parse.urlencode(url_params)}"
                        if xbmc.Player().isPlaying():
                            xbmc.Player().stop(); xbmc.sleep(500)
                        xbmc.executebuiltin(f"RunPlugin({plugin_url})")
            
            # Rating (provider-aware)
            if getattr(player_instance, 'should_prompt_rating', False) and not prompted_next:
                try:
                    from resources.lib.watched_provider import is_trakt, is_mdblist, is_simkl
                    rate_movies = ADDON.getSetting('trakt_rate_movies') == 'true'
                    rate_eps = ADDON.getSetting('trakt_rate_episodes') == 'true'
                    if (player_instance.content_type == 'movie' and rate_movies) or (is_ep and rate_eps):
                        if is_mdblist():
                            from resources.lib.mdblist_api import prompt_mdblist_rating
                            prompt_mdblist_rating(player_instance.tmdb_id, player_instance.content_type, player_instance.season, player_instance.episode, player_instance.title)
                        elif is_simkl():
                            from resources.lib.simkl_api import prompt_simkl_rating
                            prompt_simkl_rating(player_instance.tmdb_id, player_instance.content_type, player_instance.season, player_instance.episode, player_instance.title)
                        else:
                            from resources.lib import trakt_api
                            trakt_api._prompt_trakt_rating(player_instance.tmdb_id, player_instance.content_type, player_instance.season, player_instance.episode, player_instance.title)
                except Exception as e:
                    log(f"[PLAYER-MONITOR] Error prompting rating: {e}")
            
            # Refresh unic dupa 5s â€” suficient cat fullscreenvideo sa se inchida complet (chiar si Torrentio)
            xbmc.sleep(5000)
            xbmc.executebuiltin('Container.Refresh')
            log("[PLAYER-MONITOR] Container refreshed")
            # Refresh widget-uri de pe Home (UpdateLibrary ca POV): Container.Refresh nu
            # atinge widget-urile din skin (Next Episodes / In Progress). UpdateLibrary
            # emite VideoLibrary.OnUpdate -> toate widget-urile se re-randa in ~5s.
            try:
                from resources.lib.watched_provider import widget_refresh
                widget_refresh()
                log("[PLAYER-MONITOR] Widget refresh triggered (UpdateLibrary)")
            except Exception as e:
                log(f"[PLAYER-MONITOR] Widget refresh error: {e}")
        
        threading.Thread(target=_post_playback_dialogs, daemon=True).start()
        log("[PLAYER-MONITOR] Monitor thread finished")
    
    _player_monitor = threading.Thread(target=monitor_loop, daemon=True)
    _player_monitor.start()


def is_sd_or_720p(stream):
    """Verifica daca sursa este SD sau 720p (sub 1080p)."""
    full_info = (stream.get('name', '') + stream.get('title', '')).lower()
    
    # Eliminam fals-pozitivele pentru verificare 4K pur
    clean_info = full_info.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
    
    # Daca are mai multe rezolutii, e link generic, deci il tratam ca SD/720p
    res_count = sum(1 for r in ['2160p', '1080p', '720p', '480p', '360p'] if r in full_info)
    if '4k' in clean_info and '2160p' not in full_info: res_count += 1
    if res_count >= 2:
        return True
    
    # Daca are 1080p sau 4K pur, NU e SD/720p
    if '1080' in full_info or '2160' in full_info or '4k' in clean_info:
        return False
    
    # Daca are 720p sau rezolutie mai mica
    if '720' in full_info or '480' in full_info or '360' in full_info:
        return True
    
    # Daca nu are nicio rezolutie specificata
    has_quality = any(x in full_info for x in['1080', '720', '480', '360', '2160', '4k'])
    if not has_quality:
        return True  
    
    return False


# =============================================================================
# Formatter for the results window
# =============================================================================
def format_for_results_window(streams, poster_url, meta=None):
    window_results =[]
    
    # Pre-compute override name from meta for custom providers
    _override_name = ''
    if meta:
        _title_name = meta.get('tvshowtitle') or meta.get('title', '')
        _title_season = meta.get('season')
        _title_episode = meta.get('episode')
        if _title_season is not None and _title_episode is not None:
            _override_name = f"{_title_name} S{int(_title_season):02d}E{int(_title_episode):02d}" if _title_name else ''
        else:
            _title_year = str(meta.get('year', ''))
            _override_name = f"{_title_name} ({_title_year})" if _title_name and _title_year else _title_name
    
    for s in streams:
        info_extr = extract_stream_info(s)
        
        raw_name = s.get('title', '')
        if not raw_name or len(raw_name) < 5:
            raw_name = s.get('name', '')
        raw_name = ''.join(c for c in raw_name if ord(c) <= 0xFFFF)
        
        # Override name for custom providers with "Use movie title as name" enabled
        pid = s.get('provider_id', '')
        if pid in ('custom1', 'custom2', 'custom3', 'custom4', 'custom5') and _override_name:
            setting_val = ADDON.getSetting(f'{pid}_use_title')
            if setting_val == 'true':
                raw_name = _override_name
        # --- PROTECTIE STRICTA PENTRU 'info' ---
        original_info = s.get('info')
        stream_info = {}
        
        # Daca este deja dictionar (ex: din AIO Streams), copiem datele.
        # Daca este text (ex: din cache-ul vechi), il salvam izolat ca sa nu mai dea eroare la .get()
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
        
        # Acum folosim get pe stream_info (care e GARANTAT dictionar), evitand AttributeError
        stream_info['debrid_service'] = stream_info.get('debrid_service', '')
        stream_info['is_cached'] = stream_info.get('is_cached', False)
        stream_info['is_cloud'] = stream_info.get('is_cloud', False)
        stream_info['addon'] = stream_info.get('addon', '')
        stream_info['indexer'] = stream_info.get('indexer', '')
        stream_info['seeders'] = stream_info.get('seeders', 0)
        stream_info['releaseGroup'] = stream_info.get('releaseGroup', '')
        
        window_results.append({
            'name': raw_name,
            'url': s.get('url', ''),
            'info': stream_info,
            'raw_stream_data': s 
        })
    return window_results


# =============================================================================
# PLAY WITH ROLLOVER - VERSIUNE FINALA (FARA BUFFERING DUPLICAT)
# =============================================================================
def play_with_rollover(streams, start_index, tmdb_id, c_type, season, episode, info_tag, unique_ids, art, properties, resume_time=0, from_resolve=False, resolve_only=False, native_resume_mode=False):
    
    from resources.lib.resolvers.voe import _DOMAINS as _VOE_DOMAINS
    
    log("[PLAYER] === PLAY_WITH_ROLLOVER START ===")
    
    # ===========================================================================
    # CURATAM WINDOW PROPERTIES LA INCEPUT (FARA URME DE ALTE ADDONURI)
    # ===========================================================================
    win = xbmcgui.Window(10000)
    
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'tmdbmovies.release_name',
        'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
        'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
        'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
        'tmdbmovies.has_ro_sub', 'tmdbmovies.sub_text_label'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[PLAYER] Window Properties curatate la inceput')
    
    # SETAM ID-URILE CORECTE IMEDIAT (inclusiv variantele fara _ID pentru SubStudio)
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
        win.setProperty('TMDb', str(tmdb_id))
    
    final_imdb_id = unique_ids.get('imdb') if unique_ids else None
    if final_imdb_id:
        win.setProperty('imdb_id', str(final_imdb_id))
        win.setProperty('IMDb_ID', str(final_imdb_id))
        win.setProperty('IMDb', str(final_imdb_id))
        
    if season:
        win.setProperty('season', str(season))
    else:
        win.clearProperty('season')
        
    if episode:
        win.setProperty('episode', str(episode))
    else:
        win.clearProperty('episode')
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
    log(f"[PLAYER] Total sources: {total_streams}")
    
    p_title = info_tag.get('title', 'Unknown')
    p_year = info_tag.get('year', '')

    from resources.lib.utils import clean_text
    
    bad_domains =[
        'video-leech.pro', 'video-seed.pro',
    ]
    
    valid_url = None
    valid_index = -1
    p_dialog = None
    p2p_aborted = False

    # Determine initial source type for rollover grouping
    first_stream = streams[start_index]
    first_prov = str(first_stream.get('provider_id', ''))
    if first_prov.startswith('p2p_'):
        initial_type = 'p2p'
    elif first_prov in _AIO_STREMIO_IDS:
        initial_type = 'aio_stremio'
    else:
        initial_type = 'http'
    log(f"[PLAYER] Initial source type: {initial_type} (provider: {first_prov})")

    for i in range(start_index, total_streams):
        try:
            stream = streams[i]
            url = stream.get('url', '')

            is_aio = stream.get('provider_id') in _AIO_STREMIO_IDS
            is_p2p = str(stream.get('provider_id', '')).startswith('p2p_')
            current_type = 'p2p' if is_p2p else ('aio_stremio' if is_aio else 'http')

            # Skip sources that don't match the initial type
            if current_type != initial_type:
                log(f"[PLAYER] Skip source {i+1}: type {current_type} != {initial_type}")
                continue

            if is_p2p:
                try:
                    from resources.lib.torrserver.torrserver_engine import get_torrserver_url
                    item_info = {
                        'Title': info_tag.get('title', 'Torrent Stream'),
                        'Poster': art.get('poster', ''),
                        'Fanart': art.get('fanart', ''),
                        'ClearLogo': art.get('clearlogo', ''),
                        'Season': season,
                        'Episode': episode,
                        'year': info_tag.get('year', ''),
                    }
                    # Build bridge info for progress bar display
                    _raw_n = stream.get('name', 'Unknown')
                    _full_i = (_raw_n + stream.get('title', '')).lower()
                    _clean_i = _full_i.replace('ds4k', '').replace('sdr4k', '').replace('hdr4k', '').replace('4khdhub', '')
                    if '2160' in _clean_i: bridge_quality = '4K'
                    elif '1080' in _clean_i: bridge_quality = '1080p'
                    elif '720' in _clean_i: bridge_quality = '720p'
                    elif '4k' in _clean_i: bridge_quality = '4K'
                    else: bridge_quality = 'SD'
                    _pr = stream.get('provider_id', '').replace('p2p_', '').upper()
                    _inf = stream.get('info', {}) or {}
                    _p1 = [f'[COLOR FFCCCCFF][B]{i+1:02d}[/B][/COLOR]']
                    if _pr:
                        _p1.append(f'[COLOR FFDAA520][B]{_pr}[/B][/COLOR]')
                    _fl = _inf.get('freeleech', 0)
                    if _fl == 1:
                        _p1.append('[COLOR FF00FF00][B]FREE[/B][/COLOR]')
                    _du = _inf.get('doubleup', 0)
                    if _du == 1:
                        _p1.append('[COLOR FFFFFF00][B]2X[/B][/COLOR]')
                    _fmt_m = re.search(r'\.(mkv|mp4|avi|ts|m4v|mov|flv|webm)', _raw_n.lower())
                    if _fmt_m:
                        _p1.append(f'[COLOR FFCCCCFF][B]{_fmt_m.group(1).upper()}[/B][/COLOR]')
                    _idxr = _inf.get('indexer', '')
                    if _idxr:
                        _p1.append(f'[COLOR lightskyblue][B]{_idxr}[/B][/COLOR]')
                    _p2 = []
                    _st = stream.get('size', '')
                    if _st:
                        _p2.append(f'[COLOR lime][B]{_st}[/B][/COLOR]')
                    _rg = _inf.get('releaseGroup', '')
                    if _rg:
                        _p2.append(f'[COLOR FFFF69B4][B]{_rg.upper()}[/B][/COLOR]')
                    _ei = extract_stream_info(stream)
                    for _t in _ei.get('tags', []):
                        _tc = _t.upper()
                        if _tc in ('DV', 'HDR', 'HDR10'):
                            _p2.append(f'[COLOR FFFFCC00]{_t}[/COLOR]')
                        elif _tc == 'ATMOS':
                            _p2.append('[COLOR FFFF4500]Atmos[/COLOR]')
                        elif _tc == 'REMUX':
                            _p2.append('[COLOR FFFF0000]REMUX[/COLOR]')
                        elif _tc == 'HEVC':
                            _p2.append('[COLOR FFFF0000]HEVC[/COLOR]')
                        elif _tc == 'TRUEHD':
                            _p2.append('[COLOR FFFF4500]TrueHD[/COLOR]')
                        elif _tc in ('DTS', 'DTS-HD'):
                            _p2.append(f'[COLOR FF1E90FF]{_t}[/COLOR]')
                        elif _tc == 'MULTI':
                            _p2.append('[COLOR FFFFCC00]Multi[/COLOR]')
                        elif _tc in ('5.1', '7.1'):
                            _p2.append(f'[COLOR FFFAFAD2]{_t}[/COLOR]')
                        elif _tc in ('WEB-DL', 'WEBRIP'):
                            _p2.append(f'[COLOR FF00FA9A]{_t}[/COLOR]')
                        elif _tc == 'BLURAY':
                            _p2.append('[COLOR FF00BFFF]BluRay[/COLOR]')
                        else:
                            _p2.append(f'[COLOR FFDDDDDD]{_t}[/COLOR]')
                    _p2_line = ' | '.join(_p2) if _p2 else ''
                    _dname = clean_text(_raw_n).replace('\n', ' ')
                    _dname = _dname.replace('Sooti', 'Sootio').replace('XDM', 'XDMovies')[:180]
                    _p3 = f'[B][COLOR FFCCCCFF]{_dname.upper()}[/COLOR][/B]'
                    bridge_lines = [' | '.join(_p1)]
                    if _p2_line:
                        bridge_lines.append(_p2_line)
                    bridge_lines.append(_p3)
                    bridge_info = {
                        'lines': bridge_lines,
                        'quality': bridge_quality,
                    }
                    ts_url = get_torrserver_url(url, item_info, bridge_info=bridge_info,
                                                torrent_b64=stream.get('_torrent_b64') or '')
                    if ts_url:
                        log("[PLAYER] P2P resolved via TorrServer: %s" % ts_url[:60])
                        valid_url = ts_url
                        valid_index = i
                        break
                    else:
                        log("[PLAYER] P2P resolution failed, stopping all P2P attempts")
                        p2p_aborted = True
                        break
                except Exception as e:
                    log("[PLAYER] P2P error: %s" % str(e))
                    p2p_aborted = True
                    break

            # AIO/Debrid: skip intermediate code, go straight to playback
            if is_aio or any(x in (url or '').lower() for x in ['real-debrid.com', 'alldebrid', 'premiumize', 'torbox', 'debrid']):
                if is_aio and ADDON.getSetting('aio_verify_links') == 'true':
                    if p_dialog is None:
                        p_dialog = xbmcgui.DialogProgressBG()
                        p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Testing source...")
                    counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
                    display_name = clean_text(stream.get('name', 'Unknown')).replace('\n', ' ')[:50]
                    try: skin_type = ADDON.getSetting('skin_type')
                    except: skin_type = '0'
                    if skin_type == '1':
                        msg = f"{counter_str} [COLOR FFFF69B4]{display_name}[/COLOR]"
                    else:
                        msg = f"Waiting for response from {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR]"
                    p_dialog.update(int(((i - start_index + 1) / max(1, total_streams - start_index)) * 100), message=msg)
                    resolved = _fast_aio_resolve_link(url)
                    if not resolved:
                        log(f"[PLAYER] AIO source {i+1} resolve check failed, trying next")
                        continue
                    url = resolved
                valid_url = url
                valid_index = i
                log(f"[PLAYER] AIO/Debrid source {i+1}: direct play")
                break
            
            if not url: continue
            if not url.startswith(('http://', 'https://', 'file://')): continue
            
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
                if '2160' in clean_info or '4k' in clean_info:
                    qual_txt = "4K"; c_qual = "FFFF00FF"
                elif '1080' in clean_info:
                    qual_txt = "1080p"; c_qual = "FF7CFC00"
                elif '720' in clean_info:
                    qual_txt = "720p"; c_qual = "FFBA55D3"
                else:
                    qual_txt = "SD"; c_qual = "FF1E90FF"
            elif '2160' in clean_info or '4k' in clean_info:
                qual_txt = "4K"; c_qual = "FFFF00FF" 
            elif '1080' in clean_info:
                qual_txt = "1080p"; c_qual = "FF7CFC00" 
            elif '720' in clean_info:
                qual_txt = "720p"; c_qual = "FFBA55D3" 
            elif '480' in clean_info:
                qual_txt = "480p"
            
            # Show progress dialog for ALL sources (AIO/Stremio included)
            if p_dialog is None:
                p_dialog = xbmcgui.DialogProgressBG()
                p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Testing source...")
                
            counter_str = f"[B][COLOR yellow]{i+1}[/COLOR][COLOR gray]/[/COLOR][COLOR FF6AFB92]{total_streams}[/COLOR][/B]"
            try: skin_type = ADDON.getSetting('skin_type')
            except: skin_type = '0'
            if skin_type == '1':
                msg = f"{counter_str} [COLOR FFFF69B4]{display_name}[/COLOR] â€˘[B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            else:
                msg = f"Waiting for response from {counter_str}\n[COLOR FFFF69B4]{display_name}[/COLOR] â€˘[B][COLOR {c_qual}]{qual_txt}[/COLOR][/B]"
            p_dialog.update(int(((i - start_index + 1) / max(1, total_streams - start_index)) * 100), message=msg)

            log(f"[PLAYER] Testing source {i+1}: {provider_id} | {display_name} [{qual_txt}]")

            try:
                base_url = url.split('|')[0]
                check_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                if '|' in url:
                    try: check_headers = dict(urllib.parse.parse_qsl(url.split('|')[1]))
                    except: pass
                
                is_valid = False
                if is_aio or any(x in base_url.lower() for x in['real-debrid.com', 'alldebrid', 'premiumize', 'torbox', 'debrid']):
                    is_valid = True
                    log(f"[PLAYER] Sursa AIO/Debrid detectata -> Bypass verificare.")
                
                # =========================================================
                # RESOLVE VOE
                # =========================================================
                is_voe = any(d in base_url.lower() for d in _VOE_DOMAINS) or 'voe' in base_url.lower()
                
                if is_voe and not is_valid:
                    try:
                        log(f"[PLAYER] Detectat link VOE: {base_url}. Se apeleaza Resolverul...")
                        from resources.lib.resolvers.voe import resolve_voe
                        resolved_url = resolve_voe(base_url)
                        
                        if resolved_url:
                            url = resolved_url
                            base_url = url.split('|')[0]
                            log(f"[PLAYER] VOE Resolved to: {base_url[:60]}...")
                            
                            # Adaugam referer pentru a proteja link-ul .m3u8 (daca nu are deja headere)
                            if '|' not in url:
                                url = f"{url}|Referer=https://voe.sx/"
                                base_url = url.split('|')[0]
                            
                            is_valid = True
                        else:
                            log("[PLAYER] VOE Resolve FAILED. Vom sari peste aceasta sursa.")
                            is_valid = False
                    except Exception as e:
                        log(f"[PLAYER] VOE Resolve error: {e}")
                        is_valid = False
                
                # RESOLVE VSEMBED via ResolveURL (fallback Thrax)
                if provider_id == 'vsembed' and resolveurl:
                    try:
                        log(f"[PLAYER] Incercam ResolveURL pentru VSembed: {base_url[:60]}...")
                        final_link = resolveurl.resolve(url)
                        if final_link:
                            url = final_link
                            base_url = url.split('|')[0]
                            log(f"[PLAYER] ResolveURL succes: {base_url[:60]}...")
                    except Exception as re_err:
                        log(f"[PLAYER] ResolveURL eroare: {re_err}")
                
                # RESOLVE PRIMESRC.ME (Move outside AIO block)
                if provider_id == 'primesrcme' or 'primesrc.me/api/v1/l' in base_url.lower():
                    try:
                        log("[PLAYER] Resolving PrimeSrc.me link...")
                        from resources.lib.scraper import resolve_primesrcme
                        resolved_url = resolve_primesrcme(url, tmdb_id=stream.get('tmdb_id'))
                        if resolved_url:
                            url = resolved_url
                            base_url = url.split('|')[0]
                            log(f"[PLAYER] PrimeSrc Resolved to: {base_url[:60]}...")
                            
                            # Adaugam referer pentru a ajuta rezolvarea/redarea
                            if '|' not in url:
                                url = f"{url}|Referer=https://streamta.site/"
                                base_url = url.split('|')[0]
                            
                            # Daca e un link de tip embed, incercam sa-l rezolvam prin resolveurl
                            if resolveurl:
                                log(f"[PLAYER] Incercam ResolveURL pentru: {url}")
                                try:
                                    final_link = resolveurl.resolve(url)
                                    if final_link:
                                        url = final_link
                                        base_url = url.split('|')[0]
                                        log(f"[PLAYER] ResolveURL succes: {base_url[:60]}...")
                                        
                                        # Suport InputStream Adaptive pentru m3u8 (HLS)

                                except Exception as re_err:
                                    log(f"[PLAYER] ResolveURL eroare: {re_err}")
                            
                            is_valid = True
                        else:
                            log("[PLAYER] PrimeSrc Resolve FAILED")
                            is_valid = False
                    except Exception as e:
                        log(f"[PLAYER] PrimeSrc Resolve error: {e}")
                        is_valid = False
                
                if not is_valid:
                    if is_aio or any(x in base_url.lower() for x in['real-debrid.com', 'alldebrid', 'premiumize', 'torbox', 'debrid']):
                        is_valid = True
                        log(f"[PLAYER] Sursa AIO/Debrid detectata -> Bypass verificare.")
                    else:
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
                    log(f"[PLAYER] âś“ SURSA VALIDA: {i + 1}")
                    break
            except Exception as e:
                log(f"[PLAYER] Error verificare: {e}")
                continue
                
        except Exception as e:
            log(f"[PLAYER] Error sursa {i+1}: {e}", xbmc.LOGERROR)
            continue
    
    if valid_url:
        log(f"[PLAYER] === START PLAYBACK SOURCE {valid_index + 1} ===")
        
        # Android: skip Playlist.Clear (inutil, ca Redlight)
        if not _IS_ANDROID:
            xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
            xbmc.executebuiltin('Playlist.Clear')
        
        global _active_player
        

        # Extragem titlul serialului din info_tag, deoarece final_show_title nu exista in acest scop (scope)
        show_title_extracted = info_tag.get('tvshowtitle', '')
        _active_player = TMDbPlayer(tmdb_id, c_type, season, episode, title=p_title, year=str(p_year), tvshowtitle=show_title_extracted)
        player = _active_player
        # imdb_id pentru Skip Intro (SegmentScraper cere imdb_id)
        player.imdb_id = (unique_ids or {}).get('imdb') or None
        
        # Setam datele pentru Rollover Automat in caz de eroare
        player.streams = streams
        player.start_index = valid_index
        player.rollover_args = (info_tag, unique_ids, art, properties, resume_time)
        player.source_type = initial_type
        
        current_stream = streams[valid_index]

        # ==============================================================
        # FIX EASYNEWS: NO SEEK (Prevenire erori conexiune)
        # ==============================================================
        try:
            if current_stream.get('provider_id') != 'usenet' and ADDON.getSetting('easynews_noseek') != 'false':
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
                    log(f"[PLAYER] EasyNews detectat -> Adaugat seekable=0 la URL pentru a preveni erorile.")
        except: pass
        # ==============================================================
        
        # --- SALVARE METADATE PENTRU NEXT EPISODE ---
        info_extr = extract_stream_info(current_stream)
        player.prev_quality = info_extr.get('quality', '')
        player.prev_group = info_extr.get('group', '').lower() or current_stream.get('info', {}).get('releaseGroup', '').lower()
        player.prev_is_sdr = not any(t in info_extr.get('tags', []) for t in ['HDR', 'HDR10', 'HDR10+', 'DV'])
        
        raw_stream_name = current_stream.get('title', '') + current_stream.get('name', '')
        
        # Salvam Serviciul Debrid (ex: Real-Debrid, EasyNews)
        debrid_srv = current_stream.get('info', {}).get('debrid_service', '').lower()
        if 'easynews' in str(current_stream.get('info', {}).get('addon', '')).lower() or 'easynews' in valid_url.lower():
            debrid_srv = 'easynews'
        player.prev_debrid = debrid_srv
            
        # Salvam Providerul (ex: Torrentio, Sootio)
        prov = info_extr.get('provider', '').lower()
        if current_stream.get('provider_id') == 'aiostreams':
            prov = current_stream.get('info', {}).get('addon', prov).lower()
        player.prev_provider = prov
        
        # Salvam Codecul si Sursa Video
        player.prev_codec = 'HEVC' if 'hevc' in raw_stream_name.lower() or '265' in raw_stream_name.lower() else ('x264' if '264' in raw_stream_name.lower() or 'avc' in raw_stream_name.lower() else '')
        player.prev_source = 'BluRay' if 'bluray' in raw_stream_name.lower() or 'bdrip' in raw_stream_name.lower() else ('WEB' if 'web' in raw_stream_name.lower() else '')
        # --------------------------------------------
        
        # --- LOGARE STREAM DATA (sanitizat) ---
        try:
            _sd = dict(current_stream)
            _su = _sd.get('url', '')
            if 'passkey=' in _su:
                _sd['url'] = re.sub(r'(passkey=)[^&]+', r'\1***', _su)
            # _torrent_b64 = tot .torrentul in base64 (~44KB/sursa) - nu-l loga
            if '_torrent_b64' in _sd:
                _tb = _sd['_torrent_b64']
                _sd['_torrent_b64'] = '<%d chars>' % len(_tb) if isinstance(_tb, str) else '<bytes>'
            xbmc.log(f"[TMDb Movies] đź§˛ STREAM DATA đź§˛:\n{pprint.pformat(_sd, indent=2, width=120)}", xbmc.LOGINFO)
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
        # SKIP KODI HEAD REQUEST (STAT) - Previne lag-ul de 20 secunde la sursele Debrid/AIO
        li.setContentLookup(False)
        
        # Suport InputStream Adaptive pentru m3u8 (HLS)
        if '.m3u8' in valid_url.split('|')[0].lower():
            li.setMimeType("application/vnd.apple.mpegurl")
            li.setProperty('inputstream', 'inputstream.adaptive')
            li.setProperty('inputstream.adaptive.manifest_type', 'hls')
            if '|' in valid_url:
                headers_str = valid_url.split('|', 1)[1]
                li.setProperty('inputstream.adaptive.stream_headers', headers_str)
                li.setProperty('inputstream.adaptive.manifest_headers', headers_str)
        # Custom HTTP headers via Kodi http-header.* properties (Kodi 20+)
        custom_hdrs = current_stream.get('custom_headers')
        if custom_hdrs and isinstance(custom_hdrs, dict):
            for hk, hv in custom_hdrs.items():
                li.setProperty(f'http-header.{hk}', str(hv))
        # NetMirror: adaugam headere CDN pentru tv.imgcdn.kim
        if current_stream.get('provider_id') == 'netmirror':
            li.setProperty('http-header.Referer', 'https://net52.cc/')
            li.setProperty('http-header.ott', 'nf')
            li.setProperty('http-header.x-requested-with', 'NetmirrorNewTV v1.0')
        from resources.lib.tmdb_api import set_metadata
        set_metadata(li, info_tag, unique_ids)
        if art: li.setArt(art)
        for k, v in properties.items(): li.setProperty(k, str(v))
        
        if unique_ids.get('imdb'):
            from resources.lib.subtitle.subtitles import set_playback_context
            set_playback_context(unique_ids["imdb"])
        
        if resolve_only:
            # TMDb Helper: doar resolve prin setResolvedUrl, fara player.play()
            xbmcplugin.setResolvedUrl(_current_handle(), True, li)
            if p_dialog:
                try: p_dialog.close()
                except: pass
                p_dialog = None
        elif native_resume_mode:
            # Dialogul nativ a ales "Resume": PlayFile-ul Kodi asteapta setResolvedUrl si
            # va face singur seek-ul din bookmark (StartOffset sentinel). NU apelam
            # player.play() - ar reporni redarea cu un item fresh (starttime=0) si ar
            # anula seek-ul nativ. Pornim monitorul imediat - el asteapta isPlaying.
            if p_dialog:
                try: p_dialog.close()
                except: pass
                p_dialog = None
            xbmcplugin.setResolvedUrl(_current_handle(), True, li)
            start_playback_monitor(player, dialog=None)
        else:
            # Playback normal: player.play() pe main thread (ca POV) pentru metadate corecte
            # Asta asigura ca VideoPlayer.IMDBNumber e populat corect pentru toate addonurile de srt
            if p_dialog:
                try: p_dialog.close()
                except: pass
                p_dialog = None
            xbmcplugin.setResolvedUrl(_current_handle(), True, li)
            player.play(valid_url, li)
            
            start_playback_monitor(player, dialog=None)
            
            if resume_time > 0:
                log(f"[RESUME] play_with_rollover a primit resume_time={resume_time} - do_resume va rula")
                def do_resume():
                    for _ in range(30):
                        if player.isPlaying(): break
                        xbmc.sleep(500)
                    else:
                        log("[RESUME] do_resume: player-ul nu a pornit in 15s, abandon")
                        return
                    xbmc.sleep(3000)
                    target_pos = float(resume_time)
                    for attempt in range(5):
                        if not player.isPlaying(): return
                        try:
                            current_pos = player.getTime()
                            log(f"[RESUME] attempt {attempt}: current={current_pos}, target={target_pos}")
                            if abs(current_pos - target_pos) < 30:
                                log("[RESUME] deja la pozitia tinta, fara seek")
                                return
                            player.seekTime(target_pos)
                            log("[RESUME] seekTime executat")
                            xbmc.sleep(2000)
                            new_pos = player.getTime()
                            log(f"[RESUME] dupa seek: new_pos={new_pos}")
                            if abs(new_pos - target_pos) < 60: return
                        except Exception as e:
                            log(f"[RESUME] eroare do_resume: {e}")
                        xbmc.sleep(1000)
                threading.Thread(target=do_resume, daemon=True).start()
        
    else:
        if p_dialog:
            p_dialog.close()
            p_dialog = None
        log(f"[PLAYER] FAIL - No valid source din {total_streams}")
        if resolve_only:
            xbmcplugin.setResolvedUrl(_current_handle(), False, xbmcgui.ListItem())
        elif p2p_aborted or initial_type == 'p2p':
            log("[PLAYER] P2P sources failed - reopening sources window immediately")
            global _saved_window_items, _saved_meta_dict, _saved_filtered_streams
            if _saved_window_items and _saved_filtered_streams:
                try:
                    from resources.lib.results_window import ResultsWindow
                    win = ResultsWindow('results.xml', ADDON.getAddonInfo('path'), 'Default', '1080i',
                                       results=_saved_window_items, meta=_saved_meta_dict)
                    _show_modal_abortable(win)
                    selected_data = win.selected
                    del win
                    if selected_data:
                        import json
                        sel_dict = json.loads(selected_data)
                        selected_url = sel_dict.get('url')
                        for i, s in enumerate(_saved_filtered_streams):
                            if s['url'] == selected_url:
                                t = threading.Thread(target=play_with_rollover, args=(
                                    _saved_filtered_streams, i, tmdb_id, c_type, season, episode,
                                    info_tag, unique_ids, art, properties, resume_time
                                ), kwargs={'from_resolve': True})
                                t.daemon = True
                                t.start()
                                return
                except Exception as e:
                    log(f"[PLAYER] Error reopening sources window: {e}")
        elif not p2p_aborted:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "No source could be played", TMDbmovies_ICON)
    
    log("[PLAYER] === PLAYBACK COMMAND SENT ===")

# =============================================================================
# LOGICA AUTO PLAY (Windows/Android)
# =============================================================================
def sort_streams_for_autoplay(streams, profile_idx):
    """
    profile_idx: 0 = Windows 1080p, 1 = Android 4K, 2 = Android 1080p
    """
    log(f"[AUTOPLAY] Processing profile index: {profile_idx}")
    
    # Exclude 4K daca profilul e 1080p (Windows sau Android 1080p)
    if profile_idx == 0 or profile_idx == 2:
        streams = [s for s in streams if '4k' not in s.get('quality', '').lower() and '2160' not in s.get('name', '')]
    
    # 1. Android 4K sau Android 1080p -> Sortare standard (Vix primul > Calitate > Marime)
    if profile_idx == 1 or profile_idx == 2:
        return sort_streams_by_quality(streams)
    
# 2. Windows 1080p -> Logica speciala 
    if profile_idx == 0:
        top_streams = []
        priority_streams = [] # Pixel + CloudR2
        other_streams = []
        
        for s in streams:
            raw_name = s.get('name', '').lower()
            provider_id = s.get('provider_id', '').lower()
            url = s.get('url', '').lower()
            
            is_vaplayer = 'vaplayer' in provider_id or 'vaplayer' in raw_name
            is_fshdnet = 'fshdnet' in provider_id or 'fshd' in raw_name
            is_flixer = 'flixer' in provider_id or 'flixer' in raw_name
            is_cinefreak = 'cinefreak' in provider_id or 'cinefreak' in raw_name
            
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
            if is_fshdnet or is_flixer or is_vaplayer or is_cinefreak:
                top_streams.append(s)
            elif is_good_windows:
                priority_streams.append(s)
            else:
                other_streams.append(s)
        
        # Sortam standard pe calitate/marime
        top_streams = sort_streams_by_quality(top_streams)
        priority_streams = sort_streams_by_quality(priority_streams)
        other_streams = sort_streams_by_quality(other_streams)
        
        # Sorteaza top_streams: FSHDnet (5) > Flixer (4) > VAPlayer (3) > CineFreak (2)
        def get_top_score(stream):
            p_id = stream.get('provider_id', '').lower()
            n_m = stream.get('name', '').lower()
            if 'fshdnet' in p_id or 'fshd' in n_m: return 5
            if 'flixer' in p_id or 'flixer' in n_m: return 4
            if 'vaplayer' in p_id or 'vaplayer' in n_m: return 3
            if 'cinefreak' in p_id or 'cinefreak' in n_m: return 2
            return 0
            
        top_streams.sort(key=get_top_score, reverse=True)
        
        final_list = top_streams + priority_streams + other_streams
        log(f"[AUTOPLAY] Windows Logic: {len(top_streams)} Top (FSHDnet>Flixer>VAPlayer>CineFreak), {len(priority_streams)} Pixel/Cloud")
        return final_list


def find_best_stream_index(streams, prev_quality, prev_group, prev_is_sdr, prev_debrid='', prev_provider='', prev_codec='', prev_source=''):
    """Gaseste cel mai bun stream pentru Auto-Play bazat pe istoricul detaliat."""
    best_idx = -1
    best_score = -1
    
    qual_scores = {'4K': 40, '1080p': 30, '720p': 20, '480p': 10, 'SD': 10}
    prev_q_val = qual_scores.get(prev_quality, 0)
    
    log(f"[BINGE-WATCH] Cautam: Qual={prev_quality}, Group={prev_group}, Debrid={prev_debrid}, Provider={prev_provider}, Codec={prev_codec}, Source={prev_source}")
    
    for i, s in enumerate(streams):
        info = extract_stream_info(s)
        s_qual = info.get('quality', '')
        s_q_val = qual_scores.get(s_qual, 0)
        s_group = info.get('group', '').lower() or s.get('info', {}).get('releaseGroup', '').lower()
        s_tags = info.get('tags', [])
        
        # Extrageri Suplimentare pentru Noul Sistem de Scor
        raw_name = s.get('title', '') + s.get('name', '')
        s_debrid = s.get('info', {}).get('debrid_service', '').lower()
        if 'easynews' in str(s.get('info', {}).get('addon', '')).lower() or 'easynews' in s.get('url', '').lower():
            s_debrid = 'easynews'
            
        s_provider = info.get('provider', '').lower()
        if s.get('provider_id') == 'aiostreams':
            s_provider = s.get('info', {}).get('addon', s_provider).lower()
            
        s_codec = 'HEVC' if 'hevc' in raw_name.lower() or '265' in raw_name.lower() else ('x264' if '264' in raw_name.lower() or 'avc' in raw_name.lower() else '')
        s_source = 'BluRay' if 'bluray' in raw_name.lower() or 'bdrip' in raw_name.lower() else ('WEB' if 'web' in raw_name.lower() else '')
        
        s_has_hdr = any(t in s_tags for t in ['HDR', 'HDR10', 'HDR10+', 'DV'])
        s_is_sdr = not s_has_hdr
        
        s_is_cached = s.get('info', {}).get('is_cached', False)
        if s.get('provider_id') not in ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5']:
            s_is_cached = True
            
        # ===============================================================
        # EXCEPTIE USENET / EASYNEWS: Acestea sunt servere cu redare
        # directa, deci le consideram mereu CACHED ca sa nu piarda
        # intentionat in fata torrentelor debrid!
        # ===============================================================
        if 'usenet' in s_provider or 'easynews' in s_provider or 'usenet' in s_debrid:
            s_is_cached = True
            
        score = 0
        
        # 1. PROTECTIE SDR / HDR
        if prev_is_sdr:
            if not s_is_sdr: continue 
        else:
            # FIX: Am crescut de la 500 la 5000 pentru a forta pastrarea HDR-ului!
            if not s_is_sdr: score += 5000 
                
        # 2. CACHED (Pastram 10.000 ca sa protejam torrentele necached de la buffering)
        if s_is_cached: score += 10000
            
        # 3. REZOLUTIE
        if s_qual == prev_quality: score += 5000
        elif s_q_val <= prev_q_val: score += 2000 + s_q_val
        else: score += s_q_val
            
        # 4. POTRIVIRI DETALIATE (Am marit bonusul pentru Provider la 4000)
        if prev_debrid and prev_debrid == s_debrid: score += 3000
        if prev_provider and prev_provider == s_provider: score += 4000
        if prev_group and s_group and prev_group == s_group: score += 1500
        if prev_codec and prev_codec == s_codec: score += 1000
        if prev_source and prev_source == s_source: score += 500
            
        if score > best_score:
            best_score = score
            best_idx = i
            
    # FALLBACK GARANTAT
    if best_idx == -1 and len(streams) > 0:
        log("[BINGE-WATCH] Nu s-a gasit match exact. Fallback la prima sursa valida.")
        for i, s in enumerate(streams):
            if s.get('info', {}).get('is_cached', False) and '1080p' in extract_stream_info(s).get('quality', ''):
                return i
        return 0
        
    return best_idx


# =============================================================================
# LIST SOURCES - VERSIUNE CORECTATA PENTRU RESULTS WINDOW (Fara fallback)
# =============================================================================
_SCRAPE_LOCK_TIMEOUT = 10  # seconds before stale lock auto-clears

def _scrape_lock_acquire():
    """Prevent multiple simultaneous scraping sessions."""
    try:
        import time as _t
        win = xbmcgui.Window(10000)
        lock_val = win.getProperty('tmdbmovies_scrape_busy')
        if lock_val:
            try:
                start_time = float(lock_val)
                if _t.time() - start_time < _SCRAPE_LOCK_TIMEOUT:
                    xbmcgui.Dialog().notification(
                        '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
                        '[B][COLOR FFFDBD01]A search is already in progress![/COLOR][/B]',
                        ADDON.getAddonInfo('icon'), 3000, False
                    )
                    return False
            except:
                pass
        win.setProperty('tmdbmovies_scrape_busy', str(_t.time()))
        return True
    except:
        return True

def _scrape_lock_release():
    try:
        xbmcgui.Window(10000).clearProperty('tmdbmovies_scrape_busy')
    except:
        pass

def _scrape_locked(func):
    """Decorator: acquire lock before, release after (even on exception)."""
    import functools
    @functools.wraps(func)
    def wrapper(params):
        if not _scrape_lock_acquire():
            return
        try:
            return func(params)
        finally:
            _scrape_lock_release()
    return wrapper

def _show_modal_abortable(dialog):
    """doModal() care se inchide automat la shutdown Kodi."""
    mon = xbmc.Monitor()
    def _watch():
        while not mon.abortRequested():
            time.sleep(0.5)
        try: dialog.close()
        except: pass
    threading.Thread(target=_watch, daemon=True).start()
    dialog.doModal()

class ScanProgressDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.is_canceled = False
    def onInit(self):
        pass
    def update(self, content, percent):
        try: self.getControl(2000).setText(content)
        except: pass
        try: self.getControl(5000).setPercent(percent)
        except: pass
    def onAction(self, action):
        if action in (xbmcgui.ACTION_PARENT_DIR, xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_STOP, xbmcgui.ACTION_NAV_BACK):
            self.is_canceled = True
            self.close()

@_scrape_locked
def list_sources(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title')
    year = params.get('year')
    season = params.get('season')
    episode = params.get('episode')
    override_title = params.get('custom_title') or None
    override_year = params.get('custom_year') or None
    resolve_only = params.get('resolve_only') == 'true'
    
    # Daca e mod interactiv, cerem valorile acum
    if params.get('custom_interactive') == 'true':
        current_title = title
        override_title = xbmcgui.Dialog().input("Enter custom title", defaultt=current_title)
        if not override_title: return
        if c_type == 'movie':
            custom_year = xbmcgui.Dialog().input("Enter custom year (optional)", defaultt=str(year))
            if custom_year: override_year = custom_year
        else:
            custom_season = xbmcgui.Dialog().input("Season", defaultt=str(season))
            custom_episode = xbmcgui.Dialog().input("Episode", defaultt=str(episode))
            if not custom_season or not custom_episode: return
            season = custom_season
            episode = custom_episode
    
    # Daca avem custom title, cautam TMDB ID-ul corect
    if override_title:
        try:
            from resources.lib.utils import get_json
            search_type = 'movie' if c_type == 'movie' else 'tv'
            search_url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&query={urllib.parse.quote(override_title)}"
            if override_year and search_type == 'movie':
                search_url += f"&primary_release_year={override_year}"
            search_data = get_json(search_url)
            if search_data and search_data.get('results'):
                found = search_data['results'][0]
                new_tmdb = str(found['id'])
                log(f"[CUSTOM-SRC] TMDB search found: {found.get('title') or found.get('name')} (ID: {new_tmdb})")
                # Folosim noul tmdb_id in locul celui original
                tmdb_id = new_tmdb
                # Actualizam si titlul/anul cu datele corecte din TMDB
                title_override = found.get('title') or found.get('name') or override_title
                dt = found.get('release_date') or found.get('first_air_date') or ''
                year_override = dt[:4] if dt else (override_year or '')
                # Daca nu s-a specificat override_year explicit, il luam din TMDB
                if not override_year:
                    override_year = year_override
        except:
            log("[CUSTOM-SRC] TMDB search failed, using original IDs")
    
    # CURATAM WINDOW PROPERTIES LA INCEPUT
    win = xbmcgui.Window(10000)
    props_to_clear = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
        'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
        'tmdbmovies.release_name',
        'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
        'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
        'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
        'tmdbmovies.has_ro_sub', 'tmdbmovies.sub_text_label'
    ]
    for prop in props_to_clear:
        win.clearProperty(prop)
    
    log('[LIST-SOURCES] Window Properties curatate la inceput')
    
    if tmdb_id:
        win.setProperty('tmdb_id', str(tmdb_id))
        win.setProperty('TMDb_ID', str(tmdb_id))
    
    ids = {}
    
    # CALCULARE POZITIE RESUME
    # Decizia de resume se face DIN SEMNALELE KODI, nu din skin:
    #   - argv[3]='resume:true'  -> dialogul NATIV a aparut (fereastra video) si
    #     userul a ales "Resume from X". Kodi face singur seek-ul din bookmark
    #     (StartOffset sentinel -> PlayFile -> options.starttime). Nu intervenim.
    #   - argv[3]='resume:false' + fereastra video (win id != 10000) + bookmark
    #     exista in MyVideos*.db -> dialogul nativ a aparut si a fost deja
    #     raspuns cu "Play from beginning". Play 0, fara dialogul nostru.
    #   - Altfel (RunPlugin binge argv[1]=='-1', click din Home-widget fereastra
    #     10000 = PlayMedia builtin cu item fresh = nativ IMPOSIBIL, sau fereastra
    #     video FARA bookmark = click pe item nerezumabil din lista: argv='resume:false'
    #     e doar flag-ul implicit al invocarii, dialogul nativ NU a aparut)
    #     -> dialogul nostru, pe baza bazei locale de progres (autoritara).
    # NOTA: bookmark-ul din MyVideos (scris la stop de SaveFileStateJob, keyed by
    # plugin URL) e singura dovada ca dialogul nativ chiar a rulat pe click:
    # cu bookmark existent, GetResumeBookMark(path) reusesc -> item-ul e resumable ->
    # nativ a afisat. Fara bookmark, argv='resume:false' NU inseamna "nativ a raspuns",
    # ci doar invocare standard a plugin-ului (vezi cazul filmelor din Trending Today,
    # unde DialogContextMenu.xml NU se incarca niciodata la click pe movie nerezumabil).
    resume_time = 0
    native_resume_mode = False
    try: resume_from_url = int(params.get('resume_time', 0))
    except: resume_from_url = 0

    resume_argv = sys.argv[3] if len(sys.argv) > 3 else ''
    invoke_handle = sys.argv[1] if len(sys.argv) > 1 else ''
    is_runplugin = (invoke_handle == '-1')

    if resolve_only:
        # TMDb Helper JSON player: skip resume calculation, just resolve
        pass
    elif resume_argv == 'resume:true':
        # Dialogul nativ a aparut si userul a ales "Resume from X". Kodi face singur
        # seek-ul din bookmark (StartOffset sentinel -> PlayFile -> options.starttime).
        # Nu intrebam noi si NU facem player.play() (ar reseta sentinel-ul).
        native_resume_mode = True
        log("[RESUME] resume:true -> dialog nativ a ales Resume, Kodi face seek din bookmark")
    elif (resume_argv == 'resume:false' and _current_win_id() == 10000):
        # Home-widget (win id 10000): click pe item de widget = CDirectoryProvider::OnClick
        # -> ChoosePlayOrResume -> dialogul NATIV a aparut (item-ul de widget pastreaza
        # resume point pe VideoInfoTag). resume:false = userul a ales "Play from beginning"
        # -> play 0, fara dialogul nostru (altfel apar 2 dialoguri).
        # NOTA: bookmark-ul din MyVideos NU e folosit ca semnal aici â€” el e scris de
        # SaveFileStateJob la ORICE stop anterior (persistent), deci existenta lui nu
        # dovedeste ca dialogul nativ a rulat pe click-ul curent (vezi In Progress Episodes,
        # unde argv='resume:false' e doar flag-ul implicit al listelor de plugin).
        native_resume_mode = False
        resume_time = 0
        log("[RESUME] resume:false + Home-widget (win=10000) -> nativ a ales 'Play from beginning', fara dialogul nostru")
    else:
        # Dialogul nostru in TOATE cazurile ramase: RunPlugin (binge, argv[1]=='-1'),
        # click din Home-widget (fereastra 10000, PlayMedia builtin = nativ imposibil),
        # sau fereastra video FARA bookmark (crash la stop pe AF3 / progres de pe alt
        # dispozitiv -> bookmark lipsa, dar progres exista local). Baza locala e sursa
        # autoritara si proaspata; valoarea din URL (pusa de builderele de liste) e
        # doar fallback.
        progress_value = trakt_sync.get_local_playback_progress(tmdb_id, c_type, season, episode)
        log(f"[RESUME] progress_value: {progress_value}, tmdb_id: {tmdb_id}, c_type: {c_type}")
        
        if progress_value > 0 and progress_value < 90:
            duration_secs = 0
            try:
                if c_type == 'movie':
                    url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language=en-US"
                    data = get_json(url)
                    runtime = data.get('runtime') if data else 0
                    if runtime: duration_secs = int(runtime) * 60
                else:
                    url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language=en-US"
                    data = get_json(url)
                    if data:
                        runtimes = data.get('episode_run_time', [])
                        if runtimes and runtimes[0]: duration_secs = int(runtimes[0]) * 60
                        else: duration_secs = 2700
            except: pass
            if duration_secs <= 0: duration_secs = 7200
            resume_time = int((progress_value / 100.0) * duration_secs)
        elif progress_value >= 1000000:
            resume_time = int(progress_value - 1000000)
        elif resume_from_url > 0:
            # Fallback: valoarea din URL (bazele locale golite, cache stale)
            resume_time = resume_from_url

        # Meniu resume la click pe titlu (toate skin-urile, inclusiv AF3)
        if resume_time > 180:
            m, s = divmod(resume_time, 60)
            h, m = divmod(m, 60)
            time_str = f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
            
            choice = xbmcgui.Dialog().contextmenu([f"Resume from {time_str}", "Play from beginning"])
            log(f"[RESUME] contextmenu choice: {choice} (0=Resume, 1=Play from beginning, -1=cancel)")
            if choice == 1: resume_time = 0
            elif choice == -1:
                try: xbmcplugin.setResolvedUrl(_current_handle(), False, xbmcgui.ListItem())
                except: pass
                return
        elif resume_time > 0:
            resume_time = 0

    # CAUTARE / CACHE
    active_providers =[]
    http_master_enabled = ADDON.getSetting('enable_http_scrapers') == 'true'
    p2p_master_enabled = ADDON.getSetting('enable_p2p_providers') == 'true'
    debrid_ids = ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5']
    p2p_ids = ['p2p_yts', 'p2p_torrentio', 'p2p_comet', 'p2p_mediafusion', 'p2p_filelist', 'p2p_speedapp', 'p2p_seedpool', 'p2p_knaben', 'p2p_thepiratebay', 'p2p_custom1', 'p2p_custom2', 'p2p_custom3', 'p2p_custom4', 'p2p_custom5']
    for pid in ALL_KNOWN_PROVIDERS:
        is_enabled = ADDON.getSetting(f'use_{pid}') == 'true' or (pid == 'aiostreams' and ADDON.getSetting('aiostreams') == 'true')
        if not is_enabled:
            continue
        if pid in debrid_ids:
            active_providers.append(pid)
        elif pid in p2p_ids:
            if p2p_master_enabled:
                active_providers.append(pid)
        else:
            if http_master_enabled:
                active_providers.append(pid)

    use_cache = ADDON.getSetting('use_cache_sources') == 'true'
    try: cache_duration = int(ADDON.getSetting('cache_sources_duration'))
    except: cache_duration = 24
    try: cur_sort_opt = int(ADDON.getSetting('source_sorting') or '0')
    except: cur_sort_opt = 0
    
    # Dezactivam cache-ul daca folosim valori custom
    if override_title or override_year:
        use_cache = False
    
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
    
    cache_db = MainCache()
    cached_streams, error_providers_history, empty_providers_history, scanned_providers_history, cached_sort_opt = None, [], [], [], None
    
    if use_cache:
        cached_streams, error_providers_history, empty_providers_history, scanned_providers_history, cached_sort_opt = cache_db.get_source_cache(search_id)

    if scanned_providers_history is None: scanned_providers_history = []
    if error_providers_history is None: error_providers_history = []
    if empty_providers_history is None: empty_providers_history = []

    streams = []
    providers_to_scan = [] 
    
    if cached_streams is not None:
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                s_pid = get_fallback_provider_id(s.get('name', ''))
            
            if s_pid and s_pid not in active_providers:
                continue 
            valid_cached_streams.append(s)
        
        streams = valid_cached_streams
        retry_list = [p for p in error_providers_history if p in active_providers]
        missing_list = [p for p in active_providers if p not in scanned_providers_history and p not in error_providers_history and p not in empty_providers_history]
        providers_to_scan = list(set(retry_list + missing_list))
        # Reincercam providerii goi DOAR daca nu avem deloc surse in cache
        if not streams:
            empty_retry = [p for p in empty_providers_history if p in active_providers]
            providers_to_scan = list(set(providers_to_scan + empty_retry))
        
        # FIX BINGE WATCHING: Daca suntem in auto-play next si avem deja surse in cache, ignoram re-scanarea pentru a porni instant
        if params.get('auto_play_next') == 'true' and streams:
            providers_to_scan = []
            log("[BINGE-WATCH] Surse gasite in cache. Ignoram providerii esuati pentru a porni episodul instantaneu.")


    if cached_streams is None or providers_to_scan:
        ids = get_external_ids(c_type, tmdb_id)
        imdb_id = ids.get('imdb_id')
        if not imdb_id: imdb_id = f"tmdb:{tmdb_id}"

        # Pornim OS checker devreme, in paralel cu scrapingul
        try:
            from resources.lib.subtitle import check_ro_subs_bg
            check_ro_subs_bg(imdb_id=imdb_id, tmdb_id=tmdb_id, season=season, episode=episode)
        except: pass

        target_list = providers_to_scan if cached_streams is not None else None
        final_target = [p for p in target_list if p in active_providers] if target_list else active_providers

        # Fetch artwork for the dialog (devreme, ca Kodi sa aiba timp sa pre-cache-uiasca imaginile)
        fanart_url = None
        poster_url = None
        clearlogo_url = None
        try:
            from resources.lib.tmdb_api import get_tmdb_item_details
            det = get_tmdb_item_details(str(tmdb_id), c_type)
            if det:
                if det.get('backdrop_path'):
                    fanart_url = f"https://image.tmdb.org/t/p/w1280{det['backdrop_path']}"
                    win.setProperty('tmdbmovies.fanart', fanart_url)
                if det.get('poster_path'):
                    poster_url = f"https://image.tmdb.org/t/p/w500{det['poster_path']}"
                    win.setProperty('tmdbmovies.poster', poster_url)
                if det.get('clearlogo'):
                    clearlogo_url = f"https://image.tmdb.org/t/p/w500{det['clearlogo']}"
                    win.setProperty('tmdbmovies.clearlogo', clearlogo_url)
        except: pass
        # Preload imagini in cache-ul de texturi Kodi (ca dialogul sa le afiseze instant)
        try:
            for img in [fanart_url, poster_url, clearlogo_url]:
                if img:
                    li = xbmcgui.ListItem(path=img, offscreen=True)
                    li.setArt({'fanart': img, 'thumb': img})
        except: pass
        win.setProperty('tmdbmovies.scanning_mode', 'true')
        dialog = ScanProgressDialog('resolver_window.xml', ADDON.getAddonInfo('path'), 'Default', '1080i')
        scan_canceled = threading.Event()
        scan_done = threading.Event()
        scan_result = {}
        _mon = xbmc.Monitor()

        def update_progress(percent, status_data):
            if scan_canceled.is_set() or _mon.abortRequested():
                return False
            try:
                cats = status_data.get('categories')
                if cats:
                    alive = status_data.get('alive', [])
                    def fmt_row(name, color, d, lbl_bold=False, lbl_color="FFB7B4BB"):
                        total = d.get('total', 0)
                        lb = f"[B][COLOR {lbl_color}]" if lbl_bold else f"[COLOR {lbl_color}]"
                        le = "[/COLOR][/B]" if lbl_bold else "[/COLOR]"
                        return (f"[COLOR {color}][B]{name}:[/B][/COLOR] "
                                f"{lb}4K:{le} [B][COLOR {color}]{d.get('4K',0)}[/COLOR][/B] | "
                                f"{lb}1080p:{le} [B][COLOR {color}]{d.get('1080p',0)}[/COLOR][/B] | "
                                f"{lb}720p:{le} [B][COLOR {color}]{d.get('720p',0)}[/COLOR][/B] | "
                                f"{lb}SD:{le} [B][COLOR {color}]{d.get('SD',0)}[/COLOR][/B] | "
                                f"{lb}Total:{le} [B][COLOR {color}]{total}[/COLOR][/B]")
                    rows = []
                    for label, color, key in [("AIO", "FFFF00FF", "aio"), ("HTTP", "FF7CFC00", "http"), ("P2P", "FFF4A460", "p2p")]:
                        d = cats.get(key)
                        if d:
                            rows.append(fmt_row(label, color, d, lbl_bold=True, lbl_color="FFCCCCFF"))
                    if alive:
                        formatted = [f"[B][COLOR FFFF69B4]{alive[0].upper()}[/COLOR][/B]"]
                        for n in alive[1:4]:
                            formatted.append(f"[B][COLOR FFCCCCFF]{n.upper()}[/COLOR][/B]")
                        if len(alive) > 5:
                            formatted.append(f"[B][COLOR gray](+{len(alive)-5})[/COLOR][/B]")
                        rows.append(f"[B][COLOR FFCCCCFF]Scanning:[/COLOR][/B] " + ", ".join(formatted))
                    else:
                        rows.append("[B][COLOR lime]Finalizing...[/COLOR][/B]")
                    dialog.update("[CR]".join(rows), status_data.get('percent', percent))
                else:
                    dialog.update(status_data.get('estuary', str(status_data)), percent)
            except Exception as e:
                log(f"[SCAN] Progress error: {e}")
            return True

        def _run_scan():
            if _mon.abortRequested():
                scan_result['data'] = ([], [], [], True)
                scan_done.set()
                return
            try:
                result = get_stream_data(
                    imdb_id, c_type, season, episode, 
                    progress_callback=update_progress,
                    target_providers=final_target,
                    override_title=override_title,
                    override_year=override_year
                )
                scan_result['data'] = result
            except Exception as e:
                log(f"[SCAN] Thread error: {e}")
                scan_result['data'] = ([], [], [], True)
            finally:
                scan_done.set()

        scan_thread = threading.Thread(target=_run_scan, daemon=True)
        scan_thread.start()

        # Ruleaza doModal in thread separat (ca POV) â€” dialogul ramane deschis
        # pana cand ResultsWindow e gata, eliminand gap-ul vizual
        _dialog_thread = threading.Thread(target=dialog.doModal, daemon=True)
        _dialog_thread.start()

        time.sleep(0.2)

        # Asteapta scanare terminata SAU user apasa BACK
        while not scan_done.is_set() and not _mon.abortRequested():
            if dialog.is_canceled:
                scan_canceled.set()
                break
            xbmc.sleep(100)

        if scan_canceled.is_set():
            try: dialog.close()
            except: pass
            for _ in range(50):
                if scan_done.is_set() or _mon.abortRequested():
                    break
                xbmc.sleep(100)

        for _ in range(10):
            if not scan_thread.is_alive() or _mon.abortRequested():
                break
            time.sleep(0.5)

        result = scan_result.get('data', ([], [], [], True))
        new_streams, new_error, new_empty, was_canceled = result
        if scan_canceled.is_set():
            was_canceled = True
        
        if was_canceled:
            log("[LIST-SOURCES] User cancelled scanning. Aborting without saving cache.")
            try: xbmcplugin.setResolvedUrl(_current_handle(), False, xbmcgui.ListItem())
            except: pass
            return
        
        new_failed = new_error + new_empty
        final_scanned = [p for p in scanned_providers_history if p in active_providers]
        providers_attempted_now = target_list if target_list else active_providers
        for p in providers_attempted_now:
            if p not in new_failed and p not in final_scanned:
                # Only mark as scanned if it actually produced streams.
                # Providers silently skipped (master switch off) are NOT added,
                # so they will be re-scanned when the master switch is enabled.
                p_has_streams = any(
                    s.get('provider_id') == p or s.get('raw_stream_data', {}).get('provider_id') == p
                    for s in new_streams
                )
                if p_has_streams:
                    final_scanned.append(p)
        
        # Erori consecutive: daca un provider era deja in istoric si a dat iar eroare,
        # il trecem la "empty" (nu se mai retry, e mort)
        for p in list(new_error):
            if p in error_providers_history:
                new_error.remove(p)
                if p not in new_empty:
                    new_empty.append(p)
                
        final_error = new_error
        final_empty = new_empty

        if cached_streams is not None:
            streams.extend(new_streams)
        else:
            streams = new_streams
            
        if streams or final_scanned:
            streams = deduplicate_streams(streams)
            streams = sort_streams_by_quality(streams)
            if use_cache:
                cache_db.set_source_cache(search_id, streams, final_error, final_empty, final_scanned, cache_duration, cur_sort_opt)
            # lista e deja sortata cu optiunea curenta â€” display-ul nu mai re-sorteaza
            cached_sort_opt = cur_sort_opt

    if not streams:
        try: dialog.close()
        except: pass
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "No sources found", TMDbmovies_ICON)
        try: xbmcplugin.setResolvedUrl(_current_handle(), False, xbmcgui.ListItem())
        except: pass
        return

    # FILTRARE PENTRU AFISARE
    # Sortare doar daca optiunea s-a schimbat fata de cea salvata in cache
    # (cache-ul stocheaza lista deja sortata cu optiunea respectiva):
    # cu setarea neschimbata -> afisare instant, fara re-sort; cu setare noua -> re-sort instant
    all_streams_count = len(streams)
    try: cur_sort_opt = int(ADDON.getSetting('source_sorting') or '0')
    except: cur_sort_opt = 0
    if cached_sort_opt is None or cached_sort_opt != cur_sort_opt:
        streams = sort_streams_by_quality(streams)
    filtered_streams, quality_stats = filter_streams_for_display(streams)
    
    if not filtered_streams:
        try: dialog.close()
        except: pass
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", f"All {all_streams_count} sources filtered!", TMDbmovies_ICON, 3000)
        try: xbmcplugin.setResolvedUrl(_current_handle(), False, xbmcgui.ListItem())
        except: pass
        return
    
    # Prepare metadata for results window
    # SINGLE call (RAM cache, instant) â€” replaces get_poster_url (1-2 calls) + get_english_metadata (2-3 calls) + get_external_ids (1 call)
    from resources.lib.tmdb_api import get_tmdb_item_details
    details = get_tmdb_item_details(str(tmdb_id), c_type)
    
    poster_url = "DefaultVideo.png"
    eng_title = ""
    eng_tvshowtitle = ""
    extra_imdb_id = ""
    tv_show_parent_imdb_id = ""
    
    if details:
        if details.get('poster_path'):
            poster_url = f"https://image.tmdb.org/t/p/w500{details['poster_path']}"
        eng_title = details.get('title', '') if c_type == 'movie' else ''
        eng_tvshowtitle = details.get('name', '') if c_type in ('tv', 'episode') else ''
        ext_ids = details.get('external_ids', {}) or {}
        extra_imdb_id = ext_ids.get('imdb_id', '') or details.get('imdb_id', '') or ''
        tv_show_parent_imdb_id = extra_imdb_id

    if c_type == 'tv':
        final_imdb_id = tv_show_parent_imdb_id or (ids.get('imdb_id', '') if ids else '')
    else:
        final_imdb_id = extra_imdb_id or (ids.get('imdb_id', '') if ids else '')
        
    if final_imdb_id and not str(final_imdb_id).startswith('tt'):
        final_imdb_id = ''

    if final_imdb_id:
        win.setProperty('imdb_id', str(final_imdb_id))
        win.setProperty('IMDb_ID', str(final_imdb_id))
        win.setProperty('IMDb', str(final_imdb_id))
        log(f'[LIST-SOURCES] Window Property imdb_id/IMDb setat devreme: {final_imdb_id}')

    if override_title:
        final_title = override_title
        final_show_title = override_title
    else:
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
                meta_dict['fanart'] = f"https://image.tmdb.org/t/p/w1280{details['backdrop_path']}"
            if details.get('clearlogo'):
                meta_dict['clearlogo'] = f"https://image.tmdb.org/t/p/w500{details['clearlogo']}"
    except: pass

    # Fetch direct titlu episod in set language (sigur, bypass cache)
    from resources.lib.config import get_plot_language_code, LANG_TO_TMDB
    ep_lang = get_plot_language_code()
    if ep_lang != 'en' and c_type == 'tv' and season and episode:
        try:
            ep_tmdb_lang = LANG_TO_TMDB.get(ep_lang, 'en-US')
            url_ep_target = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={ep_tmdb_lang}"
            data_ep_target = get_json(url_ep_target)
            if data_ep_target and data_ep_target.get('name', '').strip():
                target_name = data_ep_target['name'].strip()
                if not re.match(r'^[A-Za-zĂ€-Ăż]+\s+\d+$', target_name):
                    meta_dict['title'] = target_name
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
        prev_debrid = params.get('prev_debrid', '')
        prev_provider = params.get('prev_provider', '')
        prev_codec = params.get('prev_codec', '')
        prev_source = params.get('prev_source', '')
        
        best_idx = find_best_stream_index(filtered_streams, prev_quality, prev_group, prev_is_sdr, prev_debrid, prev_provider, prev_codec, prev_source)
        log(f"[BINGE-WATCH] Sursa aleasa index={best_idx} din {len(filtered_streams)}")
        
        if best_idx >= 0:
            ret = best_idx
            xbmcgui.Dialog().notification("Binge Watching", "Auto-playing next episode...", TMDbmovies_ICON, 3000, False)
    # =========================================================

    # Autoplay-ul standard (Daca NU suntem in Binge Watching Next)
    if ret < 0 and auto_play and not auto_play_next:
        try:
            profile_idx = int(ADDON.getSetting('autoplay_profile'))
            filtered_streams = sort_streams_for_autoplay(filtered_streams, profile_idx)
            if filtered_streams:
                xbmcgui.Dialog().notification("Auto Play", "Selecting best source...", TMDbmovies_ICON, 3000, False)
                ret = 0 
        except: pass

    if ret < 0:
        from resources.lib.results_window import ResultsWindow
        window_items = format_for_results_window(filtered_streams, poster_url, meta_dict)
        # Inchide dialogul de scanare FIX cand ResultsWindow e gata â€” zero gap
        try: dialog.close()
        except: pass
        win = ResultsWindow('results.xml', ADDON.getAddonInfo('path'), 'Default', '1080i', results=window_items, meta=meta_dict)
        _show_modal_abortable(win)
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
        # Inchide dialogul de scanare (autoplay/binge â€” fara ResultsWindow)
        try: dialog.close()
        except: pass
        selected_streams = filtered_streams  
        properties = {'tmdb_id': str(tmdb_id)}
        if final_imdb_id:
            if c_type == 'tv': properties['tvshow.imdb_id'] = final_imdb_id
            properties['imdb_id'] = final_imdb_id
            properties['ImdbNumber'] = final_imdb_id

        # Extragem titlul curat (Garantat RO daca a fost gasit)
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
        if meta_dict.get('premiered'): info_tag['premiered'] = meta_dict['premiered']
        if meta_dict.get('mpaa'): info_tag['mpaa'] = meta_dict['mpaa']

        if final_imdb_id: info_tag['imdbnumber'] = final_imdb_id
        if c_type == 'tv':
            info_tag['tvshowtitle'] = final_show_title
            if season: info_tag['season'] = int(season)
            if episode: info_tag['episode'] = int(episode)

        unique_ids = {'tmdb': str(tmdb_id)}
        if final_imdb_id: unique_ids['imdb'] = final_imdb_id
            
        art = {'poster': poster_url, 'thumb': poster_url}
        if meta_dict.get('fanart'):
            art['fanart'] = meta_dict['fanart']
        
        # --- FIX KODI OSD CLEARLOGO ---
        if meta_dict.get('clearlogo'):
            art['clearlogo'] = meta_dict['clearlogo']
            art['tvshow.clearlogo'] = meta_dict['clearlogo'] # Obligatoriu pentru seriale in Kodi!
        # ------------------------------

        global _saved_window_items, _saved_meta_dict, _saved_filtered_streams
        try: _saved_window_items = window_items
        except: _saved_window_items = None
        _saved_meta_dict = meta_dict
        _saved_filtered_streams = filtered_streams

        play_with_rollover(
            selected_streams, ret, tmdb_id, c_type, season, episode, 
            info_tag, unique_ids, art, properties, resume_time, resolve_only=resolve_only,
            native_resume_mode=native_resume_mode
        )
            
    else:
        try: xbmcplugin.endOfDirectory(_current_handle())
        except: pass

   
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
    # FIX SMART TOGGLE: Daca se descarca deja, oferim optiunea de STOP!
    # Chiar daca meniul din Kodi a ramas vizual pe "Download", dand click va opri.
    # =================================================================
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    window = xbmcgui.Window(10000)
    
    if window.getProperty(unique_id) == 'active':
        if xbmcgui.Dialog().yesno("Download Active", f"Title [COLOR cyan]{title}[/COLOR] is already downloading in the background.\n\nDo you want to STOP the download?"):
            window.setProperty(f"{unique_id}_stop", "true")
            window.clearProperty(unique_id)
            xbmcgui.Dialog().notification("Download", "Stopping...", TMDbmovies_ICON, 2000, False)
            xbmc.sleep(300)
            xbmc.executebuiltin("Container.Refresh")
        return
    # =================================================================
    
    # Metadata â€” single call replaces year + imdb_id + poster_url
    from resources.lib.tmdb_api import get_tmdb_item_details
    md = get_tmdb_item_details(str(tmdb_id), c_type)
    if md:
        if not year:
            year = str((md.get('release_date') or md.get('first_air_date') or ''))[:4]
        ext_ids = md.get('external_ids', {}) or {}
        imdb_id = ext_ids.get('imdb_id', '') or md.get('imdb_id', '') or f"tmdb:{tmdb_id}"
        if md.get('poster_path'):
            poster_url = f"https://image.tmdb.org/t/p/w500{md['poster_path']}"
        else:
            poster_url = "DefaultVideo.png"
    else:
        imdb_id = f"tmdb:{tmdb_id}"
        poster_url = "DefaultVideo.png"
        year = year or ''

    streams = []
    
    # ID Cache
    search_id = f"src_{tmdb_id}_{c_type}"
    if c_type == 'tv': search_id += f"_s{season}e{episode}"
        
    cache_db = MainCache()
    cached_streams, error_history, empty_history, scanned_history, _ = cache_db.get_source_cache(search_id)
    
    # 2. Cache + Filtrare
    active_providers = []
    http_master_enabled = ADDON.getSetting('enable_http_scrapers') == 'true'
    p2p_master_enabled = ADDON.getSetting('enable_p2p_providers') == 'true'
    debrid_ids = ['aiostreams', 'torrentio', 'mediafusion', 'comet', 'meteor', 'usenet', 'custom1', 'custom2', 'custom3', 'custom4', 'custom5']
    p2p_ids = ['p2p_yts', 'p2p_torrentio', 'p2p_comet', 'p2p_mediafusion', 'p2p_filelist', 'p2p_speedapp', 'p2p_seedpool', 'p2p_knaben', 'p2p_thepiratebay', 'p2p_custom1', 'p2p_custom2', 'p2p_custom3', 'p2p_custom4', 'p2p_custom5']
    for pid in ALL_KNOWN_PROVIDERS:
        is_enabled = ADDON.getSetting(f'use_{pid}') == 'true' or (pid == 'aiostreams' and ADDON.getSetting('aiostreams') == 'true')
        if not is_enabled:
            continue
        if pid in debrid_ids:
            active_providers.append(pid)
        elif pid in p2p_ids:
            if p2p_master_enabled:
                active_providers.append(pid)
        else:
            if http_master_enabled:
                active_providers.append(pid)

    if cached_streams:
        log(f"[DOWNLOAD] Found {len(cached_streams)} streams in CACHE.")
        valid_cached_streams = []
        for s in cached_streams:
            s_pid = s.get('provider_id')
            if not s_pid:
                s_pid = get_fallback_provider_id(s.get('name', ''))
            
            if s_pid and s_pid in active_providers:
                valid_cached_streams.append(s)
            elif not s_pid:
                valid_cached_streams.append(s)
        streams = valid_cached_streams

    # 3. Scrape
    if not streams:
        # --- MODIFICARE: Folosim DialogProgressBG (dreapta-sus) in loc de DialogProgress (mijloc) ---
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create("[B][COLOR FFFDBD01]Download Manager[/COLOR][/B]", "Initializing...")
        
        # Citim setarea de compatibilitate a skin-ului (0 = Estuary, 1 = AF3)
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'

        def update_progress(percent, status_data):
            if isinstance(status_data, str): 
                # Fallback de siguranta
                p_dialog.update(percent, message=status_data)
                return True

            if skin_compat == '1':
                # ARCTIC FUSE 3
                msg = status_data.get('af3', '')
            else:
                # ESTUARY (Design-ul tau complet cu detalii)
                msg = status_data.get('estuary', '')
                
            p_dialog.update(percent, message=msg)
            return True

        # Observatie: get_stream_data returneaza canceled=False daca folosim DialogProgressBG
        # deoarece acesta nu are buton de cancel explicit in interfata simpla
        streams, error_providers, empty_providers, canceled = get_stream_data(imdb_id, c_type, season, episode, update_progress, active_providers)
        p_dialog.close()
        
        if canceled: return
        
        if streams:
            streams = sort_streams_by_quality(streams)
            scanned_now = [p for p in active_providers if p not in error_providers and p not in empty_providers]
            try: dur = int(ADDON.getSetting('cache_sources_duration'))
            except: dur = 24
            cache_db.set_source_cache(search_id, streams, error_providers, empty_providers, scanned_now, dur)

    if not streams:
        xbmcgui.Dialog().notification("Download", "No sources found!", TMDbmovies_ICON)
        return

    # 4. Deduplicare si sortare
    streams = deduplicate_streams(streams)
    streams = sort_streams_by_quality(streams)
    
    # =========================================================
    # FILTRARE CALITATE PENTRU AFISARE
    # =========================================================
    all_streams_count = len(streams)
    filtered_streams, quality_stats = filter_streams_for_display(streams)
    
    if not filtered_streams:
        xbmcgui.Dialog().notification("Download", f"All {all_streams_count} sources filtered!", TMDbmovies_ICON, 3000)
        return
    # =========================================================
    
    clean_title_backup = title
    if c_type == 'tv':
        st = params.get('tv_show_title', '')
        if st: clean_title_backup = st 

    display_items = build_display_items(filtered_streams, poster_url)  # <- filtered_streams!
    
    if len(filtered_streams) < all_streams_count:
        dlg_title = f"[DOWNLOAD] {len(filtered_streams)}/{all_streams_count} sources:"
    else:
        dlg_title = f"[DOWNLOAD] Select source:"
    
    if cached_streams: 
        dlg_title += " [COLOR lime][CACHE][/COLOR]"

    ret = xbmcgui.Dialog().select(dlg_title, display_items, useDetails=True)
    
    if ret >= 0:
        selected_stream = filtered_streams[ret]  # <- filtered_streams, nu streams!
        url = selected_stream['url']
        
        # Nume fisier
        raw_release_name = selected_stream.get('name', '')
        extra_title = selected_stream.get('title', '')
        if len(extra_title) > len(raw_release_name):
            raw_release_name = extra_title
        if len(raw_release_name) < 5:
             raw_release_name = None

        # START DOWNLOAD
        start_download_thread(url, clean_title_backup, year, tmdb_id, c_type, season, episode, release_name=raw_release_name)
        
        # --- MODIFICARE: REFRESH AUTOMAT ---
        # Fortam reincarcarea listei pentru ca meniul contextual sa vada noul status (Stop)
        xbmc.sleep(200) # Pauza mica sa apuce sa seteze proprietatea
        xbmc.executebuiltin("Container.Refresh")
        # -----------------------------------

def stop_download_action(params):
    """Opreste download-ul curent pentru acest item."""
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    season = params.get('season')
    episode = params.get('episode')
    
    from resources.lib.downloader import get_dl_id
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    
    window = xbmcgui.Window(10000)
    
    # 1. Trimitem semnalul de STOP catre thread-ul de download
    window.setProperty(f"{unique_id}_stop", "true")
    
    # 2. Stergem IMEDIAT flag-ul de 'active', astfel incat meniul contextual
    # sa revina la "Download" imediat ce dam refresh, chiar daca thread-ul
    # mai dureaza 1-2 secunde sa stearga fisierul.
    window.clearProperty(unique_id) 
    
    xbmcgui.Dialog().notification("Download", "Stopping...", TMDbmovies_ICON, 1000, False)



