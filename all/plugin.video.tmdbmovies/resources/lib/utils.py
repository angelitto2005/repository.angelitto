import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin  # NOU (necesar pentru meniuri)
import sys         # NOU (necesar pentru handle si argv)
import json
import re
import os
import math
from urllib.parse import quote, unquote, urlencode # NOU

# Import FĂRĂ HEADERS (care acum e funcție)
from resources.lib.config import ADDON, ADDON_DATA_DIR, GENRE_MAP

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# La începutul fișierului utils.py, după imports
_debug_cache = None

def _is_debug_enabled():
    """Verifică dacă debug-ul e activat (cu cache pentru performanță)."""
    global _debug_cache
    if _debug_cache is None:
        try:
            from resources.lib.config import ADDON
            _debug_cache = ADDON.getSetting('debug_enabled') == 'true'
        except:
            _debug_cache = True
    return _debug_cache

def reset_debug_cache():
    """Resetează cache-ul debug (apelat când se schimbă setările)."""
    global _debug_cache
    _debug_cache = None

def log(msg, level=xbmc.LOGINFO):
    """
    Loghează mesaje respectând setarea debug din addon.
    - LOGERROR și LOGWARNING: se loghează MEREU
    - LOGINFO și LOGDEBUG: doar dacă debug e activat
    """
    if level in (xbmc.LOGERROR, xbmc.LOGWARNING):
        xbmc.log(f"[tmdbmovies] {msg}", level)
        return
    
    if _is_debug_enabled():
        xbmc.log(f"[tmdbmovies] {msg}", level)

def get_language():
    return 'en-US'

def ensure_addon_dir():
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        xbmcvfs.mkdirs(ADDON_DATA_DIR)

def read_json(filepath):
    """Citește fișier JSON cu logging."""
    try:
        if not xbmcvfs.exists(filepath):
            # Nu logăm warning pentru fișiere care normal nu există încă
            return None
            
        f = xbmcvfs.File(filepath, 'r')
        content = f.read()
        f.close()
        
        if not content or content.strip() == '':
            log(f"[UTILS] ⚠️ Empty file: {filepath}", xbmc.LOGWARNING)
            return None
            
        data = json.loads(content)
        return data
    except json.JSONDecodeError as e:
        log(f"[UTILS] ❌ JSON decode error in {filepath}: {e}", xbmc.LOGERROR)
        return None
    except Exception as e:
        log(f"[UTILS] ❌ Error reading {filepath}: {e}", xbmc.LOGERROR)
        return None


def write_json(filepath, data):
    """Salvează fișier JSON."""
    ensure_addon_dir()
    try:
        content = json.dumps(data, indent=2)
        f = xbmcvfs.File(filepath, 'w')
        success = f.write(content)
        f.close()
        
        if not success:
            log(f"[UTILS] ⚠️ Write returned False for {filepath}", xbmc.LOGWARNING)
        return success
    except Exception as e:
        log(f"[UTILS] ❌ Error writing {filepath}: {e}", xbmc.LOGERROR)
        return False


def clean_text(text):
    """
    Curăță textul de caractere non-standard (emoji, steaguri, simboluri).
    Păstrează doar: Litere (A-Z), Cifre (0-9), Punctuație de bază (.-_()[]).
    """
    if not text:
        return ""
    
    # 1. Asigurăm decodare
    if isinstance(text, bytes):
        try: text = text.decode('utf-8', errors='ignore')
        except: pass

    # 2. Elimină TOT ce nu e ASCII standard (0-127)
    # Asta distruge instantaneu steagurile 🇺🇸 🇮🇳 și orice emoji
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    
    # 3. Elimină caracterele ASCII ciudate rămase (ex: |, ~, `)
    # Păstrăm doar alfanumerice și semne sigure
    text = re.sub(r'[^a-zA-Z0-9\s\.\-\_\[\]\(\)\+]', '', text)

    # 4. Curățare spații multiple
    text = ' '.join(text.split())
    
    return text.strip()

def get_json(url):
    try:
        from resources.lib.config import SESSION, get_headers
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Timeout redus: Dacă TMDb nu răspunde în 5 sec, tăiem conexiunea
        # Asta previne mesajul "waiting on thread"
        r = SESSION.get(url, headers=get_headers(), timeout=5, verify=False)
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

