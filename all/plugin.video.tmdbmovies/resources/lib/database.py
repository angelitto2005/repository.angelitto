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
    # Acum folosim 'os' definit global la inceputul fisierului
    if os.path.exists(DB_FILE):
        try:
            size_mb = os.path.getsize(DB_FILE) / (1024 * 1024)
            if size_mb > 20:
                xbmc.log(f"[tmdbmovies] maincache.db are {size_mb:.2f}MB. RESETARE AUTOMATĂ!", xbmc.LOGWARNING)
                try:
                    # Încercăm metoda Kodi
                    xbmcvfs.delete(DB_FILE)
                except:
                    # Fallback metoda sistem (acum merge corect)
                    os.remove(DB_FILE)
        except: pass
    # -----------------------------
    
    # MODIFICARE: Marim timeout la 60 secunde pentru Android
    conn = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    
    try:
        # MODIFICARE: PRAGMA intr-un bloc try/except. 
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
        
    return conn

def check_database():
    """Verifică și creează tabelele necesare dacă nu există."""
    try:
        conn = connect()
        cur = conn.cursor()
        
        # ATENȚIE: 'data blob' pentru suport compresie zlib
        cur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                       (id text unique, data blob, expires integer)""")
                       
        conn.commit()
        conn.close()
    except Exception:
        pass

# Inițializăm baza de date la importul acestui modul
check_database()