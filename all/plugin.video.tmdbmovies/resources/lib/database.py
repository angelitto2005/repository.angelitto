import sqlite3
import xbmcvfs
import os
import xbmc
from resources.lib.config import ADDON_DATA_DIR

DB_FILE = os.path.join(ADDON_DATA_DIR, 'maincache.db')

def connect():
    """Stabilește conexiunea la baza de date SQLite."""
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        try:
            xbmcvfs.mkdirs(ADDON_DATA_DIR)
        except:
            pass
    
    # --- PROTECȚIE DIMENSIUNE (20MB) ---
    if os.path.exists(DB_FILE):
        try:
            size_mb = os.path.getsize(DB_FILE) / (1024 * 1024)
            if size_mb > 20:
                xbmc.log(f"[tmdbmovies] maincache.db are {size_mb:.2f}MB. RESETARE AUTOMATĂ!", xbmc.LOGWARNING)
                try:
                    xbmcvfs.delete(DB_FILE)
                except:
                    os.remove(DB_FILE)
        except: pass
    # -----------------------------
    
    conn = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    
    try:
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = WAL") # <--- MODIFICAT DIN OFF ÎN WAL
        conn.execute("PRAGMA mmap_size = 268435456")
        conn.execute("PRAGMA cache_size = -10000")
    except Exception:
        pass
        
    return conn

def check_database():
    """Verifică și creează tabelele necesare dacă nu există."""
    try:
        conn = connect()
        cur = conn.cursor()
        
        cur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                       (id text unique, data blob, expires integer)""")
                       
        conn.commit()
        conn.close()
    except Exception:
        pass

# MODIFICARE: Nu mai rulăm check_database() aici! 
# Se va rula doar când este nevoie din cache.py