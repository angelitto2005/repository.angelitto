# Core imports (always needed)
import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmc
import xbmcaddon
import xbmcvfs
import os
import time
import json
import re
from threading import Lock
import threading
from contextlib import closing

# Heavy imports moved to function level for lazy loading:
# - requests (only for HTTP scanning)
# - BeautifulSoup (only for HTML parsing)
# - FTP (only for FTP scanning)
# - Queue, ThreadPoolExecutor (only for parallel scanning)

# --- Settings ---
PAGE_SIZE = 50
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMG_URL = "https://image.tmdb.org/t/p/w500"

# --- Scanning Configuration Functions ---
from functools import lru_cache

@lru_cache(maxsize=1)
def get_video_extensions():
    """Get configured video extensions from settings (cached)"""
    extensions_str = ADDON.getSetting('video_extensions')
    if not extensions_str:
        # Default extensions
        return tuple(['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.ts', '.vob', '.mpg', '.mpeg', '.3gp', '.webm'])
    
    # Parse user-configured extensions
    extensions = [ext.strip() for ext in extensions_str.split(',') if ext.strip()]
    # Ensure they start with dot
    return tuple(['.' + ext.lstrip('.').lower() for ext in extensions])

@lru_cache(maxsize=1)
def get_exclude_folders():
    """Get list of folder names to exclude from scanning (cached)"""
    exclude_str = ADDON.getSetting('exclude_folders')
    if not exclude_str:
        return tuple(['sample', 'extras', 'subs', 'subtitles', '.@__thumb', '@eadir', 'bonus', 'deleted'])
    return tuple([f.strip().lower() for f in exclude_str.split(',') if f.strip()])

@lru_cache(maxsize=1)
def get_exclude_patterns():
    """Get list of filename patterns to exclude (cached)"""
    import fnmatch
    patterns_str = ADDON.getSetting('exclude_patterns')
    if not patterns_str:
        return tuple(['*sample*', '*trailer*', '*-trailer.*', '*bonus*'])
    return tuple([p.strip().lower() for p in patterns_str.split(',') if p.strip()])

def should_skip_folder(folder_name):
    """Check if folder should be skipped based on exclusion rules"""
    folder_lower = folder_name.lower()
    exclude_folders = get_exclude_folders()
    
    for exclude in exclude_folders:
        if exclude in folder_lower:
            return True
    return False

def should_skip_file(filename):
    """Check if file matches exclude patterns"""
    import fnmatch
    filename_lower = filename.lower()
    patterns = get_exclude_patterns()
    
    for pattern in patterns:
        if fnmatch.fnmatch(filename_lower, pattern):
            return True
    return False

def should_process_file(filename, file_size_bytes=None):
    """
    Check if file should be processed based on all filters
    
    Args:
        filename: Name of the file
        file_size_bytes: Optional file size in bytes
        
    Returns:
        True if file should be processed, False otherwise
    """
    # Check extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in get_video_extensions():
        return False
    
    # Check exclude patterns
    if should_skip_file(filename):
        return False
    
    # Check for sample files (additional check)
    if ADDON.getSetting('exclude_samples') == 'true':
        filename_lower = filename.lower()
        if 'sample' in filename_lower:
            return False
    
    # Check minimum file size
    if file_size_bytes is not None:
        try:
            min_size_mb = int(ADDON.getSetting('min_file_size'))
            if min_size_mb > 0:
                min_size_bytes = min_size_mb * 1024 * 1024
                if file_size_bytes < min_size_bytes:
                    return False
        except (ValueError, TypeError):
            pass
    
    return True

def get_folder_depth(path, base_path):
    """
    Calculate folder depth relative to base path
    
    Args:
        path: Current path
        base_path: Base path to calculate from
        
    Returns:
        Depth as integer (0 for base path)
    """
    # Normalize paths
    path = path.rstrip('/').rstrip('\\')
    base_path = base_path.rstrip('/').rstrip('\\')
    
    if path == base_path:
        return 0
    
    relative = path[len(base_path):].strip('/').strip('\\')
    if not relative:
        return 0
    
    # Count separators
    return relative.count('/') + relative.count('\\') + 1

# --- End Settings ---


# --- Rate Limiting for Dahmer Movies ---
DAHMER_RATE_LIMITER = {'last_request': 0, 'lock': Lock()}
DAHMER_REQUEST_INTERVAL = 2  # 2 seconds between requests to Dahmer Movies
# --- End Rate Limiting ---

# Base URL and Handle for Kodi plugin (protected for standalone imports)
try:
    _BASE_URL = sys.argv[0]
    _HANDLE = int(sys.argv[1])
except (IndexError, ValueError):
    _BASE_URL = ''
    _HANDLE = -1  # Standalone mode

ADDON = xbmcaddon.Addon()
ADDON_PROFILE_DIR = ADDON.getAddonInfo('profile')
PROFILES_FILE = os.path.join(ADDON_PROFILE_DIR, 'profiles.json')

# --- Profile Management ---
if not xbmcvfs.exists(ADDON_PROFILE_DIR):
    xbmcvfs.mkdirs(ADDON_PROFILE_DIR)

# Profile caching - avoid repeated file I/O
_PROFILES_CACHE = None
_PROFILES_MTIME = 0

def read_profiles():
    """Read profiles from JSON file with caching"""
    global _PROFILES_CACHE, _PROFILES_MTIME
    
    if not xbmcvfs.exists(PROFILES_FILE):
        return []
    
    # Get current modification time
    try:
        stat = xbmcvfs.Stat(PROFILES_FILE)
        current_mtime = stat.st_mtime()
        
        # Return cached if file unchanged
        if _PROFILES_CACHE is not None and current_mtime == _PROFILES_MTIME:
            return _PROFILES_CACHE
        
        # Load and cache
        with closing(xbmcvfs.File(PROFILES_FILE, 'r')) as f:
            content = f.read()
        
        _PROFILES_CACHE = json.loads(content)
        _PROFILES_MTIME = current_mtime
        return _PROFILES_CACHE
    except:
        return []

def write_profiles(profiles):
    """Write profiles to JSON file and invalidate cache"""
    global _PROFILES_CACHE, _PROFILES_MTIME
    
    with closing(xbmcvfs.File(PROFILES_FILE, 'w')) as f:
        f.write(json.dumps(profiles, indent=4))
    
    # Invalidate cache
    _PROFILES_CACHE = None
    _PROFILES_MTIME = 0

def get_profile_by_id(profile_id):
    for p in read_profiles():
        if p['id'] == profile_id:
            return p
    return None

# --- SSL Proxy ---
_SSL_PROXY = None
_SSL_PROXY_LOCK = threading.Lock()

def get_ssl_proxy():
    """
    Get or create SSL proxy instance
    
    Returns:
        SSLProxyServer instance or None if disabled/failed
    """
    global _SSL_PROXY
    
    # Check if proxy is enabled
    if ADDON.getSetting('enable_ssl_proxy') != 'true':
        return None
    
    with _SSL_PROXY_LOCK:
        # Return existing instance if already running
        if _SSL_PROXY is not None and _SSL_PROXY.is_running():
            return _SSL_PROXY
        
        # Create and start new instance
        try:
            from ssl_proxy import SSLProxyServer
            
            # Get port from settings
            try:
                port = int(ADDON.getSetting('ssl_proxy_port') or 8765)
            except (ValueError, TypeError):
                port = 8765
            
            xbmc.log(f"[SSL Proxy] Initializing proxy on port {port}", xbmc.LOGINFO)
            
            _SSL_PROXY = SSLProxyServer(port)
            if _SSL_PROXY.start():
                xbmc.log(f"[SSL Proxy] Proxy started successfully on port {_SSL_PROXY.port}", xbmc.LOGINFO)
                return _SSL_PROXY
            else:
                xbmc.log("[SSL Proxy] Failed to start proxy", xbmc.LOGERROR)
                _SSL_PROXY = None
                return None
                
        except Exception as e:
            xbmc.log(f"[SSL Proxy] Error initializing proxy: {e}", xbmc.LOGERROR)
            import traceback
            xbmc.log(f"[SSL Proxy] Traceback: {traceback.format_exc()}", xbmc.LOGERROR)
            _SSL_PROXY = None
            return None

def stop_ssl_proxy():
    """Stop SSL proxy if running"""
    global _SSL_PROXY
    
    with _SSL_PROXY_LOCK:
        if _SSL_PROXY is not None:
            _SSL_PROXY.stop()
            _SSL_PROXY = None
            xbmc.log("[SSL Proxy] Proxy stopped", xbmc.LOGINFO)

# --- Host Verification ---
def mark_profile_offline(profile_id, is_offline):
    """
    Update profile's offline status
    
    Args:
        profile_id: ID of the profile to update
        is_offline: True to mark offline, False to mark online
    """
    profiles = read_profiles()
    updated = False
    
    for profile in profiles:
        if profile['id'] == profile_id:
            profile['offline'] = is_offline
            from datetime import datetime
            profile['last_checked'] = datetime.now().isoformat()
            updated = True
            break
    
    if updated:
        write_profiles(profiles)
        status = "OFFLINE" if is_offline else "ONLINE"
        xbmc.log(f"[Host Verifier] Marked profile {profile_id} as {status}", xbmc.LOGINFO)

def cleanup_offline_profile_cache(profile_id):
    """
    Remove cache file for offline profile
    
    Args:
        profile_id: ID of the offline profile
    """
    cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile_id}.json")
    if xbmcvfs.exists(cache_file):
        try:
            xbmcvfs.delete(cache_file)
            xbmc.log(f"[Host Verifier] Cleaned up cache for offline profile {profile_id}", xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"[Host Verifier] Error cleaning cache for profile {profile_id}: {e}", xbmc.LOGERROR)

def verify_hosts_on_startup():
    """
    Verify all hosts on plugin startup
    Updates offline flags and cleans up caches for offline hosts
    """
    # Check if verification is enabled
    if ADDON.getSetting('verify_hosts_startup') != 'true':
        return
    
    profiles = read_profiles()
    if not profiles:
        return
    
    xbmc.log("[Host Verifier] Starting host verification on startup", xbmc.LOGINFO)
    
    # Get timeout setting
    try:
        timeout = int(ADDON.getSetting('host_check_timeout'))
    except (ValueError, TypeError):
        timeout = 5  # Default 5 seconds
    
    # Import host verifier
    try:
        from host_verifier import verify_all_profiles
    except ImportError as e:
        xbmc.log(f"[Host Verifier] Could not import host_verifier: {e}", xbmc.LOGERROR)
        return
    
    # Verify all profiles
    results = verify_all_profiles(profiles, timeout)
    
    # Update profiles and cleanup caches
    auto_cleanup = ADDON.getSetting('auto_cleanup_offline') == 'true'
    
    for profile_id, is_online in results.items():
        is_offline = not is_online
        mark_profile_offline(profile_id, is_offline)
        
        if is_offline and auto_cleanup:
            cleanup_offline_profile_cache(profile_id)
    
    online_count = sum(1 for status in results.values() if status)
    offline_count = len(results) - online_count
    
    xbmc.log(f"[Host Verifier] Verification complete: {online_count} online, {offline_count} offline", xbmc.LOGINFO)

def recheck_profile_availability(profile_id):
    """
    Manually re-check a single profile's availability
    
    Args:
        profile_id: ID of the profile to check
    """
    profile = get_profile_by_id(profile_id)
    if not profile:
        return
    
    # Get timeout setting
    try:
        timeout = int(ADDON.getSetting('host_check_timeout'))
    except (ValueError, TypeError):
        timeout = 5
    
    # Import and verify
    try:
        from host_verifier import verify_profile
        is_online = verify_profile(profile, timeout)
        mark_profile_offline(profile_id, not is_online)
        
        status = "online" if is_online else "offline"
        xbmcgui.Dialog().notification(
            'Host Check',
            f"Profile '{profile.get('name')}' is {status}",
            xbmcgui.NOTIFICATION_INFO,
            3000
        )
    except Exception as e:
        xbmc.log(f"[Host Verifier] Error rechecking profile {profile_id}: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            'Host Check Error',
            f"Could not check profile availability",
            xbmcgui.NOTIFICATION_ERROR,
            3000
        )

# --- TMDb API Logic ---
def get_tmdb_api_key():
    return ADDON.getSetting('tmdb_api_key')

def select_best_match(results, expected_title, expected_year=None):
    """
    Select best matching result from TMDb search results using multiple criteria
    
    Args:
        results: List of TMDb search results
        expected_title: Title extracted from filename
        expected_year: Year extracted from filename (optional)
        
    Returns:
        Best matching result dict or None
    """
    from difflib import SequenceMatcher
    
    if not results:
        return None
    
    # If only one result, return it
    if len(results) == 1:
        return results[0]
    
    best_match = None
    best_score = 0
    
    # Check top 5 results for best match
    for result in results[:5]:
        score = 0
        
        # Get titles (works for both movies and TV shows)
        result_title = result.get('title') or result.get('name', '')
        result_original_title = result.get('original_title') or result.get('original_name', '')
        
        # Calculate title similarity (0-1 ratio)
        title_similarity = SequenceMatcher(None, expected_title.lower(), result_title.lower()).ratio()
        original_similarity = SequenceMatcher(None, expected_title.lower(), result_original_title.lower()).ratio()
        
        # Use best similarity between title and original title
        max_similarity = max(title_similarity, original_similarity)
        score += max_similarity * 50  # Max 50 points for title match
        
        # Year matching (if available)
        if expected_year:
            result_date = result.get('release_date') or result.get('first_air_date', '')
            if result_date:
                try:
                    result_year = int(result_date.split('-')[0])
                    year_diff = abs(int(expected_year) - result_year)
                    
                    if year_diff == 0:
                        score += 30  # Exact year match
                    elif year_diff == 1:
                        score += 20  # Off by 1 year (common for release dates)
                    elif year_diff <= 3:
                        score += 10  # Close enough
                    else:
                        score -= 20  # Wrong year penalty
                except (ValueError, IndexError):
                    pass
        
        # Popularity bonus (prevents matching to obscure results)
        popularity = result.get('popularity', 0)
        if popularity > 10:
            score += 10
        elif popularity > 5:
            score += 5
        
        # Vote average bonus (quality indicator)
        vote_average = result.get('vote_average', 0)
        if vote_average > 7:
            score += 5
        elif vote_average > 5:
            score += 2
        
        # Track best match
        if score > best_score:
            best_score = score
            best_match = result
    
    # Get minimum confidence threshold from settings
    try:
        min_confidence = int(ADDON.getSetting('min_confidence_score'))
    except (ValueError, TypeError):
        min_confidence = 30  # Default threshold
    
    # Require minimum confidence
    if best_score < min_confidence:
        result_title = best_match.get('title') or best_match.get('name', 'Unknown') if best_match else 'None'
        xbmc.log(f"[TMDb Match] No confident match for '{expected_title}' (best: '{result_title}', score: {best_score})", 
                level=xbmc.LOGWARNING)
        return None
    
    result_title = best_match.get('title') or best_match.get('name', 'Unknown')
    xbmc.log(f"[TMDb Match] Matched '{expected_title}' → '{result_title}' (score: {best_score})", 
            level=xbmc.LOGINFO)
    
    return best_match

