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
from resources.lib.ext_config import ADDON, ADDON_DATA_DIR, GENRE_MAP

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# La începutul fișierului utils.py, după imports
_debug_cache = None

def _is_debug_enabled():
    """Verifică dacă debug-ul e activat (cu cache pentru performanță)."""
    global _debug_cache
    if _debug_cache is None:
        try:
            from resources.lib.ext_config import ADDON
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
        xbmc.log(f"[TMDb Movies] {msg}", level)
        return
    
    if _is_debug_enabled():
        xbmc.log(f"[TMDb Movies] {msg}", level)

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
        from resources.lib.ext_config import SESSION, get_headers
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
    from resources.lib.utils import clean_text
    import re
    clean_t = clean_text(str(raw_title) or "")
    clean_n = clean_text(str(raw_name) or "")
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
    elif 'hdhub' in full_text: provider = "HDHub"
    elif 'sooti' in full_text or 'hs+' in full_text: provider = "Sooti"
    elif 'vega' in full_text: provider = "Vega"
    elif 'streamvix' in full_text: provider = "StreamVix"
    else:
        parts = clean_n.split(' ')
        if parts and parts[0]: provider = parts[0][:15]

    # --- 3. Determinare Rezoluție (Strictă) ---
    res = "SD"
    if re.search(r'\b(2160p|4k\s|4k$|uhd)\b', full_text): res = "4K"
    elif re.search(r'\b(1080p|1080i|fhd)\b', full_text): res = "1080p"
    elif re.search(r'\b(720p|720i|hd)\b', full_text): res = "720p"
    elif re.search(r'\b(480p|360p|sd)\b', full_text): res = "SD"
    
    if res == "SD" and "4k" in full_text:
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
    quality = str(quality).lower()
    if '4k' in quality or '2160' in quality: return "FFFF00FF"
    elif '1080' in quality: return "FF7CFC00"
    elif '720' in quality: return "FFBA55D3"
    else: return "FF1E90FF"

def clear_cache():
    from resources.lib.ext_config import ADDON_DATA_DIR
    from resources.lib import trakt_sync
    from resources.lib import database
    import os
    import xbmcvfs
    import sqlite3
    from resources.lib.utils import log
    import xbmcgui

    deleted = False
    try:
        trakt_sync.get_connection().close()
        database.connect().close()
    except: pass

    # <<-- ÎNCEPUT MODIFICARE: Nu mai ștergem fișierele DB, ci doar conținutul cache -->>
    
    # 1. Definirea tabelelor care SUNT cache și pot fi golite în siguranță
    CACHE_TABLES_MAIN = ['maincache', 'sources_cache']
    CACHE_TABLES_SYNC = ['meta_cache_items', 'meta_cache_seasons', 'discovery_cache', 'tmdb_discovery', 
                         'trakt_lists', 'user_lists', 'user_list_items', 'tmdb_custom_lists', 
                         'tmdb_custom_list_items', 'tmdb_account_lists', 'tmdb_recommendations']

    try:
        # Golim tabelele de cache din maincache.db
        conn_main = database.connect()
        c_main = conn_main.cursor()
        for table in CACHE_TABLES_MAIN:
            try:
                c_main.execute(f"DELETE FROM {table}")
                if c_main.rowcount > 0: deleted = True
            except sqlite3.OperationalError: pass
        conn_main.commit()
        conn_main.execute("VACUUM")
        conn_main.close()
        log("[CACHE] Main cache tables cleared.")

        # Golim tabelele de cache din trakt_sync.db
        conn_sync = trakt_sync.get_connection()
        c_sync = conn_sync.cursor()
        for table in CACHE_TABLES_SYNC:
            try:
                c_sync.execute(f"DELETE FROM {table}")
                if c_sync.rowcount > 0: deleted = True
            except sqlite3.OperationalError: pass
        conn_sync.commit()
        conn_sync.execute("VACUUM")
        conn_sync.close()
        log("[CACHE] Sync cache tables cleared.")
        
    except Exception as e:
        log(f"[CACHE] Error clearing DB tables: {e}", xbmc.LOGERROR)

    # <<-- FINAL MODIFICARE -->>

    # --- Păstrăm logica ta originală pentru fișierele JSON și proprietățile ferestrei ---
    json_files = ['sources_cache.json', 'tmdb_lists_cache.json', 'trakt_lists_cache.json', 'trakt_history.json', 'last_sync.json']

    for jf in json_files:
        path = os.path.join(ADDON_DATA_DIR, jf)
        if xbmcvfs.exists(path):
            try:
                xbmcvfs.delete(path)
                deleted = True # Am setat 'deleted' la True pentru a păstra logica
            except: pass

    try:
        trakt_sync.init_database() 
        database.check_database()  
        log("[CACHE] Baze de date re-inițializate (doar structura).")
    except Exception as e:
        log(f"[CACHE] Eroare la re-inițializare: {e}", xbmc.LOGERROR)

    try:
        window = xbmcgui.Window(10000)
        props = [
            'tmdbmovies.src_id', 'tmdbmovies.src_data', 'tmdbmovies.need_fast_return',
            'tmdb.list.id', 'tmdb.list.data', 'tmdb.list.use_cache',
            'tmdb.seasons.id', 'tmdb.seasons.data', 'tmdb.seasons.use_cache',
            'tmdb.episodes.id', 'tmdb.episodes.data', 'tmdb.episodes.use_cache',
            'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
            'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
            'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
            'tmdbmovies.has_ro_sub'
        ]
        for p in props:
            window.clearProperty(p)
    except: pass

    return deleted # Am schimbat din 'True' în 'deleted' pentru a reflecta dacă s-a șters ceva

