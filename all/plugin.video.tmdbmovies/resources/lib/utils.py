import xbmc
import xbmcvfs
import xbmcgui
import json
import re
import os
import math

# Import FĂRĂ HEADERS (care acum e funcție)
from resources.lib.config import ADDON, ADDON_DATA_DIR, GENRE_MAP

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

def log(msg, level=xbmc.LOGINFO):
    if ADDON.getSetting('debug_enabled') == 'true' or level == xbmc.LOGERROR:
        xbmc.log(f"[tmdbmovies] {msg}", level)

def get_language():
    return 'en-US'

def ensure_addon_dir():
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        xbmcvfs.mkdirs(ADDON_DATA_DIR)

def read_json(filepath):
    ensure_addon_dir()
    if not xbmcvfs.exists(filepath):
        return {}
    try:
        f = xbmcvfs.File(filepath)
        content = f.read()
        f.close()
        return json.loads(content) if content else {}
    except:
        return {}

def write_json(filepath, data):
    ensure_addon_dir()
    try:
        f = xbmcvfs.File(filepath, 'w')
        f.write(json.dumps(data))
        f.close()
    except:
        pass

def clean_text(text):
    """Curăță textul de caractere non-ASCII."""
    if not text:
        return ""
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('\n', ' ').replace('\r', '')
    return text.strip()

def get_json(url):
    """
    Funcție simplă pentru request-uri directe.
    Folosește Lazy Import pentru requests.
    """
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Import funcția get_headers() în loc de constanta HEADERS
        from resources.lib.config import get_headers
        
        r = requests.get(url, headers=get_headers(), timeout=10, verify=False)
        r.raise_for_status()
        return r.json()
    except:
        return {}

def paginate_list(item_list, page, limit=20):
    """
    Funcție esențială pentru noul sistem de cache.
    Primește o listă lungă (ex: 100 filme) și returnează doar cele 20 
    pentru pagina curentă, plus numărul total de pagini.
    """
    if not item_list:
        return [], 0
    count = len(item_list)
    total_pages = math.ceil(count / limit)
    
    start = (page - 1) * limit
    end = start + limit
    
    current_items = item_list[start:end]
    
    return current_items, total_pages

def extract_size_provider(raw_title, raw_name):
    """Extrage dimensiunea și provider-ul din titlul sursei."""
    clean_t = clean_text(raw_title or "")
    size_match = re.search(r'(\d+(\.\d+)?\s?GB)', clean_t, re.IGNORECASE)
    size = size_match.group(1) if size_match else "N/A"
    
    raw_lower = (raw_name or "").lower()
    provider = "Unknown"
    
    # Detectare provider
    if 'fsl' in raw_lower or 'flash' in raw_lower:
        provider = "Flash"
    elif 'pix' in raw_lower or 'pixeldrain' in raw_lower:
        provider = "PixelDrain"
    elif 'vixsrc' in raw_lower:
        provider = "VixSrc"
    elif 'gdrive' in raw_lower or 'google' in raw_lower:
        provider = "GDrive"
    elif 'fichier' in raw_lower or '1fichier' in raw_lower:
        provider = "1Fichier"
    elif 'hubcloud' in raw_lower:
        provider = "HubCloud"
    elif 'vidzee' in raw_lower or 'vflix' in raw_lower:
        provider = "Vidzee"
    elif 'flixhq' in raw_lower:
        provider = "FlixHQ"
    elif 'nuvio' in raw_lower:
        provider = "Nuvio"
    elif 'webstream' in raw_lower:
        provider = "WebStream"
    elif 'sooti' in raw_lower or 'hs+' in raw_lower:
        provider = "Sooti"
    else:
        parts = clean_text(raw_name or "").split(' ')
        if parts and parts[0]:
            provider = parts[0][:15]
        
    return size, provider

def get_genres_string(genre_ids):
    """Convertește lista de ID-uri de gen în string."""
    if not genre_ids:
        return ''
    
    # Folosim GENRE_MAP din config (importat sus)
    names = [GENRE_MAP.get(g_id, '') for g_id in genre_ids]
    return ', '.join(filter(None, names))

def get_color_for_quality(quality):
    """Returnează culoarea pentru o calitate video."""
    quality = quality.lower()
    if '4k' in quality or '2160' in quality:
        return "FF00FFFF"  # Cyan
    elif '1080' in quality:
        return "FF00FF7F"  # Verde
    elif '720' in quality:
        return "FFFFD700"  # Galben
    else:
        return "FF00BFFF"  # Albastru

def clear_cache():
    """
    Șterge complet fișierele de cache fizic și REINIȚIALIZEAZĂ bazele de date.
    """
    from resources.lib.config import ADDON_DATA_DIR
    from resources.lib import trakt_sync
    from resources.lib import database
    import os
    import xbmcvfs
    import sqlite3

    deleted = False
    
    # 1. Închidem orice conexiune agățată (preventiv)
    try:
        trakt_sync.get_connection().close()
        database.connect().close()
    except: pass

    # 2. Fișierele de șters
    db_files = [
        'maincache.db', 'maincache.db-shm', 'maincache.db-wal',
        'trakt_sync.db', 'trakt_sync.db-shm', 'trakt_sync.db-wal'
    ]

    json_files = [
        'sources_cache.json',
        'tmdb_lists_cache.json',
        'trakt_lists_cache.json',
        'trakt_history.json'
    ]

    # 3. Ștergere Fizică
    for db in db_files:
        path = os.path.join(ADDON_DATA_DIR, db)
        if xbmcvfs.exists(path):
            try:
                xbmcvfs.delete(path)
                deleted = True
            except: 
                # Fallback pentru Windows/Android dacă fișierul e blocat
                try: os.remove(path)
                except: pass

    for jf in json_files:
        path = os.path.join(ADDON_DATA_DIR, jf)
        if xbmcvfs.exists(path):
            try: xbmcvfs.delete(path)
            except: pass

    # 4. RE-INIȚIALIZARE OBLIGATORIE (Aici era problema!)
    # Recreăm tabelele goale imediat, altfel addonul dă eroare la următorul pas
    try:
        trakt_sync.init_database() # Recreează tabelele în trakt_sync.db
        database.check_database()  # Recreează tabelele în maincache.db
        log("[CACHE] Baze de date re-inițializate cu succes.")
    except Exception as e:
        log(f"[CACHE] Eroare la re-inițializare: {e}", xbmc.LOGERROR)

    # 5. Curățare RAM (Properties)
    try:
        window = xbmcgui.Window(10000)
        props = [
            'tmdbmovies.src_id', 'tmdbmovies.src_data', 'tmdbmovies.need_fast_return',
            'tmdb.list.id', 'tmdb.list.data', 'tmdb.list.use_cache',
            'tmdb.seasons.id', 'tmdb.seasons.data', 'tmdb.seasons.use_cache',
            'tmdb.episodes.id', 'tmdb.episodes.data', 'tmdb.episodes.use_cache'
        ]
        for p in props:
            window.clearProperty(p)
    except: pass

    return True

def clear_all_caches_with_notification():
    success = clear_cache()
    if success:
        xbmcgui.Dialog().notification(
            "[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Cache șters!",
            TMDbmovies_ICON, 3000, False)
    else:
        xbmcgui.Dialog().notification(
            "[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]",
            "Cache-ul era deja gol.",
            TMDbmovies_ICON, 3000, False)
    return success