def remove_common_prefixes(title):
    """Remove common prefixes that might interfere with TMDb search"""
    prefixes = ['The ', 'A ', 'An ', 'Le ', 'La ', 'Les ', 'El ', 'Los ', 'Las ']
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):]
    return title

def extract_original_title(title):
    """Try to extract original/alternative title from filename patterns"""
    # Pattern: "English Title AKA Original Title"
    aka_match = re.search(r'(.+?)\s+(?:AKA|aka|a\.k\.a\.)\s+(.+)', title, re.IGNORECASE)
    if aka_match:
        return aka_match.group(2).strip()
    
    return None

def fetch_metadata(title, year, media_type):
    """
    Fetch metadata from TMDb with caching support
    Optimized to use cache and reduce API calls from 3 to 1
    Includes request deduplication to prevent concurrent API calls for the same item
    """
    # Lazy imports
    from metadata_cache import get_cache
    import requests
    
    api_key = get_tmdb_api_key()
    if not api_key: 
        return None
    
    # Check if caching is enabled
    cache_enabled = ADDON.getSetting('enable_cache') == 'true'
    
    # Try cache first if enabled
    if cache_enabled:
        cache = get_cache()
        cached_metadata = cache.get(media_type, title, year)
        if cached_metadata:
            return cached_metadata

    # Deduplication Logic: Prevent concurrent API calls for the same item
    cache_key = f"{media_type}_{title}_{year}"
    
    must_wait = False
    fetch_event = None
    
    with _FETCH_LOCK:
        if cache_key in _FETCH_EVENTS:
            must_wait = True
            fetch_event = _FETCH_EVENTS[cache_key]
        else:
            # We are the first! specific event for this item
            fetch_event = threading.Event()
            _FETCH_EVENTS[cache_key] = fetch_event
            
    if must_wait:
        # Wait for the other thread to finish fetching
        fetch_event.wait(timeout=20) # Wait max 20s
        
        # After waiting, check cache again
        if cache_enabled:
            return cache.get(media_type, title, year)
        return None

    # We are the active fetcher. 
    try:
        return _fetch_metadata_internal(api_key, title, year, media_type, cache_enabled)
    finally:
        # Always clear the event so others can proceed (even if we failed)
        with _FETCH_LOCK:
            if cache_key in _FETCH_EVENTS:
                del _FETCH_EVENTS[cache_key]
        if fetch_event:
            fetch_event.set()

# Initialize locks at module level
_FETCH_LOCK = threading.Lock()
_FETCH_EVENTS = {}

def _fetch_metadata_internal(api_key, title, year, media_type, cache_enabled):
    import requests
    from metadata_cache import get_cache
    search_type = 'tv' if media_type == 'tv_show' else 'movie'
    
    # Retry logic for API calls
    # 0 retries = 1 attempt (Fastest) to 5 retries = 6 attempts (Robust)
    try:
        max_retries_setting = int(ADDON.getSetting('max_api_retries'))
    except:
        max_retries_setting = 0
        
    total_attempts = max_retries_setting + 1
    import time
    
    for attempt in range(total_attempts):
        try:
            # Step 1: Search for the media
            search_params = {
                'api_key': api_key, 
                'query': title, 
                'language': 'en-US'
            }
            if year: 
                search_params['year'] = year

            response = requests.get(
                f"{TMDB_BASE_URL}/search/{search_type}", 
                params=search_params, 
                timeout=15
            )
            
            if response.status_code == 429:
                wait_time = (attempt + 1) * 2
                xbmc.log(f"[TMDb] Rate limited during search for '{title}'. Retrying in {wait_time}s...", xbmc.LOGWARNING)
                time.sleep(wait_time)
                continue
                
            response.raise_for_status()
            results = response.json().get('results', [])
            
            if not results: 
                xbmc.log(f"[TMDb] No results found for '{title}' (year: {year})", xbmc.LOGINFO)
                return None
            
            tmdb_id = results[0]['id']
            
            # Step 2: Get details with videos in ONE API call using append_to_response
            details_params = {
                'api_key': api_key, 
                'language': 'en-US',
                'append_to_response': 'videos'  # Get videos in same request
            }
            
            details_response = requests.get(
                f"{TMDB_BASE_URL}/{search_type}/{tmdb_id}", 
                params=details_params, 
                timeout=15
            )
            
            if details_response.status_code == 429:
                wait_time = (attempt + 1) * 2
                xbmc.log(f"[TMDb] Rate limited during details fetch for '{title}'. Retrying in {wait_time}s...", xbmc.LOGWARNING)
                time.sleep(wait_time)
                continue

            details_response.raise_for_status()
            details = details_response.json()

            # Extract video/trailer info from appended response
            youtube_id = ''
            videos = details.get('videos', {}).get('results', [])
            for video in videos:
                if video.get('site') == 'YouTube' and video.get('type') == 'Trailer':
                    youtube_id = video.get('key', '')
                    break

            # Build trailer URL (Only YouTube)
            trailer_url = ''
            if youtube_id:
                trailer_url = f"plugin://plugin.video.youtube/play/?video_id={youtube_id}"

            # Extract release year
            date_str = details.get('release_date') or details.get('first_air_date') or ''
            release_year = 0
            if date_str and '-' in date_str:
                try: 
                    release_year = int(date_str.split('-')[0])
                except (ValueError, IndexError): 
                    release_year = 0

            # Build metadata structure
            info = {
                'title': details.get('title') or details.get('name'),
                'originaltitle': details.get('original_title') or details.get('original_name'),
                'year': release_year,
                'plot': details.get('overview'),
                'rating': details.get('vote_average'),
                'popularity': details.get('popularity'),
                'votes': details.get('vote_count'),
                'genre': ' / '.join([g['name'] for g in details.get('genres', [])]),
                'mediatype': search_type,
                'tmdb_id': tmdb_id,
                'trailer': trailer_url
            }
            
            art = {
                'poster': f"{TMDB_IMG_URL}{details.get('poster_path')}" if details.get('poster_path') else '',
                'fanart': f"https://image.tmdb.org/t/p/original{details.get('backdrop_path')}" if details.get('backdrop_path') else ''
            }
            
            metadata = {'info': info, 'art': art, 'tmdb_id': tmdb_id}
            
            # Cache the result if caching is enabled
            if cache_enabled:
                cache = get_cache()
                cache.set(media_type, title, metadata, year)
            
            return metadata

        except requests.RequestException as e:
            if attempt < total_attempts - 1:
                wait_time = (attempt + 1) * 2
                xbmc.log(f"[TMDb] Network error fetching '{title}': {e}. Retrying in {wait_time}s...", xbmc.LOGWARNING)
                time.sleep(wait_time)
            else:
                xbmc.log(f"[TMDb] Failed to fetch metadata for '{title}' after {total_attempts} attempts: {e}", xbmc.LOGERROR)
                return None

# --- Core Logic ---
def build_url(query):
    return _BASE_URL + "?" + urllib.parse.urlencode(query)

# Pre-compile regex patterns for performance
YEAR_PATTERNS = [
    re.compile(r'\((\d{4})\)'),
    re.compile(r'[\.\s_-](\d{4})[\.\s_-]'),
    re.compile(r'^(\d{4})[\.\s_-]'),
    re.compile(r'[\.\s_-](\d{4})$')
]

CLEAN_PATTERNS = [
    # Resolution and quality (match even if attached to words)
    re.compile(r'(2160p|1080p|720p|480p|360p|4K|UHD|HD|SD)', re.IGNORECASE),
    # Video codecs
    re.compile(r'\b(x264|x265|H\.?264|H\.?265|HEVC|AVC|10bit|8bit|HDR|HDR10|DV|DoVi)\b', re.IGNORECASE),
    # Source
    re.compile(r'\b(BluRay|BRRip|BDRip|WEBRip|WEB-DL|HDTV|DVDRip|DVD|REMUX|NF|AMZN|DSNP)\b', re.IGNORECASE),
    # Audio
    re.compile(r'\b(DTS-HD|DTS|DD|AAC|AC3|TrueHD|FLAC|Atmos|MA|5\.1|7\.1|2\.0)\b', re.IGNORECASE),
    # Release groups (usually at the end with dash)
    re.compile(r'-[A-Z0-9]+$', re.IGNORECASE),
    # Brackets and parentheses (except year)
    re.compile(r'\[.*?\]'),
    re.compile(r'\((?!\d{4}\)).*?\)'),
]

def clean_and_get_year(filename):
    """
    Extract title and year from filename
    Aggressively removes all quality indicators and release info
    """
    name_without_ext = os.path.splitext(filename)[0]
    
    # Step 1: Extract and remove year
    year = None
    for pattern in YEAR_PATTERNS:
        match = pattern.search(name_without_ext)
        if match:
            year = int(match.group(1))
            name_without_ext = pattern.sub(' ', name_without_ext, count=1)
            break
    
    # Step 2: Replace dots/dashes/underscores with spaces
    title = re.sub(r'[\._-]+', ' ', name_without_ext)
    
    # Step 3: Remove all quality tags
    for pattern in CLEAN_PATTERNS:
        title = pattern.sub(' ', title)
    
    # Step 4.0: Remove Season/Episode patterns (S01, E01, S01E01, 1x01, Season 1)
    # This is critical when extracting title from a Season folder name
    title = re.sub(r'\bS\d+E\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bS\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bSeason\s*\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\b\d+x\d+\b', ' ', title, flags=re.IGNORECASE)

    # Step 4: Remove common extra tags
    # Language tags
    title = re.sub(r'\b(CHINESE|KOREAN|JAPANESE|FRENCH|GERMAN|SPANISH|ITALIAN|RUSSIAN|HINDI)\b', ' ', title, flags=re.IGNORECASE)
    # Edition tags  
    title = re.sub(r'\b(DC|EXTENDED|UNRATED|REMASTERED|DIRECTORS\.?CUT|THEATRICAL)\b', ' ', title, flags=re.IGNORECASE)
    # Numbers with dots (like 5.1, 7.1, 2.0, H.265, etc.)
    title = re.sub(r'\b[0-9]+\.[0-9]+\b', ' ', title)
    # Single letters followed by numbers or vice versa (H 265, R 265, etc.) but preserve single letters if they might be part of title (rare)
    # We already removed Sxx, so S 03 won't match here unless spaced
    title = re.sub(r'\b[A-Za-z]\s+[0-9]+\b', ' ', title)
    title = re.sub(r'\b[0-9]+\s+[A-Za-z]\b', ' ', title)
    
    # Step 5: Remove release groups (ALL patterns)
    # Remove words with numbers in middle (B0MBARDiERS, R10Plus, etc.)
    title = re.sub(r'\b[A-Z]+[0-9]+[A-Z]+[A-Za-z0-9]*\b', ' ', title)
    # Remove CamelCase with lowercase i (TERMiNAL, PETRiFiED, AViATOR, etc.)
    title = re.sub(r'\b[A-Z]+[a-z]*[A-Z]+[a-z]*[A-Z]*[a-z]*\b', ' ', title)
    # Remove words with @ or special chars (Lee@C, etc.)
    title = re.sub(r'\b[A-Za-z]+[@#][A-Za-z]+\b', ' ', title)
    # Remove standard CamelCase
    title = re.sub(r'\b[a-z]+[A-Z][a-zA-Z]*\b', ' ', title)
    title = re.sub(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b', ' ', title)
    # Remove ALL CAPS words at the end (release groups)
    title = re.sub(r'\s+[A-Z][A-Z0-9]{2,}\s*$', ' ', title)
    
    # Step 6: Remove specific problematic words
    # Common false positives from quality tags
    problematic_words = ['True', 'WEB', 'ray', 'ATVP', 'KOGi', 'VERSION', 'Ctrl', 'seedpool', 'Blu', 'Cut', 'Arrow', 'Blood']
    for word in problematic_words:
        title = re.sub(rf'\b{word}\b', ' ', title, flags=re.IGNORECASE)
    
    # Step 7: Remove standalone short words and numbers at the end
    # This catches remaining tags like "R", "DL", etc.
    for _ in range(5):  # Repeat 5 times to catch multiple trailing tags
        title = re.sub(r'\s+[A-Z][A-Z0-9]{0,5}\s*$', ' ', title)  # Short CAPS words (up to 5 chars)
        title = re.sub(r'\s+[0-9]+\s*$', ' ', title)  # Numbers
        title = re.sub(r'\s+[a-z]{1,3}\s*$', ' ', title)  # Short lowercase (ray, etc.)
    # These are now part of _JUNK_PATTERN
    
    # Step 8: Remove rating tags (R10+, R10Plus, etc.)
    title = re.sub(r'\bR[0-9]+\+?\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bR[0-9]+Plus\b', ' ', title, flags=re.IGNORECASE)
    
    
    return title, year


def is_dahmer_movies_path(path):
    """
    DISABLED: This function caused too many false positives.
    
    Previously matched files with:
    - S01E01 patterns (matched ALL TV shows)
    - "dahmer" in path (matched "Monster: The Jeffrey Dahmer Story")
    - Quality indicators like 1080p, 720p (matched MOST movies)
    
    Dahmer Movies detection is now ONLY done in scan_http_parallel()
    based on server domain (a.111477.xyz or dahmermovies).
    """
    return False


def enforce_dahmer_rate_limit():
    """
    Enforce rate limiting for Dahmer Movies site access across all threads
    """
    with DAHMER_RATE_LIMITER['lock']:
        current_time = time.time()
        time_since_last = current_time - DAHMER_RATE_LIMITER['last_request']

        if time_since_last < DAHMER_REQUEST_INTERVAL:
            sleep_time = DAHMER_REQUEST_INTERVAL - time_since_last
            time.sleep(sleep_time)

        DAHMER_RATE_LIMITER['last_request'] = time.time()

def get_all_media(media_type, profile_id=None):
    """
    Get all media of specified type
    
    Args:
        media_type: 'movies' or 'tv_shows'
        profile_id: Optional - if provided, only return media from this server
    """
    aggregated_media = {}
    profiles = read_profiles()
    
    # Filter profiles if profile_id is specified (handle potential string/int mismatch)
    if profile_id:
        profiles = [p for p in profiles if str(p.get('id')) == str(profile_id)]
    
    for profile in profiles:
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile['id']}.json")
        if xbmcvfs.exists(cache_file):
            with closing(xbmcvfs.File(cache_file, 'r')) as f:
                media = json.loads(f.read())
            
            if media_type == 'movies' and isinstance(media.get('movies'), dict):
                for tmdb_id, movie_data in media.get('movies', {}).items():
                    if tmdb_id not in aggregated_media:
                        aggregated_media[tmdb_id] = {
                            'info': movie_data.get('info'),
                            'art': movie_data.get('art'),
                            'sources': []
                        }
                    for source in movie_data.get('sources', []):
                        source_copy = source.copy()
                        source_copy['profile_id'] = profile['id']
                        aggregated_media[tmdb_id]['sources'].append(source_copy)
            elif media_type == 'tv_shows' and isinstance(media.get('tv_shows'), dict):
                 for tmdb_id, show_data in media.get('tv_shows', {}).items():
                    if tmdb_id not in aggregated_media:
                        aggregated_media[tmdb_id] = show_data
                        # Store profile_id only on the first occurrence (maintains 1:1 mapping if filtering)
                        aggregated_media[tmdb_id]['profile_id'] = profile['id']
                    else:
                        # Logic for merging could go here, but for now just don't overwrite the original profile_id
                        pass

    return list(aggregated_media.values())

