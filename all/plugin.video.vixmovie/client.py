import base64
import codecs
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin, urlencode, parse_qsl, urlunparse

import requests
import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_PROFILE_PATH = ADDON.getAddonInfo("profile")
CACHE_PATH = f"{ADDON_PROFILE_PATH}/cache.json"
CACHE_EXPIRY_DAYS = 7
MAX_RETRIES = 3
RETRY_DELAY = 2

# --- In-memory cache (loaded once per plugin invocation) ---
_cache_data = None
_cache_dirty = False
_cache_lock = threading.Lock()

# --- In-memory favorites cache ---
_favorites_cache = None


# --- Global session for performance (connection reuse) ---
_session = requests.Session()


def retry_on_failure(func):
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    log(
                        f"Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}, retrying...",
                        level="warning",
                    )
                    time.sleep(RETRY_DELAY)
                else:
                    log(
                        f"All {MAX_RETRIES} attempts failed for {func.__name__}: {e}",
                        level="error",
                    )
        return None

    return wrapper


def get_lang():
    try:
        show_titles_en = (
            ADDON.getSettingBool("titles_english")
            if hasattr(ADDON, "getSettingBool")
            else (ADDON.getSetting("titles_english") == "true")
        )
    except Exception:
        show_titles_en = True
    if show_titles_en:
        return "ro-RO"
    try:
        return ADDON.getSetting("tmdb_lang") or "ro-RO"
    except Exception:
        return "ro-RO"


def log(msg, level="info"):
    prefix = "[VIXMOVIE-CLIENT]"
    print(f"{prefix} [{level.upper()}]: {msg}")


