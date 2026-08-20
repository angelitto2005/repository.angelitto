import json
import time
import zlib
import sqlite3
import os
import xbmcgui
from resources.lib.database import connect
from resources.lib.config import ADDON, ADDON_DATA_DIR

class MainCache:
    def __init__(self):
        self.dbcon = connect()
        self.dbcur = self.dbcon.cursor()
        self._create_tables()

    def _create_tables(self):
        try:
            self.dbcur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                           (id text unique, data blob, expires integer)""")
            
            # Modify table structure: add 'scanned_providers'
            # If the table already exists without this column, the insert might error,
            # so we try to add the column (simple migration)
            self.dbcur.execute("""CREATE TABLE IF NOT EXISTS sources_cache 
                           (id text unique, streams blob, failed_providers text, scanned_providers text, sort_opt text, expires integer)""")
            
            # Migration for existing users (try/except ignores if already exists)
            try:
                self.dbcur.execute("ALTER TABLE sources_cache ADD COLUMN scanned_providers text")
            except: pass
            try:
                self.dbcur.execute("ALTER TABLE sources_cache ADD COLUMN sort_opt text")
            except: pass
            
            self.dbcon.commit()
        except: pass

    def get(self, string):
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, data FROM maincache WHERE id = ?", (string,))
            result = self.dbcur.fetchone()
            if result:
                expires, data_blob = result
                if expires > current_time:
                    if isinstance(data_blob, bytes):
                        return json.loads(zlib.decompress(data_blob))
                    return json.loads(data_blob)
                else:
                    self.delete(string)
        except: pass
        return None

    def set(self, string, data, expiration=48):
        try:
            expires = int(time.time() + (expiration * 3600))
            json_data = json.dumps(data)
            compressed = zlib.compress(json_data.encode('utf-8'))
            self.dbcur.execute("INSERT OR REPLACE INTO maincache (id, data, expires) VALUES (?, ?, ?)", 
                               (string, compressed, expires))
            self.dbcon.commit()
        except: pass

    def delete(self, string):
        try:
            self.dbcur.execute("DELETE FROM maincache WHERE id = ?", (string,))
            self.dbcon.commit()
        except: pass
            
    def delete_all(self):
        try:
            self.dbcur.execute("DELETE FROM maincache")
            self.dbcur.execute("DELETE FROM sources_cache") # Also clear sources
            self.dbcon.execute("VACUUM")
            self.dbcon.commit()
        except: pass

# --- NEW METHODS FOR SOURCES (MODIFIED) ---
    def get_source_cache(self, search_id):
        """Returneaza: (streams, error_providers, empty_providers, scanned_providers, sort_opt)
        sort_opt = optiunea de sortare folosita cand lista a fost salvata (None pt randuri vechi)."""
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, streams, failed_providers, scanned_providers, sort_opt FROM sources_cache WHERE id = ?", (search_id,))
            result = self.dbcur.fetchone()
            
            if result:
                expires, streams_blob, failed_json, scanned_json, saved_sort_opt = result
                if expires > current_time:
                    streams = []
                    if streams_blob:
                        try: streams = json.loads(zlib.decompress(streams_blob))
                        except: pass
                    
                    error_list = []
                    empty_list = []
                    if failed_json:
                        try:
                            parsed = json.loads(failed_json)
                            if isinstance(parsed, list):
                                # Old format: all providers are errors (retry)
                                error_list = parsed
                            elif isinstance(parsed, dict):
                                error_list = parsed.get('error', [])
                                empty_list = parsed.get('empty', [])
                        except: pass
                    
                    scanned_list = []
                    if scanned_json:
                        try: scanned_list = json.loads(scanned_json)
                        except: pass
                        
                    try: saved_sort_opt = int(saved_sort_opt)
                    except: saved_sort_opt = None
                    
                    return streams, error_list, empty_list, scanned_list, saved_sort_opt
                else:
                    self.delete_source_cache(search_id)
        except Exception as e:
            pass
        return None, None, None, None, None

    def set_source_cache(self, search_id, streams, error_providers, empty_providers, scanned_providers, expiration_hours, sort_opt=None):
        try:
            expires = int(time.time() + (expiration_hours * 3600))
            
            json_streams = json.dumps(streams)
            compressed_streams = zlib.compress(json_streams.encode('utf-8'))
            
            json_failed = json.dumps({"error": error_providers, "empty": empty_providers})
            json_scanned = json.dumps(scanned_providers)
            
            self.dbcur.execute("INSERT OR REPLACE INTO sources_cache (id, streams, failed_providers, scanned_providers, sort_opt, expires) VALUES (?, ?, ?, ?, ?, ?)", 
                               (search_id, compressed_streams, json_failed, json_scanned, sort_opt, expires))
            self.dbcon.commit()
        except: pass
        
    def delete_source_cache(self, search_id):
        try:
            self.dbcur.execute("DELETE FROM sources_cache WHERE id = ?", (search_id,))
            self.dbcon.commit()
        except: pass

def cache_object(function, string, url, json_output=True, expiration=48):
    cache = MainCache()
    cached_data = cache.get(string)
    if cached_data: return cached_data
    
    if isinstance(url, list): result = function(*url)
    else: result = function(url)
        
    if result:
        if json_output and hasattr(result, 'json'):
            try: data = result.json()
            except: data = result
        else: data = result
        cache.set(string, data, expiration=expiration)
        return data
    return None
    

# --- FAST CACHE (RAM) ---
def get_fast_cache(key):
    """Returns data from RAM. Language + page_limit are part of the key to react instantly to setting changes."""
    try:
        import xbmcgui
        from resources.lib.config import get_page_limit_index
        curr_lang = ADDON.getSetting('plot_language')
        curr_limit = get_page_limit_index()
        actual_key = f"{key}_{curr_lang}_{curr_limit}"

        window = xbmcgui.Window(10000)
        ver = window.getProperty("tmdbmovies_fast_cache_version")
        data = window.getProperty(f"tmdbmovies_fast_{actual_key}")

        if data:
            cache_obj = json.loads(data)
            if cache_obj.get('ver') == ver:
                return cache_obj.get('items')
    except: pass
    return None

def set_fast_cache(key, items):
    """Saves data in RAM."""
    try:
        import xbmcgui
        from resources.lib.config import get_page_limit_index
        curr_lang = ADDON.getSetting('plot_language')
        curr_limit = get_page_limit_index()
        actual_key = f"{key}_{curr_lang}_{curr_limit}"

        window = xbmcgui.Window(10000)
        ver = window.getProperty("tmdbmovies_fast_cache_version")
        cache_obj = {'ver': ver, 'items': items}
        window.setProperty(f"tmdbmovies_fast_{actual_key}", json.dumps(cache_obj))
    except: pass

def clear_all_fast_cache():
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        window.setProperty("tmdbmovies_fast_cache_version", str(time.time()))
        # Also bump RAM meta cache version
        window.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except: pass


# Ensure ram cache version is initialized on first access
def _ensure_ram_cache_ver():
    try:
        w = _get_ram_window()
        if not w.getProperty("tmdbmovies_ram_cache_version"):
            w.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except:
        pass


# =============================================================================
# RAM META CACHE (Window Properties) — instant between plugin calls
# =============================================================================
_RAM_WINDOW = None

def _get_ram_window():
    global _RAM_WINDOW
    if _RAM_WINDOW is None:
        import xbmcgui
        _RAM_WINDOW = xbmcgui.Window(10000)
    return _RAM_WINDOW

_RAM_TTL = 168 * 3600  # 7 days in seconds

def ram_cache_get(tag, key):
    """Generic RAM cache get. Checks version + TTL."""
    try:
        w = _get_ram_window()
        ver = w.getProperty("tmdbmovies_ram_cache_version")
        raw = w.getProperty(f'tmdb_ram_{tag}_{key}')
        if not raw:
            return None
        import json
        data = json.loads(raw)
        if data.get('_ver') != ver:
            w.clearProperty(f'tmdb_ram_{tag}_{key}')
            return None
        expires = data.get('_expires', 0)
        if time.time() > expires:
            w.clearProperty(f'tmdb_ram_{tag}_{key}')
            return None
        return data.get('meta')
    except:
        return None

def ram_cache_set(tag, key, data, ttl=_RAM_TTL):
    """Generic RAM cache set."""
    try:
        import json
        w = _get_ram_window()
        ver = w.getProperty("tmdbmovies_ram_cache_version")
        cache_obj = {'meta': data, '_expires': time.time() + ttl, '_ver': ver}
        w.setProperty(f'tmdb_ram_{tag}_{key}', json.dumps(cache_obj))
    except:
        pass

def ram_cache_get_tvshow(tmdb_id):
    return ram_cache_get('tv', tmdb_id)

def ram_cache_set_tvshow(tmdb_id, data, ttl=_RAM_TTL):
    ram_cache_set('tv', tmdb_id, data, ttl)

def ram_cache_get_season(tmdb_id, season_num):
    return ram_cache_get('season', f'{tmdb_id}_{season_num}')

def ram_cache_set_season(tmdb_id, season_num, data, ttl=_RAM_TTL):
    ram_cache_set('season', f'{tmdb_id}_{season_num}', data, ttl)

def ram_cache_clear_all():
    """Clear all RAM cache by bumping version. All entries with old ver become stale."""
    try:
        w = _get_ram_window()
        w.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except:
        pass

# =============================================================================
# GLOBAL RAM META POOL (Python dict — no Window Property size limits)
# =============================================================================
_RAM_META_POOL = {}
_RAM_META_POOL_MAX = 500

def ram_pool_get(tmdb_id):
    """O(1) dict lookup — instant, no serialization."""
    return _RAM_META_POOL.get(str(tmdb_id))

def ram_pool_set(tmdb_id, data):
    """Store metadata in global pool. Silently skips if pool is full."""
    if len(_RAM_META_POOL) >= _RAM_META_POOL_MAX:
        return
    _RAM_META_POOL[str(tmdb_id)] = data

def ram_pool_clear():
    _RAM_META_POOL.clear()

def warm_ram_pool_from_db():
    """Load most recent non‑expired metadata entries into the global RAM pool.
    Called once at service startup — makes trending lists load instantly
    for shows the user has already browsed."""
    try:
        conn = sqlite3.connect(os.path.join(ADDON_DATA_DIR, 'trakt_sync.db'), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        c = conn.cursor()
        now = int(time.time())
        c.execute("SELECT tmdb_id, media_type, data FROM meta_cache_items WHERE expires > ? ORDER BY rowid DESC LIMIT ?", (now, _RAM_META_POOL_MAX))
        rows = c.fetchall()
        conn.close()
        count = 0
        for tmdb_id, media_type, data_blob in rows:
            try:
                if isinstance(data_blob, bytes):
                    data = json.loads(zlib.decompress(data_blob))
                else:
                    data = json.loads(data_blob)
                _RAM_META_POOL[str(tmdb_id)] = data
                count += 1
            except:
                pass
        if count:
            from resources.lib.utils import log
            log(f"[CACHE] RAM meta pool warmed with {count} entries")
    except Exception as e:
        from resources.lib.utils import log
        log(f"[CACHE] RAM meta pool warmup skipped: {e}")