# --- Scanning Logic ---
def scan_library(profile_id, scan_mode='full'):
    """Scan a profile and update its library"""
    # Lazy imports
    from queue import Queue, Empty
    from concurrent.futures import ThreadPoolExecutor
    
    profile = get_profile_by_id(profile_id)
    if not profile:
        return
    
    api_key = get_tmdb_api_key()
    if not api_key:
        xbmcgui.Dialog().ok("API Key Missing", "Please enter your TMDb API key in the addon settings.")
        ADDON.openSettings()
        return

    dialog = xbmcgui.DialogProgress()
    dialog.create(f"Scanning Profile: {profile['name']}", 'Initializing...')

    cancel_event = threading.Event()
    results_container = {'paths': None}
    progress_queue = Queue()
    media_lock = threading.Lock()

    def _scan_runner():
        profile_type = profile.get('type', 'ftp')
        max_workers = int(ADDON.getSetting('parallel_connections'))
        
        paths = []
        try:
            if profile_type == 'ftp':
                paths = scan_ftp_parallel(profile, scan_mode, max_workers, cancel_event, progress_queue)
            elif profile_type == 'http':
                paths = scan_http_parallel(profile, scan_mode, max_workers, cancel_event, progress_queue)
            
            if not cancel_event.is_set():
                results_container['paths'] = paths
        except Exception as e:
            xbmc.log(f"Error in scan runner thread: {e}", level=xbmc.LOGERROR)
            results_container['paths'] = None 

    scan_thread = threading.Thread(target=_scan_runner)
    scan_thread.daemon = True  # Allow Kodi to close even if thread is running
    scan_thread.start()

    while scan_thread.is_alive():
        if dialog.iscanceled():
            cancel_event.set()
        try:
            progress = progress_queue.get(timeout=0.1)
            dialog.update(progress['percent'], f"{progress.get('line1', '')}\n{progress.get('line2', '')}")
        except Empty:
            pass
        time.sleep(0.1)
    
    # Wait for scan thread with timeout to avoid blocking
    scan_thread.join(timeout=2.0)  # Wait max 2 seconds
    
    # If thread is still alive after timeout, it will be terminated when Python exits
    # since we set it as daemon

    if cancel_event.is_set():
        dialog.close()
        return

    all_video_paths_on_server = results_container['paths']
    if all_video_paths_on_server is None:
        dialog.close()
        xbmcgui.Dialog().ok("Scan Failed", "Could not connect to the server. Check logs for details.")
        return

    dialog.update(50, 'Fetching metadata for new items...')
    cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile['id']}.json")
    media = {'movies': {}, 'tv_shows': {}}
    if scan_mode == 'incremental' and xbmcvfs.exists(cache_file):
        with closing(xbmcvfs.File(cache_file, 'r')) as f:
            media = json.loads(f.read())

    new_files_count = 0
    processed_files = 0
    total_files = len(all_video_paths_on_server)
    max_workers = int(ADDON.getSetting('parallel_connections'))

    def metadata_worker(path):
        # Check if this is a Dahmer Movies path that we should handle specially
        if is_dahmer_movies_path(path):
            # Handle Dahmer Movies specific path structure
            filename = os.path.basename(urllib.parse.unquote(path))

            # Try to extract season and episode information from filename
            # Look for patterns like S01E01, S02E05 in the filename
            season_episode_match = re.search(r'([sS](\d{2})[eE](\d{2}))', filename, re.IGNORECASE)
            if season_episode_match:
                show_dir = os.path.dirname(path)
                show_name, year = clean_and_get_year(os.path.basename(urllib.parse.unquote(show_dir)))

                # Extract season and episode numbers
                full_match = season_episode_match.group(1)  # Full match like S01E01
                season_num = season_episode_match.group(2)  # S01 -> 01
                episode_num = season_episode_match.group(3)  # E01 -> 01

                metadata = fetch_metadata(show_name, year, 'tv_show')
                if metadata:
                    # Handle the case where lstrip results in empty string (e.g., "00" becomes "")
                    # Convert to integers, handling the case where lstrip results in empty string
                    try:
                        season_val = int(season_num.lstrip('0')) if season_num.lstrip('0') else 1
                        episode_val = int(episode_num.lstrip('0')) if episode_num.lstrip('0') else 1
                        return path, metadata, 'tv_show', {'season': season_val, 'episode': episode_val}
                    except ValueError:
                        # In case of any conversion error, default to 1
                        return path, metadata, 'tv_show', {'season': 1, 'episode': 1}

            # If no season/episode pattern, try to handle as movie
            else:
                title, year = clean_and_get_year(filename)
                if title:
                    metadata = fetch_metadata(title, year, 'movie')
                    return path, metadata, 'movie', None
        else:
            # 1. Check for season folder structure
            match = re.search(r'/(Season|Sezon|Sezonul|S|SO)[\s._]?(\d+)/', path, re.IGNORECASE)
            if match:
                show_folder_path = path[:match.start(0)]
                show_name, year = clean_and_get_year(os.path.basename(urllib.parse.unquote(show_folder_path)))
                metadata = fetch_metadata(show_name, year, 'tv_show')
                # Pass the match object through
                if metadata:
                    return path, metadata, 'tv_show', {'folder_match': match}

            filename = os.path.basename(urllib.parse.unquote(path))
            # 2. Check for filename patterns (e.g., S01E01, 1x01)
            tv_match = re.search(r'(?:[._\s-]|^)(?:S(\d{1,2})E(\d{1,2})|(\d{1,2})x(\d{1,2}))', filename, re.IGNORECASE)
            if tv_match:
                # Show name is the parent directory
                # Check if parent directory is a season folder (e.g., "Season 1", "Season%201")
                parent_dir = os.path.dirname(path)
                parent_dir_name = os.path.basename(urllib.parse.unquote(parent_dir))
                
                # Check if parent is a season folder
                if re.search(r'^(Season|Sezon|Sezonul|S|SO)[\s._]?\d+$', parent_dir_name, re.IGNORECASE):
                    # Parent is a season folder, go up one more level to get show name
                    show_dir = os.path.dirname(parent_dir)
                    show_name, year = clean_and_get_year(os.path.basename(urllib.parse.unquote(show_dir)))
                else:
                    # Parent is the show folder directly
                    show_name, year = clean_and_get_year(parent_dir_name)
                metadata = fetch_metadata(show_name, year, 'tv_show')

                season_num = tv_match.group(1) or tv_match.group(3)
                episode_num = tv_match.group(2) or tv_match.group(4)

                # Pass the extracted numbers through if metadata was found
                # Ensure proper handling of leading zeros
                if season_num and episode_num:
                    # Convert to integers, handling the case where lstrip results in empty string
                    try:
                        season_val = int(season_num.lstrip('0')) if season_num.lstrip('0') else 1
                        episode_val = int(episode_num.lstrip('0')) if episode_num.lstrip('0') else 1
                        return path, metadata, 'tv_show', {'season': season_val, 'episode': episode_val}
                    except ValueError:
                        # In case of any conversion error, default to 1
                        return path, metadata, 'tv_show', {'season': 1, 'episode': 1}
                else:
                    return path, metadata, 'tv_show', {'season': 1, 'episode': 1}

            # 3. Fallback to movie
            title, year = clean_and_get_year(filename)
            if title:
                metadata = fetch_metadata(title, year, 'movie')
                if metadata:
                    # Update cache with file path for JLOM integration
                    metadata['file_path'] = path
                    from metadata_cache import get_cache
                    cache = get_cache()
                    cache.set('movie', title, metadata, year)
                return path, metadata, 'movie', None

        return path, None, None, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        from concurrent.futures import as_completed
        future_to_path = {executor.submit(metadata_worker, path): path for path in all_video_paths_on_server}
        for future in as_completed(future_to_path):
            if cancel_event.is_set() or dialog.iscanceled():
                for f in future_to_path:
                    f.cancel()
                break

            path, metadata, media_type, context = future.result()
            processed_files += 1
            percentage = 50 + int((processed_files / total_files) * 50) if total_files > 0 else 50
            dialog.update(percentage, f"Processing: {os.path.basename(path)}")

            if not metadata or not metadata.get('tmdb_id'):
                continue

            if not metadata or not metadata.get('tmdb_id'):
                continue

            tmdb_id = str(metadata['tmdb_id'])

            # CRITICAL: Synchronize access to shared 'media' dictionary to prevent race conditions
            # Without this, concurrent threads overwrote season lists, causing missing episodes
            with media_lock:
                if media_type == 'tv_show':
                    if tmdb_id not in media['tv_shows']:
                        media['tv_shows'][tmdb_id] = {'seasons': {}, 'info': metadata['info'], 'art': metadata['art']}

                    season_name = None
                    if context and 'folder_match' in context:
                        match = context['folder_match']
                        season_group = match.group(1)
                        season_number = match.group(2)
                        if season_group.upper() in ['S', 'SO']:
                            season_name = f"Season {season_number.zfill(2)}"
                        else:
                            season_name = f"{season_group.capitalize()} {season_number.zfill(2)}"
                    
                    elif context and 'season' in context:
                        season_number = context['season']
                        season_name = f"Season {str(season_number).zfill(2)}"

                    if season_name:
                        if season_name not in media['tv_shows'][tmdb_id]['seasons']:
                            media['tv_shows'][tmdb_id]['seasons'][season_name] = []
                        
                        if path not in media['tv_shows'][tmdb_id]['seasons'][season_name]:
                            media['tv_shows'][tmdb_id]['seasons'][season_name].append(path)
                            new_files_count += 1
                
                elif media_type == 'movie':
                    source_entry = {'path': path, 'filename': os.path.basename(path)}
                    if tmdb_id not in media['movies']:
                        media['movies'][tmdb_id] = {'info': metadata['info'], 'art': metadata['art'], 'sources': [source_entry]}
                        new_files_count += 1
                    else:
                        if not any(s['path'] == path for s in media['movies'][tmdb_id]['sources']):
                            media['movies'][tmdb_id]['sources'].append(source_entry)
                            new_files_count += 1

    dialog.close()

    if not cancel_event.is_set():
        with closing(xbmcvfs.File(cache_file, 'w')) as f:
            f.write(json.dumps(media, indent=4))
        
        msg = f"Added/Updated {new_files_count} files." if scan_mode == 'incremental' else f"Library built successfully."
        xbmcgui.Dialog().ok('Scan Complete', msg)
        xbmc.executebuiltin('Container.Refresh')

def get_existing_paths_from_cache(cache_file):
    existing_paths = set()
    if xbmcvfs.exists(cache_file):
        with closing(xbmcvfs.File(cache_file, 'r')) as f:
            media = json.loads(f.read())
        for movie_data in media.get('movies', {}).values():
            for source in movie_data.get('sources',[]): existing_paths.add(source['path'])
        for show_data in media.get('tv_shows', {}).values():
            for season in show_data.get('seasons', {}).values(): existing_paths.update(season)
    return existing_paths

