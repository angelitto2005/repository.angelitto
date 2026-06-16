import json
import time
import zlib
import sqlite3
import os
import xbmcgui
from resources.lib.database import connect
from resources.lib.config import ADDON_DATA_DIR

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
                           (id text unique, streams blob, failed_providers text, scanned_providers text, expires integer)""")
            
            # Migration for existing users (try/except ignores if already exists)
            try:
                self.dbcur.execute("ALTER TABLE sources_cache ADD COLUMN scanned_providers text")
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
        """Returnează: (streams, error_providers, empty_providers, scanned_providers)"""
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, streams, failed_providers, scanned_providers FROM sources_cache WHERE id = ?", (search_id,))
            result = self.dbcur.fetchone()
            
            if result:
                expires, streams_blob, failed_json, scanned_json = result
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
                        
                    return streams, error_list, empty_list, scanned_list
                else:
                    self.delete_source_cache(search_id)
        except Exception as e:
            pass
        return None, None, None, None

    def set_source_cache(self, search_id, streams, error_providers, empty_providers, scanned_providers, expiration_hours):
        try:
            expires = int(time.time() + (expiration_hours * 3600))
            
            json_streams = json.dumps(streams)
            compressed_streams = zlib.compress(json_streams.encode('utf-8'))
            
            json_failed = json.dumps({"error": error_providers, "empty": empty_providers})
            json_scanned = json.dumps(scanned_providers)
            
            self.dbcur.execute("INSERT OR REPLACE INTO sources_cache (id, streams, failed_providers, scanned_providers, expires) VALUES (?, ?, ?, ?, ?)", 
                               (search_id, compressed_streams, json_failed, json_scanned, expires))
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
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.tmdbmovies')
        curr_lang = addon.getSetting('plot_language')
        curr_limit = addon.getSetting('page_limit')
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
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.tmdbmovies')
        curr_lang = addon.getSetting('plot_language')
        curr_limit = addon.getSetting('page_limit')
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
    except: pass

