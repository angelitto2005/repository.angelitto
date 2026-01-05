import sqlite3
import xbmcvfs
import os
from resources.lib.config import ADDON_DATA_DIR

DB_FILE = os.path.join(ADDON_DATA_DIR, 'maincache.db')

def connect():
    """Stabilește conexiunea la baza de date SQLite."""
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        try:
            xbmcvfs.mkdirs(ADDON_DATA_DIR)
        except:
            pass
    
    # MODIFICARE: Marim timeout la 60 secunde pentru Android
    conn = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    
    try:
        # MODIFICARE: PRAGMA intr-un bloc try/except. 
        # Daca baza e blocata, ignoram optimizarea si mergem mai departe fara eroare.
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
        
        cur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                       (id text unique, data text, expires integer)""")
                       
        conn.commit()
        conn.close()
    except Exception:
        pass

# Inițializăm baza de date la importul acestui modul
check_database()