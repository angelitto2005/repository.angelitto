import os
import requests
import xbmc
import xbmcgui
import xbmcvfs
import time
from resources.lib.config import ADDON

# --- CONFIG ---
ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# OpenSubtitles APIs
OS_V3_BASE_URL = 'https://opensubtitles-v3.strem.io/subtitles'
OS_REST_BASE_URL = 'https://rest.opensubtitles.org/search'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Mapare limbi pentru OpenSubtitles
NORM_LANG = {
    'rum': 'ro', 'ron': 'ro', 'ro': 'ro',
    'eng': 'en', 'en': 'en',
    'spa': 'es', 'es': 'es', 'spa_la': 'es',
    'fre': 'fr', 'fra': 'fr', 'fr': 'fr',
    'ger': 'de', 'de': 'de',
    'ita': 'it', 'it': 'it',
    'hun': 'hu', 'hu': 'hu'
}

REST_LANG = {
    'ro': 'rum', 'en': 'eng', 'es': 'spa', 'fr': 'fre', 
    'de': 'ger', 'it': 'ita', 'hu': 'hun'
}

def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[tmdbmovies-subs] {msg}", level)

def get_subs_folder():
    temp_dir = xbmcvfs.translatePath('special://temp/')
    subs_path = os.path.join(temp_dir, 'tmdbmovies_subs')
    if not xbmcvfs.exists(subs_path):
        xbmcvfs.mkdirs(subs_path)
    return subs_path

def cleanup_subs():
    subs_path = get_subs_folder()
    try:
        dirs, files = xbmcvfs.listdir(subs_path)
        for f in files:
            xbmcvfs.delete(os.path.join(subs_path, f))
    except Exception as e:
        log(f"Cleanup error: {e}", xbmc.LOGERROR)

