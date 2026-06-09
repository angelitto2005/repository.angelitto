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

# Import WITHOUT HEADERS (which is now a function)
from resources.lib.config import ADDON, ADDON_DATA_DIR, GENRE_MAP

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# At the beginning of utils.py, after imports
_debug_cache = None

def _is_debug_enabled():
    """Check if debug is enabled (with cache for performance)."""
    global _debug_cache
    if _debug_cache is None:
        try:
            from resources.lib.config import ADDON
            _debug_cache = ADDON.getSetting('debug_enabled') == 'true'
        except:
            _debug_cache = True
    return _debug_cache

def reset_debug_cache():
    """Reset debug cache (called when settings change)."""
    global _debug_cache
    _debug_cache = None

def log(msg, level=xbmc.LOGINFO):
    """
    Log messages respecting the debug setting from addon.
    - LOGERROR and LOGWARNING: always logged
    - LOGINFO and LOGDEBUG: only if debug is enabled
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
    """Read JSON file with logging."""
    try:
        if not xbmcvfs.exists(filepath):
            # No log warning for files that normally don't exist yet
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
    """Save JSON file."""
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
    Clean text of non-standard characters (emoji, flags, symbols).
    Keeps only: Letters (A-Z), Numbers (0-9), Basic punctuation (.-_()[]).
    """
    if not text:
        return ""
    
    # 1. Ensure decoding
    if isinstance(text, bytes):
        try: text = text.decode('utf-8', errors='ignore')
        except: pass

    # 2. Remove ALL non-ASCII (0-127)
    # This instantly destroys flags and any emoji
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    
    # 3. Remove remaining weird ASCII chars (e.g. |, ~, `)
    # Keep only alphanumeric and safe signs
    text = re.sub(r'[^a-zA-Z0-9\s\.\-\_\[\]\(\)\+]', '', text)

    # 4. Clean multiple spaces
    text = ' '.join(text.split())
    
    return text.strip()

def get_json(url):
    try:
        from resources.lib.config import SESSION, get_headers
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Reduced timeout: If TMDb doesn't respond in 5 sec, cut the connection
        # This prevents the "waiting on thread" message
        r = SESSION.get(url, headers=get_headers(), timeout=5, verify=False)
        r.raise_for_status()
        return r.json()
    except:
        return {}

