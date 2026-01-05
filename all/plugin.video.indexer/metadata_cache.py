"""
Metadata Cache System for TMDb API responses
Reduces API calls by caching metadata with configurable TTL
Compatible with both Kodi and standalone environments
"""
import json
import time
import os
import hashlib
from contextlib import closing

# Detect if running in Kodi or standalone
try:
    import xbmcvfs
    import xbmcaddon
    KODI_MODE = True
    ADDON = xbmcaddon.Addon()
    ADDON_PROFILE_DIR = ADDON.getAddonInfo('profile')
    CACHE_DIR = os.path.join(ADDON_PROFILE_DIR, 'metadata_cache')
except ImportError:
    KODI_MODE = False
    # Standalone mode - use current directory
    CACHE_DIR = os.path.join(os.path.dirname(__file__), 'metadata_cache')

# Ensure cache directory exists
if KODI_MODE:
    if not xbmcvfs.exists(CACHE_DIR):
        xbmcvfs.mkdirs(CACHE_DIR)
else:
    os.makedirs(CACHE_DIR, exist_ok=True)


class MetadataCache:
    """
    Persistent cache for TMDb metadata with TTL support
    """
    
    def __init__(self, default_ttl=30*24*3600):  # 30 days default
        """
        Initialize metadata cache
        
        Args:
            default_ttl: Time to live in seconds (default: 30 days)
        """
        self.default_ttl = default_ttl
        self.cache_dir = CACHE_DIR
    
    def _get_cache_key(self, media_type, title, year=None):
        """
        Generate cache key from media info
        
        Args:
            media_type: 'movie' or 'tv_show'
            title: Media title
            year: Optional year
            
        Returns:
            Hash-based cache key
        """
        # Normalize inputs
        title_normalized = title.lower().strip()
        year_str = str(year) if year else ""
        
        # Create unique key
        key_string = f"{media_type}:{title_normalized}:{year_str}"
        
        # Use hash to avoid filesystem issues with special characters
        key_hash = hashlib.md5(key_string.encode('utf-8')).hexdigest()
        
        return key_hash
    
    def _get_cache_path(self, cache_key):
        """Get full path to cache file"""
        return os.path.join(self.cache_dir, f"{cache_key}.json")
    
    def get(self, media_type, title, year=None):
        """
        Retrieve metadata from cache
        
        Args:
            media_type: 'movie' or 'tv_show'
            title: Media title
            year: Optional year
            
        Returns:
            Cached metadata dict or None if not found/expired
        """
        cache_key = self._get_cache_key(media_type, title, year)
        cache_path = self._get_cache_path(cache_key)
        
        # Check if file exists (mode-aware)
        if KODI_MODE:
            if not xbmcvfs.exists(cache_path):
                return None
        else:
            if not os.path.exists(cache_path):
                return None
        
        try:
            # Read file (mode-aware)
            if KODI_MODE:
                with closing(xbmcvfs.File(cache_path, 'r')) as f:
                    cache_data = json.loads(f.read())
            else:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            
            # Check if expired
            if self._is_expired(cache_data):
                # Clean up expired cache (mode-aware)
                if KODI_MODE:
                    xbmcvfs.delete(cache_path)
                else:
                    os.remove(cache_path)
                return None
            
            return cache_data.get('metadata')
            
        except (json.JSONDecodeError, KeyError, IOError):
            # Corrupted cache, delete it (mode-aware)
            try:
                if KODI_MODE:
                    xbmcvfs.delete(cache_path)
                else:
                    os.remove(cache_path)
            except:
                pass
            return None
    
    def set(self, media_type, title, metadata, year=None, ttl=None):
        """
        Store metadata in cache
        
        Args:
            media_type: 'movie' or 'tv_show'
            title: Media title
            metadata: Metadata dict to cache
            year: Optional year
            ttl: Time to live in seconds (uses default if None)
        """
        if not metadata:
            return
        
        cache_key = self._get_cache_key(media_type, title, year)
        cache_path = self._get_cache_path(cache_key)
        
        ttl = ttl if ttl is not None else self.default_ttl
        
        cache_data = {
            'metadata': metadata,
            'cached_at': time.time(),
            'ttl': ttl,
            'media_type': media_type,
            'title': title,
            'year': year
        }
        
        try:
            # Write file (mode-aware)
            if KODI_MODE:
                with closing(xbmcvfs.File(cache_path, 'w')) as f:
                    f.write(json.dumps(cache_data, indent=2))
            else:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, indent=2)
        except IOError:
            # Failed to write cache, not critical
            pass
    
    def _is_expired(self, cache_data):
        """
        Check if cache entry is expired
        
        Args:
            cache_data: Cache data dict
            
        Returns:
            True if expired, False otherwise
        """
        cached_at = cache_data.get('cached_at', 0)
        ttl = cache_data.get('ttl', self.default_ttl)
        
        return (time.time() - cached_at) > ttl
    
    def clear(self):
        """Clear all cache entries"""
        try:
            # Get all cache files (mode-aware)
            if KODI_MODE:
                dirs, files = xbmcvfs.listdir(self.cache_dir)
            else:
                files = os.listdir(self.cache_dir)
            
            for filename in files:
                if filename.endswith('.json'):
                    file_path = os.path.join(self.cache_dir, filename)
                    if KODI_MODE:
                        xbmcvfs.delete(file_path)
                    else:
                        os.remove(file_path)
                    
        except Exception:
            pass
    
    def clear_expired(self):
        """Remove expired cache entries"""
        try:
            # Get files (mode-aware)
            if KODI_MODE:
                dirs, files = xbmcvfs.listdir(self.cache_dir)
            else:
                files = os.listdir(self.cache_dir)
            
            for filename in files:
                if not filename.endswith('.json'):
                    continue
                
                file_path = os.path.join(self.cache_dir, filename)
                
                try:
                    # Read file (mode-aware)
                    if KODI_MODE:
                        with closing(xbmcvfs.File(file_path, 'r')) as f:
                            cache_data = json.loads(f.read())
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    
                    if self._is_expired(cache_data):
                        if KODI_MODE:
                            xbmcvfs.delete(file_path)
                        else:
                            os.remove(file_path)
                        
                except:
                    # Corrupted file, delete it
                    try:
                        if KODI_MODE:
                            xbmcvfs.delete(file_path)
                        else:
                            os.remove(file_path)
                    except:
                        pass
                        
        except Exception:
            pass
    
    def get_stats(self):
        """
        Get cache statistics
        
        Returns:
            Dict with cache stats (total_entries, total_size_mb, expired_count)
        """
        stats = {
            'total_entries': 0,
            'total_size_bytes': 0,
            'expired_count': 0
        }
        
        try:
            # Get files (mode-aware)
            if KODI_MODE:
                dirs, files = xbmcvfs.listdir(self.cache_dir)
            else:
                files = os.listdir(self.cache_dir)
            
            for filename in files:
                if not filename.endswith('.json'):
                    continue
                
                stats['total_entries'] += 1
                file_path = os.path.join(self.cache_dir, filename)
                
                try:
                    # Get file size (mode-aware)
                    if KODI_MODE:
                        with closing(xbmcvfs.File(file_path, 'r')) as f:
                            content = f.read()
                            stats['total_size_bytes'] += len(content)
                            cache_data = json.loads(content)
                    else:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            stats['total_size_bytes'] += len(content.encode('utf-8'))
                            cache_data = json.loads(content)
                    
                    # Check if expired
                    if self._is_expired(cache_data):
                        stats['expired_count'] += 1
                except:
                    pass
            
            stats['total_size_mb'] = round(stats['total_size_bytes'] / (1024 * 1024), 2)
            
        except Exception:
            pass
        
        return stats