def get_detailed_subtitle_names(imdb_id, target_lang=None, season=None, episode=None):
    mapping = {}
    if not imdb_id: return mapping
    try:
        numeric_id = str(imdb_id).replace('tt', '')
        parts = []
        if season and str(season) != '0' and episode and str(episode) != '0':
            parts.append(f"episode-{episode}")
        
        parts.append(f"imdbid-{numeric_id}")
        
        if season and str(season) != '0':
            parts.append(f"season-{season}")
            
        if target_lang:
            rest_lang = REST_LANG.get(target_lang, 'eng')
            parts.append(f"sublanguageid-{rest_lang}")
        
        rest_url = f"{OS_REST_BASE_URL}/{'/'.join(parts)}"
        r = requests.get(rest_url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    file_name = item.get('SubFileName')
                    if not file_name: continue
                    for key in ('IDSubtitleFile', 'IDSubtitle'):
                        val = str(item.get(key, ''))
                        if val:
                            mapping[val] = file_name
    except Exception as e:
        pass
    return mapping

def search_subtitles(imdb_id, season=None, episode=None):
    if not imdb_id: return []
    langs_setting = ADDON.getSetting('osv3_langs') or 'ro,en'
    languages = [l.strip().lower() for l in langs_setting.split(',')]
    found_subs = []
    
    is_tv = season and episode and str(season) != '0' and str(episode) != '0'
    if is_tv:
        media_type = 'series'
        query_id = f"{imdb_id}:{season}:{episode}"
    else:
        media_type = 'movie'
        query_id = imdb_id

    api_url = f"{OS_V3_BASE_URL}/{media_type}/{query_id}.json"
    try:
        r = requests.get(api_url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return found_subs
            
        data = r.json()
        subtitles = data.get('subtitles', [])
        if not subtitles:
            return found_subs

        detailed_names = {}
        for lang in languages:
            detailed_names.update(get_detailed_subtitle_names(imdb_id, lang, season, episode))

        seen_urls = set()
        for sub in subtitles:
            sub_lang_raw = sub.get('lang', '').lower()
            sub_lang_2 = NORM_LANG.get(sub_lang_raw, sub_lang_raw)
            
            if sub_lang_2 in languages:
                url = sub.get('url', '')
                if not url or url in seen_urls:
                    continue
                    
                seen_urls.add(url)
                sub_id = str(sub.get('id', ''))
                release_name = detailed_names.get(sub_id, f"OpenSubtitles_{sub_id}")
                if release_name.lower().endswith('.srt'):
                    release_name = release_name[:-4]

                found_subs.append({
                    'url': url,
                    'language': sub_lang_2,
                    'release': release_name,
                    'format': 'srt',
                    'source': 'OpenSubtitles'
                })
    except Exception as e:
        log(f"Eroare căutare OpenSubtitles v3: {e}", xbmc.LOGERROR)
    
    return found_subs

def download_and_save(sub_data, index):
    try:
        url = sub_data.get('url')
        if not url: return None
        
        folder = get_subs_folder()
        ext = sub_data.get('format', 'srt')
        lang_code = sub_data.get('language', 'unk')
        release_name = sub_data.get('release', f'Sub_{index}')
        
        raw_filename = f"{release_name}.{index:02d}.{lang_code}.{ext}"
        safe_filename = "".join(c for c in raw_filename if c not in r'\/:*?"<>|')
        filepath = os.path.join(folder, safe_filename)
        
        r = requests.get(url, timeout=15, headers=HEADERS)
        if r.status_code == 200:
            raw_content = r.content
            if b'<html' in raw_content.lower():
                return None
                
            # --- FIX ENCODING: Transformăm orice format ciudat în UTF-8 pur ---
            try:
                text = raw_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text = raw_content.decode('cp1250') # Format specific Românesc
                except UnicodeDecodeError:
                    try:
                        text = raw_content.decode('iso-8859-2')
                    except UnicodeDecodeError:
                        text = raw_content.decode('utf-8', errors='replace')
            
            # Adăugăm BOM (Byte Order Mark). Este secretul care forțează player-ul Kodi 
            # să o citească ca pe un fișier UTF-8 valid la orice schimbare din meniu!
            utf8_content = b'\xef\xbb\xbf' + text.encode('utf-8')
            
            f = xbmcvfs.File(filepath, 'wb')
            f.write(utf8_content)
            f.close()
            
            return filepath
    except Exception as e: 
        log(f"Download error: {e}", xbmc.LOGERROR)
    return None

def run_wyzie_service(imdb_id, season=None, episode=None):
    if ADDON.getSetting('use_osv3_subs') != 'true':
        return
    if not imdb_id:
        return

    if not str(imdb_id).startswith('tt') and str(imdb_id).isdigit():
        imdb_id = f"tt{imdb_id}"

    player = xbmc.Player()
    monitor = xbmc.Monitor()
    
    retries = 40 
    while not monitor.abortRequested() and retries > 0:
        if player.isPlaying():
            break
        xbmc.sleep(500)
        retries -= 1
        
    if not player.isPlaying():
        return

    xbmc.sleep(1500)

    try:
        existing_subs = player.getAvailableSubtitleStreams()
        found_embedded_ro = False
        if existing_subs:
            for sub_name in existing_subs:
                name_lower = sub_name.lower()
                if 'romania' in name_lower or 'ro' == name_lower or 'rum' in name_lower:
                    found_embedded_ro = True
                    break
        if found_embedded_ro:
            log("Subtitrare Română detectată în video. Anulez descărcarea.")
            return
    except Exception as e:
        log(f"Eroare verificare subtitrări existente: {e}", xbmc.LOGWARNING)

    log(f"Start serviciu subtitrări (OpenSubtitles) pentru: {imdb_id}")
    
    cleanup_subs()
    subs_list = search_subtitles(imdb_id, season, episode)
    
    if not subs_list:
        log("Nu s-au găsit subtitrări pe OpenSubtitles.")
        return

    downloaded_paths = []
    for i, sub in enumerate(subs_list):
        path = download_and_save(sub, i)
        if path: 
            downloaded_paths.append(path)
    
    if not downloaded_paths:
        return

    log(f"S-au descărcat {len(downloaded_paths)} subtitrări.")

    try:
        # --- FIX KODI DUPLICATE STREAM BUG ---
        # Inversăm lista: adăugăm subtitrările de la coadă la cap. 
        # Ultima adăugată în player devine automat cea activă (prima noastră opțiune).
        # Așa evităm să chemăm `player.setSubtitles(downloaded_paths[0])` de două ori, 
        # lucru care crea căi duplicate în Kodi și făcea textul invizibil la re-selectare.
        downloaded_paths.reverse()
        
        for idx, sub_path in enumerate(downloaded_paths):
            try:
                player.setSubtitles(sub_path)
                xbmc.sleep(350)
            except Exception as e:
                log(f"Eroare la adăugare sub: {e}", xbmc.LOGERROR)
        
        player.showSubtitles(True)
        
        # Inversăm înapoi lista doar pentru a raporta numărul corect la notificare (opțional)
        total_subs = len(downloaded_paths)
        first_sub_source = subs_list[0].get("source", "OpenSubtitles") if subs_list else "OpenSubtitles"
        
        notif_title = "[B][COLOR FFFDBD01]TMDb Subs[/COLOR][/B]"
        notif_message = (
            f"Aplicate: [B][COLOR yellow]{total_subs}[/COLOR][/B] "
            f"[B][COLOR FF00BFFF]  '{first_sub_source}'[/COLOR][/B]"
        )
        xbmcgui.Dialog().notification(notif_title, notif_message, TMDbmovies_ICON, 3000)
            
    except Exception as e:
        log(f"Eroare setare subtitrare: {e}", xbmc.LOGERROR)