def scan_ftp_parallel(profile, scan_mode, max_workers, cancel_event, progress_queue):
    # Lazy imports - only load when FTP scanning
    from ftplib import FTP
    from queue import Queue
    from concurrent.futures import ThreadPoolExecutor
    
    results = []
    results_lock = threading.Lock()
    q = Queue()
    q.put(profile['path'])
    scanned_paths = {profile['path']}
    scanned_paths_lock = threading.Lock()
    
    connection_errors = 0
    connection_errors_lock = threading.Lock()

    def worker():
        nonlocal connection_errors
        ftp = None
        try:
            user = 'anonymous' if profile['anonymous'] else profile['user']
            password = '' if profile['anonymous'] else profile['pass']
            timeout = int(ADDON.getSetting('connection_timeout'))
            ftp = FTP(profile['host'], timeout=timeout)
            ftp.login(user, password)
        except Exception as e:
            with connection_errors_lock:
                connection_errors += 1
            xbmc.log(f"FTP worker failed to connect: {e}", level=xbmc.LOGERROR)
            return

        # Get scanning settings
        max_depth = int(ADDON.getSetting('max_folder_depth'))
        use_mlsd = ADDON.getSetting('ftp_use_mlsd') == 'true'
        base_path = profile['path']

        while not cancel_event.is_set():
            try:
                current_path = q.get(timeout=1)
            except Empty:
                break

            try:
                # Check depth limit
                if max_depth > 0:
                    depth = get_folder_depth(current_path, base_path)
                    if depth >= max_depth:
                        xbmc.log(f"Skipping {current_path} - max depth {max_depth} reached", level=xbmc.LOGDEBUG)
                        q.task_done()
                        continue

                with scanned_paths_lock:
                    total_discovered = len(scanned_paths)
                    scanned_count = total_discovered - q.qsize()
                    if total_discovered > 0:
                        percentage = int((scanned_count / total_discovered) * 49)
                        with results_lock:
                            line1 = f"Found {len(results)} video files..."
                        line2 = f"Scanning: {current_path}"
                        progress_queue.put({'percent': percentage, 'line1': line1, 'line2': line2})

                # Try MLSD first (faster, provides size info)
                items_processed = False
                if use_mlsd:
                    try:
                        for name, facts in ftp.mlsd(current_path):
                            if cancel_event.is_set():
                                break
                            
                            if name in ['.', '..']:
                                continue
                            
                            item_type = facts.get('type', 'file')
                            full_path = os.path.join(current_path, name).replace('\\', '/')
                            
                            if item_type == 'dir':
                                # Check if folder should be excluded
                                if should_skip_folder(name):
                                    xbmc.log(f"Skipping excluded folder: {name}", level=xbmc.LOGDEBUG)
                                    continue
                                
                                with scanned_paths_lock:
                                    if full_path not in scanned_paths:
                                        scanned_paths.add(full_path)
                                        q.put(full_path)
                            
                            elif item_type == 'file':
                                # Get file size from MLSD
                                try:
                                    file_size = int(facts.get('size', 0))
                                except (ValueError, TypeError):
                                    file_size = None
                                
                                # Check if file should be processed
                                if should_process_file(name, file_size):
                                    with results_lock:
                                        results.append(full_path)
                                else:
                                    xbmc.log(f"Skipping file: {name} (filtered)", level=xbmc.LOGDEBUG)
                        
                        items_processed = True
                    except Exception as e:
                        xbmc.log(f"MLSD failed, falling back to NLST: {e}", level=xbmc.LOGDEBUG)
                        items_processed = False

                # Fallback to NLST if MLSD not supported or failed
                if not items_processed:
                    items = ftp.nlst(current_path)
                    for item_name in items:
                        if cancel_event.is_set():
                            break
                        
                        full_path = os.path.join(current_path, os.path.basename(item_name)).replace('\\', '/')
                        basename = os.path.basename(item_name)
                        
                        # Check if it's a video file
                        if any(full_path.lower().endswith(ext) for ext in get_video_extensions()):
                            # Check if file should be processed (no size info with NLST)
                            if should_process_file(basename):
                                with results_lock:
                                    results.append(full_path)
                            else:
                                xbmc.log(f"Skipping file: {basename} (filtered)", level=xbmc.LOGDEBUG)
                        
                        # Check if it's a directory (no extension)
                        elif '.' not in basename:
                            # Check if folder should be excluded
                            if should_skip_folder(basename):
                                xbmc.log(f"Skipping excluded folder: {basename}", level=xbmc.LOGDEBUG)
                                continue
                            
                            with scanned_paths_lock:
                                if full_path not in scanned_paths:
                                    scanned_paths.add(full_path)
                                    q.put(full_path)
            
            except Exception as e:
                xbmc.log(f"FTP scan error in path {current_path}: {e}", level=xbmc.LOGWARNING)
            finally:
                q.task_done()
        
        if ftp:
            try:
                ftp.quit()
            except:
                pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker) for _ in range(max_workers)]
        
        # Wait for futures but exit early if canceled
        for future in futures:
            if cancel_event.is_set():
                break  # Don't wait for remaining futures
            try:
                future.result(timeout=1.0)  # Wait max 1 second per future
            except Exception:
                pass  # Ignore errors if canceling
    
    # Don't wait for queue if canceled
    if not cancel_event.is_set():
        q.join()

    if not cancel_event.is_set() and connection_errors == max_workers:
        raise ConnectionError(f"All scanning threads failed to connect to {profile['host']}.")

    if cancel_event.is_set(): return None

    if scan_mode == 'incremental':
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile['id']}.json")
        existing_paths = get_existing_paths_from_cache(cache_file)
        results = [p for p in results if p not in existing_paths]

    return results

def parse_dahmer_movies_links(html_content):
    """
    Parse HTML content from Dahmer Movies site to extract links with file sizes.
    Based on the parsing logic from dahmermovies.js
    """
    from bs4 import BeautifulSoup
    import re

    soup = BeautifulSoup(html_content, 'html.parser')
    links = []

    # Parse table rows to get both links and file sizes
    rows = soup.find_all('tr')

    for row in rows:
        # Extract link from the row
        link = row.find('a')
        if not link:
            continue

        href = link.get('href', '')
        text = link.get_text().strip()

        # Skip parent directory and empty links
        if not text or href == '../' or text == '../':
            continue

        # Extract file size from the same row - try multiple patterns
        size = None

        # Pattern 1: DahmerMovies specific - data-sort attribute with byte size
        td_with_data_sort = row.find('td', attrs={'data-sort': True})
        if td_with_data_sort and td_with_data_sort.get_text().strip():
            size = td_with_data_sort.get_text().strip()

        # Pattern 2: Standard Apache directory listing with filesize class
        if not size:
            td_filesize = row.find('td', class_='filesize')
            if td_filesize:
                size = td_filesize.get_text().strip()

        # Pattern 3: Look for size in any td element after the link (formatted sizes)
        if not size:
            all_tds = row.find_all('td')
            for td in all_tds:
                td_text = td.get_text().strip()
                if re.search(r'(\d+(?:\.\d+)?\s*(?:GB|MB|KB|B|bytes?))', td_text, re.IGNORECASE):
                    size = td_text
                    break

        # Pattern 4: Look for size anywhere in the row (more permissive)
        if not size:
            row_text = row.get_text()
            size_match = re.search(r'(\d+(?:\.\d+)?\s*(?:GB|MB|KB|B|bytes?))', row_text, re.IGNORECASE)
            if size_match:
                size = size_match.group(1).strip()

        links.append({'text': text, 'href': href, 'size': size})

    # Fallback to simple link parsing if table parsing fails
    if not links:
        for link in soup.find_all('a'):
            href = link.get('href', '')
            text = link.get_text().strip()
            if text and href and href != '../' and text != '../':
                links.append({'text': text, 'href': href, 'size': None})

    return links