# Global cache instance
_cache_instance = None

def get_cache():
    """Get or create global cache instance"""
    global _cache_instance
    
    if _cache_instance is None:
        # Get TTL from settings (in days, convert to seconds)
        try:
            if KODI_MODE:
                ttl_days = int(ADDON.getSetting('cache_ttl'))
            else:
                ttl_days = 30  # Default 30 days in standalone mode
        except:
            ttl_days = 30  # Default 30 days
        
        ttl_seconds = ttl_days * 24 * 3600
        _cache_instance = MetadataCache(default_ttl=ttl_seconds)
    
    return _cache_instance


def get_all_cached_movies():
    """
    Get all cached movie metadata (for JLOM matching)
    
    Returns:
        List of dicts with 'metadata' and 'path' keys
    """
    cached_movies = []
    
    try:
        # Get all cache files (mode-aware)
        if KODI_MODE:
            dirs, files = xbmcvfs.listdir(CACHE_DIR)
        else:
            files = os.listdir(CACHE_DIR)
        
        for filename in files:
            if not filename.endswith('.json'):
                continue
            
            file_path = os.path.join(CACHE_DIR, filename)
            
            try:
                # Read file (mode-aware)
                if KODI_MODE:
                    with closing(xbmcvfs.File(file_path, 'r')) as f:
                        cache_data = json.loads(f.read())
                else:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                
                # Only include movies (not TV shows)
                if cache_data.get('media_type') == 'movie':
                    metadata = cache_data.get('metadata', {})
                    
                    # Extract path from metadata if available
                    # Note: This might need adjustment based on actual cache structure
                    path = metadata.get('file_path', '')
                    
                    cached_movies.append({
                        'metadata': metadata,
                        'path': path
                    })
                    
            except:
                # Skip corrupted files
                continue
                
    except Exception:
        pass
    
    return cached_movies