def clear_all_caches_with_notification():
    success = clear_cache()
    if success:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Cache șters!",
            TMDbmovies_ICON, 3000, False)
    else:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
            "Cache-ul era deja gol.",
            TMDbmovies_ICON, 3000, False)
    return success


def set_resume_point(li, resume_seconds, total_seconds):
    """
    Setează punctul de resume pentru un ListItem.
    Compatibil cu Kodi 20+ (fără deprecation warnings).
    """
    try:
        # Metoda nouă (Kodi 20+)
        info_tag = li.getVideoInfoTag()
        if resume_seconds > 0 and total_seconds > 0:
            info_tag.setResumePoint(float(resume_seconds), float(total_seconds))
        else:
            info_tag.setResumePoint(0.0, 0.0)
    except AttributeError:
        # Fallback pentru Kodi 19 (Leia)
        if resume_seconds > 0 and total_seconds > 0:
            li.setProperty('resumetime', str(int(resume_seconds)))
            li.setProperty('totaltime', str(int(total_seconds)))
        else:
            li.setProperty('resumetime', '0')
            li.setProperty('totaltime', '0')


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


# =============================================================================
# AUTO-MAINTENANCE (CLEAN SETTINGS ON UPDATE)
# =============================================================================

def clean_settings():
    """
    Compară settings.xml al utilizatorului cu cel oficial din addon.
    Șterge orice setare 'moartă' (care nu mai există în addon).
    """
    import xml.etree.ElementTree as ET
    from resources.lib.ext_config import ADDON, ADDON_DATA_DIR
    
    addon_path = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
    default_xml = os.path.join(addon_path, 'resources', 'settings.xml')
    profile_xml = os.path.join(ADDON_DATA_DIR, 'settings.xml')
    
    if not os.path.exists(default_xml) or not os.path.exists(profile_xml):
        return False
        
    try:
        # 1. Citim setările oficiale curente din addon
        tree_default = ET.parse(default_xml)
        root_default = tree_default.getroot()
        # Colectăm toate ID-urile valide
        active_settings = [item.get('id') for item in root_default.iter('setting') if item.get('id')]
        
        # 2. Citim setările din profilul utilizatorului
        tree_profile = ET.parse(profile_xml)
        root_profile = tree_profile.getroot()
        
        removed_count = 0
        # 3. Căutăm setările orfane/vechi și le ștergem
        for item in root_profile.findall('setting'):
            if item.get('id') not in active_settings and item.get('id') != 'installed_version':
                root_profile.remove(item)
                removed_count += 1
                
        # 4. Dacă am șters ceva, salvăm fișierul curat
        if removed_count > 0:
            tree_profile.write(profile_xml, encoding='utf-8', xml_declaration=True)
            log(f"[MAINTENANCE] Curățare reușită! S-au șters {removed_count} setări vechi/invalide.")
            return True
            
    except Exception as e:
        log(f"[MAINTENANCE] Eroare la curățarea setărilor: {e}", xbmc.LOGERROR)
        
    return False


def check_addon_update():
    """
    Verifică dacă addon-ul a fost actualizat. Dacă da, rulează mentenanța.
    Se apelează automat la pornirea Kodi (din service.py).
    """
    from resources.lib.ext_config import ADDON
    
    current_version = ADDON.getAddonInfo('version')
    saved_version = ADDON.getSetting('installed_version')
    
    if saved_version != current_version:
        log(f"[MAINTENANCE] Update detectat: de la v{saved_version} la v{current_version}. Rulez auto-curățarea...")
        
        # 1. Curățăm setările vechi din XML
        clean_settings()
        
        # 2. Golim cache-ul (pentru a preveni conflicte cu structuri vechi de date)
        # Nu va șterge istoricul vizionărilor, doar cache-ul temporar!
        from resources.lib.utils import clear_cache
        clear_cache()
        
        # 3. Salvăm noua versiune
        ADDON.setSetting('installed_version', current_version)
        log("[MAINTENANCE] Procesul de update și curățare a fost finalizat cu succes!")


# =============================================================================
# SUPORT ȘI DEPANARE (LOG & DONAȚII)
# =============================================================================