def scan_http_parallel(profile, scan_mode, max_workers, cancel_event, progress_queue):
    # Lazy imports - only load when HTTP scanning
    import requests
    from bs4 import BeautifulSoup
    from queue import Queue
    from concurrent.futures import ThreadPoolExecutor
    
    results = []
    results_lock = threading.Lock()
    q = Queue()
    base_url = profile['host']
    start_path = profile['path']
    start_url = base_url.rstrip('/') + '/' + start_path.lstrip('/')
    q.put(start_url)
    scanned_urls = {start_url}
    scanned_urls_lock = threading.Lock()

    connection_errors = 0
    connection_errors_lock = threading.Lock()
    
    # Extract base domain for validation
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    
    def is_same_domain(url):
        """Check if URL belongs to the same domain as base_url"""
        try:
            parsed = urllib.parse.urlparse(url)
            url_domain = parsed.netloc.lower()
            
            # If URL has a domain (absolute URL), it MUST match base_domain exactly
            if url_domain:
                is_same = url_domain == base_domain
                if not is_same:
                    xbmc.log(f"[Domain Check] Rejecting external domain: {url_domain} != {base_domain}", level=xbmc.LOGDEBUG)
                return is_same
            
            # Relative URLs (no domain) are allowed
            return True
        except Exception as e:
            xbmc.log(f"[Domain Check] Error parsing URL {url}: {e}", level=xbmc.LOGWARNING)
            return False

    def worker():
        nonlocal connection_errors
        auth = None
        if not profile['anonymous']:
            auth = requests.auth.HTTPBasicAuth(profile['user'], profile['pass'])

        # Get scanning settings
        max_depth = int(ADDON.getSetting('max_folder_depth'))
        use_head = ADDON.getSetting('http_use_head') == 'true'
        timeout = int(ADDON.getSetting('connection_timeout'))
        base_path = start_path

        # Check if this is a Dahmer Movies site (exact domain match)
        is_dahmer_movies_profile = 'a.111477.xyz' in profile['host'] or 'dahmermovies' in profile['host'].lower()

        # Initialize proxy rotation if enabled globally and profile has proxy list
        proxy_rotator = None
        proxy_enabled = ADDON.getSetting('enable_proxy_rotation') == 'true'
        
        if proxy_enabled and profile.get('proxy_list'):
            try:
                from proxy_manager import ProxyRotator
                proxy_rotator = ProxyRotator(profile['proxy_list'])
                xbmc.log(f"[HTTP Scan] Proxy rotation enabled with {len(profile['proxy_list'])} proxies", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[HTTP Scan] Failed to initialize proxy rotation: {e}", xbmc.LOGWARNING)
        elif not proxy_enabled and profile.get('proxy_list'):
            xbmc.log(f"[HTTP Scan] Proxy list configured but proxy rotation disabled in settings", xbmc.LOGINFO)

        # SSL Verification setting - Apply GLOBALLY to worker
        verify_ssl = ADDON.getSetting('verify_ssl') == 'true'
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        try:
            with requests.Session() as session:
                session.auth = auth
                session.verify = verify_ssl
                
                # Set proxy if available
                if proxy_rotator:
                    proxy_dict = proxy_rotator.get_next_proxy()
                    if proxy_dict:
                        session.proxies.update(proxy_dict)
                        xbmc.log(f"[HTTP Scan] Using proxy for initial connection", xbmc.LOGDEBUG)
                
                # Set a more compatible User-Agent for Dahmer Movies site
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Cache-Control': 'max-age=0'
                })

                # Check if this is a Dahmer Movies site and add delays before initial request
                if is_dahmer_movies_profile:
                    enforce_dahmer_rate_limit()  # Use the global rate limiter for initial request too

                # Try initial connection with proxy rotation if needed
                max_retries = 3 if proxy_rotator else 1
                response = None
                for attempt in range(max_retries):
                    try:
                        response = session.get(start_url, timeout=timeout)
                        if response.status_code == 429:
                            xbmc.log(f"Rate limited at start URL: {start_url}. Waiting before retry...", level=xbmc.LOGWARNING)
                            import time
                            time.sleep(15)  # Wait 15 seconds before retry
                            response = session.get(start_url, timeout=30)  # Retry once
                        response.raise_for_status()
                        break  # Success
                    except requests.RequestException as e:
                        if proxy_rotator and attempt < max_retries - 1:
                            # Mark proxy as failed and try next
                            proxy_rotator.mark_proxy_failed(session.proxies)
                            next_proxy = proxy_rotator.get_next_proxy()
                            if next_proxy:
                                session.proxies.update(next_proxy)
                                xbmc.log(f"[HTTP Scan] Proxy failed, rotating to next proxy", xbmc.LOGWARNING)
                            else:
                                # No more proxies, try direct
                                session.proxies.clear()
                                xbmc.log(f"[HTTP Scan] All proxies failed, trying direct connection", xbmc.LOGWARNING)
                        else:
                            raise  # Re-raise on last attempt
                
                if not response:
                    raise requests.RequestException("Failed to connect after all retries")
                    
        except requests.RequestException as e:
            with connection_errors_lock:
                connection_errors += 1
            xbmc.log(f"HTTP worker failed to connect: {e}", level=xbmc.LOGERROR)
            return

        with requests.Session() as session:
            session.auth = auth
            session.verify = verify_ssl
            # Set a more compatible User-Agent for Dahmer Movies site
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            })

            # Add small delay after session setup for Dahmer site
            if is_dahmer_movies_profile:
                import time
                time.sleep(0.5)  # Small delay after session setup

            while not cancel_event.is_set():
                try:
                    current_url = q.get(timeout=1)
                except Empty:
                    break

                try:
                    # Check depth limit
                    if max_depth > 0:
                        current_path = urllib.parse.urlparse(current_url).path
                        depth = get_folder_depth(current_path, base_path)
                        if depth >= max_depth:
                            xbmc.log(f"Skipping {current_url} - max depth {max_depth} reached", level=xbmc.LOGDEBUG)
                            q.task_done()
                            continue
                    with scanned_urls_lock:
                        total_discovered = len(scanned_urls)
                        scanned_count = total_discovered - q.qsize()
                        if total_discovered > 0:
                            percentage = int((scanned_count / total_discovered) * 49)
                            with results_lock:
                                line1 = f"Found {len(results)} video files..."
                            line2 = f"Scanning: {urllib.parse.unquote(current_url)}"
                            progress_queue.put({'percent': percentage, 'line1': line1, 'line2': line2})

                    # Check if this is a Dahmer Movies site (exact domain match)
                    is_dahmer_movies = 'a.111477.xyz' in current_url or 'dahmermovies' in current_url.lower()
                    if is_dahmer_movies:
                        enforce_dahmer_rate_limit()  # Use the global rate limiter

                    response = session.get(current_url, timeout=30)
                    if response.status_code == 429:  # Too Many Requests
                        xbmc.log(f"Rate limited by server: {current_url}. Waiting before retry...", level=xbmc.LOGWARNING)
                        import time
                        time.sleep(10)  # Wait 10 seconds before retry
                        response = session.get(current_url, timeout=30)  # Retry once
                    response.raise_for_status()
                    if response.status_code == 429:  # If still rate limited after retry
                        xbmc.log(f"Still rate limited after retry: {current_url}. Skipping...", level=xbmc.LOGWARNING)
                        continue  # Skip this URL and continue with the next

                    # Check if this is a Dahmer Movies site by looking for specific patterns
                    is_dahmer_movies = 'a.111477.xyz' in current_url or 'dahmer' in current_url.lower()

                    if is_dahmer_movies:
                        # Use the enhanced Dahmer Movies parsing
                        dahmer_links = parse_dahmer_movies_links(response.text)

                        # Process the links found with Dahmer Movies parsing
                        processed_hrefs = set()
                        for link_data in dahmer_links:
                            if cancel_event.is_set():
                                break
                            href = link_data['href']
                            if not href or href.startswith('?') or link_data['text'] in ['../', 'Parent Directory', '../ (Parent Directory)']:
                                continue

                            # Track hrefs to avoid processing the same file multiple times
                            if href in processed_hrefs:
                                continue
                            processed_hrefs.add(href)

                            full_url = urllib.parse.urljoin(current_url, href)
                            filename = link_data['text']
                            
                            # CRITICAL: Check if URL is allowed (same domain AND subpath)
                            if not is_same_domain(full_url):
                                xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                continue

                            if any(full_url.lower().endswith(ext) for ext in get_video_extensions()):
                                # Try to get file size from HEAD request if enabled
                                file_size = None
                                if use_head:
                                    try:
                                        head_response = session.head(full_url, timeout=5)
                                        if head_response.status_code == 200:
                                            content_length = head_response.headers.get('Content-Length')
                                            if content_length:
                                                file_size = int(content_length)
                                    except:
                                        pass
                                
                                # Check if file should be processed
                                if should_process_file(filename, file_size):
                                    path = urllib.parse.urlparse(full_url).path
                                    with results_lock:
                                        if path not in results:
                                            results.append(path)
                                else:
                                    xbmc.log(f"Skipping file: {filename} (filtered)", level=xbmc.LOGDEBUG)
                            elif href.endswith('/'):
                                # Check if folder should be excluded
                                folder_name = href.rstrip('/')
                                if should_skip_folder(folder_name):
                                    xbmc.log(f"Skipping excluded folder: {folder_name}", level=xbmc.LOGDEBUG)
                                    continue
                                
                                # Check if URL is allowed
                                if not is_same_domain(full_url):
                                    xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                    continue
                                
                                with scanned_urls_lock:
                                    if full_url not in scanned_urls:
                                        scanned_urls.add(full_url)
                                        q.put(full_url)
                    else:
                        # Use original parsing logic for non-Dahmer Movies sites
                        soup = BeautifulSoup(response.text, 'html.parser')
                        found_on_page = False

                        # Enhanced parsing for Dahmer Movies site structure
                        # Look for table rows with data-sort attributes (common in Dahmer Movies)
                        file_table = soup.find('table', {'id': 'fileTable'})
                        if file_table:
                            for a_tag in file_table.find_all('a'):
                                if cancel_event.is_set(): break
                                href = a_tag.get('href')
                                if not href or href.startswith('?') or '/../' in href or a_tag.get_text(strip=True) == '../ (Parent Directory)': continue

                                full_url = urllib.parse.urljoin(current_url, href)
                                
                                # CRITICAL: Check if URL is allowed
                                if not is_same_domain(full_url):
                                    xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                    continue

                                if any(full_url.lower().endswith(ext) for ext in get_video_extensions()):
                                    path = urllib.parse.urlparse(full_url).path
                                    found_on_page = True
                                    with results_lock:
                                        if path not in results:
                                            results.append(path)
                                elif href.endswith('/'):
                                    # It's a directory
                                    full_url = urllib.parse.urljoin(current_url, href)
                                    
                                    # Check if URL is same domain
                                    if not is_same_domain(full_url):
                                        xbmc.log(f"Skipping external domain link: {full_url}", level=xbmc.LOGDEBUG)
                                        continue
                                    
                                    with scanned_urls_lock:
                                        if full_url not in scanned_urls:
                                            scanned_urls.add(full_url)
                                            q.put(full_url)
                        else:
                            # Try alternative parsing methods for Dahmer Movies site
                            # Look for table rows with data-sort attributes
                            table_rows = soup.find_all('tr')
                            processed_hrefs = set()  # Track processed hrefs to avoid duplicates

                            if not table_rows:
                                for a_tag in soup.find_all('a'):
                                    if cancel_event.is_set(): break
                                    href = a_tag.get('href')
                                    if not href or href.startswith('?') or a_tag.get_text(strip=True) in ['../', 'Parent Directory', '../ (Parent Directory)']: continue

                                    if href in processed_hrefs: continue
                                    processed_hrefs.add(href)

                                    full_url = urllib.parse.urljoin(current_url, href)
                                    
                                    # Check if URL is same domain
                                    if not is_same_domain(full_url):
                                        xbmc.log(f"Skipping external domain link: {full_url}", level=xbmc.LOGDEBUG)
                                        continue

                                    if any(full_url.lower().endswith(ext) for ext in get_video_extensions()):
                                        path = urllib.parse.urlparse(full_url).path
                                        found_on_page = True
                                        with results_lock:
                                            if path not in results:
                                                results.append(path)
                                    elif href.endswith('/'):
                                        # Check if URL is same domain
                                        if not is_same_domain(full_url):
                                            xbmc.log(f"Skipping external domain link: {full_url}", level=xbmc.LOGDEBUG)
                                            continue
                                        
                                        found_on_page = True
                                        with scanned_urls_lock:
                                            if full_url not in scanned_urls:
                                                scanned_urls.add(full_url)
                                                q.put(full_url)
                            
                            for tr in table_rows:
                                a_tags = tr.find_all('a')
                                for a_tag in a_tags:
                                    if cancel_event.is_set(): break
                                    href = a_tag.get('href')
                                    if not href or href.startswith('?') or a_tag.get_text(strip=True) in ['../', 'Parent Directory', '../ (Parent Directory)']: continue

                                    # Track hrefs to avoid processing the same file multiple times
                                    if href in processed_hrefs:
                                        continue
                                    processed_hrefs.add(href)

                                    full_url = urllib.parse.urljoin(current_url, href)
                                    
                                    # Check if URL is allowed
                                    if not is_same_domain(full_url):
                                        xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                        continue

                                    if any(full_url.lower().endswith(ext) for ext in get_video_extensions()):
                                        path = urllib.parse.urlparse(full_url).path
                                        found_on_page = True
                                        with results_lock:
                                            if path not in results:
                                                results.append(path)
                                    elif href.endswith('/'):
                                        # Check if URL is allowed
                                        if not is_same_domain(full_url):
                                            xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                            continue
                                        
                                        found_on_page = True
                                        with scanned_urls_lock:
                                            if full_url not in scanned_urls:
                                                scanned_urls.add(full_url)
                                                q.put(full_url)

                            # If still no results, try the fallback method of parsing all links
                            if not found_on_page:
                                for a_tag in soup.find_all('a'):
                                    if cancel_event.is_set(): break
                                    href = a_tag.get('href')
                                    if not href or href.startswith('?') or a_tag.get_text(strip=True) in ['../', 'Parent Directory', '../ (Parent Directory)']: continue

                                    full_url = urllib.parse.urljoin(current_url, href)
                                    
                                    # CRITICAL: Check if URL is allowed
                                    if not is_same_domain(full_url):
                                        xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                        continue

                                    if any(full_url.lower().endswith(ext) for ext in get_video_extensions()):
                                        path = urllib.parse.urlparse(full_url).path
                                        with results_lock:
                                            if path not in results:
                                                results.append(path)
                                    elif href.endswith('/'):
                                        # CRITICAL: Check if URL is allowed
                                        if not is_same_domain(full_url):
                                            xbmc.log(f"Skipping disallowed link: {full_url}", level=xbmc.LOGDEBUG)
                                            continue
                                        
                                        with scanned_urls_lock:
                                            if full_url not in scanned_urls:
                                                scanned_urls.add(full_url)
                                                q.put(full_url)
                except requests.RequestException as e:
                    xbmc.log(f"HTTP scan error in url {current_url}: {e}", level=xbmc.LOGWARNING)
                finally:
                    q.task_done()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker) for _ in range(max_workers)]
        
        # Wait for futures but exit early if canceled
        for future in futures:
            if cancel_event.is_set():
                break  # Don't wait for remaining futures
            try:
                future.result(timeout=1.0)  # Wait max 1 second per future
            except Exception:
                pass  # Ignore errors if canceling
    
    # Don't wait for queue if canceled
    if not cancel_event.is_set():
        q.join()

    if not cancel_event.is_set() and connection_errors == max_workers:
        raise ConnectionError(f"All scanning threads failed to connect to {profile['host']}.")

    if cancel_event.is_set(): return None

    if scan_mode == 'incremental':
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile['id']}.json")
        existing_paths = get_existing_paths_from_cache(cache_file)
        results = [p for p in results if p not in existing_paths]

    return results


# --- GitHub Setup Download ---
def download_github_setup():
    """
    Manually download setup files from GitHub
    Can be called from main menu at any time
    """
    from github_downloader import GitHubDownloader
    
    dialog = xbmcgui.Dialog()
    
    # Ask what to download
    message = "What would you like to download from GitHub?"
    options = [
        "Both profiles and cache (Recommended)",
        "Only profiles",
        "Only cache",
        "Cancel"
    ]
    
    choice = dialog.select("Download from GitHub", options)
    
    if choice == -1 or choice == 3:
        # User cancelled
        return
    
    download_profiles = choice in [0, 1]
    download_cache = choice in [0, 2]
    
    # Warn about overwriting
    if download_profiles:
        if xbmcvfs.exists(PROFILES_FILE):
            confirm = dialog.yesno(
                'Overwrite Warning',
                'This will overwrite your existing profiles.json file.\n'
                'Are you sure you want to continue?'
            )
            if not confirm:
                return
    
    # Download
    downloader = GitHubDownloader(ADDON_PROFILE_DIR)
    success = downloader.download_all(download_profiles, download_cache)
    
    if success:
        dialog.notification(
            'Download Complete',
            'Successfully downloaded and extracted files!',
            xbmcgui.NOTIFICATION_INFO,
            5000
        )
        
        # Invalidate profiles cache
        global _PROFILES_CACHE, _PROFILES_MTIME
        _PROFILES_CACHE = None
        _PROFILES_MTIME = 0
        
        # Ask if user wants to refresh
        if dialog.yesno('Refresh Plugin', 'Download complete! Refresh the plugin to see changes?'):
            xbmc.executebuiltin('Container.Refresh')
    else:
        dialog.ok(
            'Download Failed',
            'Could not download files from GitHub.\n'
            'Please check your internet connection and try again.'
        )


# --- UI Functions ---
def set_view():
    try:
        view_type_index = int(ADDON.getSetting('view_type'))
        # Corresponds to the enum in settings.xml: "List|Big List|Thumbnails|Poster Wrap|Wall|Shift"
        view_ids = [50, 51, 54, 500, 501, 502, 503] 
        if 0 <= view_type_index < len(view_ids):
            view_id = view_ids[view_type_index]
            xbmc.executebuiltin(f'Container.SetViewMode({view_id})')
    except Exception as e:
        xbmc.log(f"Error setting view type: {e}", level=xbmc.LOGERROR)

