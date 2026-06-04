import sqlite3
import xbmcvfs
import os
import xbmc
from resources.lib.config import ADDON_DATA_DIR

DB_FILE = os.path.join(ADDON_DATA_DIR, 'maincache.db')

def connect():
    """Establishes the SQLite database connection."""
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        try:
            xbmcvfs.mkdirs(ADDON_DATA_DIR)
        except:
            pass
    
    # --- SIZE PROTECTION (20MB) ---
    if os.path.exists(DB_FILE):
        try:
            size_mb = os.path.getsize(DB_FILE) / (1024 * 1024)
            if size_mb > 20:
                xbmc.log(f"[TMDb Movies] maincache.db is {size_mb:.2f}MB. AUTO RESET!", xbmc.LOGWARNING)
                try:
                    xbmcvfs.delete(DB_FILE)
                except:
                    os.remove(DB_FILE)
        except: pass
    # -----------------------------
    
    conn = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    
    try:
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = WAL") # <--- CHANGED FROM OFF TO WAL
        conn.execute("PRAGMA mmap_size = 268435456")
        conn.execute("PRAGMA cache_size = -10000")
    except Exception:
        pass
        
    return conn

def check_database():
    """Check and create necessary tables if they don't exist."""
    try:
        conn = connect()
        cur = conn.cursor()
        
        cur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                       (id text unique, data blob, expires integer)""")
                       
        conn.commit()
        conn.close()
    except Exception:
        pass

# MODIFICATION: No longer run check_database() here!
# It will run only when needed from cache.py