def upload_logfile():
    """Citește fișierul kodi.log și îl încarcă pe paste.kodi.tv"""
    import requests
    dialog = xbmcgui.Dialog()
    
    log_file = xbmcvfs.translatePath('special://logpath/kodi.log')
    url = 'https://paste.kodi.tv/'
    
    if not xbmcvfs.exists(log_file):
        dialog.ok("Eroare", "Fișierul Log nu a fost găsit.")
        return

    # Redus la 2 rânduri
    if not dialog.yesno("Upload Kodi Log", "Vrei să încarci Kodi log (jurnalul) pe paste.kodi.tv?\nEste util pentru raportarea erorilor."):
        return

    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        f = xbmcvfs.File(log_file, 'r')
        text = f.read()
        f.close()
        
        if isinstance(text, str):
            text = text.encode('utf-8', errors='ignore')
            
        response = requests.post(f"{url}documents", data=text, timeout=10.0).json()
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        if 'key' in response:
            link = f"{url}{response['key']}"
            colored_link = f"[B][COLOR FF6AFB92]{link}[/COLOR][/B]"
            # Redus la 2 rânduri
            dialog.ok("Încărcare Reușită", f"Log-ul a fost încărcat cu succes!\n\nLink: {colored_link}")
        else:
            dialog.ok("Eroare", "Încărcarea a eșuat. Verifică log-ul Kodi.")
            
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        log(f"[UTILS] Upload Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Eroare", f"Eroare la încărcare: {str(e)}")


def show_donate_link():
    """Afișează un dialog cu link-ul de donație către Ko-fi"""
    dialog = xbmcgui.Dialog()
    
    # Comprimat la exact 3 rânduri - GARANTAT fără scroll!
    text = (
        "Susține dezvoltarea addonului cumpărându-mi o cafea!\n"
        "Link: [B][COLOR FF6AFB92]https://ko-fi.com/angelitto[/COLOR][/B]\n"
        "Îți mulțumesc pentru sprijin!"
    )
    
    dialog.ok("Susține Proiectul", text)


def perform_trakt_backup(manual=False):
    """Salvează istoricul Trakt (Filme + Episoade) din SQL într-un fișier local JSON."""
    import time
    import datetime
    from resources.lib.utils import write_json, read_json, log
    from resources.lib import trakt_sync

    try:
        # Verificăm setările dacă rulăm în mod automat (în fundal)
        if not manual:
            try: auto_enabled = ADDON.getSetting('trakt_auto_backup') == 'true'
            except: auto_enabled = False
            
            if not auto_enabled:
                return

            try: freq = ADDON.getSetting('trakt_backup_frequency') # 0=Săptămânal, 1=Lunar
            except: freq = '0'
            
            last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
            last_time_data = read_json(last_backup_file) or {}
            last_backup = last_time_data.get('last_run', 0)
            
            days_passed = (time.time() - last_backup) / 86400
            
            if freq == '0' and days_passed < 7:
                return # Nu a trecut o săptămână
            elif freq == '1' and days_passed < 30:
                return # Nu a trecut o lună

        # 1. Creăm folderul dacă nu există
        backup_dir = os.path.join(ADDON_DATA_DIR, 'Trakt_History')
        if not xbmcvfs.exists(backup_dir):
            xbmcvfs.mkdirs(backup_dir)

        # 2. Extragem datele din baza locală SQLite
        backup_data = {'movies': [], 'episodes': []}
        conn = trakt_sync.get_connection()
        c = conn.cursor()

        try:
            c.execute("SELECT tmdb_id, title, year, last_watched_at FROM trakt_watched_movies")
            for row in c.fetchall():
                backup_data['movies'].append(dict(row))
        except: pass

        try:
            c.execute("SELECT tmdb_id, title, season, episode, last_watched_at FROM trakt_watched_episodes")
            for row in c.fetchall():
                backup_data['episodes'].append(dict(row))
        except: pass
        
        conn.close()

        if not backup_data['movies'] and not backup_data['episodes']:
            if manual:
                xbmcgui.Dialog().notification("[B][COLOR pink]Backup[/COLOR][/B]", "Nu există istoric de salvat!", xbmcgui.NOTIFICATION_WARNING)
            return

        # 3. Generăm numele fișierului pe baza datei curente
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"Trakt_History_{date_str}.json"
        filepath = os.path.join(backup_dir, filename)

        # 4. Salvăm fișierul
        if write_json(filepath, backup_data):
            log(f"[BACKUP] Salvare completă în: {filepath}")
            
            # Actualizăm timpul ultimului backup automat
            if not manual:
                last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
                write_json(last_backup_file, {'last_run': time.time()})

            if manual:
                msg = f"Istoric salvat cu succes!\nS-au salvat [B][COLOR FF00FA9A]{len(backup_data['movies'])} filme[/COLOR][/B] și [B][COLOR FF00FA9A]{len(backup_data['episodes'])} episoade[/COLOR][/B] în locația:\n[B][COLOR yellow]Trakt_History/{filename}[/COLOR][/B]"
                xbmcgui.Dialog().ok("Backup Trakt Complet", msg)

    except Exception as e:
        log(f"[BACKUP] Eroare la salvarea istoricului: {e}", xbmc.LOGERROR)
        if manual:
            xbmcgui.Dialog().notification("Eroare", "Eroare la crearea backup-ului.", xbmcgui.NOTIFICATION_ERROR)


