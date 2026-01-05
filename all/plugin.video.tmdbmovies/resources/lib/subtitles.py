import os
import requests
import xbmc
import xbmcgui
import xbmcvfs
import shutil
import time
from resources.lib.config import ADDON, ADDON_DATA_DIR


# --- CONFIG ---
ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')
BASE_URL = 'https://sub.wyzie.ru/search'


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[tmdbmovies-subs] {msg}", level)

def get_subs_folder():
    subs_path = os.path.join(ADDON_DATA_DIR, 'subs')
    if not xbmcvfs.exists(subs_path):
        xbmcvfs.mkdirs(subs_path)
    return subs_path

def cleanup_subs():
    """Curăță folderul de subtitrări la start."""
    subs_path = get_subs_folder()
    try:
        dirs, files = xbmcvfs.listdir(subs_path)
        for f in files:
            xbmcvfs.delete(os.path.join(subs_path, f))
    except Exception as e:
        log(f"Cleanup error: {e}", xbmc.LOGERROR)

def search_subtitles(imdb_id, season=None, episode=None):
    if not imdb_id: return []

    # Luăm limbile din setări (default: ro,en)
    langs_setting = ADDON.getSetting('wyzie_langs') or 'ro,en'
    languages = [l.strip() for l in langs_setting.split(',')]
    
    found_subs = []
    
    for lang in languages:
        params = {'id': imdb_id, 'language': lang, 'format': 'srt'}
        if season and episode:
            params.update({'season': season, 'episode': episode})

        try:
            r = requests.get(BASE_URL, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list): found_subs.extend(data)
                elif isinstance(data, dict): found_subs.append(data)
        except: pass
    
    return found_subs

def download_and_save(sub_data, index):
    try:
        url = sub_data.get('url')
        if not url: return None
        
        folder = get_subs_folder()
        
        # --- MODIFICARE NUME FIȘIER ---
        # Format dorit: ReleaseName.Index.Lang.srt
        # Exemplu: Eternity.2025...H.264-BYNDR.00.ro.srt
        
        ext = sub_data.get('format', 'srt')
        lang_code = sub_data.get('language', 'unk') # 'ro', 'en'
        
        # Preferăm numele release-ului, dacă nu există, folosim numele media
        release_name = sub_data.get('release', sub_data.get('media', f'Sub_{index}'))
        
        # Construim numele exact cum ai cerut:
        # {Nume}.{Index}.{Limba}.{Extensie}
        # index:02d pune zero în față (00, 01, etc.)
        raw_filename = f"{release_name}.{index:02d}.{lang_code}.{ext}"
        
        # Curățăm caracterele interzise în numele de fișiere
        safe_filename = "".join(c for c in raw_filename if c not in r'\/:*?"<>|')
        
        filepath = os.path.join(folder, safe_filename)
        
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(r.content)
            return filepath
    except Exception as e: 
        log(f"Download error: {e}", xbmc.LOGERROR)
    return None

def run_wyzie_service(imdb_id, season=None, episode=None):
    """
    Această funcție rulează în fundal (Thread).
    """
    if ADDON.getSetting('use_wyzie_subs') != 'true':
        return

    if not imdb_id:
        return

    log(f"Start serviciu subtitrări pentru: {imdb_id}")
    
    # 1. Curățare & Căutare
    cleanup_subs()
    subs_list = search_subtitles(imdb_id, season, episode)
    
    if not subs_list:
        log("Nu s-au găsit subtitrări.")
        return

    # 2. Descărcare
    downloaded_paths = []
    for i, sub in enumerate(subs_list):
        path = download_and_save(sub, i)
        if path: 
            downloaded_paths.append(path)
    
    if not downloaded_paths:
        return

    log(f"S-au descărcat {len(downloaded_paths)} subtitrări. Aștept player-ul...")

    # 3. Monitorizare Player
    player = xbmc.Player()
    monitor = xbmc.Monitor()
    
    retries = 40 
    while not monitor.abortRequested() and retries > 0:
        if player.isPlaying():
            break
        xbmc.sleep(500)
        retries -= 1
        
    # 4. Setare Subtitrări - UNA CÂTE UNA
    if player.isPlaying():
        xbmc.sleep(1500)  # Așteaptă puțin mai mult pentru stabilitate
        
        try:
            # Setează TOATE subtitrările una câte una
            # Kodi le va adăuga ca track-uri disponibile
            for idx, sub_path in enumerate(downloaded_paths):
                try:
                    player.setSubtitles(sub_path)
                    log(f"Subtitrare adăugată: {sub_path}")
                    xbmc.sleep(200)  # Mică pauză între adăugări
                except Exception as e:
                    log(f"Eroare la adăugare sub {idx}: {e}", xbmc.LOGERROR)
            
            # Activează prima subtitrare (sau cea preferată)
            # După ce toate sunt adăugate, setează prima ca activă
            if downloaded_paths:
                player.setSubtitles(downloaded_paths[0])
                player.showSubtitles(True)
            
            # --- NOTIFICARE ---
            total_subs = len(downloaded_paths)
            first_sub_source = subs_list[0].get("source", "Wyzie") if subs_list else "Wyzie"
            source_display = first_sub_source.capitalize() if first_sub_source else "Wyzie"

            notif_title = "[B][COLOR FFFDBD01]Wyzie Subs[/COLOR][/B]"
            notif_message = (
                f"Aplicate: [B][COLOR yellow]{total_subs}[/COLOR][/B] "
                f"[B][COLOR FF00BFFF]  '{source_display}'[/COLOR][/B]"
            )
            
            xbmcgui.Dialog().notification(
                notif_title, 
                notif_message, 
                TMDbmovies_ICON, 
                3000
            )
            
            log(f"✓ {total_subs} subtitrări disponibile în player")
                
        except Exception as e:
            log(f"Eroare setare subtitrare: {e}", xbmc.LOGERROR)
    else:
        log("Player-ul nu a pornit la timp.")