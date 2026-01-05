# Copyright (C) 2025
# JLOM Lists Integration Module for Media Indexer Plugin
#
# This module provides functionality to fetch and cache movie recommendation lists
# from the JLOM (Just Lists Of Movies) plugin's GitHub repository.

import os
import json
import time
import xbmc
import xbmcaddon
import xbmcvfs
import requests

ADDON = xbmcaddon.Addon()

# Default JLOM lists URL (can be overridden in settings)
DEFAULT_JLOM_URL = "https://raw.githubusercontent.com/lbnt/jlom_lists/main/"

# Cache settings
CACHE_DIR = xbmcvfs.translatePath(os.path.join(ADDON.getAddonInfo('profile'), 'jlom_cache'))
CACHE_DURATION = 3600  # 1 hour in seconds


def ensure_cache_dir():
    """Create cache directory if it doesn't exist"""
    if not xbmcvfs.exists(CACHE_DIR):
        xbmcvfs.mkdirs(CACHE_DIR)


def get_cache_file_path(list_type, list_id):
    """Get cache file path for a specific list"""
    ensure_cache_dir()
    cache_filename = f"{list_type}_{list_id}.json"
    return os.path.join(CACHE_DIR, cache_filename)


def is_cache_valid(cache_file):
    """Check if cache file exists and is not expired"""
    if not xbmcvfs.exists(cache_file):
        return False
    
    # Get file modification time
    stat = xbmcvfs.Stat(cache_file)
    mtime = stat.st_mtime()
    current_time = time.time()
    
    # Check if cache is still valid (within CACHE_DURATION)
    return (current_time - mtime) < CACHE_DURATION


def read_cache(cache_file):
    """Read data from cache file"""
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        xbmc.log(f"[JLOM] Error reading cache: {e}", xbmc.LOGWARNING)
        return None


