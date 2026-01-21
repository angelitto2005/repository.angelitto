import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import requests
import time
import re
from urllib.parse import parse_qsl, urljoin
from resources.lib.config import ADDON
from resources.lib.utils import clean_text

# Definim iconița local
TMDbmovies_ICON = os.path.join(ADDON.getAddonInfo('path'), 'icon.png')

# CULORI UI
COL_HEADER = "FFFDBD01"
COL_PCT = "yellow"
COL_TXT = "cyan"
COL_SPEED = "lime"

# PRAG MINIM VALIDARE (5 MB)
MIN_FILE_SIZE = 5 * 1024 * 1024 

# --- FUNCȚII FORMATARE ---
def format_size_stable(size_bytes):
    mb = size_bytes / (1024 * 1024)
    if mb < 1000: return f"{int(mb)} MB"
    else: return f"{mb/1024:.2f} GB"

def format_speed_stable(bytes_per_sec):
    return f"{bytes_per_sec/(1024*1024):.1f} MB/s"

def get_dl_id(tmdb_id, c_type, season=None, episode=None):
    if c_type == 'movie':
        return f"dl_movie_{tmdb_id}"
    else:
        return f"dl_tv_{tmdb_id}_{season}_{episode}"

def start_download_thread(url, title, year, tmdb_id, c_type, season=None, episode=None, release_name=None):
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    window = xbmcgui.Window(10000)
    window.setProperty(unique_id, 'active')
    window.clearProperty(f"{unique_id}_stop")
    
    import threading
    t = threading.Thread(target=_download_worker, args=(url, title, year, tmdb_id, c_type, season, episode, release_name))
    t.daemon = True
    t.start()

def _download_worker(url, title, year, tmdb_id, c_type, season, episode, release_name):
    unique_id = get_dl_id(tmdb_id, c_type, season, episode)
    window = xbmcgui.Window(10000)
    
    # 1. Configurare Căi
    base_dir = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    downloads_dir = os.path.join(base_dir, 'Downloads')
    
    folder_title = clean_text(title)
    folder_name = f"{folder_title} ({year})"
    final_dir = os.path.join(downloads_dir, folder_name)
    
    if not xbmcvfs.exists(final_dir):
        xbmcvfs.mkdirs(final_dir)
        
    # Nume Fișier
    if release_name:
        final_filename = clean_text(release_name)
        if not final_filename.lower().endswith(('.mkv', '.mp4', '.avi', '.ts')):
            final_filename += ".mkv"
        if len(final_filename) < 5: final_filename = None
    else:
        final_filename = None

    if not final_filename:
        if season and episode:
            final_filename = f"{folder_title}.S{int(season):02d}E{int(episode):02d}.mkv"
        else:
            final_filename = f"{folder_title} ({year}).mkv"
        
    file_path = os.path.join(final_dir, final_filename)
    
    # 2. Parsare URL
    real_url = url.split('|')[0]
    headers = {}
    if '|' in url:
        try: headers = dict(parse_qsl(url.split('|')[1]))
        except: pass
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

    xbmc.log(f"[DOWNLOAD] Start: {file_path}", xbmc.LOGINFO)

    # 3. Detecție HLS
    is_hls = '.m3u8' in real_url.lower() or 'vixsrc' in real_url.lower() or 'playlist' in real_url.lower()

    # --- LOGICA NOTIFICARE START ---
    try:
        show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
    except: show_ui = True

    bg = None
    if show_ui:
        # Creăm bara imediat
        bg = xbmcgui.DialogProgressBG()
        bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"Conectare: [COLOR {COL_TXT}]{final_filename}[/COLOR]")
    else:
        # Notificare Toast (Doar dacă bara e OFF)
        header_msg = f"[B][COLOR {COL_HEADER}]Download Pornit[/COLOR][/B]"
        xbmcgui.Dialog().notification(header_msg, f"[COLOR {COL_TXT}]{final_filename}[/COLOR]", TMDbmovies_ICON, 3000, False)

    try:
        if is_hls:
            _download_hls_stream(real_url, headers, file_path, title, final_filename, bg, window, unique_id)
        else:
            _download_direct_stream(real_url, headers, file_path, title, final_filename, bg, window, unique_id)
            
    except Exception as e:
        if bg: bg.close()
        xbmc.log(f"[DOWNLOAD] CRASH: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Download Eșuat", "Verifică jurnalul", xbmcgui.NOTIFICATION_ERROR)
        try: 
            if xbmcvfs.exists(file_path): xbmcvfs.delete(file_path)
            _remove_folder_if_empty(file_path)
        except: pass
    finally:
        # --- CLEANUP FINAL ---
        window.clearProperty(unique_id)
        window.clearProperty(f"{unique_id}_stop")
        
        # REFRESH LISTA
        time.sleep(0.5)
        xbmc.executebuiltin("Container.Refresh")