def list_main_menu():
    # Search
    li = xbmcgui.ListItem(label='[COLOR cyan]Search...[/COLOR]')
    li.setArt({'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'get_search_query'}), listitem=li, isFolder=False)
    
    # Movies
    li = xbmcgui.ListItem(label='Movies')
    li.setArt({'icon': 'DefaultMovies.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'list_media_type_menu', 'type': 'movies'}), listitem=li, isFolder=True)
    
    # TV Shows
    li = xbmcgui.ListItem(label='TV Shows')
    li.setArt({'icon': 'DefaultTVShows.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'list_media_type_menu', 'type': 'tv_shows'}), listitem=li, isFolder=True)
    
    # Movie Lists
    li = xbmcgui.ListItem(label='[COLOR cyan]Movie Lists[/COLOR]')
    li.setArt({'icon': 'DefaultPlaylist.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'list_jlom_main'}), listitem=li, isFolder=True)
    
    # Servere
    li = xbmcgui.ListItem(label='[COLOR orange]Servere[/COLOR]')
    li.setArt({'icon': 'DefaultNetwork.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'list_servers'}), listitem=li, isFolder=True)
    
    # Profile Manager
    li = xbmcgui.ListItem(label='[COLOR yellow]Profile Manager[/COLOR]')
    li.setArt({'icon': 'DefaultAddonService.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'manage_profiles'}), listitem=li, isFolder=True)
    
    # Download Setup from GitHub
    li = xbmcgui.ListItem(label='[COLOR lime]Download Setup from GitHub[/COLOR]')
    li.setArt({'icon': 'DefaultAddonProgram.png'})
    li.setInfo('video', {'plot': 'Download pre-configured profiles and cache from GitHub'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'download_github_setup'}), listitem=li, isFolder=False)
    
    # Settings
    li = xbmcgui.ListItem(label='[COLOR white]Settings[/COLOR]')
    li.setArt({'icon': 'DefaultAddonService.png'})
    li.setInfo('video', {'plot': 'Open addon settings'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_url({'action': 'open_settings'}), listitem=li, isFolder=False)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def check_and_install_youtube_addon():
    if not xbmc.getCondVisibility("System.HasAddon(plugin.video.youtube)"):
        dialog = xbmcgui.Dialog()
        if dialog.yesno("YouTube Addon Missing", "The official YouTube addon is recommended for playing trailers. Would you like to install it now?"):
            xbmc.executebuiltin("InstallAddon(plugin.video.youtube)")

def test_server_speed(profile):
    """
    Test the response speed of a single server
    
    Args:
        profile: Profile dict with server configuration
        
    Returns:
        Tuple of (profile_id, profile_name, response_time_ms, error_message)
    """
    import time
    
    profile_id = profile.get('id')
    profile_name = profile.get('name', f"Server {profile_id}")
    profile_type = profile.get('type')
    
    try:
        start_time = time.time()
        
        if profile_type == 'ftp':
            # Test FTP connection
            from ftplib import FTP
            host = profile['host']
            port = 21
            
            ftp = FTP()
            ftp.connect(host, port, timeout=10)
            
            if not profile.get('anonymous', True):
                ftp.login(profile.get('user', ''), profile.get('pass', ''))
            else:
                ftp.login()
            
            # Try to list directory to ensure connection works
            ftp.cwd(profile.get('path', '/'))
            ftp.nlst()
            ftp.quit()
            
        elif profile_type == 'http':
            # Test HTTP connection
            import requests
            base_url = profile['host']
            
            # Use HEAD request for speed (no content download)
            response = requests.head(base_url, timeout=10, allow_redirects=True)
            response.raise_for_status()
        
        else:
            return (profile_id, profile_name, None, f"Unknown type: {profile_type}")
        
        end_time = time.time()
        response_time_ms = int((end_time - start_time) * 1000)
        
        return (profile_id, profile_name, response_time_ms, None)
        
    except Exception as e:
        return (profile_id, profile_name, None, str(e))


def test_all_servers_speed():
    """
    Test speed of all configured servers and display results
    """
    profiles = read_profiles()
    
    if not profiles:
        xbmcgui.Dialog().notification('Server Speed Test', 'No servers configured', xbmcgui.NOTIFICATION_WARNING, 3000)
        return
    
    # Create progress dialog
    progress = xbmcgui.DialogProgress()
    progress.create('Testing Server Speed', 'Preparing to test servers...')
    
    results = []
    total = len(profiles)
    
    # Test servers sequentially to avoid overwhelming network
    for i, profile in enumerate(profiles):
        if progress.iscanceled():
            break
        
        profile_name = profile.get('name', f"Server {profile.get('id')}")
        progress.update(int((i / total) * 100), f'Testing: {profile_name}')
        
        result = test_server_speed(profile)
        results.append(result)
    
    progress.close()
    
    if not results:
        return
    
    # Sort results: successful tests first (by speed), then failed tests
    successful = [(pid, name, ms, err) for pid, name, ms, err in results if ms is not None]
    failed = [(pid, name, ms, err) for pid, name, ms, err in results if ms is None]
    
    successful.sort(key=lambda x: x[2])  # Sort by response time
    sorted_results = successful + failed
    
    # Display results
    xbmcplugin.setPluginCategory(_HANDLE, 'Server Speed Test Results')
    
    for profile_id, profile_name, response_time_ms, error in sorted_results:
        if response_time_ms is not None:
            # Success - show response time
            label = f"{profile_name}: [COLOR lime]{response_time_ms}ms[/COLOR]"
            li = xbmcgui.ListItem(label=label)
            li.setInfo('video', {'plot': f'Response time: {response_time_ms}ms'})
        else:
            # Failed - show error
            label = f"{profile_name}: [COLOR red]FAILED[/COLOR]"
            li = xbmcgui.ListItem(label=label)
            li.setInfo('video', {'plot': f'Error: {error}'})
        
        li.setProperty('IsPlayable', 'false')
        # Dummy URL (non-interactive)
        url = build_url({'action': 'test_all_servers_speed'})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def list_servers():
    """
    List all servers from profiles.json
    Each server shows as a folder with its name
    Only shows servers that have cached content
    """
    profiles = read_profiles()
    
    if not profiles:
        xbmcgui.Dialog().notification('Servere', 'Nu există servere configurate', xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    servers_with_content = 0
    total_movies = 0
    total_tv_shows = 0
    server_items = []
    
    for profile in profiles:
        profile_id = profile.get('id')
        profile_name = profile.get('name', f"Server {profile_id}")
        is_offline = profile.get('offline', False)
        
        # Check if server has any media
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile_id}.json")
        if not xbmcvfs.exists(cache_file):
            continue  # Skip servers without cache
        
        # Read cache to check if it has content
        try:
            with closing(xbmcvfs.File(cache_file, 'r')) as f:
                media = json.loads(f.read())
        except:
            continue  # Skip if cache is corrupted
        
        movies_count = len(media.get('movies', {}))
        tv_shows_count = len(media.get('tv_shows', {}))
        
        has_movies = bool(movies_count)
        has_tv_shows = bool(tv_shows_count)
        
        if not has_movies and not has_tv_shows:
            continue  # Skip empty servers
            
        # Accumulate stats
        total_movies += movies_count
        total_tv_shows += tv_shows_count
        
        servers_with_content += 1
        
        display_name = profile_name
        if is_offline:
            display_name = f"[COLOR red]{profile_name} (OFFLINE)[/COLOR]"
        else:
            display_name = f"[COLOR green]{profile_name}[/COLOR]"
            
        # Create list item for server
        li = xbmcgui.ListItem(label=f"[B]{display_name}[/B]")
        li.setArt({'icon': 'DefaultNetwork.png'})
        
        # Add server info
        info_text = []
        if has_movies:
            info_text.append(f"{movies_count} filme")
        if has_tv_shows:
            info_text.append(f"{tv_shows_count} seriale")
        
        li.setInfo('video', {
            'plot': f"Server: {profile.get('host', 'N/A')}\nConținut: {', '.join(info_text)}"
        })
        
        url = build_url({'action': 'list_server_menu', 'profile_id': profile_id})
        server_items.append((url, li, True))
    
    if servers_with_content == 0:
        xbmcgui.Dialog().notification('Servere', 'Nu există servere cu conținut', xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        # Add Statistics Item at the top
        stats_label = f"[COLOR white]Total Library: {total_movies} Movies • {total_tv_shows} TV Series[/COLOR]"
        stats_li = xbmcgui.ListItem(label=stats_label)
        stats_li.setArt({'icon': 'DefaultIconInfo.png'})
        stats_li.setProperty('IsPlayable', 'false')
        # Dummy action to refresh
        stats_url = build_url({'action': 'list_servers'}) 
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=stats_url, listitem=stats_li, isFolder=False)
        
        # Add Server Speed Test item
        speed_test_li = xbmcgui.ListItem(label='[COLOR cyan]🚀 Test Server Speed[/COLOR]')
        speed_test_li.setArt({'icon': 'DefaultAddonProgram.png'})
        speed_test_li.setInfo('video', {'plot': 'Test response time of all configured servers'})
        speed_test_url = build_url({'action': 'test_all_servers_speed'})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=speed_test_url, listitem=speed_test_li, isFolder=True)
        
        # Add actual server items
        for url, li, is_folder in server_items:
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=is_folder)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def list_server_menu(profile_id):
    """
    List media types available on a specific server
    Only shows Movies/TV Shows if they exist on this server
    """
    cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile_id}.json")
    
    if not xbmcvfs.exists(cache_file):
        xbmcgui.Dialog().notification('Server', 'Cache-ul serverului nu există', xbmcgui.NOTIFICATION_WARNING, 3000)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    # Read cache
    try:
        with closing(xbmcvfs.File(cache_file, 'r')) as f:
            media = json.loads(f.read())
    except:
        xbmcgui.Dialog().notification('Server', 'Eroare la citirea cache-ului', xbmcgui.NOTIFICATION_ERROR, 3000)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    has_movies = bool(media.get('movies'))
    has_tv_shows = bool(media.get('tv_shows'))
    
    # Add Movies if available
    if has_movies:
        movies_count = len(media.get('movies', {}))
        list_item = xbmcgui.ListItem(label=f'Movies ({movies_count})')
        url = build_url({'action': 'list_media_type_menu', 'type': 'movies', 'profile_id': profile_id})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=list_item, isFolder=True)
    
    # Add TV Shows if available
    if has_tv_shows:
        shows_count = len(media.get('tv_shows', {}))
        list_item = xbmcgui.ListItem(label=f'TV Shows ({shows_count})')
        url = build_url({'action': 'list_media_type_menu', 'type': 'tv_shows', 'profile_id': profile_id})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=list_item, isFolder=True)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def list_media_type_menu(media_type, profile_id=None):
    if media_type == 'movies':
        check_and_install_youtube_addon()
    label = media_type.replace('_', ' ').title()
    xbmcplugin.setPluginCategory(_HANDLE, label)
    
    # Build URLs with profile_id if provided
    def build_menu_url(action, **kwargs):
        params = {'action': action, 'type': media_type}
        if profile_id:
            params['profile_id'] = profile_id
        params.update(kwargs)
        return build_url(params)
    
    # All
    li = xbmcgui.ListItem(label='All')
    li.setArt({'icon': 'DefaultFolder.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_menu_url('list_filtered_media', filter_by='all', page='1'), listitem=li, isFolder=True)
    
    # Popular
    li = xbmcgui.ListItem(label="Popular")
    li.setArt({'icon': 'DefaultRecentlyAddedMovies.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_menu_url('list_filtered_media', filter_by='popular', page='1'), listitem=li, isFolder=True)
    
    # By Alphabet
    li = xbmcgui.ListItem(label='By Alphabet')
    li.setArt({'icon': 'DefaultAddonAlphabet.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_menu_url('list_by_alphabet'), listitem=li, isFolder=True)
    
    # By Year
    li = xbmcgui.ListItem(label='By Year')
    li.setArt({'icon': 'DefaultYear.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_menu_url('list_years'), listitem=li, isFolder=True)
    
    # By Genre
    li = xbmcgui.ListItem(label='By Genre')
    li.setArt({'icon': 'DefaultGenre.png'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=build_menu_url('list_genres'), listitem=li, isFolder=True)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def list_by_alphabet(media_type, profile_id=None):
    letters = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    for letter in letters:
        li = xbmcgui.ListItem(label=letter)
        params = {'action': 'list_filtered_media', 'type': media_type, 'filter_by': 'letter', 'filter_value': letter, 'page': '1'}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def list_years(media_type, profile_id=None):
    all_media = get_all_media(media_type, profile_id)
    years = sorted(list(set(item['info'].get('year', 0) for item in all_media if item.get('info'))), reverse=True)
    for year in years:
        if year == 0: continue
        list_item = xbmcgui.ListItem(label=str(year))
        params = {'action': 'list_filtered_media', 'type': media_type, 'filter_by': 'year', 'filter_value': str(year), 'page': '1'}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=list_item, isFolder=True)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def list_genres(media_type, profile_id=None):
    all_media = get_all_media(media_type, profile_id)
    all_genres = set()
    for item in all_media:
        if item.get('info', {}).get('genre'):
            for genre in item['info']['genre'].split(' / '):
                all_genres.add(genre.strip())
    
    for genre in sorted(list(all_genres)):
        li = xbmcgui.ListItem(label=genre)
        params = {'action': 'list_filtered_media', 'type': media_type, 'filter_by': 'genre', 'filter_value': genre, 'page': '1'}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def list_filtered_media(media_type, filter_by, page, filter_value=None, profile_id=None):
    all_items = get_all_media(media_type, profile_id)
    
    if filter_by == 'year' and filter_value:
        try:
            target_year = int(filter_value)
            all_items = [i for i in all_items if i.get('info', {}).get('year') == target_year]
        except ValueError:
            pass # Invalid year filter, show all
    elif filter_by == 'genre' and filter_value:
        # Case insensitive genre check
        all_items = [i for i in all_items if filter_value.lower() in i.get('info', {}).get('genre', '').lower()]
    elif (filter_by == 'alpha' or filter_by == 'letter') and filter_value:
        if filter_value == '#':
            all_items = [i for i in all_items if not i.get('info',{}).get('title',' ')[0].isalpha()]
        else:
            all_items = [i for i in all_items if i.get('info',{}).get('title','').upper().startswith(filter_value.upper())]

    if filter_by == 'popular':
        # Enhanced popularity sorting:
        # 1. Use TMDB popularity score if available
        # 2. If not, use weighted rating (rating * log(votes)) to favor items with more votes
        # 3. Fallback to raw rating
        import math
        def popularity_score(item):
            info = item.get('info', {})
            pop = float(info.get('popularity', 0) or 0)
            if pop > 0.1: return pop * 1000 # Boost popularity score to be primary
            
            rating = float(info.get('rating', 0) or 0)
            votes = int(info.get('votes', 0) or 0)
            if votes > 0:
                return rating * math.log(votes + 1)
            return rating

        all_items.sort(key=popularity_score, reverse=True)
    elif media_type == 'movies':
        all_items.sort(key=lambda x: x.get('info', {}).get('title', ''))
    elif media_type == 'tv_shows':
        all_items.sort(key=lambda x: x.get('info', {}).get('title', ''))

    total_items = len(all_items)
    start_index = (page - 1) * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    items_to_display = all_items[start_index:end_index]

    for item in items_to_display:
        info = item.get('info', {})
        art = item.get('art', {})
        tmdb_id = info.get('tmdb_id')
        info_for_kodi = info.copy()
        info_for_kodi.pop('tmdb_id', None)

        if media_type == 'movies':
            li = xbmcgui.ListItem(label=info.get('title', 'Unknown Movie'))
            li.setInfo('video', info_for_kodi)
            li.setArt(art)
            li.setProperty("IsPlayable", "true")
            # Add context menu for trailer
            if info.get('trailer'):
                li.addContextMenuItems([('Play Trailer', f'RunPlugin({build_url({"action": "play_trailer", "trailer_url": info["trailer"]})})')])
            url = build_url({'action': 'play_movie', 'tmdb_id': tmdb_id})
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)
        elif media_type == 'tv_shows':
            li = xbmcgui.ListItem(label=info.get('title', 'Unknown Show'))
            li.setInfo('video', info_for_kodi)
            li.setArt(art)
            # Add context menu for trailer
            if info.get('trailer'):
                li.addContextMenuItems([('Play Trailer', f'RunPlugin({build_url({"action": "play_trailer", "trailer_url": info["trailer"]})})')])
            
            params = {'action': 'list_seasons', 'tmdb_id': tmdb_id, 'page': '1'}
            if profile_id:
                params['profile_id'] = profile_id
            url = build_url(params)
            
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    if end_index < total_items:
        next_page_li = xbmcgui.ListItem(label='[COLOR yellow]Next Page >>[/COLOR]')
        url = build_url({'action': 'list_filtered_media', 'type': media_type, 'filter_by': filter_by, 'filter_value': filter_value, 'page': str(page + 1)})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=next_page_li, isFolder=True)
    
    content_type = 'tvshows' if media_type == 'tv_shows' else 'movies'
    xbmcplugin.setContent(_HANDLE, content_type)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def play_movie(tmdb_id):
    all_movies = get_all_media('movies')
    movie_to_play = None
    for movie in all_movies:
        if str(movie.get('info', {}).get('tmdb_id')) == tmdb_id:
            movie_to_play = movie
            break

    if not movie_to_play or not movie_to_play.get('sources'):
        xbmcgui.Dialog().ok("No Sources", "Could not find any playable sources for this movie.")
        return

    sources = movie_to_play['sources']
    if len(sources) == 1:
        play_video(sources[0]['profile_id'], sources[0]['path'])
        return

    source_labels = []
    for source in sources:
        profile = get_profile_by_id(source['profile_id'])
        profile_name = profile['name'] if profile else 'Unknown'
        label = f"[{profile_name}] {source['filename']}"
        source_labels.append(label)

    dialog = xbmcgui.Dialog()
    choice = dialog.select(movie_to_play['info']['title'], source_labels)

    if choice >= 0:
        selected_source = sources[choice]
        play_video(selected_source['profile_id'], selected_source['path'])

def play_trailer(trailer_url):
    """Play trailer using configured method"""
    if trailer_url:
        xbmc.log(f"[plugin.video.indexer] Playing trailer: {trailer_url}", level=xbmc.LOGINFO)
        xbmc.Player().play(trailer_url)
    else:
        xbmc.log("[plugin.video.indexer] No trailer URL found.", level=xbmc.LOGWARNING)
        xbmcgui.Dialog().notification("No Trailer", "No trailer URL was found for this item.")

def get_search_query():
    dialog = xbmcgui.Dialog()
    query = dialog.input("Search Library")
    if query:
        url = build_url({'action': 'show_search_results', 'query': query})
        xbmc.executebuiltin(f'Container.Update({url})')

def show_search_results(query):
    query = query.lower()
    all_media = get_all_media('movies') + get_all_media('tv_shows')
    
    search_results = []
    for item in all_media:
        title = item.get('info', {}).get('title', '').lower()
        if query in title:
            search_results.append(item)
    
    for item in sorted(search_results, key=lambda x: x.get('info', {}).get('title')):
        info = item.get('info', {})
        art = item.get('art', {})
        tmdb_id = info.get('tmdb_id')
        info_for_kodi = info.copy()
        info_for_kodi.pop('tmdb_id', None)

        li = xbmcgui.ListItem(label=info.get('title', 'Search Result'))
        li.setInfo('video', info_for_kodi)
        li.setArt(art)
        if info.get('mediatype') == 'movie':
            li.setProperty("IsPlayable", "true")
            url = build_url({'action': 'play_movie', 'tmdb_id': tmdb_id})
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)
        else:
            url = build_url({'action': 'list_seasons', 'tmdb_id': tmdb_id, 'page': '1'})
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.setContent(_HANDLE, 'videos')
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def manage_profiles():
    profiles = read_profiles()
    for profile in profiles:
        profile_type = profile.get('type', 'ftp')
        is_offline = profile.get('offline', False)
        movie_count = 0
        show_count = 0
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile['id']}.json")
        if xbmcvfs.exists(cache_file):
            try:
                with closing(xbmcvfs.File(cache_file, 'r')) as f:
                    media = json.loads(f.read())
                movie_count = len(media.get('movies', {}))
                show_count = len(media.get('tv_shows', {}))
            except Exception: pass

        # Add offline indicator to label
        if is_offline:
            status_indicator = "[COLOR red][OFFLINE][/COLOR] "
        else:
            status_indicator = ""
        
        label = f"{status_indicator}{profile['name']} ({profile_type.upper()}) [COLOR gray]({movie_count} Movies, {show_count} Shows)[/COLOR]"
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': 'DefaultAddonService.png'})
        context_menu = []
        context_menu.append(('[COLOR yellow]Update Library (Fast)[/COLOR]', f"RunPlugin({build_url({'action': 'scan', 'profile_id': profile['id'], 'mode': 'incremental'})})"))
        context_menu.append(('[COLOR orange]Rebuild Library (Full)[/COLOR]', f"RunPlugin({build_url({'action': 'scan', 'profile_id': profile['id'], 'mode': 'full'})})"))
        context_menu.append(('[COLOR lightblue]Re-check Availability[/COLOR]', f"RunPlugin({build_url({'action': 'recheck_host', 'profile_id': profile['id']})})"))
        context_menu.append(('Edit Profile', f"RunPlugin({build_url({'action': 'edit_profile', 'profile_id': profile['id']})})"))
        context_menu.append(('[COLOR red]Delete Profile[/COLOR]', f"RunPlugin({build_url({'action': 'delete_profile', 'profile_id': profile['id']})})"))
        li.addContextMenuItems(context_menu)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

    li = xbmcgui.ListItem(label='[COLOR lightgreen]Add New Profile...[/COLOR]')
    li.setArt({'icon': 'DefaultAddSource.png'})
    url = build_url({'action': 'add_profile'})
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def add_or_edit_profile(profile_id=None):
    profiles = read_profiles()
    dialog = xbmcgui.Dialog()
    profile_data = get_profile_by_id(profile_id) if profile_id else {}

    if not profile_id:
        profile_type_idx = dialog.select("Select Profile Type", ["FTP", "HTTP"])
        if profile_type_idx < 0: return
        profile_type = ["ftp", "http"][profile_type_idx]
    else:
        profile_type = profile_data.get('type', 'ftp')

    name = dialog.input("Profile Name", defaultt=profile_data.get('name', ""))
    if not name: return
    host = dialog.input(f"{profile_type.upper()} Host/Address (e.g., ftp.server.com or http://server.com)", defaultt=profile_data.get('host', ""))
    if not host: return
    path = dialog.input("Start Path (e.g., /movies/)", defaultt=profile_data.get('path', "/"))
    if not path: return
    is_anonymous = dialog.yesno("Login", "Use Anonymous / No Login?", yeslabel="Yes", nolabel="Username/Password")
    user, password = "", ""
    if not is_anonymous:
        user = dialog.input("Username", defaultt=profile_data.get('user', ""))
        password = dialog.input("Password", option=xbmcgui.INPUT_PASSWORD)

    # Proxy configuration (only for HTTP profiles)
    proxy_list = []
    if profile_type == 'http':
        xbmc.log("[Profile Editor] Asking for proxy list for HTTP profile", xbmc.LOGINFO)
        
        # Get proxy list as comma-separated or newline-separated
        existing_proxies = profile_data.get('proxy_list', [])
        default_proxies = ','.join(existing_proxies) if existing_proxies else ""
        
        proxy_input = dialog.input(
            "Proxy List (optional, comma-separated)",
            defaultt=default_proxies
        )
        
        xbmc.log(f"[Profile Editor] Proxy input: {proxy_input}", xbmc.LOGDEBUG)
        
        if proxy_input:
            # Split by comma or newline
            proxy_list = [p.strip() for p in proxy_input.replace('\n', ',').split(',') if p.strip()]
            
            if proxy_list:
                xbmc.log(f"[Profile Editor] Added {len(proxy_list)} proxies", xbmc.LOGINFO)
                dialog.notification(
                    'Proxy Configuration',
                    f'Added {len(proxy_list)} proxies. Enable in Settings to use.',
                    xbmcgui.NOTIFICATION_INFO,
                    3000
                )
            else:
                xbmc.log("[Profile Editor] No valid proxies entered", xbmc.LOGWARNING)
        else:
            xbmc.log("[Profile Editor] No proxy list entered", xbmc.LOGINFO)

    new_profile = {
        'id': profile_id or str(int(time.time())),
        'name': name, 'type': profile_type, 'host': host, 'path': path, 
        'anonymous': is_anonymous, 'user': user, 'pass': password,
        'proxy_list': proxy_list  # Always include, even if empty
    }

    if profile_id:
        profiles = [p for p in profiles if p['id'] != profile_id]
    profiles.append(new_profile)
    write_profiles(profiles)

    if not profile_id:
        scan_library(new_profile['id'], 'full')
    xbmc.executebuiltin('Container.Refresh')

def delete_profile(profile_id):
    if xbmcgui.Dialog().yesno("Confirm Delete", "Are you sure you want to delete this profile and its library?"):
        profiles = [p for p in read_profiles() if p['id'] != profile_id]
        write_profiles(profiles)
        cache_file = os.path.join(ADDON_PROFILE_DIR, f"cache_{profile_id}.json")
        if xbmcvfs.exists(cache_file):
            xbmcvfs.delete(cache_file)
        xbmc.executebuiltin('Container.Refresh')

def play_video(profile_id, path):
    profile = get_profile_by_id(profile_id)
    
    # Debug logging
    if not profile:
        xbmc.log(f"[Playback] ERROR: Profile not found for ID: {profile_id}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Playback Error', 'Profile not found', xbmcgui.NOTIFICATION_ERROR)
        return
    
    xbmc.log(f"[Playback] Profile found: {profile.get('name', 'Unknown')}", xbmc.LOGINFO)
    xbmc.log(f"[Playback] Profile type: {profile.get('type', 'unknown')}", xbmc.LOGINFO)
    xbmc.log(f"[Playback] Anonymous: {profile.get('anonymous', 'not set')}", xbmc.LOGINFO)
    xbmc.log(f"[Playback] Has user: {bool(profile.get('user'))}", xbmc.LOGINFO)
    xbmc.log(f"[Playback] Has pass: {bool(profile.get('pass'))}", xbmc.LOGINFO)
    xbmc.log(f"[Playback] Path (raw): {path}", xbmc.LOGINFO)
    
    profile_type = profile.get('type', 'http')
    
    if profile_type == 'http':
        # HTTP/HTTPS playback
        host = profile['host']
        
        # Construct full URL
        # Ensure path starts with /
        if not path.startswith('/'):
            path = '/' + path
        
        # Combine host and path
        if host.endswith('/'):
            playable_url = host.rstrip('/') + path
        else:
            playable_url = host + path
        
        xbmc.log(f"[Playback] Original URL: {playable_url}", xbmc.LOGINFO)
        
        # Check if SSL proxy should be used
        use_proxy = ADDON.getSetting('enable_ssl_proxy') == 'true' and playable_url.startswith('https://')
        
        if use_proxy:
            # Try to use SSL proxy
            proxy = get_ssl_proxy()
            if proxy and proxy.is_running():
                # Rewrite URL to use proxy
                proxy_url = proxy.get_proxy_url(playable_url)
                xbmc.log(f"[Playback] Using SSL Proxy: {proxy_url}", xbmc.LOGINFO)
                li = xbmcgui.ListItem(path=proxy_url)
            else:
                # Proxy failed to start, fall back to direct URL with SSL bypass attempt
                xbmc.log("[Playback] SSL Proxy not available, using direct URL", xbmc.LOGWARNING)
                verify_ssl = ADDON.getSetting('verify_ssl') == 'true'
                if not verify_ssl:
                    playable_url_with_options = f"{playable_url}|verifypeer=false"
                    xbmc.log(f"[Playback] HTTP URL (with SSL bypass): {playable_url_with_options}", xbmc.LOGINFO)
                    li = xbmcgui.ListItem(path=playable_url_with_options)
                else:
                    xbmc.log(f"[Playback] HTTP URL (normal): {playable_url}", xbmc.LOGINFO)
                    li = xbmcgui.ListItem(path=playable_url)
        else:
            # Direct playback (HTTP or proxy disabled)
            xbmc.log(f"[Playback] HTTP URL (direct): {playable_url}", xbmc.LOGINFO)
            li = xbmcgui.ListItem(path=playable_url)
    
    elif profile_type == 'ftp':
        # For anonymous FTP, use 'anonymous' as user and email as password (FTP convention)
        if profile.get('anonymous'):
            # For anonymous FTP, DON'T include credentials in URL
            # Let Kodi handle it automatically (like VLC does)
            
            xbmc.log(f"[Playback] Path (raw): {repr(path)}", xbmc.LOGINFO)
            
            # Fix UTF-8 encoding if needed
            try:
                path_fixed = path.encode('latin-1').decode('utf-8')
                xbmc.log(f"[Playback] Path (fixed): {repr(path_fixed)}", xbmc.LOGINFO)
                path = path_fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                xbmc.log(f"[Playback] Path already in correct encoding", xbmc.LOGDEBUG)
                pass
            
            # DON'T encode the URL - Kodi uses raw URLs for FTP!
            # When accessing FTP directly, Kodi doesn't encode Cyrillic characters
            playable_url = f"ftp://{profile['host']}{path}"
            
            xbmc.log(f"[Playback] Using anonymous FTP (no credentials, raw URL)", xbmc.LOGINFO)
            xbmc.log(f"[Playback] FTP URL (anonymous): {playable_url}", xbmc.LOGINFO)
            
            # Create ListItem with proper video properties
            li = xbmcgui.ListItem(path=playable_url)
            
            # Set video properties to help Kodi handle the stream
            li.setProperty('IsPlayable', 'true')
            li.setProperty('IsInternetStream', 'false')
            
            # Set info tag to indicate this is a video file
            info_tag = li.getVideoInfoTag()
            info_tag.setMediaType('video')
            
            # Extract filename for title
            import os
            filename = os.path.basename(path)
            info_tag.setTitle(filename)
            
            xbmc.log(f"[Playback] ListItem created with video properties", xbmc.LOGINFO)
            
        else:
            # For authenticated FTP, include credentials
            user = profile.get('user', 'USERNAME')
            password = profile.get('pass', 'PASSWORD')
            
            # Check if credentials are placeholder values
            if user == 'USERNAME' or password == 'PASSWORD':
                xbmc.log(f"[Playback] ERROR: Credentials not set! User: {user}, Pass: {'***' if password else 'EMPTY'}", xbmc.LOGERROR)
                xbmcgui.Dialog().notification('Playback Error', 'FTP credentials not configured', xbmcgui.NOTIFICATION_ERROR)
                return
            
            from urllib.parse import quote, unquote
            user_encoded = quote(user, safe='')
            password_encoded = quote(password, safe='')
            
            from urllib.parse import quote, unquote
            user_encoded = quote(user, safe='')
            password_encoded = quote(password, safe='')
            
            # Decode path first for raw string
            path = unquote(path)
            
            # Fix UTF-8 encoding if needed
            try:
                path_fixed = path.encode('latin-1').decode('utf-8')
                path = path_fixed
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
            
            # Pass RAW path + force IsInternetStream to true
            # This aims to let Kodi handle the URL construction without double-encoding % characters
            # but hopefully encoding wild characters correctly
            playable_url = f"ftp://{user_encoded}:{password_encoded}@{profile['host']}{path}"
            
            xbmc.log(f"[Playback] FTP URL (credentials hidden): ftp://{user}:***@{profile['host']}{path}", xbmc.LOGINFO)
            
            li = xbmcgui.ListItem(path=playable_url)
            li.setProperty('IsInternetStream', 'true')
            li.setProperty('IsPlayable', 'true')
        
        xbmc.log(f"[Playback] ListItem created with path, attempting playback...", xbmc.LOGINFO)
        
    elif profile_type == 'http':
        user_pass = ""
        if not profile.get('anonymous'):
            from urllib.parse import quote
            user_encoded = quote(profile.get('user', ''), safe='')
            password_encoded = quote(profile.get('pass', ''), safe='')
            user_pass = f"{user_encoded}:{password_encoded}@"
        host = profile['host'].rstrip('/')
        
        # Decode path first to avoid double encoding (e.g. %20 becoming %2520)
        from urllib.parse import unquote, quote
        path = unquote(path)
        path = path.lstrip('/')
        
        # Encode path but keep forward slashes
        path_encoded = quote(path, safe='/')
        
        base_url_parts = urllib.parse.urlparse(host)
        playable_url = f"{base_url_parts.scheme}://{user_pass}{base_url_parts.netloc}/{path_encoded}"
        
        # Check SSL verification setting
        verify_ssl = ADDON.getSetting('verify_ssl') == 'true'
        if not verify_ssl:
            playable_url += "|verifypeer=false"
        
        li = xbmcgui.ListItem(path=playable_url)

    xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=li)

# --- Router and other UI functions ---
def list_seasons(tmdb_id, page, profile_id=None):
    all_shows = get_all_media('tv_shows', profile_id)
    show = next((s for s in all_shows if str(s.get('info',{}).get('tmdb_id')) == tmdb_id), None)
    if not show: return

    all_seasons = sorted(show['seasons'].keys())
    total_items = len(all_seasons)
    start_index = (page - 1) * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    seasons_to_display = all_seasons[start_index:end_index]
    for season_name in seasons_to_display:
        li = xbmcgui.ListItem(label=season_name)
        params = {'action': 'list_episodes', 'tmdb_id': tmdb_id, 'season': season_name, 'page': '1'}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    if end_index < total_items:
        next_page_li = xbmcgui.ListItem(label='[COLOR yellow]Next Page >>[/COLOR]')
        params = {'action': 'list_seasons', 'tmdb_id': tmdb_id, 'page': str(page + 1)}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=next_page_li, isFolder=True)
    xbmcplugin.setContent(_HANDLE, 'seasons')
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

def list_episodes(tmdb_id, season_name, page, profile_id=None):
    all_shows = get_all_media('tv_shows', profile_id)
    show = next((s for s in all_shows if str(s.get('info',{}).get('tmdb_id')) == tmdb_id), None)
    if not show: return

    all_episodes = sorted(show['seasons'][season_name])
    total_items = len(all_episodes)
    start_index = (page - 1) * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    episodes_to_display = all_episodes[start_index:end_index]
    for episode_path in episodes_to_display:
        source_profile_id = show.get('profile_id')
        if not source_profile_id: continue

        li = xbmcgui.ListItem(label=os.path.basename(episode_path))
        li.setProperty("IsPlayable", "true")
        url = build_url({'action': 'play', 'profile_id': source_profile_id, 'path': episode_path})
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=False)
    if end_index < total_items:
        next_page_li = xbmcgui.ListItem(label='[COLOR yellow]Next Page >>[/COLOR]')
        params = {'action': 'list_episodes', 'tmdb_id': tmdb_id, 'season': season_name, 'page': str(page + 1)}
        if profile_id:
            params['profile_id'] = profile_id
        url = build_url(params)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=next_page_li, isFolder=True)
    xbmcplugin.setContent(_HANDLE, 'episodes')
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)

# ===== JLOM Movie Lists Integration =====

def list_jlom_main():
    """Display JLOM master folder list"""
    import jlom_lists
    
    xbmcplugin.setPluginCategory(_HANDLE, 'Movie Lists')
    xbmcplugin.setContent(_HANDLE, 'files')
    
    master_list = jlom_lists.get_jlom_list('folder_list', 'master')
    
    if not master_list:
        xbmcgui.Dialog().notification('Movie Lists', 'Failed to load lists', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    folders = master_list.get('folders', [])
    
    for folder in folders:
        title = folder.get('title', 'Unknown')
        folder_type = folder.get('type', 'folder_list')
        folder_id = folder.get('id', '')
        
        list_item = xbmcgui.ListItem(label=title)
        
        if folder_type == 'folder_list':
            url = build_url({'action': 'list_jlom_folders', 'id': folder_id})
        elif folder_type == 'movie_list':
            url = build_url({'action': 'list_jlom_movies', 'id': folder_id}) # Changed list_id to folder_id
        else:
            continue
        
        xbmcplugin.addDirectoryItem(_HANDLE, url, list_item, isFolder=True)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def list_jlom_folders(params):
    """Display JLOM folder contents"""
    import jlom_lists
    
    folder_id = params.get('id', '')
    folder_list = jlom_lists.get_jlom_list('folder_list', folder_id)
    
    if not folder_list:
        xbmcgui.Dialog().notification('Movie Lists', 'Failed to load folder', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    title = folder_list.get('title', 'Movie Lists')
    xbmcplugin.setPluginCategory(_HANDLE, title)
    xbmcplugin.setContent(_HANDLE, 'files')
    
    folders = folder_list.get('folders', [])
    
    for folder in folders:
        folder_title = folder.get('title', 'Unknown')
        folder_type = folder.get('type', 'folder_list')
        folder_id = folder.get('id', '')
        
        list_item = xbmcgui.ListItem(label=folder_title)
        
        if folder_type == 'folder_list':
            url = build_url({'action': 'list_jlom_folders', 'id': folder_id})
        elif folder_type == 'movie_list':
            url = build_url({'action': 'list_jlom_movies', 'id': folder_id})
        else:
            continue
        
        xbmcplugin.addDirectoryItem(_HANDLE, url, list_item, isFolder=True)
    
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def list_jlom_movies(params):
    """Display movies from JLOM list with availability status"""
    import jlom_lists
    from urllib.parse import quote
    
    list_id = params.get('id', '')
    xbmc.log(f"[JLOM] list_jlom_movies called with id: {list_id}", xbmc.LOGINFO)
    
    movie_list = jlom_lists.get_jlom_list('movie_list', list_id)
    
    if not movie_list:
        xbmc.log(f"[JLOM] Failed to load movie_list: {list_id}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Movie Lists', 'Failed to load movies', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(_HANDLE)
        return
    
    xbmc.log(f"[JLOM] Successfully loaded movie_list: {list_id}", xbmc.LOGINFO)
    
    title = movie_list.get('title', 'Movies')
    xbmcplugin.setPluginCategory(_HANDLE, title)
    xbmcplugin.setContent(_HANDLE, 'movies')
    
    movies = movie_list.get('movies', [])
    ordered_by = movie_list.get('ordered_by', '')
    
    # Pagination logic
    try:
        page = int(params.get('page', '1'))
    except ValueError:
        page = 1
        
    page_size = 20
    total_items = len(movies)
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    
    movies_to_display = movies[start_index:end_index]
    
    xbmc.log(f"[JLOM] Displaying page {page} ({start_index}-{end_index}) of {total_items} movies", xbmc.LOGINFO)
    
    for index, movie in enumerate(movies_to_display):
        real_rank = start_index + index + 1
        try:
            original_title = movie.get('original_title', '')
            title = movie.get('title', original_title)
            release_date = movie.get('release_date', '')
            overview = movie.get('overview', '')
            poster_path = movie.get('poster_path')
            backdrop_path = movie.get('backdrop_path')
            
            year = release_date[:4] if release_date else None
            match = None
            if year:
                match = jlom_lists.find_movie_in_cache(original_title, year)
            
            label = f"{real_rank} - {title}" if ordered_by == 'rank' else title
            list_item = xbmcgui.ListItem(label=label)
            
            if poster_path:
                list_item.setArt({'poster': f"https://image.tmdb.org/t/p/w500{poster_path}"})
            if backdrop_path:
                list_item.setArt({'fanart': f"https://image.tmdb.org/t/p/w500{backdrop_path}"})
            
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType('movie')
            info_tag.setTitle(title)
            info_tag.setPlot(overview)
            
            if year:
                info_tag.setYear(int(year))
            
            if match:
                matched_tmdb_id, file_path, metadata, profile_id = match
                info_tag.setPath(file_path)
                list_item.setProperty('IsPlayable', 'true')
                
                tagline = f"Ranked {real_rank} ✅ Available" if ordered_by == 'rank' else "✅ Available in your library"
                info_tag.setTagLine(tagline)
                
                # Use standard 'play' action which handles full URL reconstruction via profile_id
                url = build_url({'action': 'play', 'path': file_path, 'profile_id': profile_id})
                is_folder = False
            else:
                list_item.setProperty('IsPlayable', 'false')
                tagline = f"Ranked {real_rank} ❌ Not in library" if ordered_by == 'rank' else "❌ Not in your library"
                info_tag.setTagLine(tagline)
                
                url = build_url({'action': 'jlom_not_available', 'title': original_title})
                is_folder = False
            
            xbmcplugin.addDirectoryItem(_HANDLE, url, list_item, is_folder)
            
        except Exception as e:
            xbmc.log(f"[JLOM] Error processing movie {real_rank}: {title if 'title' in locals() else 'unknown'} - {str(e)}", xbmc.LOGERROR)
            import traceback
            xbmc.log(f"[JLOM] Traceback: {traceback.format_exc()}", xbmc.LOGERROR)
            continue
            
    # Add Next Page item
    if end_index < total_items:
        next_page = page + 1
        list_item = xbmcgui.ListItem(label=f"[COLOR yellow]Next Page ({next_page}) >>[/COLOR]")
        url = build_url({'action': 'list_jlom_movies', 'id': list_id, 'page': str(next_page)})
        xbmcplugin.addDirectoryItem(_HANDLE, url, list_item, isFolder=True)
    
    xbmc.log(f"[JLOM] Added {len(movies_to_display)} movies to directory", xbmc.LOGINFO)
    set_view()
    xbmcplugin.endOfDirectory(_HANDLE)


def play_jlom(params):
    """Play movie from JLOM list"""
    file_path = params.get('path', '')
    
    if not file_path:
        xbmcgui.Dialog().notification('Playback Error', 'Invalid file path', xbmcgui.NOTIFICATION_ERROR)
        return
    
    play_item = xbmcgui.ListItem(path=file_path)
    play_item.setProperty('IsPlayable', 'true')
    xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=play_item)


def jlom_not_available(params):
    """Handle unavailable movie selection"""
    title = params.get('title', 'Unknown')
    xbmcgui.Dialog().notification('Movie Not Available', f'{title} is not in your library', xbmcgui.NOTIFICATION_INFO, 3000)


def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring))
    action = params.get('action')
    page = int(params.get('page', '1'))
    profile_id = params.get('profile_id')
    tmdb_id = params.get('tmdb_id')

    if not action:
        # Check for first run and offer GitHub download
        try:
            from first_run_setup import FirstRunSetup
            setup = FirstRunSetup(ADDON_PROFILE_DIR)
            
            if setup.is_first_run():
                # Run setup wizard
                setup.run_setup()
                # Continue to main menu regardless of outcome
        except Exception as e:
            xbmc.log(f"[First Run] Error in setup wizard: {e}", xbmc.LOGERROR)
        
        # Verify hosts on startup (only on first load)
        verify_hosts_on_startup()
        list_main_menu()
    elif action == 'list_servers':
        list_servers()
    elif action == 'list_server_menu':
        list_server_menu(profile_id)
    elif action == 'list_media_type_menu':
        list_media_type_menu(params['type'], profile_id)
    elif action == 'list_filtered_media':
        list_filtered_media(params['type'], params['filter_by'], page, params.get('filter_value'), profile_id)
    elif action == 'list_years':
        list_years(params['type'], profile_id)
    elif action == 'list_genres':
        list_genres(params['type'], profile_id)
    elif action == 'list_by_alphabet':
        list_by_alphabet(params['type'], profile_id)
    elif action == 'manage_profiles':
        manage_profiles()
    elif action == 'add_profile':
        add_or_edit_profile()
    elif action == 'edit_profile':
        add_or_edit_profile(profile_id)
    elif action == 'delete_profile':
        delete_profile(profile_id)
    elif action == 'recheck_host':
        recheck_profile_availability(profile_id)
    elif action == 'scan':
        scan_library(profile_id, params.get('mode', 'full'))
    elif action == 'get_search_query':
        get_search_query()
    elif action == 'show_search_results':
        show_search_results(params['query'])
    elif action == 'play_movie':
        play_movie(tmdb_id)
    elif action == 'play_trailer':
        play_trailer(params.get('trailer_url'))
    elif action == 'list_seasons':
        list_seasons(tmdb_id, page, profile_id)
    elif action == 'list_episodes':
        page = int(params.get('page', '1'))
        list_episodes(tmdb_id, params['season'], page, profile_id)
    elif action == 'list_jlom_main':
        list_jlom_main()
    elif action == 'list_jlom_folders':
        list_jlom_folders(params)
    elif action == 'list_jlom_movies':
        list_jlom_movies(params)
    elif action == 'play_jlom':
        play_jlom(params)
    elif action == 'jlom_not_available':
        jlom_not_available(params)
    elif action == 'test_all_servers_speed':
        test_all_servers_speed()
    elif action == 'download_github_setup':
        download_github_setup()
    elif action == 'open_settings':
        ADDON.openSettings()
    elif action == 'play':
        play_video(profile_id, params['path'])

if __name__ == '__main__':
    router(sys.argv[2][1:])
