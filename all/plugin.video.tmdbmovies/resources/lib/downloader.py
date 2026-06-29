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

def start_download_thread(url, title, year, tmdb_id, c_type, season=None, episode=None, release_name=None, provider_id=''):
    if provider_id.startswith('p2p_') or url.startswith('magnet:'):
        xbmcgui.Dialog().notification("Download", "Not available for P2P sources", xbmcgui.NOTIFICATION_ERROR)
        return
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
    
    # 1. Path Configuration
    base_dir = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    downloads_dir = os.path.join(base_dir, 'Downloads')
    
    folder_title = clean_text(title)
    is_tv = season and episode and str(season) != '0' and str(episode) != '0'
    
    if year and str(year).strip() not in ('', 'None'):
        folder_name = f"{folder_title} ({year})"
    else:
        folder_name = folder_title
    
    if is_tv:
        content_dir = os.path.join(downloads_dir, 'TV Shows', folder_name, f"Season {int(season)}")
    else:
        content_dir = os.path.join(downloads_dir, 'Movies', folder_name)
    
    if not xbmcvfs.exists(content_dir):
        xbmcvfs.mkdirs(content_dir)
        
    # Filename
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
        
    file_path = os.path.join(content_dir, final_filename)
    
    # 2. Parsare URL
    real_url = url.split('|')[0]
    headers = {}
    if '|' in url:
        try: headers = dict(parse_qsl(url.split('|')[1]))
        except: pass
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

    xbmc.log(f"[DOWNLOAD] Start: {file_path}", xbmc.LOGINFO)

    # 3. HLS Detection — doar indicatori siguri (playlist e prea vag)
    is_hls = '.m3u8' in real_url.lower() or 'vixsrc' in real_url.lower() or '/api/hls' in real_url.lower() or 'meowserver' in real_url.lower()
    if is_hls:
        xbmc.log(f"[DOWNLOAD] HLS detected in URL: {real_url[:200]}", xbmc.LOGINFO)

    # --- LOGICA NOTIFICARE START ---
    try:
        show_ui = xbmcaddon.Addon().getSetting('show_download_progress') == 'true'
    except: show_ui = True

    bg = None
    if show_ui:
        # Creăm bara imediat
        bg = xbmcgui.DialogProgressBG()
        bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"Connecting: [COLOR {COL_TXT}]{final_filename}[/COLOR]")
    else:
        # Notificare Toast (Doar dacă bara e OFF)
        header_msg = f"[B][COLOR {COL_HEADER}]Download Started[/COLOR][/B]"
        xbmcgui.Dialog().notification(header_msg, f"[COLOR {COL_TXT}]{final_filename}[/COLOR]", TMDbmovies_ICON, 3000, False)

    try:
        if is_hls:
            _download_hls_stream(real_url, headers, file_path, title, final_filename, bg, window, unique_id)
        else:
            _download_direct_stream(real_url, headers, file_path, title, final_filename, bg, window, unique_id)
            
    except Exception as e:
        if bg: bg.close()
        xbmc.log(f"[DOWNLOAD] CRASH: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Download Failed", "Check the log", xbmcgui.NOTIFICATION_ERROR)
        try: 
            if xbmcvfs.exists(file_path): xbmcvfs.delete(file_path)
            _remove_folder_if_empty(file_path)
        except: pass
    finally:
        # --- CLEANUP FINAL ---
        window.clearProperty(unique_id)
        window.clearProperty(f"{unique_id}_stop")
        
        # REFRESH LIST
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

    # 1. Close if setting is OFF
    if not show_ui and bg:
        bg.close()
        return None
    
    # 2. Create if setting is ON and doesn't exist
    if show_ui and not bg:
        bg = xbmcgui.DialogProgressBG()
        bg.create(f"[COLOR {COL_HEADER}]Download[/COLOR]", f"[COLOR {COL_TXT}]{final_filename}[/COLOR]")
    
    # 3. Update
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
                xbmcgui.Dialog().notification("Download Stopped", "File deleted.", TMDbmovies_ICON, 3000, False)
            
            _remove_folder_if_empty(file_path)
        except: pass
        return True
    return False