# =============================================================================
# UI MANAGEMENT
# =============================================================================
def manage_progress_ui(bg, percent, display_title, msg, final_filename):
    try:
        show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
    except:
        show_ui = True

    # 1. Închidem dacă setarea e OFF
    if not show_ui and bg:
        bg.close()
        return None
    
    # 2. Creăm dacă setarea e ON și nu există
    if show_ui and not bg:
        bg = xbmcgui.DialogProgressBG()
        bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"[COLOR {COL_TXT}]{final_filename}[/COLOR]")
    
    # 3. Actualizăm
    if show_ui and bg:
        bg.update(percent, heading=f"[COLOR {COL_HEADER}]Download: {display_title}[/COLOR]", message=msg)
        
    return bg

# =============================================================================
# CLEANUP & VALIDATE
# =============================================================================
def perform_cleanup_if_stopped(window, unique_id, file_path, bg):
    if window.getProperty(f"{unique_id}_stop") == 'true':
        if bg: bg.close()
        xbmc.log(f"[DOWNLOAD] Stop requested via flag. Deleting partial file.", xbmc.LOGINFO)
        
        try:
            if xbmcvfs.exists(file_path):
                xbmcvfs.delete(file_path)
                xbmcgui.Dialog().notification("Download Oprit", "Fișier șters.", TMDbmovies_ICON, 3000, False)
            
            _remove_folder_if_empty(file_path)
        except: pass
        return True
    return False

def _remove_folder_if_empty(file_path):
    try:
        parent_dir = os.path.dirname(file_path)
        dirs, files = xbmcvfs.listdir(parent_dir)
        if not dirs and not files:
            xbmcvfs.rmdir(parent_dir)
            xbmc.log(f"[DOWNLOAD] Empty folder removed: {parent_dir}", xbmc.LOGINFO)
    except: pass

def _validate_and_finish(file_path, filename):
    try:
        size = os.path.getsize(file_path)
        if size < MIN_FILE_SIZE:
            xbmc.log(f"[DOWNLOAD] File too small ({size} bytes). Deleting invalid file.", xbmc.LOGWARNING)
            xbmcvfs.delete(file_path)
            _remove_folder_if_empty(file_path)
            xbmcgui.Dialog().notification("Eroare Download", "Fișier invalid (prea mic).", TMDbmovies_ICON, 4000, False)
        else:
            # Afișăm notificare de final DOAR dacă bara (BG) este OPRITĂ
            try:
                show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
            except: show_ui = True
            
            if not show_ui:
                _finish_notify(filename)

    except Exception as e:
        xbmc.log(f"[DOWNLOAD] Validation error: {e}", xbmc.LOGERROR)
        # În caz de eroare verificare, notificăm doar dacă e OFF
        try:
            show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
        except: show_ui = True
        
        if not show_ui:
            _finish_notify(filename)

def _finish_notify(filename):
    header_fin = f"[B][COLOR {COL_HEADER}]Download Complet[/COLOR][/B]"
    msg_fin = f"[B][COLOR {COL_PCT}]100%[/COLOR][/B] • [COLOR {COL_TXT}]{filename}[/COLOR]"
    xbmcgui.Dialog().notification(header_fin, msg_fin, TMDbmovies_ICON, 3000, False)