def paginate_list(item_list, page, limit=20):
    """
    Essential function for the new cache system.
    Receives a long list (e.g. 100 movies) and returns only the 20
    for the current page, plus the total number of pages.
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

    # --- 1. Extract Size ---
    size_match = re.search(r'(\d+(\.\d+)?\s?(gb|gib|mb|mib))', full_text, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else "N/A"
    
    # --- 2. Determine Provider ---
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
    elif 'webstream' in full_text: provider = "WebStream"
    elif 'hdhub' in full_text: provider = "HDHub"
    elif 'sooti' in full_text or 'hs+' in full_text: provider = "Sooti"
    elif 'vega' in full_text: provider = "Vega"
    elif 'streamvix' in full_text: provider = "StreamVix"
    else:
        parts = clean_n.split(' ')
        if parts and parts[0]: provider = parts[0][:15]

    # --- 3. Determine Resolution (Strict) ---
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
    """Convert list of genre IDs to string."""
    if not genre_ids:
        return ''
    
    # Use GENRE_MAP from config (imported above)
    names = [GENRE_MAP.get(g_id, '') for g_id in genre_ids]
    return ', '.join(filter(None, names))

def get_color_for_quality(quality):
    quality = str(quality).lower()
    if '4k' in quality or '2160' in quality: return "FFFF00FF"
    elif '1080' in quality: return "FF7CFC00"
    elif '720' in quality: return "FFBA55D3"
    else: return "FF1E90FF"

def clear_cache():
    from resources.lib.config import ADDON_DATA_DIR
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

    # <<-- BEGIN MODIFICATION: Don't delete DB files anymore, only cache content -->>
    
    # 1. Define cache tables that can be safely emptied
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

    # <<-- END MODIFICATION -->>

    # --- Keep your original logic for JSON files and window properties ---
    json_files = ['sources_cache.json', 'tmdb_lists_cache.json', 'trakt_lists_cache.json', 'trakt_history.json', 'last_sync.json']

    for jf in json_files:
        path = os.path.join(ADDON_DATA_DIR, jf)
        if xbmcvfs.exists(path):
            try:
                xbmcvfs.delete(path)
                deleted = True # Set 'deleted' to True to maintain logic
            except: pass

    try:
        trakt_sync.init_database() 
        database.check_database()  
        log("[CACHE] Databases re-initialized (structure only).")
    except Exception as e:
        log(f"[CACHE] Error re-initializing: {e}", xbmc.LOGERROR)

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
            'tmdbmovies.has_ro_sub', 'tmdbmovies.sub_text_label'
        ]
        for p in props:
            window.clearProperty(p)
    except: pass

    return deleted # Changed from 'True' to 'deleted' to reflect if something was deleted

def clear_all_caches_with_notification():
    success = clear_cache()
    if success:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Cache cleared!",
            TMDbmovies_ICON, 3000, False)
    else:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
            "Cache was already empty.",
            TMDbmovies_ICON, 3000, False)
    return success


def set_resume_point(li, resume_seconds, total_seconds):
    """
    Sets the resume point for a ListItem.
    Compatible with Kodi 20+ (no deprecation warnings).
    """
    try:
    # New method (Kodi 20+)
        info_tag = li.getVideoInfoTag()
        if resume_seconds > 0 and total_seconds > 0:
            info_tag.setResumePoint(float(resume_seconds), float(total_seconds))
        else:
            info_tag.setResumePoint(0.0, 0.0)
    except AttributeError:
        # Fallback for Kodi 19 (Leia)
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
    Builds the list of downloaded files.
    Folders have custom menu, files use native Kodi menu.
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

    # --- FOLDERS (Keep Rename and Delete from you) ---
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

    # --- FILES (Let Kodi handle context menu) ---
    for f in files:
        if f.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.strm', '.mov')):
            full_path = path_to_list + f
            
            li = xbmcgui.ListItem(label=f"[COLOR cyan]{f}[/COLOR]")
            # Important: setInfo helps Kodi activate Resume options
            li.setInfo('video', {'title': f}) 
            li.setArt({'icon': 'DefaultVideo.png'})
            li.setProperty('IsPlayable', 'true')
            li.setPath(full_path)
            
            # NO longer add li.addContextMenuItems(cm_file) here.
            # Kodi will automatically show its standard menu (Play, Resume, Delete, Rename).
            
            listing.append((full_path, li, False))

    xbmcplugin.addDirectoryItems(handle, listing, len(listing))
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.endOfDirectory(handle)
    

def delete_download_folder(params):
    path = unquote(params.get('path'))
    
    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Delete Folder", f"Are you sure you want to delete the folder?\n[COLOR yellow]{path}[/COLOR]"):
        return

    try:
        # Empty the folder first (Kodi doesn't delete non-empty folders)
        dirs, files = xbmcvfs.listdir(path)
        for f in files:
            xbmcvfs.delete(path + f)
            
        if dirs:
            xbmcgui.Dialog().notification("Error", "The folder contains other folders.", xbmcgui.NOTIFICATION_ERROR)
            return

        if xbmcvfs.rmdir(path):
            xbmcgui.Dialog().notification("Success", "Folder deleted.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Error", "Could not delete.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Delete Error: {e}", xbmc.LOGERROR)


def rename_download_folder(params):
    path = unquote(params.get('path'))
    
    clean_path = path.rstrip('/') 
    old_name = clean_path.split('/')[-1]
    parent_dir = clean_path.rsplit('/', 1)[0] + '/'
    
    dialog = xbmcgui.Dialog()
    new_name = dialog.input("Rename", defaultt=old_name)
    
    if not new_name or new_name == old_name:
        return

    new_path = parent_dir + new_name + "/"
    
    try:
        # Try the rename
        success = False
        if xbmcvfs.rename(clean_path, new_path[:-1]): success = True
        elif xbmcvfs.rename(path, new_path): success = True
        
        if success:
            xbmcgui.Dialog().notification("Success", "Renamed.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Error", "Could not rename.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Rename Error: {e}", xbmc.LOGERROR)


# =============================================================================
# AUTO-MAINTENANCE (CLEAN SETTINGS ON UPDATE)
# =============================================================================

def clean_settings():
    """
    Compares user's settings.xml with the official one from the addon.
    Removes any 'dead' setting (that no longer exists in the addon).
    """
    import xml.etree.ElementTree as ET
    from resources.lib.config import ADDON, ADDON_DATA_DIR
    
    addon_path = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
    default_xml = os.path.join(addon_path, 'resources', 'settings.xml')
    profile_xml = os.path.join(ADDON_DATA_DIR, 'settings.xml')
    
    if not os.path.exists(default_xml) or not os.path.exists(profile_xml):
        return False
        
    try:
        # 1. Read current official settings from addon
        tree_default = ET.parse(default_xml)
        root_default = tree_default.getroot()
        # Collect all valid IDs
        active_settings = [item.get('id') for item in root_default.iter('setting') if item.get('id')]
        
        # 2. Read settings from user profile
        tree_profile = ET.parse(profile_xml)
        root_profile = tree_profile.getroot()
        
        removed_count = 0
        # 3. Search for orphan/old settings and delete them
        for item in root_profile.findall('setting'):
            if item.get('id') not in active_settings and item.get('id') != 'installed_version':
                root_profile.remove(item)
                removed_count += 1
                
        # 4. If we deleted something, save the clean file
        if removed_count > 0:
            tree_profile.write(profile_xml, encoding='utf-8', xml_declaration=True)
            log(f"[MAINTENANCE] Clean successful! Deleted {removed_count} old/invalid settings.")
            return True
            
    except Exception as e:
        log(f"[MAINTENANCE] Error cleaning settings: {e}", xbmc.LOGERROR)
        
    return False


def check_addon_update():
    """
    Checks if the addon has been updated. If so, runs maintenance.
    Called automatically on Kodi startup (from service.py).
    """
    from resources.lib.config import ADDON
    
    current_version = ADDON.getAddonInfo('version')
    saved_version = ADDON.getSetting('installed_version')
    
    if saved_version != current_version:
        log(f"[MAINTENANCE] Update detected: from v{saved_version} to v{current_version}. Running auto-cleanup...")
        
        # 1. Clean old settings from XML
        clean_settings()
        
        # 2. Clear cache (to prevent conflicts with old data structures)
        # Will NOT delete watch history, only temporary cache!
        from resources.lib.utils import clear_cache
        clear_cache()
        
        # 3. Save new version
        ADDON.setSetting('installed_version', current_version)
        log("[MAINTENANCE] Update and cleanup process completed successfully!")


# =============================================================================
# SUPPORT & TROUBLESHOOTING (LOG & DONATIONS)
# =============================================================================

def upload_logfile():
    """Reads kodi.log file and uploads it to paste.kodi.tv"""
    import requests
    dialog = xbmcgui.Dialog()
    
    log_file = xbmcvfs.translatePath('special://logpath/kodi.log')
    url = 'https://paste.kodi.tv/'
    
    if not xbmcvfs.exists(log_file):
        dialog.ok("Error", "Log file not found.")
        return

    # Redus la 2 rânduri
    if not dialog.yesno("Upload Kodi Log", "Do you want to upload the Kodi log to paste.kodi.tv?\nUseful for error reporting."):
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
            dialog.ok("Upload Successful", f"The log was uploaded successfully!\n\nLink: {colored_link}")
        else:
            dialog.ok("Error", "Upload failed. Check the Kodi log.")
            
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        log(f"[UTILS] Upload Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Error", f"Load error: {str(e)}")


def show_donate_link():
    """Shows a dialog with the donation link to Ko-fi"""
    dialog = xbmcgui.Dialog()
    
    # Comprimat la exact 3 rânduri - GARANTAT fără scroll!
    text = (
        "Support addon development by buying me a coffee!\n"
        "Link: [B][COLOR FF6AFB92]https://ko-fi.com/angelitto[/COLOR][/B]\n"
        "Thank you for your support!"
    )
    
    dialog.ok("Support the Project", text)


def perform_trakt_backup(manual=False):
    """Saves Trakt history (Movies + Episodes) from SQL to a local JSON file."""
    import time
    import datetime
    from resources.lib.utils import write_json, read_json, log
    from resources.lib import trakt_sync

    try:
        # Check settings if running in automatic mode (background)
        if not manual:
            try: auto_enabled = ADDON.getSetting('trakt_auto_backup') == 'true'
            except: auto_enabled = False
            
            if not auto_enabled:
                return

            try: freq = ADDON.getSetting('trakt_backup_frequency') # 0=Weekly, 1=Monthly
            except: freq = '0'
            
            last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
            last_time_data = read_json(last_backup_file) or {}
            last_backup = last_time_data.get('last_run', 0)
            
            days_passed = (time.time() - last_backup) / 86400
            
            if freq == '0' and days_passed < 7:
                return # Hasn't been a week
            elif freq == '1' and days_passed < 30:
                return # Hasn't been a month

        # 1. Create folder if it doesn't exist
        backup_dir = os.path.join(ADDON_DATA_DIR, 'Trakt_History')
        if not xbmcvfs.exists(backup_dir):
            xbmcvfs.mkdirs(backup_dir)

        # 2. Extract data from local SQLite database
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
                xbmcgui.Dialog().notification("[B][COLOR pink]Backup[/COLOR][/B]", "No history to save!", xbmcgui.NOTIFICATION_WARNING)
            return

        # 3. Generate file name based on current date
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"Trakt_History_{date_str}.json"
        filepath = os.path.join(backup_dir, filename)

        # 4. Save file
        if write_json(filepath, backup_data):
            log(f"[BACKUP] Complete save in: {filepath}")
            
            # Update last backup time
            if not manual:
                last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
                write_json(last_backup_file, {'last_run': time.time()})

            if manual:
                msg = f"History saved successfully!\nSaved [B][COLOR FF00FA9A]{len(backup_data['movies'])} movies[/COLOR][/B] and [B][COLOR FF00FA9A]{len(backup_data['episodes'])} episodes[/COLOR][/B] at:\n[B][COLOR yellow]Trakt_History/{filename}[/COLOR][/B]"
                xbmcgui.Dialog().ok("Backup Trakt Complet", msg)

    except Exception as e:
        log(f"[BACKUP] Error saving history: {e}", xbmc.LOGERROR)
        if manual:
            xbmcgui.Dialog().notification("Error", "Error creating backup.", xbmcgui.NOTIFICATION_ERROR)