def _remove_folder_if_empty(file_path):
    try:
        parent_dir = os.path.dirname(file_path)
        downloads_dir = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'Downloads')
        while parent_dir and parent_dir.startswith(downloads_dir) and parent_dir != downloads_dir:
            dirs, files = xbmcvfs.listdir(parent_dir)
            if not dirs and not files:
                xbmcvfs.rmdir(parent_dir)
                xbmc.log(f"[DOWNLOAD] Empty folder removed: {parent_dir}", xbmc.LOGINFO)
                parent_dir = os.path.dirname(parent_dir)
            else:
                break
    except: pass


def cleanup_empty_download_folders():
    """Recursively removes empty folders inside Downloads directory."""
    try:
        base_dir = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        downloads_dir = os.path.join(base_dir, 'Downloads')
        _prune_empty_dirs(downloads_dir, downloads_dir)
    except Exception as e:
        xbmc.log(f"[DOWNLOAD] Cleanup error: {e}", xbmc.LOGERROR)


def _prune_empty_dirs(path, root):
    """Recursively remove empty subdirectories from bottom up."""
    try:
        dirs, files = xbmcvfs.listdir(path)
        for d in dirs:
            full = os.path.join(path, d)
            _prune_empty_dirs(full, root)
        dirs2, files2 = xbmcvfs.listdir(path)
        if not dirs2 and not files2 and path != root:
            xbmcvfs.rmdir(path)
            xbmc.log(f"[DOWNLOAD] Empty folder pruned: {path}", xbmc.LOGINFO)
    except:
        pass


def _validate_and_finish(file_path, filename):
    try:
        size = os.path.getsize(file_path)
        if size < MIN_FILE_SIZE:
            xbmc.log(f"[DOWNLOAD] File too small ({size} bytes). Deleting invalid file.", xbmc.LOGWARNING)
            xbmcvfs.delete(file_path)
            _remove_folder_if_empty(file_path)
            xbmcgui.Dialog().notification("Error Download", "Invalid file (too small).", TMDbmovies_ICON, 4000, False)
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
    header_fin = f"[B][COLOR {COL_HEADER}]Download Complete[/COLOR][/B]"
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
def _parse_hls_playlist(content, base_url):
    """Extrage URL-urile segmentelor dintr-un playlist HLS."""
    segments = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            if line.startswith('http'): segments.append(line)
            else: segments.append(urljoin(base_url, line))
    return segments

TS_PACKET_SIZE = 188
TS_SYNC = 0x47

# Stream types
STREAM_H264 = 0x1B
STREAM_HEVC = 0x24
STREAM_MPEG2_VIDEO = 0x02
STREAM_AAC = 0x0F
STREAM_AC3 = 0x81
STREAM_EAC3 = 0x87
STREAM_DTS = 0x82
STREAM_DTSHD = 0x86
STREAM_TRUEHD = 0x83
STREAM_MPEG1_AUDIO = 0x03
STREAM_MPEG2_AUDIO = 0x04

def _crc32_mpeg(data):
    """CRC-32/MPEG-2 used by MPEG-TS."""
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = (crc << 1) ^ 0x04C11DB7
            else:
                crc <<= 1
            crc &= 0xFFFFFFFF
    return crc

def _make_ts_packet(payload, pid, cc, start=False):
    """Construiește un pachet TS de 188 bytes."""
    buf = bytearray(TS_PACKET_SIZE)
    buf[0] = TS_SYNC
    if start:
        buf[1] = 0x40 | (pid >> 8) & 0x1F  # payload_unit_start_indicator
    else:
        buf[1] = 0x00 | (pid >> 8) & 0x1F
    buf[2] = pid & 0xFF
    buf[3] = 0x10 | (cc & 0x0F)  # payload only
    data_len = min(len(payload), TS_PACKET_SIZE - 4)
    buf[4:4+data_len] = payload[:data_len]
    return bytes(buf)