def _convert_to_json_serializable(data):
    if isinstance(data, set):
        return list(data)
    elif isinstance(data, dict):
        return {k: _convert_to_json_serializable(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_convert_to_json_serializable(item) for item in data]
    return data


def _convert_from_json(data):
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if isinstance(v, dict):
                # Try to convert keys to int — needed for episode_info structure
                # {season_int: set(episode_ints)}.  For all other cached TMDb
                # responses (which have string keys like "cast", "crew",
                # "results", etc.) the conversion fails and we keep the dict
                # as-is.
                try:
                    result[k] = {
                        int(sk): set(v[sk]) if isinstance(v[sk], list) else v[sk]
                        for sk in v
                    }
                except (ValueError, TypeError):
                    result[k] = v
            else:
                result[k] = v
        return result
    return data


def _load_cache():
    """Return the in-memory cache, loading from disk only on first call."""
    global _cache_data
    if _cache_data is not None:
        return _cache_data
    with _cache_lock:
        # Double-checked locking: another thread may have loaded it already
        if _cache_data is not None:
            return _cache_data
        cache = {}
        if not xbmcvfs.exists(ADDON_PROFILE_PATH):
            xbmcvfs.mkdirs(ADDON_PROFILE_PATH)
        if xbmcvfs.exists(CACHE_PATH):
            f = None
            try:
                f = xbmcvfs.File(CACHE_PATH, "r")
                content = f.read()
                if content:
                    cache = json.loads(content)
            except Exception as e:
                log(f"Error loading cache file: {e}", level="error")
            finally:
                if f:
                    f.close()
        _cache_data = cache
        log(f"Cache loaded from disk ({len(cache)} keys)")
    return _cache_data


def _save_cache(cache_data):
    """Update the in-memory cache and mark it dirty (will be flushed at end of request)."""
    global _cache_data, _cache_dirty
    _cache_data = cache_data
    _cache_dirty = True


def _write_cache_to_disk(cache_data):
    """Write cache data to disk (called only by flush_cache)."""
    f = None
    try:
        if not xbmcvfs.exists(ADDON_PROFILE_PATH):
            xbmcvfs.mkdirs(ADDON_PROFILE_PATH)
        f = xbmcvfs.File(CACHE_PATH, "w")
        content = json.dumps(cache_data, indent=2)
        f.write(content)
        log(f"Cache flushed to disk ({len(cache_data)} keys)")
    except Exception as e:
        log(f"Error writing to cache file: {e}", level="error")
    finally:
        if f:
            f.close()


def flush_cache():
    """Persist the in-memory cache to disk if it was modified this session.
    Call this once at the end of each plugin action (in router())."""
    global _cache_dirty
    if _cache_dirty and _cache_data is not None:
        _write_cache_to_disk(_cache_data)
        _cache_dirty = False


def _is_cache_valid(cache_data, key):
    if key not in cache_data:
        return False
    cached_time = cache_data.get(f"{key}_timestamp", 0)
    expiry_seconds = CACHE_EXPIRY_DAYS * 86400
    return (time.time() - cached_time) < expiry_seconds


def _get_cached_data(cache_data, key):
    if not _is_cache_valid(cache_data, key):
        return None
    data = cache_data.get(key)
    if data is None:
        return None
    return _convert_from_json(data)


def _set_cached_data(cache_data, key, data):
    data = _convert_to_json_serializable(data)
    cache_data[key] = data
    cache_data[f"{key}_timestamp"] = time.time()
    return cache_data


def get_cache_entry(key):
    cache = _load_cache()
    return _get_cached_data(cache, key)


def set_cache_entry(key, data):
    global _cache_dirty
    cache = _load_cache()
    _set_cached_data(cache, key, data)
    _cache_dirty = True


UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def get_imdb_id(tmdb_id, media_type):
    if media_type == "movie":
        data = _call_tmdb_api(f"movie/{tmdb_id}")
    else:
        data = _call_tmdb_api(f"tv/{tmdb_id}/external_ids")
    
    if data:
        return data.get("imdb_id")
    return None


def verify_stream_link(url, headers=None):
    """Rigorous verification: check the playlist AND the first segment to avoid 404 errors in player."""
    try:
        # 1. Fetch the playlist content
        r = _session.get(url, headers=headers, timeout=5, stream=True)
        if r.status_code != 200:
            return False
            
        if ".m3u8" in url.lower():
            content = ""
            for line in r.iter_lines(decode_unicode=True):
                if line: content += line + "\n"
                if len(content) > 10000: break
            
            if "#EXTM3U" not in content:
                return False

            # 2. Extract the first stream or segment
            lines = content.splitlines()
            target_sub_url = None
            for i, line in enumerate(lines):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Found the first data line
                target_sub_url = line
                break
            
            if target_sub_url:
                if not target_sub_url.startswith("http"):
                    target_sub_url = urljoin(url, target_sub_url)
                
                # 3. CRITICAL: Verify the actual sub-segment/sub-playlist
                # Your log showed 404 on these sub-URLs
                try:
                    sr = _session.head(target_sub_url, headers=headers, timeout=5, allow_redirects=True)
                    if sr.status_code == 200:
                        return True
                    log(f"Verification failed: Sub-URL {target_sub_url} returned {sr.status_code}")
                    return False
                except Exception as e:
                    log(f"Verification error on sub-URL: {e}")
                    return False
            
            # If no sub-url found but file is EXTM3U, it's risky but might be a valid empty-ish master
            return "#EXT-X-STREAM-INF" in content or "#EXT-X-TARGETDURATION" in content
            
        return True # For mp4, 200 is enough
    except Exception as e:
        log(f"Verification global error: {e}")
        return False


def get_stream_url(
    tmdb_id,
    season=None,
    episode=None,
    force_scraper=None,
    fast_auto=True,
    return_source=False,
):
    if not tmdb_id:
        log("ID-ul TMDb lipsește. Anulare.", level="error")
        return (None, None) if return_source else None

    media_type = "tv" if season and episode else "movie"
    
    try:
        choice = int(force_scraper) if force_scraper else int(ADDON.getSetting("scraper_choice") or "0")
    except Exception:
        choice = 0

    # 1. Try VixSrc (if Auto or specifically selected)
    if choice in (0, 1):
        try:
            log(f"Attempting VixSrc extraction for {media_type} {tmdb_id}")
            verify_vixsrc = not (choice == 0 and fast_auto)
            stream = extract_vixsrc(
                tmdb_id,
                media_type,
                season,
                episode,
                choice,
                verify=verify_vixsrc,
            )
            if stream:
                log("SUCCESS: Found stream via VixSrc")
                return (stream, "vixsrc") if return_source else stream
        except Exception as e:
            log(f"Error in VixSrc extractor: {e}", level="warning")

    # 2. Try Vaplayer (if Auto or specifically selected, or if VixSrc failed in Auto)
    if choice in (0, 2):
        try:
            log(f"Attempting Vaplayer extraction for {media_type} {tmdb_id}")
            stream = extract_vaplayer(tmdb_id, media_type, season, episode)
            if stream:
                log("SUCCESS: Found stream via Vaplayer")
                return (stream, "vaplayer") if return_source else stream
        except Exception as e:
            log(f"Error in Vaplayer extractor: {e}", level="warning")

    return (None, None) if return_source else None


def _merge_url_query(url, query_dict):
    if not query_dict:
        return url
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query))
    params.update(query_dict)
    # Rebuild URL with new query
    # parts: scheme, netloc, path, params, query, fragment
    parts = list(parsed)
    parts[4] = urlencode(params)
    return urlunparse(parts)