def _notify_milestone(percent, title):
    # Aici folosim parametrul 'percent' doar pentru verificarea logicii,
    # dar în textul afișat scriem valori fixe pentru estetică.
    
    display_percent = "25"
    if percent >= 75: display_percent = "75"
    elif percent >= 50: display_percent = "50"
    
    header_notif = f"[B][COLOR {COL_HEADER}]Download[/COLOR][/B]"
    msg_notif = f"[B][COLOR {COL_PCT}]{display_percent}%[/COLOR][/B] • [COLOR {COL_TXT}]{title}[/COLOR]"
    xbmcgui.Dialog().notification(header_notif, msg_notif, TMDbmovies_ICON, 2000, False)

# =============================================================================
# DOWNLOADER NORMAL
# =============================================================================
def _download_direct_stream(url, headers, file_path, display_title, filename, bg, window, unique_id):
    stop_flag = False
    
    # Flags pentru notificări (doar când BG e off)
    n25 = n50 = n75 = False
    
    try:
        with requests.get(url, headers=headers, stream=True, verify=False, timeout=10, allow_redirects=True) as r:
            r.raise_for_status()
            
            ctype = r.headers.get('Content-Type', '').lower()
            if 'mpegurl' in ctype:
                r.close()
                _download_hls_stream(url, headers, file_path, display_title, filename, bg, window, unique_id)
                return

            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 1024 * 1024
            
            start_time = time.time()
            last_time = start_time
            last_downloaded = 0
            current_speed = "0.0 MB/s"
            
            with xbmcvfs.File(file_path, 'w') as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if window.getProperty(f"{unique_id}_stop") == 'true':
                        stop_flag = True
                        break

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        current_time = time.time()
                        if current_time - last_time >= 1.0:
                            # 1. Verificăm setarea LIVE
                            try:
                                show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
                            except: show_ui = True

                            # Calcule
                            bytes_diff = downloaded - last_downloaded
                            time_diff = current_time - last_time
                            if time_diff > 0:
                                current_speed = format_speed_stable(bytes_diff / time_diff)
                            last_time = current_time
                            last_downloaded = downloaded
                            
                            downloaded_str = format_size_stable(downloaded)
                            percent = 0
                            
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                            
                            # --- LOGICA AFIȘARE ---
                            if show_ui:
                                # Mod Bară
                                if not bg:
                                    bg = xbmcgui.DialogProgressBG()
                                    bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"[COLOR {COL_TXT}]{filename}[/COLOR]")
                                
                                total_str = format_size_stable(total_size) if total_size > 0 else "?"
                                msg = f"[B][COLOR {COL_PCT}]{percent}%[/COLOR][/B] • {downloaded_str} / {total_str} • [COLOR {COL_SPEED}]{current_speed}[/COLOR]"
                                bg.update(percent, heading=f"[COLOR {COL_HEADER}]Download: {display_title}[/COLOR]", message=msg)
                            else:
                                # Mod Toast (Fără Bară)
                                if bg:
                                    bg.close()
                                    bg = None
                                
                                if total_size > 0:
                                    if percent >= 25 and not n25:
                                        _notify_milestone(percent, display_title)
                                        n25 = True
                                    elif percent >= 50 and not n50:
                                        _notify_milestone(percent, display_title)
                                        n50 = True
                                    elif percent >= 75 and not n75:
                                        _notify_milestone(percent, display_title)
                                        n75 = True

        if stop_flag:
            perform_cleanup_if_stopped(window, unique_id, file_path, bg)
        else:
            if bg: bg.close()
            _validate_and_finish(file_path, filename)
            
    except Exception as e:
        if bg: bg.close()
        raise e