def _build_pat(prog_num, pmt_pid):
    """Construiește secțiunea PAT (fără header TS)."""
    section_data = bytearray()
    section_data.append(0x00)  # table_id
    # section_length (filled later)
    section_data.extend([0, 0])
    section_data.extend([0, 1])  # transport_stream_id
    section_data.append(0xC3)  # version_number=0, current_next_indicator=1
    section_data.append(0)  # section_number
    section_data.append(0)  # last_section_number
    # program_number + PMT_PID
    section_data.append((prog_num >> 8) & 0xFF)
    section_data.append(prog_num & 0xFF)
    section_data.append(0xE0 | ((pmt_pid >> 8) & 0x1F))
    section_data.append(pmt_pid & 0xFF)
    section_length = len(section_data) - 3 + 4  # +4 for CRC
    section_data[1] = 0xB0 | ((section_length >> 8) & 0x0F)
    section_data[2] = section_length & 0xFF
    # CRC
    crc = _crc32_mpeg(section_data)
    section_data.extend([(crc >> 24) & 0xFF, (crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])
    return bytes(section_data)

def _build_pmt(streams, pcr_pid):
    """Construiește secțiunea PMT. streams = [(stream_type, pid)]."""
    section_data = bytearray()
    section_data.append(0x02)  # table_id
    section_data.extend([0, 0])  # section_length placeholder
    section_data.append(1)  # program_number
    section_data.append(0xC3)  # version_number=0, current_next=1
    section_data.append(0)  # section_number
    section_data.append(0)  # last_section_number
    section_data.append(0xE0 | ((pcr_pid >> 8) & 0x1F))
    section_data.append(pcr_pid & 0xFF)
    section_data.extend([0, 0])  # program_info_length = 0
    for st, spid in streams:
        section_data.append(st)
        section_data.append(0xE0 | ((spid >> 8) & 0x1F))
        section_data.append(spid & 0xFF)
        section_data.extend([0, 0])  # ES_info_length = 0
    section_length = len(section_data) - 3 + 4
    section_data[1] = 0xB0 | ((section_length >> 8) & 0x0F)
    section_data[2] = section_length & 0xFF
    crc = _crc32_mpeg(section_data)
    section_data.extend([(crc >> 24) & 0xFF, (crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])
    return bytes(section_data)

def _parse_pat(ts_data):
    """Parsează primul PAT din date TS. Returnează (program_number, pmt_pid) sau (0,0)."""
    for i in range(0, len(ts_data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if ts_data[i] != TS_SYNC: continue
        pid = ((ts_data[i+1] & 0x1F) << 8) | ts_data[i+2]
        if pid != 0x0000: continue
        off = 4
        if ts_data[i+3] & 0x20:  # adaptation field
            off += 1 + ts_data[i+4]
        if off + 1 >= TS_PACKET_SIZE: continue
        if not (ts_data[i+off] & 0x40): continue  # payload_unit_start_indicator
        pointer = ts_data[i+off+1]
        sec_start = i + off + 2 + pointer
        if sec_start + 7 > len(ts_data): continue
        sec = ts_data[sec_start:sec_start+8]
        prog_num = (sec[3] << 8) | sec[4]
        if prog_num == 0: continue
        pmt_pid = ((sec[5] & 0x1F) << 8) | sec[6]
        return prog_num, pmt_pid
    return 0, 0

def _parse_pmt(ts_data, pmt_pid):
    """Parsează PMT din date TS. Returnează [(stream_type, pid)]."""
    streams = []
    for i in range(0, len(ts_data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if ts_data[i] != TS_SYNC: continue
        pid = ((ts_data[i+1] & 0x1F) << 8) | ts_data[i+2]
        if pid != pmt_pid: continue
        off = 4
        if ts_data[i+3] & 0x20:
            off += 1 + ts_data[i+4]
        if off + 1 >= TS_PACKET_SIZE: continue
        if not (ts_data[i+off] & 0x40): continue
        pointer = ts_data[i+off+1]
        sec_start = off + 2 + pointer
        if sec_start + 12 > TS_PACKET_SIZE: continue
        sec = ts_data[i+sec_start:i+sec_start+12]
        p_info_len = ((sec[7] & 0x0F) << 8) | sec[8]
        es_off = 9 + p_info_len
        es_data = ts_data[i+sec_start+es_off:i+TS_PACKET_SIZE]
        # Modelează secțiuni care continuă în pachetul următor (simplist: doar primul pachet)
        while len(es_data) >= 5:
            st = es_data[0]
            spid = ((es_data[1] & 0x1F) << 8) | es_data[2]
            es_info_len = ((es_data[3] & 0x0F) << 8) | es_data[4]
            streams.append((st, spid))
            es_data = es_data[5 + es_info_len:]
        if streams:
            break
    return streams

def _strip_psi(ts_data, pmt_pids):
    """Elimină PAT (PID 0x0000) și PMT (PIDuri din set) din datele TS."""
    result = bytearray()
    kill_pids = {0x0000}
    if pmt_pids:
        kill_pids.update(pmt_pids)
    for i in range(0, len(ts_data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE):
        if ts_data[i] != TS_SYNC:
            # packet not aligned, fall back to scan
            break
        pid = ((ts_data[i+1] & 0x1F) << 8) | ts_data[i+2]
        if pid in kill_pids:
            continue
        result.extend(ts_data[i:i+TS_PACKET_SIZE])
    if len(result) == 0:
        # fallback: no alignment, return all
        return ts_data
    return bytes(result)

def _dl_seg(seg_url, seg_headers, window, unique_id):
    """Descarcă un segment HLS. Returnează bytes sau None."""
    for attempt in range(3):
        if window.getProperty(f"{unique_id}_stop") == 'true':
            return None
        try:
            with requests.get(seg_url, headers=seg_headers, stream=True, verify=False, timeout=10) as seg_r:
                if seg_r.status_code == 200:
                    return seg_r.content
                elif seg_r.status_code in [429, 503]:
                    xbmc.sleep(1500)
        except:
            xbmc.sleep(800)
    return None

def _download_hls_stream(url, headers, file_path, display_title, filename, bg, window, unique_id):
    xbmc.log("[DOWNLOAD] Detected HLS Stream.", xbmc.LOGINFO)
    
    seg_headers = dict(headers)
    if 'Referer' not in seg_headers:
        seg_headers['Referer'] = url.split('|')[0] if '|' in url else url
    
    import urllib.parse
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=15)
        content = r.text
    except Exception as e:
        xbmc.log(f"[DOWNLOAD] HLS master playlist error: {e}", xbmc.LOGWARNING)
        if bg: bg.close()
        xbmcgui.Dialog().notification("Error", "HLS master fetch failed", xbmcgui.NOTIFICATION_ERROR)
        return
    
    actual_m3u8_url = url
    if '?url=' in url or '&url=' in url:
        try:
            parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if 'url' in parsed_qs:
                actual_m3u8_url = parsed_qs['url'][0]
        except: pass
    
    base_url = actual_m3u8_url.rsplit('/', 1)[0] + '/'
    
    video_segments = []
    audio_segments = []
    
    if '#EXT-X-STREAM-INF' not in content:
        video_segments = _parse_hls_playlist(content, base_url)
    else:
        lines = content.splitlines()
        best_bandwidth = 0
        best_url = None
        audio_url = None
        for i, line in enumerate(lines):
            if '#EXT-X-MEDIA:TYPE=AUDIO' in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                default_match = re.search(r'DEFAULT=(\w+)', line)
                if uri_match and (not default_match or default_match.group(1) == 'YES'):
                    au = uri_match.group(1)
                    if not au.startswith('http'): au = urllib.parse.urljoin(base_url, au)
                    audio_url = au
            elif '#EXT-X-STREAM-INF' in line:
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                bw = int(bw_match.group(1)) if bw_match else 0
                if i + 1 < len(lines):
                    pl_url = lines[i+1].strip()
                    if not pl_url.startswith('#'):
                        if bw > best_bandwidth:
                            best_bandwidth = bw
                            best_url = pl_url
        
        if best_url:
            if not best_url.startswith('http'): best_url = urllib.parse.urljoin(base_url, best_url)
            try:
                r_v = requests.get(best_url, headers=seg_headers, verify=False, timeout=10)
                video_base = best_url.rsplit('/', 1)[0] + '/'
                video_segments = _parse_hls_playlist(r_v.text, video_base)
            except:
                pass
        
        if audio_url:
            try:
                r_a = requests.get(audio_url, headers=seg_headers, verify=False, timeout=10)
                audio_base = audio_url.rsplit('/', 1)[0] + '/'
                audio_segments = _parse_hls_playlist(r_a.text, audio_base)
            except:
                pass
    
    if not video_segments:
        if bg: bg.close()
        xbmcgui.Dialog().notification("Error", "HLS without segments", xbmcgui.NOTIFICATION_ERROR)
        return
    
    total_video = len(video_segments)
    total_audio = len(audio_segments)
    total_segments = max(total_video, total_audio) if audio_segments else total_video
    has_audio = total_audio > 0
    
    if has_audio:
        xbmc.log(f"[DOWNLOAD] HLS audio group found ({total_audio} audio, {total_video} video segments)", xbmc.LOGINFO)
    
    # --- Descarcă primul segment video și audio în memorie pentru a descoperi PIDs ---
    video0_data = _dl_seg(video_segments[0], seg_headers, window, unique_id)
    if video0_data is None:
        if bg: bg.close()
        xbmcgui.Dialog().notification("Error", "HLS first segment failed", xbmcgui.NOTIFICATION_ERROR)
        return
    
    audio0_data = b""
    if has_audio:
        a0 = _dl_seg(audio_segments[0], seg_headers, window, unique_id)
        if a0 is not None:
            audio0_data = a0
    
    # Parsează PAT/PMT din primul segment video
    prog_num, pmt_pid_v = _parse_pat(video0_data)
    if prog_num == 0:
        prog_num = 1  # fallback
    streams_v = _parse_pmt(video0_data, pmt_pid_v) if pmt_pid_v else []
    
    # Parsează PAT/PMT din primul segment audio (dacă există)
    streams_a = []
    pmt_pid_a = 0
    if audio0_data:
        _, pmt_pid_a = _parse_pat(audio0_data)
        streams_a = _parse_pmt(audio0_data, pmt_pid_a) if pmt_pid_a else []
    
    # Construiește lista unificată de streamuri: video + audio
    seen_pids = set()
    merged_streams = []
    pcr_pid = 0
    for st, spid in streams_v + streams_a:
        if spid not in seen_pids:
            seen_pids.add(spid)
            merged_streams.append((st, spid))
            if pcr_pid == 0 and st in (STREAM_H264, STREAM_HEVC, STREAM_MPEG2_VIDEO):
                pcr_pid = spid
    
    if pcr_pid == 0 and merged_streams:
        pcr_pid = merged_streams[0][1]
    
    pmt_pid = max(0x1001, (prog_num << 8) | 0x01)
    
    # Construiește noile pachete PAT + PMT
    pat_section = _build_pat(prog_num, pmt_pid)
    pmt_section = _build_pmt(merged_streams, pcr_pid)
    
    pat_packet = _make_ts_packet(pat_section, 0x0000, 0, start=True)
    pmt_cc = 1
    pmt_packets = []
    # Împarte secțiunea PMT în pachete de 184 bytes (188-4 header)
    remaining = pmt_section
    first = True
    while remaining:
        chunk = remaining[:184]
        remaining = remaining[184:]
        pmt_packets.append(_make_ts_packet(chunk, pmt_pid, pmt_cc, start=first))
        pmt_cc = (pmt_cc + 1) & 0x0F
        first = False
    
    # Pregătește PSI strip pentru primele segmente
    all_pmt_pids = {pmt_pid_v} if pmt_pid_v else set()
    if pmt_pid_a:
        all_pmt_pids.add(pmt_pid_a)
    
    video0_stripped = _strip_psi(video0_data, all_pmt_pids)
    audio0_stripped = _strip_psi(audio0_data, all_pmt_pids) if audio0_data else b""
    
    # --- Scriere fișier ---
    with xbmcvfs.File(file_path, 'w') as f_out:
        # 1. Scrie noul PAT + PMT (cu toate streamurile reunite)
        f_out.write(pat_packet)
        for pkt in pmt_packets:
            f_out.write(pkt)
        
        # 2. Scrie datele primului segment video (fără PAT/PMT)
        f_out.write(video0_stripped)
        start_offset = len(pat_packet) + len(b''.join(pmt_packets)) + len(video0_stripped)
        
        # 3. Scrie datele primului segment audio (fără PAT/PMT)
        if audio0_stripped:
            f_out.write(audio0_stripped)
        
        downloaded_bytes = len(pat_packet) + len(b''.join(pmt_packets)) + len(video0_stripped) + len(audio0_stripped)
        start_time = time.time()
        last_time = start_time
        last_downloaded_bytes = downloaded_bytes
        current_speed = "0.0 MB/s"
        stop_flag = False
        consecutive_errors = 0
        
        # 4. Segmentele rămase (i=1..N) cu PSI strip
        for i in range(1, total_segments):
            if window.getProperty(f"{unique_id}_stop") == 'true':
                stop_flag = True; break
            
            sz_v = 0
            if i < total_video:
                d = _dl_seg(video_segments[i], seg_headers, window, unique_id)
                if d:
                    d = _strip_psi(d, all_pmt_pids)
                    f_out.write(d)
                    sz_v = len(d)
                else:
                    consecutive_errors += 1
                    if consecutive_errors > 8:
                        break
                    continue
            
            sz_a = 0
            if has_audio and i < total_audio:
                d = _dl_seg(audio_segments[i], seg_headers, window, unique_id)
                if d:
                    d = _strip_psi(d, all_pmt_pids)
                    f_out.write(d)
                    sz_a = len(d)
                else:
                    consecutive_errors += 1
                    if consecutive_errors > 8:
                        break
                    continue
            
            consecutive_errors = 0
            downloaded_bytes += sz_v + sz_a
            
            if i % 5 == 0 or i == total_segments - 1:
                current_time = time.time()
                if current_time - last_time >= 1.0:
                    bytes_diff = downloaded_bytes - last_downloaded_bytes
                    time_diff = current_time - last_time
                    if time_diff > 0: current_speed = format_speed_stable(bytes_diff / time_diff)
                    last_time = current_time
                    last_downloaded_bytes = downloaded_bytes
                    pct = int(((i + 1) / total_segments) * 100)
                    down_str = format_size_stable(downloaded_bytes)
                    msg = f"[B][COLOR {COL_PCT}]{pct}%[/COLOR][/B] • {down_str} • [COLOR {COL_SPEED}]{current_speed}[/COLOR]"
                    if has_audio: msg += " • [COLOR cyan]AUDIO[/COLOR]"
                    if bg:
                        bg.update(pct, heading=f"[COLOR {COL_HEADER}]Download: {display_title}[/COLOR]", message=msg)
    
    if not stop_flag:
        if bg: bg.close()
        _validate_and_finish(file_path, filename)
    else:
        if bg: bg.close()
        try:
            if xbmcvfs.exists(file_path): xbmcvfs.delete(file_path)
        except: pass