def _decode_js_url(value):
    if not value:
        return value
    value = value.replace('\\/', '/')
    try:
        value = codecs.decode(value, "unicode_escape")
    except Exception:
        value = value.replace("\\u0026", "&")
    return value


def parse_best_quality(content, master_url):
    try:
        lines = content.split('\n')
        best = None
        best_bandwidth = 0
        for i in range(len(lines)):
            if lines[i].startswith('#EXT-X-STREAM-INF'):
                # Extract bandwidth
                bw_match = re.search(r'BANDWIDTH=(\d+)', lines[i])
                bw = int(bw_match.group(1)) if bw_match else 0
                if i + 1 < len(lines):
                    src = lines[i+1].strip()
                    if src and not src.startswith('#'):
                        if bw >= best_bandwidth:
                            best_bandwidth = bw
                            if src.startswith('http'):
                                best = src
                            else:
                                best = urljoin(master_url, src)
        if best:
            log(f"Selected best quality: {best_bandwidth // 1000}kbps")
            return best
    except Exception as e:
        log(f"Error parsing quality: {e}")
    return master_url


def extract_vaplayer(tmdb_id, media_type, season=None, episode=None):
    imdb_id = get_imdb_id(tmdb_id, media_type)
    if not imdb_id:
        log(f"Could not get IMDb ID for TMDB ID {tmdb_id}")
        return None

    log(f"Attempting Vaplayer extraction for {imdb_id}")
    
    vaplayer_api_url = 'https://streamdata.vaplayer.ru/api.php'
    brightpath_base = 'https://brightpathsignals.com/embed'
    
    # In scraper.js: type is 'series' or 'movie'
    v_type = 'series' if media_type == 'tv' else 'movie'
    
    if v_type == 'series':
        referer = f"{brightpath_base}/tv/{imdb_id}/{season}/{episode}"
        params = {'imdb': imdb_id, 'type': 'tv', 'season': season, 'episode': episode}
    else:
        referer = f"{brightpath_base}/movie/{imdb_id}"
        params = {'imdb': imdb_id, 'type': 'movie'}

    headers = {
        'User-Agent': UA,
        'Referer': referer,
        'Origin': 'https://brightpathsignals.com',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
    }

    try:
        log(f"Vaplayer API Request: {vaplayer_api_url} with {params}")
        resp = _session.get(vaplayer_api_url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            log(f"Vaplayer API returned status {resp.status_code}")
            return None
        
        body = resp.json()
        if not body or not body.get('data'):
            log(f"Vaplayer API returned no data: {body}")
            return None
        
        stream_urls = body['data'].get('stream_urls')
        if not stream_urls or not isinstance(stream_urls, list):
            return None

        for m3u8_url in stream_urls[:3]:
            try:
                # Try to fetch and parse quality
                h = {'User-Agent': UA, 'Referer': referer}
                r = _session.get(m3u8_url, headers=h, timeout=5)
                if r.status_code == 200 and "#EXTM3U" in r.text:
                    best_url = parse_best_quality(r.text, m3u8_url)
                    # Verify the best URL (sequential but fast)
                    if verify_stream_link(best_url, h):
                        return f"{best_url}|Referer={referer}&User-Agent={UA}"
            except Exception:
                continue

        # Final fallback
        return f"{stream_urls[0]}|Referer={referer}&User-Agent={UA}"

    except Exception as e:
        log(f"Error in Vaplayer extractor: {e}", level="warning")
    return None


def extract_vixsrc(tmdb_id, media_type, season=None, episode=None, choice=0, verify=True):
    try:
        base_url = 'https://vixsrc.to'
        if media_type == 'movie':
            url = f'{base_url}/movie/{tmdb_id}'
        else:
            url = f'{base_url}/tv/{tmdb_id}/{season}/{episode}'
        
        headers = {
            'Referer': f'{base_url}/',
            'User-Agent': UA
        }
        
        # 1. Try new API fetch logic (fastest)
        api_url = url.replace('/tv/', '/api/tv/').replace('/movie/', '/api/movie/')
        target_fetch_url = url
        try:
            # Use shorter timeout for API
            api_resp = _session.get(api_url, headers=headers, timeout=5)
            if api_resp.status_code == 200:
                api_json = api_resp.json()
                if 'src' in api_json:
                    target_fetch_url = urljoin(base_url, api_json['src'])
        except Exception:
            pass

        wp_resp = _session.get(target_fetch_url, headers={'Referer': url, 'User-Agent': UA}, timeout=5)
        if wp_resp.status_code != 200:
            return None
        wp = wp_resp.text
        
        tk_match = re.search(r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]", wp)
        
        # Fallback to legacy iframe parsing if no token in main page
        if not tk_match:
            ip_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', wp, re.IGNORECASE)
            if ip_match:
                iframe_url = urljoin(url, ip_match.group(1))
                try:
                    wp_resp = _session.get(iframe_url, headers={'Referer': url, 'User-Agent': UA}, timeout=5)
                    if wp_resp.status_code == 200:
                        wp = wp_resp.text
                        tk_match = re.search(r"['\"]token['\"]\s*:\s*['\"](\w+)['\"]", wp)
                except Exception:
                    pass
        
        if tk_match:
            tk = tk_match.group(1)
            raw_url_match = re.search(r"(?:['\"]url['\"]|url)\s*:\s*['\"]([^'\"]+)['\"]", wp)
            if raw_url_match:
                raw_url = _decode_js_url(raw_url_match.group(1))
                su = re.sub(r'(/playlist/[^/?]+)(?!\.m3u8)(?=[?#]|$)', r'\1.m3u8', raw_url)
                
                exp_match = re.search(r"['\"]expires['\"]\s*:\s*['\"](\d+)['\"]", wp)
                q = {'token': tk}
                if exp_match:
                    q['expires'] = exp_match.group(1)
                
                if re.search(r'canPlayFHD\s*=\s*true', wp):
                    q['h'] = '1'
                
                final_url = _merge_url_query(su, q)
                if not verify:
                    log("VixSrc fast mode: returning stream without rigorous verification")
                    return f"{final_url}|Referer={url}&Origin={base_url}&User-Agent={UA}"
                
                # VERIFICATION: Robustly check if the URL actually works
                verify_headers = {'Referer': url, 'Origin': base_url, 'User-Agent': UA}
                if verify_stream_link(final_url, verify_headers):
                    return f"{final_url}|Referer={url}&Origin={base_url}&User-Agent={UA}"
                else:
                    log(f"VixSrc link failed rigorous verification, but we'll try it as last resort: {final_url}")
                    # Return it anyway if specifically selected, but for Auto it failed
                    if choice == 1:
                        return f"{final_url}|Referer={url}&Origin={base_url}&User-Agent={UA}"
        
        # Final fallback: generic scrape
        res = extract_video_from_page(url, f'{base_url}/')
        if res:
            return f"{res}|Referer={url}&User-Agent={UA}"
    except Exception as e:
        log(f"Extractor error for vixsrc: {e}", level="warning")
    return None


def extract_video_from_page(url, referer=''):
    try:
        headers = {'User-Agent': UA, 'Referer': referer or url}
        resp = _session.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return None
            
        text = resp.text
        
        # Look for m3u8 and mp4 URLs
        m3u8_pattern = r'(https?://[^\s\'"<>\)\]\}\\]+\.m3u8[^\s\'"<>\)\]\}\\]*)'
        mp4_pattern = r'(https?://[^\s\'"<>\)\]\}\\]+\.mp4[^\s\'"<>\)\]\}\\]*)'
        
        all_matches = re.findall(m3u8_pattern, text) + re.findall(mp4_pattern, text)
        
        for match in all_matches:
            if 'ad' in match.lower() and '.m3u8' not in match.lower():
                continue
            
            # Verify if the found link is actually playable
            if verify_stream_link(match, {'User-Agent': UA, 'Referer': url}):
                return match
                
        return None
    except Exception as e:
        log(f"Generic extraction error for {url}: {e}")
    return None


def get_api_key():
    return ADDON.getSetting("tmdb_api_key")


def get_source_movie_ids():
    global _cache_dirty
    cache = _load_cache()
    cached_data = _get_cached_data(cache, "movie_ids")
    if cached_data is not None:
        log(f"Using cached movie IDs ({len(cached_data)} items)")
        return cached_data

    id_set = set()
    page = 1
    while True:
        url = f"https://vixsrc.to/api/list/movie?page={page}"
        try:
            response = _session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            items = []
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            elif isinstance(data, list):
                items = data
            
            if not items:
                break
                
            for item in items:
                if item.get("tmdb_id"):
                    id_set.add(str(item["tmdb_id"]))
            
            if isinstance(data, dict):
                current = data.get("current_page", page)
                last = data.get("last_page", 1)
                if current >= last:
                    break
            else:
                break
            
            page += 1
            if page > 200: break
        except Exception as e:
            log(f"Error fetching movie list page {page}: {e}")
            break

    if id_set:
        log(f"Found {len(id_set)} valid movie IDs across {page} pages.")
        _set_cached_data(cache, "movie_ids", id_set)
        _cache_dirty = True
        return id_set

    expired_data = cache.get("movie_ids")
    if expired_data:
        return _convert_from_json(expired_data)
    return set()


def get_source_tv_ids():
    global _cache_dirty
    cache = _load_cache()
    cached_data = _get_cached_data(cache, "tv_ids")
    if cached_data is not None:
        log(f"Using cached TV IDs ({len(cached_data)} items)")
        return cached_data

    id_set = set()
    page = 1
    while True:
        url = f"https://vixsrc.to/api/list/tv?page={page}"
        try:
            response = _session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            items = []
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            elif isinstance(data, list):
                items = data
            
            if not items:
                break
                
            for item in items:
                if item.get("tmdb_id"):
                    id_set.add(str(item["tmdb_id"]))
            
            if isinstance(data, dict):
                current = data.get("current_page", page)
                last = data.get("last_page", 1)
                if current >= last:
                    break
            else:
                break
            
            page += 1
            if page > 200: break
        except Exception as e:
            log(f"Error fetching TV list page {page}: {e}")
            break

    if id_set:
        log(f"Found {len(id_set)} valid TV show IDs across {page} pages.")
        _set_cached_data(cache, "tv_ids", id_set)
        _cache_dirty = True
        return id_set

    expired_data = cache.get("tv_ids")
    if expired_data:
        return _convert_from_json(expired_data)
    return set()


def get_source_episode_info():
    global _cache_dirty
    cache = _load_cache()
    cached_data = _get_cached_data(cache, "episode_info")
    if cached_data is not None:
        log(f"Using cached episode info ({len(cached_data)} TV shows)")
        return cached_data

    episode_map = {}
    page = 1
    while True:
        url = f"https://vixsrc.to/api/list/episode?page={page}"
        try:
            response = _session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            items = []
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            elif isinstance(data, list):
                items = data
            
            if not items:
                break

            for item in items:
                tmdb_id = str(item.get("tmdb_id")) if item.get("tmdb_id") else None
                season = item.get("s")
                episode = item.get("e")
                if tmdb_id and season is not None and episode is not None:
                    if tmdb_id not in episode_map:
                        episode_map[tmdb_id] = {}
                    if season not in episode_map[tmdb_id]:
                        episode_map[tmdb_id][season] = set()
                    episode_map[tmdb_id][season].add(episode)

            if isinstance(data, dict):
                current = data.get("current_page", page)
                last = data.get("last_page", 1)
                if current >= last:
                    break
            else:
                break

            page += 1
            if page > 500: break # Episodes can be many
        except Exception as e:
            log(f"Error fetching episode list page {page}: {e}")
            break

    if episode_map:
        log(f"Processed episode info for {len(episode_map)} TV shows across {page} pages.")
        _set_cached_data(cache, "episode_info", episode_map)
        _cache_dirty = True
        return episode_map

    expired_data = cache.get("episode_info")
    if expired_data:
        return _convert_from_json(expired_data)
    return {}


def _call_tmdb_api(endpoint, params=None):
    global _cache_dirty
    api_key = get_api_key()
    if not api_key:
        log("TMDb API key is not set.", level="error")
        return None

    cache_key = f"tmdb_{endpoint}_{json.dumps(params, sort_keys=True)}"
    cache = _load_cache()
    cached = _get_cached_data(cache, cache_key)
    if cached is not None:
        return cached

    base_url = "https://api.themoviedb.org/3"
    params = params or {}
    params["api_key"] = api_key

    for attempt in range(MAX_RETRIES):
        try:
            response = _session.get(f"{base_url}/{endpoint}", params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            # Update in-memory cache only; flush_cache() will persist at end of request
            _set_cached_data(cache, cache_key, data)
            _cache_dirty = True
            return data
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                log(
                    f"TMDb API attempt {attempt + 1} failed: {e}, retrying...",
                    level="warning",
                )
                time.sleep(RETRY_DELAY)
            else:
                log(
                    f"TMDb API request failed after {MAX_RETRIES} attempts: {e}",
                    level="error",
                )
                return None


def _best_trailer_from_results(
    results, prefer_langs=("en", "en-US", "", "es-ES", "es", "ro-RO")
):
    if not results:
        return None

    def score(v):
        s = 0
        if (v.get("type") or "").lower() == "trailer":
            s += 10
        if v.get("official"):
            s += 5
        if (v.get("site") or "").lower() == "youtube":
            s += 3
        lang = v.get("iso_639_1") or ""
        try:
            s += 5 - prefer_langs.index(lang)
        except ValueError:
            pass
        if v.get("published_at"):
            s += 1
        return s

    best = max(results, key=score)
    if (best.get("site") or "").lower() == "youtube" and best.get("key"):
        return f"plugin://plugin.video.youtube/?action=play_video&videoid={best['key']}"
    return None


def get_movie_trailer_url(tmdb_id, language="en-US"):
    data = _call_tmdb_api(
        f"movie/{tmdb_id}/videos",
        {
            "language": language if language else "en-US",
            "include_video_language": "en,en-US,null",
        },
    )
    results = (data or {}).get("results") or []
    url = _best_trailer_from_results(results)
    return url


def get_tv_trailer_url(tmdb_id, language="en-US"):
    data = _call_tmdb_api(
        f"tv/{tmdb_id}/videos",
        {
            "language": language if language else "en-US",
            "include_video_language": "en,en-US,null",
        },
    )
    results = (data or {}).get("results") or []
    url = _best_trailer_from_results(results)
    return url


def get_movie_full_details(movie_id, language="ro-RO"):
    """Fetch movie details + credits + videos in a single TMDb API call.

    Using append_to_response avoids 3 separate round-trips per list item,
    which is the primary source of slow list-loading times.
    """
    return _call_tmdb_api(
        f"movie/{movie_id}",
        {
            "language": language,
            "append_to_response": "credits,videos",
            "include_video_language": "en,en-US,null",
        },
    )


def get_tv_full_details(tv_id, language="ro-RO"):
    """Fetch TV show details + credits + videos in a single TMDb API call."""
    return _call_tmdb_api(
        f"tv/{tv_id}",
        {
            "language": language,
            "append_to_response": "credits,videos",
            "include_video_language": "en,en-US,null",
        },
    )


def get_trailer_url_from_videos_data(videos_data):
    """Extract the best trailer URL from a 'videos' sub-response dict."""
    results = (videos_data or {}).get("results") or []
    return _best_trailer_from_results(results)


def get_popular_tmdb(page=1):
    return _call_tmdb_api("movie/popular", {"page": page, "language": "ro-RO"})


def get_movies_by_year_tmdb(year=None, page=1, year_start=None, year_end=None):
    params = {
        "sort_by": "popularity.desc",
        "page": page,
        "language": "ro-RO",
    }
    if year:
        params["primary_release_year"] = year
    elif year_start and year_end:
        params["primary_release_date.gte"] = f"{year_start}-01-01"
        params["primary_release_date.lte"] = f"{year_end}-12-31"
    return _call_tmdb_api("discover/movie", params)


def get_genres_tmdb():
    return _call_tmdb_api("genre/movie/list", {"language": "ro-RO"})


def get_movies_by_genre_tmdb(genre_id, page=1):
    params = {
        "with_genres": genre_id,
        "sort_by": "popularity.desc",
        "page": page,
        "language": "ro-RO",
    }
    return _call_tmdb_api("discover/movie", params)


def search_tmdb(query, page=1):
    return _call_tmdb_api(
        "search/movie", {"query": query, "page": page, "language": "ro-RO"}
    )


def get_popular_tv_tmdb(page=1):
    return _call_tmdb_api("tv/popular", {"page": page, "language": "ro-RO"})


def get_tv_by_year_tmdb(year=None, page=1, year_start=None, year_end=None):
    params = {
        "sort_by": "popularity.desc",
        "page": page,
        "language": "ro-RO",
    }
    if year:
        params["first_air_date_year"] = year
    elif year_start and year_end:
        params["first_air_date.gte"] = f"{year_start}-01-01"
        params["first_air_date.lte"] = f"{year_end}-12-31"
    return _call_tmdb_api("discover/tv", params)


def get_tv_genres_tmdb():
    return _call_tmdb_api("genre/tv/list", {"language": "ro-RO"})


def get_tv_by_genre_tmdb(genre_id, page=1):
    params = {
        "with_genres": genre_id,
        "sort_by": "popularity.desc",
        "page": page,
        "language": "ro-RO",
    }
    return _call_tmdb_api("discover/tv", params)


def search_tv_tmdb(query, page=1):
    return _call_tmdb_api(
        "search/tv", {"query": query, "page": page, "language": "ro-RO"}
    )


def get_tv_details_tmdb(tv_id):
    return _call_tmdb_api(f"tv/{tv_id}", {"language": "ro-RO"})


def get_season_details_tmdb(tv_id, season_number):
    return _call_tmdb_api(f"tv/{tv_id}/season/{season_number}", {"language": "ro-RO"})


def get_movie_credits_tmdb(movie_id):
    return _call_tmdb_api(f"movie/{movie_id}/credits", {"language": "ro-RO"})


def get_tv_credits_tmdb(tv_id):
    return _call_tmdb_api(f"tv/{tv_id}/credits", {"language": "ro-RO"})


def get_movie_details_en(movie_id):
    return _call_tmdb_api(f"movie/{movie_id}", {"language": "en-US"})


def get_tv_details_en(tv_id):
    return _call_tmdb_api(f"tv/{tv_id}", {"language": "en-US"})


def get_season_details_en(tv_id, season_number):
    return _call_tmdb_api(f"tv/{tv_id}/season/{season_number}", {"language": "en-US"})


def get_episode_details_en(tv_id, season_number, episode_number):
    return _call_tmdb_api(
        f"tv/{tv_id}/season/{season_number}/episode/{episode_number}",
        {"language": "en-US"},
    )


def get_top_rated_tmdb(page=1):
    return _call_tmdb_api("movie/top_rated", {"page": page, "language": "ro-RO"})


def get_upcoming_tmdb(page=1):
    return _call_tmdb_api("movie/upcoming", {"page": page, "language": "ro-RO"})


def get_now_playing_tmdb(page=1):
    return _call_tmdb_api("movie/now_playing", {"page": page, "language": "ro-RO"})


def get_top_rated_tv_tmdb(page=1):
    return _call_tmdb_api("tv/top_rated", {"page": page, "language": "ro-RO"})


def get_airing_today_tv_tmdb(page=1):
    return _call_tmdb_api("tv/airing_today", {"page": page, "language": "ro-RO"})


def get_on_the_air_tv_tmdb(page=1):
    return _call_tmdb_api("tv/on_the_air", {"page": page, "language": "ro-RO"})


def get_movie_collections(page=1):
    return _call_tmdb_api("collection/popular", {"page": page, "language": "ro-RO"})


def get_trending_movies(page=1):
    return _call_tmdb_api("trending/movie/week", {"page": page, "language": "ro-RO"})


def get_trending_tv(page=1):
    return _call_tmdb_api("trending/tv/week", {"page": page, "language": "ro-RO"})


def get_collection_details(collection_id):
    return _call_tmdb_api(f"collection/{collection_id}", {"language": "ro-RO"})


POPULAR_NETWORKS = [
    {"id": 213, "name": "Netflix (Seriale)"},
    {"id": 1024, "name": "Netflix (Filme)"},
    {"id": 453, "name": "HBO"},
    {"id": 2596, "name": "HBO Max"},
    {"id": 318, "name": "Amazon Prime Video"},
    {"id": 350, "name": "Apple TV+"},
    {"id": 1025, "name": "Hulu"},
    {"id": 467, "name": "Starz"},
    {"id": 37, "name": "BBC"},
    {"id": 16, "name": "ABC"},
    {"id": 21, "name": "CBS"},
    {"id": 20, "name": "NBC"},
    {"id": 19, "name": "FOX"},
    {"id": 209, "name": "ITV"},
    {"id": 284, "name": "AMC"},
    {"id": 174, "name": "Sky"},
    {"id": 128, "name": "FX"},
    {"id": 2548, "name": "Disney+"},
    {"id": 2739, "name": "DC Universe"},
    {"id": 2308, "name": "Peacock"},
]


def get_tv_networks():
    return {"results": POPULAR_NETWORKS}


def get_movie_networks():
    return {"results": POPULAR_NETWORKS[:10]}


def get_tv_by_network_tmdb(network_id, page=1):
    return _call_tmdb_api(
        "discover/tv", {"with_networks": network_id, "page": page, "language": "ro-RO"}
    )


def search_person_tmdb(query, page=1):
    return _call_tmdb_api(
        "search/person", {"query": query, "page": page, "language": "ro-RO"}
    )


def get_person_movies_tmdb(person_id):
    return _call_tmdb_api(f"person/{person_id}/movie_credits", {"language": "ro-RO"})


def get_person_tv_tmdb(person_id):
    return _call_tmdb_api(f"person/{person_id}/tv_credits", {"language": "ro-RO"})


def get_recently_added_movies():
    return _call_tmdb_api("movie/now_playing", {"page": 1, "language": "ro-RO"})


def get_recently_added_tv():
    return _call_tmdb_api("tv/on_the_air", {"page": 1, "language": "ro-RO"})


FAVORITES_PATH = f"{ADDON_PROFILE_PATH}/favorites.json"


def _load_favorites():
    """Return the in-memory favorites dict, loading from disk only on first call."""
    global _favorites_cache
    if _favorites_cache is not None:
        return _favorites_cache
    if not xbmcvfs.exists(FAVORITES_PATH):
        _favorites_cache = {"movies": [], "tv": []}
        return _favorites_cache
    try:
        f = xbmcvfs.File(FAVORITES_PATH, "r")
        content = f.read()
        f.close()
        _favorites_cache = json.loads(content)
    except Exception as e:
        log(f"Error loading favorites: {e}", level="error")
        _favorites_cache = {"movies": [], "tv": []}
    return _favorites_cache


def _save_favorites(favorites):
    global _favorites_cache
    _favorites_cache = favorites
    try:
        f = xbmcvfs.File(FAVORITES_PATH, "w")
        f.write(json.dumps(favorites, indent=4))
        f.close()
    except Exception as e:
        log(f"Error saving favorites: {e}", level="error")


def add_favorite(tmdb_id, media_type, title):
    favorites = _load_favorites()
    key = "movies" if media_type == "movie" else "tv"
    item = {"id": str(tmdb_id), "title": title}
    if not any(f["id"] == item["id"] for f in favorites[key]):
        favorites[key].append(item)
        _save_favorites(favorites)
        log(f"Added to favorites: {title}", level="info")
        return True
    return False


def remove_favorite(tmdb_id, media_type):
    favorites = _load_favorites()
    key = "movies" if media_type == "movie" else "tv"
    favorites[key] = [f for f in favorites[key] if f["id"] != str(tmdb_id)]
    _save_favorites(favorites)
    log(f"Removed from favorites: {tmdb_id}", level="info")
    return True


def get_favorites(media_type):
    favorites = _load_favorites()
    key = "movies" if media_type == "movie" else "tv"
    return favorites.get(key, [])


def is_favorite(tmdb_id, media_type):
    favorites = _load_favorites()
    key = "movies" if media_type == "movie" else "tv"
    return any(f["id"] == str(tmdb_id) for f in favorites.get(key, []))