def extract_details(raw_title, raw_name):
    """
    Extrage mărimea, provider-ul și rezoluția REALĂ.
    Ignoră '4k' din numele site-urilor (ex: 4khdhub).
    """
    clean_t = clean_text(raw_title or "")
    clean_n = clean_text(raw_name or "")
    full_text = (clean_n + " " + clean_t).lower()

    # --- 1. Extragere Mărime ---
    size_match = re.search(r'(\d+(\.\d+)?\s?(gb|gib|mb|mib))', full_text, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else "N/A"
    
    # --- 2. Determinare Provider ---
    provider = "Unknown"
    if 'fsl' in full_text or 'flash' in full_text: provider = "Flash"
    elif 'pix' in full_text or 'pixeldrain' in full_text: provider = "PixelDrain"
    elif 'vixsrc' in full_text: provider = "VixSrc"
    elif 'gdrive' in full_text or 'google' in full_text: provider = "GDrive"
    elif 'fichier' in full_text: provider = "1Fichier"
    elif 'hubcloud' in full_text: provider = "HubCloud"
    elif 'vidzee' in full_text or 'vflix' in full_text: provider = "Vidzee"
    elif 'meow' in full_text: provider = "MeowTV"
    elif 'flixhq' in full_text: provider = "FlixHQ"
    elif 'nuvio' in full_text: provider = "Nuvio"
    elif 'webstream' in full_text: provider = "WebStream"
    elif 'sooti' in full_text or 'hs+' in full_text: provider = "Sooti"
    elif 'vega' in full_text: provider = "Vega"
    elif 'streamvix' in full_text: provider = "StreamVix"
    else:
        parts = clean_n.split(' ')
        if parts and parts[0]: provider = parts[0][:15]

    # --- 3. Determinare Rezoluție (Strictă) ---
    # Căutăm tipare specifice de rezoluție (2160p, 1080p) NU doar cuvinte
    res = "SD"
    
    # Prioritate 1: Regex strict (ex: "2160p", "4k 10bit", "4k hdr")
    if re.search(r'\b(2160p|4k\s|4k$|uhd)\b', full_text): 
        res = "4K"
    elif re.search(r'\b(1080p|1080i|fhd)\b', full_text): 
        res = "1080p"
    elif re.search(r'\b(720p|720i|hd)\b', full_text): 
        res = "720p"
    elif re.search(r'\b(480p|360p|sd)\b', full_text): 
        res = "SD"
    
    # Fallback: Dacă nu găsim "p", dar găsim "4k" izolat și nu e în numele site-ului
    if res == "SD" and "4k" in full_text:
        # Excludem site-urile cunoscute cu 4k în nume
        if "4khdhub" not in full_text and "4kmovies" not in full_text:
             res = "4K"

    return size, provider, res

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
        'trakt_history.json',
        'last_sync.json' # <--- ADĂUGAT PENTRU SMART SYNC FIX
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


def set_resume_point(li, resume_seconds, total_seconds):
    """
    Setează punctul de resume pentru un ListItem.
    Compatibil cu Kodi 20+ (fără deprecation warnings).
    
    Args:
        li: xbmcgui.ListItem
        resume_seconds: secunde vizionate (float/int)
        total_seconds: durata totală în secunde (float/int)
    """
    if resume_seconds > 0 and total_seconds > 0:
        try:
            # Metoda nouă (Kodi 20+)
            info_tag = li.getVideoInfoTag()
            info_tag.setResumePoint(float(resume_seconds), float(total_seconds))
        except AttributeError:
            # Fallback pentru Kodi 19 (Leia) - dacă mai ai useri pe versiuni vechi
            li.setProperty('resumetime', str(int(resume_seconds)))
            li.setProperty('totaltime', str(int(total_seconds)))


# =============================================================================
# DOWNLOADS BROWSER & MANAGER
# =============================================================================

def build_downloads_list(params):
    """
    Construiește lista de fișiere descărcate.
    Folderele au meniu personalizat, fișierele folosesc meniul nativ Kodi.
    """
    try:
        handle = int(sys.argv[1])
    except:
        handle = -1

    addon_id = ADDON.getAddonInfo('id')
    base_path = f"special://profile/addon_data/{addon_id}/Downloads/"
    
    current_folder = params.get('folder')
    path_to_list = unquote(current_folder) if current_folder else base_path

    if not path_to_list.endswith('/'):
        path_to_list += '/'

    if not xbmcvfs.exists(path_to_list):
        xbmcvfs.mkdirs(path_to_list)

    listing = []
    dirs, files = xbmcvfs.listdir(path_to_list)
    dirs.sort()
    files.sort()

    # --- FOLDERE (Păstrăm Rename și Delete de la tine) ---
    for d in dirs:
        full_path = path_to_list + d + "/"
        li = xbmcgui.ListItem(label=f"[COLOR yellow]{d}[/COLOR]")
        li.setArt({'icon': 'DefaultFolder.png'})
        li.setInfo('video', {'title': d})
        
        # Meniu contextual personalizat DOAR pentru foldere
        cm = []
        del_url = f"RunPlugin({sys.argv[0]}?mode=delete_download&path={quote(full_path)})"
        cm.append(('Delete Folder', del_url))
        
        ren_url = f"RunPlugin({sys.argv[0]}?mode=rename_download&path={quote(full_path)})"
        cm.append(('Rename Folder', ren_url))
        
        li.addContextMenuItems(cm)
        
        url = f"{sys.argv[0]}?mode=downloads_menu&folder={quote(full_path)}"
        listing.append((url, li, True))

    # --- FIȘIERE (Lăsăm Kodi să gestioneze context menu) ---
    for f in files:
        if f.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.strm', '.mov')):
            full_path = path_to_list + f
            
            li = xbmcgui.ListItem(label=f"[COLOR cyan]{f}[/COLOR]")
            # Important: setInfo ajută Kodi să activeze opțiunile de Resume
            li.setInfo('video', {'title': f}) 
            li.setArt({'icon': 'DefaultVideo.png'})
            li.setProperty('IsPlayable', 'true')
            li.setPath(full_path)
            
            # NU mai adăugăm li.addContextMenuItems(cm_file) aici.
            # Kodi va afișa automat meniul lui standard (Play, Resume, Delete, Rename).
            
            listing.append((full_path, li, False))

    xbmcplugin.addDirectoryItems(handle, listing, len(listing))
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.endOfDirectory(handle)
    

def delete_download_folder(params):
    path = unquote(params.get('path'))
    
    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Ștergere Folder", f"Sigur vrei să ștergi folderul?\n[COLOR yellow]{path}[/COLOR]"):
        return

    try:
        # Golim folderul întâi (Kodi nu șterge foldere pline)
        dirs, files = xbmcvfs.listdir(path)
        for f in files:
            xbmcvfs.delete(path + f)
            
        if dirs:
            xbmcgui.Dialog().notification("Eroare", "Folderul conține alte foldere.", xbmcgui.NOTIFICATION_ERROR)
            return

        if xbmcvfs.rmdir(path):
            xbmcgui.Dialog().notification("Succes", "Folder șters.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Eroare", "Nu s-a putut șterge.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Delete Error: {e}", xbmc.LOGERROR)


def rename_download_folder(params):
    path = unquote(params.get('path'))
    
    clean_path = path.rstrip('/') 
    old_name = clean_path.split('/')[-1]
    parent_dir = clean_path.rsplit('/', 1)[0] + '/'
    
    dialog = xbmcgui.Dialog()
    new_name = dialog.input("Redenumire", defaultt=old_name)
    
    if not new_name or new_name == old_name:
        return

    new_path = parent_dir + new_name + "/"
    
    try:
        # Încercăm redenumirea
        success = False
        if xbmcvfs.rename(clean_path, new_path[:-1]): success = True
        elif xbmcvfs.rename(path, new_path): success = True
        
        if success:
            xbmcgui.Dialog().notification("Succes", "Redenumit.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Eroare", "Nu s-a putut redenumi.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Rename Error: {e}", xbmc.LOGERROR)