# =============================================================================
# DOWNLOADER HLS
# =============================================================================
def _download_hls_stream(url, headers, file_path, display_title, filename, bg, window, unique_id):
    xbmc.log("[DOWNLOAD] Detected HLS Stream.", xbmc.LOGINFO)
    
    r = requests.get(url, headers=headers, verify=False, timeout=10)
    content = r.text
    base_url = url.rsplit('/', 1)[0] + '/'

    if '#EXT-X-STREAM-INF' in content:
        lines = content.splitlines()
        best_bandwidth = 0
        best_url = None
        for i, line in enumerate(lines):
            if '#EXT-X-STREAM-INF' in line:
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                bw = int(bw_match.group(1)) if bw_match else 0
                if i + 1 < len(lines):
                    pl_url = lines[i+1].strip()
                    if not pl_url.startswith('#'):
                        if bw > best_bandwidth:
                            best_bandwidth = bw
                            best_url = pl_url
        if best_url:
            if not best_url.startswith('http'): best_url = urljoin(base_url, best_url)
            r = requests.get(best_url, headers=headers, verify=False, timeout=10)
            content = r.text
            base_url = best_url.rsplit('/', 1)[0] + '/'
    
    segments = []
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if line.startswith('http'): segments.append(line)
            else: segments.append(urljoin(base_url, line))
    
    total_segments = len(segments)
    if total_segments == 0:
        if bg: bg.close()
        xbmcgui.Dialog().notification("Eroare", "HLS fără segmente", xbmcgui.NOTIFICATION_ERROR)
        return

    start_time = time.time()
    last_time = start_time
    downloaded_bytes = 0
    last_downloaded_bytes = 0
    current_speed = "0.0 MB/s"
    
    stop_flag = False
    consecutive_errors = 0
    estimated_total_bytes = 0 
    
    # Flags notificare
    n25 = n50 = n75 = False

    with xbmcvfs.File(file_path, 'w') as f_out:
        for i, seg_url in enumerate(segments):
            
            if window.getProperty(f"{unique_id}_stop") == 'true':
                stop_flag = True
                break
                
            if consecutive_errors > 3:
                window.setProperty(f"{unique_id}_stop", "true")
                stop_flag = True
                break

            success = False
            segment_size = 0
            
            for attempt in range(2):
                if window.getProperty(f"{unique_id}_stop") == 'true':
                    stop_flag = True
                    break

                try:
                    with requests.get(seg_url, headers=headers, stream=True, verify=False, timeout=3) as seg_r:
                        if seg_r.status_code == 200:
                            f_out.write(seg_r.content)
                            segment_size = len(seg_r.content)
                            success = True
                            consecutive_errors = 0
                            break
                except:
                    pass
            
            if stop_flag: break

            if not success:
                consecutive_errors += 1
            else:
                downloaded_bytes += segment_size
                if i == 0 and segment_size > 0:
                    estimated_total_bytes = segment_size * total_segments
                
                current_time = time.time()
                if (current_time - last_time >= 1.0):
                    # 1. Verificare Setare LIVE
                    try:
                        show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
                    except: show_ui = True

                    bytes_diff = downloaded_bytes - last_downloaded_bytes
                    time_diff = current_time - last_time
                    if time_diff > 0:
                        current_speed = format_speed_stable(bytes_diff / time_diff)
                    last_time = current_time
                    last_downloaded_bytes = downloaded_bytes
                    
                    percent = int(((i + 1) / total_segments) * 100)
                    down_str = format_size_stable(downloaded_bytes)
                    
                    if show_ui:
                        # Mod Bară
                        if not bg:
                            bg = xbmcgui.DialogProgressBG()
                            bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"[COLOR {COL_TXT}]{filename}[/COLOR]")
                        
                        msg = f"[B][COLOR {COL_PCT}]{percent}%[/COLOR][/B] • {down_str}"
                        if estimated_total_bytes > 0:
                            est_str = format_size_stable(estimated_total_bytes)
                            msg += f" / ~{est_str}"
                        msg += f" • [COLOR {COL_SPEED}]{current_speed}[/COLOR]"
                        bg.update(percent, heading=f"[COLOR {COL_HEADER}]Download: {display_title}[/COLOR]", message=msg)
                    else:
                        # Mod Toast
                        if bg:
                            bg.close()
                            bg = None
                        
                        if percent >= 25 and not n25:
                            _notify_milestone(percent, display_title)
                            n25 = True
                        elif percent >= 50 and not n50:
                            _notify_milestone(percent, display_title)
                            n50 = True
                        elif percent >= 75 and not n75:
                            _notify_milestone(percent, display_title)
                            n75 = True

    if stop_flag:
        perform_cleanup_if_stopped(window, unique_id, file_path, bg)
    else:
        if bg: bg.close()
        _validate_and_finish(file_path, filename)