def write_cache(cache_file, data):
    """Write data to cache file"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        xbmc.log(f"[JLOM] Error writing cache: {e}", xbmc.LOGWARNING)
        return False


def get_jlom_url():
    """Get JLOM lists URL from settings or use default"""
    url = ADDON.getSetting('jlom_lists_url')
    if not url:
        url = DEFAULT_JLOM_URL
    
    # Ensure URL ends with /
    return url if url.endswith('/') else url + '/'


def get_jlom_list(list_type, list_id):
    """
    Fetch JLOM list from GitHub with caching
    
    Args:
        list_type: 'folder_list' or 'movie_list'
        list_id: ID of the list (e.g., 'master', 'imdb_top_250')
    
    Returns:
        Dictionary with list data or None on error
    """
    # Check cache first
    cache_file = get_cache_file_path(list_type, list_id)
    
    if is_cache_valid(cache_file):
        xbmc.log(f"[JLOM] Loading {list_type}/{list_id} from cache", xbmc.LOGDEBUG)
        cached_data = read_cache(cache_file)
        if cached_data:
            return cached_data
    
    # Fetch from GitHub
    base_url = get_jlom_url()
    list_url = f"{base_url}{list_type}/{list_id}.json"
    
    xbmc.log(f"[JLOM] Fetching list from: {list_url}", xbmc.LOGINFO)
    
    try:
        response = requests.get(list_url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Cache the response
        write_cache(cache_file, data)
        
        xbmc.log(f"[JLOM] Successfully fetched {list_type}/{list_id}", xbmc.LOGINFO)
        return data
        
    except requests.exceptions.RequestException as e:
        xbmc.log(f"[JLOM] Error fetching list: {e}", xbmc.LOGERROR)
        return None
    except json.JSONDecodeError as e:
        xbmc.log(f"[JLOM] Error parsing JSON: {e}", xbmc.LOGERROR)
        return None


# Cache for movie lookups - avoid repeated file I/O
_MOVIE_CACHE = None
_MOVIE_INDEX = None

def _build_movie_index():
    """Build index for fast movie lookups using profile caches"""
    global _MOVIE_INDEX
    
    # Path to profile directory (virtual)
    profile_path = xbmcaddon.Addon().getAddonInfo('profile')
    
    if not xbmcvfs.exists(profile_path):
        _MOVIE_INDEX = {}
        return

    _MOVIE_INDEX = {}
    count = 0
    
    try:
        # listdir works with special:// paths
        dirs, files = xbmcvfs.listdir(profile_path)
        for filename in files:
            if filename.startswith('cache_') and filename.endswith('.json'):
                # Construct virtual path first (e.g. special://profile/addon_data/.../file.json)
                virtual_path = os.path.join(profile_path, filename)
                # Translate to real OS path for open()
                real_path = xbmcvfs.translatePath(virtual_path)
                
                try:
                    with open(real_path, 'r', encoding='utf-8') as f:
                        media_data = json.load(f)
                        
                    # Extract profile_id from filename (cache_{id}.json)
                    # filename is like cache_123456.json
                    try:
                        profile_id = filename.replace('cache_', '').replace('.json', '')
                    except:
                        profile_id = ''
                        
                    # cache structure: {'movies': {path: metadata}, 'tv_shows': {...}}
                    movies_dict = media_data.get('movies', {})
                    
                    for tmdb_id_key, metadata in movies_dict.items():
                        if not metadata: continue
                        
                        # Extract file path from sources list
                        sources = metadata.get('sources', [])
                        if not sources: continue
                        
                        # Take the first available source path
                        file_path = sources[0].get('path')
                        if not file_path: continue
                        
                        info = metadata.get('info', {})
                        
                        # Try to get title and year
                        original_title = info.get('originaltitle', info.get('title', ''))
                        year_val = info.get('year', '')
                        if not year_val:
                            year_val = info.get('date', '')[:4] if info.get('date') else ''
                            
                        # Fallback to legacy metadata structure
                        if not original_title:
                            original_title = metadata.get('original_title', '')
                        if not year_val:
                            release_date = metadata.get('release_date', '')
                            year_val = release_date[:4] if release_date else ''
                            
                        original_title = original_title.lower()
                        
                        if year_val and original_title:
                            try:
                                year = int(year_val)
                                
                                # Create movie data object
                                movie_data = {
                                    'metadata': metadata,
                                    'path': file_path,
                                    'profile_id': profile_id
                                }
                                
                                # Index by title and year (±2 tolerance)
                                for y in range(year - 2, year + 3):
                                    key = (original_title, y)
                                    if key not in _MOVIE_INDEX:
                                        _MOVIE_INDEX[key] = []
                                    _MOVIE_INDEX[key].append(movie_data)
                                count += 1
                            except (ValueError, TypeError):
                                continue
                except Exception as e:
                    xbmc.log(f"[JLOM] Error reading cache file {filename}: {e}", xbmc.LOGERROR)
                    continue
                    
    except Exception as e:
        xbmc.log(f"[JLOM] Error listing profile directory: {e}", xbmc.LOGERROR)
        _MOVIE_INDEX = {}
        return
    
    xbmc.log(f"[JLOM] Built movie index with {len(_MOVIE_INDEX)} entries from {count} movies across all profiles", xbmc.LOGINFO)


def find_movie_in_cache(original_title, year):
    """
    Search for movie in indexer's metadata cache (optimized with indexing)
    
    Args:
        original_title: Original title of the movie
        year: Release year (string or int)
    
    Returns:
        Tuple of (tmdb_id, file_path, metadata, profile_id) or None if not found
    """
    global _MOVIE_INDEX
    
    # Build index on first use
    if _MOVIE_INDEX is None:
        _build_movie_index()
    
    if not _MOVIE_INDEX:
        return None
    
    try:
        year_int = int(year)
    except (ValueError, TypeError):
        xbmc.log(f"[JLOM] Invalid year: {year}", xbmc.LOGWARNING)
        return None
    
    # Fast O(1) lookup using index
    key = (original_title.lower(), year_int)
    matches = _MOVIE_INDEX.get(key, [])
    
    if matches:
        # Return first match
        movie_data = matches[0]
        metadata = movie_data.get('metadata', {})
        tmdb_id = metadata.get('id')
        file_path = movie_data.get('path', '')
        profile_id = movie_data.get('profile_id', '')
        
        xbmc.log(f"[JLOM] Found match: {original_title} ({year}) -> {file_path}", xbmc.LOGDEBUG)
        return (tmdb_id, file_path, metadata, profile_id)
    
    xbmc.log(f"[JLOM] No match found for: {original_title} ({year})", xbmc.LOGDEBUG)
    return None


def clear_movie_cache():
    """Clear the movie cache and index (call when cache is updated)"""
    global _MOVIE_CACHE, _MOVIE_INDEX
    _MOVIE_CACHE = None
    _MOVIE_INDEX = None
    xbmc.log("[JLOM] Movie cache cleared", xbmc.LOGDEBUG)


def clear_cache():
    """Clear all JLOM cache files"""
    if not xbmcvfs.exists(CACHE_DIR):
        return
    
    try:
        dirs, files = xbmcvfs.listdir(CACHE_DIR)
        for filename in files:
            if filename.endswith('.json'):
                file_path = os.path.join(CACHE_DIR, filename)
                xbmcvfs.delete(file_path)
        
        xbmc.log("[JLOM] Cache cleared successfully", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[JLOM] Error clearing cache: {e}", xbmc.LOGWARNING)
