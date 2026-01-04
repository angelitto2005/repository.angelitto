# -*- coding: utf-8 -*-

import json
from operator import itemgetter
import os
import re
import shutil
import sys
import unicodedata
import platform
import zipfile
import time
import traceback
import random
import binascii
import difflib

try: 
    import urllib
    import urllib2
    py3 = False
except ImportError: 
    import urllib.parse as urllib
    import urllib.request as urllib2
    py3 = True

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

__addon__ = xbmcaddon.Addon()
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')

if py3:
    xpath = xbmcvfs.translatePath
else:
    xpath = xbmc.translatePath

__cwd__        = xpath(__addon__.getAddonInfo('path')) if py3 else xpath(__addon__.getAddonInfo('path')).decode("utf-8")
__profile__    = xpath(__addon__.getAddonInfo('profile')) if py3 else xpath(__addon__.getAddonInfo('profile')).decode("utf-8")
__resource__   = xpath(os.path.join(__cwd__, 'resources', 'lib')) if py3 else xpath(os.path.join(__cwd__, 'resources', 'lib')).decode("utf-8")

__temp__       = xpath(os.path.join(__profile__, 'temp', ''))
if not py3 and isinstance(__temp__, str):
    __temp__ = __temp__.decode('utf-8')

BASE_URL = "https://subs.ro/"

sys.path.append (__resource__)

import requests
from bs4 import BeautifulSoup
import PTN

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def log(module, msg):
    if __addon__.getSetting('debug_log') != 'true':
        return

    try:
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', 'ignore')
        full_msg = "### [%s] - %s" % (__scriptid__, msg)
        if py3: xbmc.log(full_msg, level=xbmc.LOGINFO)
        else: xbmc.log(full_msg.encode('utf-8'), level=xbmc.LOGNOTICE)
    except: pass

def get_imdb_from_tmdb(tmdb_id, media_type='tv'):
    """
    Convertește TMDb ID în IMDb ID folosind API-ul TMDb.
    """
    try:
        api_key = "f090bb54758cabf231fb605d3e3e0468"
        url = "https://api.themoviedb.org/3/%s/%s/external_ids?api_key=%s" % (media_type, tmdb_id, api_key)
        
        req = requests.get(url, timeout=5)
        if req.status_code == 200:
            data = req.json()
            imdb_id = data.get('imdb_id')
            if imdb_id:
                log(__name__, "[API] Conversie reusita: TMDb %s -> IMDb %s" % (tmdb_id, imdb_id))
                return imdb_id.replace('tt', '')
    except Exception as e:
        log(__name__, "[API] Eroare la conversie TMDb->IMDb: %s" % e)
    return None

def get_file_signature(file_path):
    try:
        with open(file_path, 'rb') as f:
            header = f.read(7)
        hex_header = binascii.hexlify(header).decode('utf-8').upper()
        
        log(__name__, "[SIGNATURE] Header: %s" % hex_header)
        if hex_header.startswith('52617221'): 
            return 'rar'
        if hex_header.startswith('504B'): 
            return 'zip'
        if hex_header.startswith('3C21444F') or hex_header.startswith('3C68746D'):
            return 'html'
        return 'unknown'
    except Exception as e:
        log(__name__, "[SIGNATURE] Error reading header: %s" % str(e))
        return 'error'

def scan_archive(archive_physical_path, archive_type):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    all_files_vfs = []
    
    try:
        normalized_archive_path = archive_physical_path.replace('\\', '/')
        if not normalized_archive_path.startswith('/'):
            normalized_archive_path = '/' + normalized_archive_path
        
        if py3:
            quoted_path = urllib.quote(normalized_archive_path, safe='')
        else:
            quoted_path = urllib.quote(str(normalized_archive_path), safe='')

        root_vfs_path = '%s://%s/' % (archive_type, quoted_path)
        
        log(__name__, "[VFS] Scanez radacina: %s" % root_vfs_path)
        
        def recursive_scan(current_vfs_path):
            found_subs = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                
                for file_name in files:
                    if not py3 and isinstance(file_name, bytes):
                        file_name = file_name.decode('utf-8')

                    file_ext = os.path.splitext(file_name)[1].lower()
                    
                    if file_ext in subtitle_exts:
                        if current_vfs_path.endswith('/'):
                            full_vfs_path = current_vfs_path + file_name
                        else:
                            full_vfs_path = current_vfs_path + '/' + file_name
                        
                        found_subs.append(full_vfs_path)

                for dir_name in dirs:
                    if not py3 and isinstance(dir_name, bytes):
                        dir_name = dir_name.decode('utf-8')
                    
                    if current_vfs_path.endswith('/'):
                        next_vfs_path = current_vfs_path + dir_name + '/'
                    else:
                        next_vfs_path = current_vfs_path + '/' + dir_name + '/'
                        
                    found_subs.extend(recursive_scan(next_vfs_path))
            
            except Exception as e:
                log(__name__, "EROARE la scanarea VFS %s: %s" % (current_vfs_path, e))

            return found_subs

        all_files_vfs = recursive_scan(root_vfs_path)
        log(__name__, "[VFS] Total fisiere gasite: %d" % len(all_files_vfs))
        return all_files_vfs

    except Exception as e:
        log(__name__, "EROARE fatala la scanarea arhivei: %s" % e)
        return []

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2: return "%%%%%"
    try:
        season, epnr = int(parts[0]), int(parts[1])
        patterns = []
        
        # S02E01, s2e1, S02.E01, S02_E01, S02 E01
        patterns.append(r'[Ss]0?%d[\.\s\_\-]*[Ee]0?%d(?!\d)' % (season, epnr))
        
        # 02x01, 2x01
        patterns.append(r'(?<!\d)0?%d[Xx]0?%d(?!\d)' % (season, epnr))
        
        # Season 2 Episode 1, Season.2.Episode.01
        patterns.append(r'[Ss]eason[\.\s\_\-]*0?%d[\.\s\_\-]*[Ee]pisode[\.\s\_\-]*0?%d(?!\d)' % (season, epnr))

        final_pattern = '(?:%s)' % '|'.join(patterns)
        return final_pattern
    except:
        return "%%%%%"

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

def get_best_subtitle_match(video_filename, subtitle_files):
    """
    Algoritm avansat de matching:
    1. Tip Sursa (BluRay/WEB/HDTV) - Prioritate CRITICA (+100/-100)
    2. Fallback Priority (BluRay > AMZN/NF > WEB-DL)
    3. Release Group - Prioritate MARE (+50)
    4. Token-uri comune
    """
    if not subtitle_files: return None
    if len(subtitle_files) == 1: return subtitle_files[0]

    # --- 1. PREGATIRE DATA VIDEO ---
    video_base = os.path.basename(video_filename).lower()
    
    sources = {
        'bluray': ['bluray', 'blu-ray', 'bdrip', 'brrip', 'remux', 'uhd', '1080p-bluray', '2160p-bluray', 'bdr'],
        'web':    ['web-dl', 'webrip', 'web', 'vod', 'amzn', 'nf', 'hulu', 'disney', 'itunes', 'hbomax', 'playweb', 'atvp'],
        'hdtv':   ['hdtv', 'pdtv', 'tvrip'],
        'dvd':    ['dvdrip', 'dvd5', 'dvd9'],
        'hdrip':  ['hdrip', 'hd-rip']
    }
    
    video_source_type = 'unknown'
    for stype, tags in sources.items():
        if any(tag in video_base for tag in tags):
            video_source_type = stype
            break

    # b) Identificare Release Group Video
    video_release_group = None
    
    ignore_tags_extended = [
        'x264', 'x265', 'h264', 'h265', 'hevc', 'avc',
        '1080p', '2160p', '720p', '480p', 
        'web', 'web-dl', 'webrip', 'bluray', 'hdtv', 'bdrip', 'brrip', 'hdrip',
        'hdr', 'dv', 'hdr10', 'hdr10plus', 'dts', 'dts-hd', 'truehd', 'atmos', 'ddp5', 'dd5', 'ac3', 'aac', 
        'remux', 'repack', 'proper', 'internal', 'multi', 'sub', 
        'ro', 'ron', 'rum', 'eng', 'english', 'romanian'
    ]

    # Metoda 1: Cautare cu cratima
    match_group_hyphen = re.search(r'-([a-zA-Z0-9]+)(?:\.[a-z0-9]{2,4})?$', os.path.basename(video_filename))
    if match_group_hyphen:
        potential_group = match_group_hyphen.group(1).lower()
        if potential_group not in ignore_tags_extended and len(potential_group) > 2:
            video_release_group = potential_group
    
    # Metoda 2: Fallback la ultimul token
    if not video_release_group:
        try:
            filename_no_ext = os.path.splitext(os.path.basename(video_filename))[0]
            tokens = re.split(r'[\.\s]+', filename_no_ext)
            if tokens:
                last_token = tokens[-1].lower()
                if (last_token not in ignore_tags_extended and 
                    len(last_token) > 2 and 
                    not last_token.isdigit() and
                    not re.match(r's\d+e\d+', last_token)):
                    video_release_group = last_token
        except: pass

    video_tokens = set(re.split(r'[\s\.\-\_]+', video_base))
    
    # --- 2. COMPARARE ---
    best_match = subtitle_files[0]
    best_score = -9999

    log(__name__, "[MATCH] Video: %s | Tip: %s | Grup: %s" % (video_base, video_source_type, video_release_group))

    for sub_path in subtitle_files:
        sub_name = os.path.basename(sub_path).lower()
        if sub_path.startswith('rar://'):
            try: sub_name = os.path.basename(urllib.unquote(sub_path)).lower()
            except: pass
        
        sub_tokens = set(re.split(r'[\s\.\-\_]+', sub_name))
        
        score = 0
        sub_source_type = 'unknown'
        for stype, tags in sources.items():
            if any(tag in sub_name for tag in tags):
                sub_source_type = stype
                break
        
        if video_source_type != 'unknown' and sub_source_type != 'unknown':
            if video_source_type == sub_source_type:
                score += 100
            else:
                score -= 100
        
        is_amzn   = 'amzn' in sub_name or 'amazon' in sub_name
        is_nf     = 'nf' in sub_tokens or 'netflix' in sub_name
        is_bluray = 'bluray' in sub_name or 'bdrip' in sub_name or 'blu-ray' in sub_name
        is_webdl  = 'web-dl' in sub_name
        is_webrip = 'webrip' in sub_name

        if is_bluray:
            score += 30  
        elif is_amzn or is_nf:
            score += 25 
        elif is_webdl:
            score += 10
        elif is_webrip:
            score += 5 
        
        if video_release_group and video_release_group in sub_name:
            score += 50
        
        common_tokens = video_tokens.intersection(sub_tokens)
        score += len(common_tokens)
        
        if '2160p' in video_base and '2160p' in sub_name: score += 10
        if '1080p' in video_base and '1080p' in sub_name: score += 10
        if 'ro' in sub_name or 'rum' in sub_name: score += 5 

        if score > best_score:
            best_score = score
            best_match = sub_path

    log(__name__, "[MATCH] Castigator: %s (Scor: %d)" % (os.path.basename(best_match), best_score))
    return best_match

def Search(item):
    
    if os.path.exists(__temp__):
        try: shutil.rmtree(__temp__, ignore_errors=True)
        except: pass
    try: os.makedirs(__temp__)
    except: pass
    
    try: handle = int(sys.argv[1])
    except: handle = -1
    is_auto_download = __addon__.getSetting('auto_download') == 'true'

    filtered_subs, raw_count = searchsubtitles(item)
    
    if not filtered_subs:
        if handle == -1:
            log(__name__, "[AUTO] Nu s-au gasit rezultate pe site. Se deschide cautarea manuala.")
            xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
        else:
            log(__name__, "[MANUAL] Nu s-au gasit subtitrari.")
        return

    unique_subs = []
    seen_links = set()
    for sub in filtered_subs:
        link = sub["ZipDownloadLink"]
        if link not in seen_links:
            seen_links.add(link)
            unique_subs.append(sub)
    
    filtered_subs = unique_subs
    
    priority_list = ['subrip', 'retail', 'retailsubs', 'netflix', 'hbo', 'amazon', 'disney', 'itunes']
    def priority_sort_key(sub_item):
        trad = sub_item.get('Traducator', '').lower()
        is_priority = any(p in trad for p in priority_list)
        return (not is_priority)
    filtered_subs.sort(key=priority_sort_key)
    
    log(__name__, "--- [DEBUG] LISTA ARHIVE GASITE (%d) ---" % len(filtered_subs))
    for idx, sub in enumerate(filtered_subs):
        clean_name = sub['SubFileName'].replace('[B]', '').replace('[/B]', '').replace('[COLOR FFFDBD01]', '').replace('[/COLOR]', '')
        log(__name__, "Candidat #%d: %s | Trad: %s" % (idx, clean_name, sub.get('Traducator', 'N/A')))
    log(__name__, "---------------------------------------------")

    # =========================================================================
    #                    LOGICA AUTO-DOWNLOAD
    # =========================================================================
    
    if handle == -1 and is_auto_download:
        log(__name__, "[AUTO] Mod Auto activ. Se verifica arhivele la rand...")
        
        for idx, candidate in enumerate(filtered_subs):
            link = candidate["ZipDownloadLink"]
            # log(__name__, "[AUTO] Verific arhiva #%d: %s" % (idx, candidate['SubFileName']))
            
            s = requests.Session()
            s.headers.update({'Referer': BASE_URL})
            
            timestamp = str(int(time.time()))
            temp_file_name = "sub_%s_%d.dat" % (timestamp, idx)
            raw_path = os.path.join(__temp__, temp_file_name)
            
            valid_download = False
            for attempt in range(1, 6):
                try:
                    response = s.get(link, verify=False)
                    with open(raw_path, 'wb') as f: 
                        f.write(response.content)
                        f.flush()
                        os.fsync(f.fileno())
                    real_type = get_file_signature(raw_path)
                    if real_type == 'html':
                        log(__name__, "[AUTO] Tentativa %d/5 esuata (HTML). Astept 1 sec..." % attempt)
                        time.sleep(1.0)
                        continue
                    else:
                        valid_download = True
                        break
                except Exception as e:
                    log(__name__, "[AUTO] Tentativa %d/5 esuata (Retea). Astept 1 sec..." % attempt)
                    time.sleep(1.0)
            
            if not valid_download:
                log(__name__, "[AUTO] Esuat definitiv la arhiva #%d." % idx)
                if os.path.exists(raw_path): os.remove(raw_path)
                continue

            if real_type == 'unknown': real_type = 'zip'
            
            final_ext = 'rar' if real_type == 'rar' else 'zip'
            final_rar_name = "sub_%s_%d.%s" % (timestamp, idx, final_ext)
            final_rar_path = os.path.join(__temp__, final_rar_name)
            
            try:
                if os.path.exists(final_rar_path): os.remove(final_rar_path)
                shutil.move(raw_path, final_rar_path)
                raw_path = final_rar_path
            except: continue

            all_files = []
            extract_path = "" 
            
            if real_type == 'rar':
                if xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
                    all_files = scan_archive(raw_path, 'rar')
            elif real_type == 'zip':
                log(__name__, "[AUTO] ZIP - Extrag direct in temp (fara subfoldere)")
                try:
                    with zipfile.ZipFile(raw_path, 'r') as zip_ref:
                        zip_contents = zip_ref.namelist()
                        subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
                        extracted_names = set()
                        
                        for zip_entry in zip_contents:
                            if zip_entry.endswith('/'):
                                continue
                            
                            entry_ext = os.path.splitext(zip_entry)[1].lower()
                            if entry_ext not in subtitle_exts:
                                continue
                            
                            original_filename = os.path.basename(zip_entry)
                            
                            # Scurtam numele daca e prea lung
                            if len(original_filename) > 150:
                                name_part, ext_part = os.path.splitext(original_filename)
                                match = re.search(r'[Ss]\d+[Ee]\d+', name_part)
                                if match:
                                    prefix = name_part[:match.end() + 20] if match.end() + 20 < len(name_part) else name_part[:match.end()]
                                    suffix = name_part[-30:]
                                    short_name = prefix + "..." + suffix + ext_part
                                else:
                                    short_name = name_part[:60] + "..." + name_part[-30:] + ext_part
                                dest_filename = short_name
                            else:
                                dest_filename = original_filename
                            
                            if dest_filename in extracted_names:
                                name_part, ext_part = os.path.splitext(dest_filename)
                                dest_filename = "%s_%d%s" % (name_part, len(extracted_names), ext_part)
                            
                            extracted_names.add(dest_filename)
                            dest_path = os.path.join(__temp__, dest_filename)
                            
                            try:
                                with zip_ref.open(zip_entry) as source:
                                    content = source.read()
                                with open(dest_path, 'wb') as dest:
                                    dest.write(content)
                                all_files.append(dest_path)
                            except Exception as extract_err:
                                log(__name__, "[AUTO] EROARE extragere %s: %s" % (original_filename, str(extract_err)))
                        
                        log(__name__, "[AUTO] Extragere ZIP completa. Total: %d" % len(all_files))
                except Exception as e:
                    log(__name__, "[AUTO] EROARE ZIP: %s" % str(e))

            if not all_files:
                if os.path.exists(raw_path): os.remove(raw_path)
                if extract_path and os.path.isdir(extract_path): shutil.rmtree(extract_path, ignore_errors=True)
                continue

            valid_episode_files = []
            if item.get('season') and item.get('episode') and item.get('season') != "0" and item.get('episode') != "0":
                epstr = '%s:%s' % (item['season'], item['episode'])
                episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
                
                log(__name__, "[AUTO] Filtrez pentru episod: %s | Pattern: %s" % (epstr, get_episode_pattern(epstr)))
                
                for sub_file in all_files:
                    check_name = sub_file
                    if sub_file.startswith('rar://'):
                        try: check_name = urllib.unquote(sub_file)
                        except: pass
                    
                    basename = os.path.basename(check_name)
                    match_result = episode_regex.search(basename)
                    # log(__name__, "[AUTO] Verific: '%s' -> Match: %s" % (basename, 'DA' if match_result else 'NU'))
                    
                    if match_result:
                        valid_episode_files.append(sub_file)
                
                if not valid_episode_files:
                    log(__name__, "[AUTO] Arhiva #%d NU contine episodul cautat. STERGERE si continuare..." % idx)
                    # Stergem arhiva
                    if os.path.exists(raw_path): 
                        try: os.remove(raw_path)
                        except: pass
                    # Stergem fisierele extrase (sunt direct in __temp__, le stergem individual)
                    for extracted_file in all_files:
                        if os.path.exists(extracted_file):
                            try: os.remove(extracted_file)
                            except: pass
                    continue 
                else:
                    all_files = valid_episode_files
            
            all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))
            best_match = all_files[0]
            if len(all_files) > 1:
                video_file = item.get('file_original_path', '')
                if video_file:
                     match = get_best_subtitle_match(video_file, all_files)
                     if match: best_match = match
            
            final_path_auto = best_match
            if best_match.startswith('rar://'):
                try:
                    base_filename = os.path.basename(best_match)
                    try: base_filename = urllib.unquote(base_filename)
                    except: pass
                    dest_file = os.path.join(__temp__, base_filename)
                    source_obj = xbmcvfs.File(best_match, 'rb')
                    dest_obj = xbmcvfs.File(dest_file, 'wb')
                    content = source_obj.readBytes() if py3 else source_obj.read()
                    if not py3 and isinstance(content, unicode): dest_obj.write(content.encode('utf-8'))
                    else: dest_obj.write(content)
                    source_obj.close()
                    dest_obj.close()
                    final_path_auto = dest_file
                except: pass
            
            if os.path.exists(final_path_auto):
                folder = os.path.dirname(final_path_auto)
                filename = os.path.basename(final_path_auto)
                name, ext = os.path.splitext(filename)
                if not '.ro.' in filename.lower() and not name.lower().endswith('.ro'):
                    new_filename = "%s.ro%s" % (name, ext)
                    new_path = os.path.join(folder, new_filename)
                    try: os.rename(final_path_auto, new_path); final_path_auto = new_path
                    except: pass
            
            xbmc.Player().setSubtitles(final_path_auto)
            trad_auto = candidate.get('Traducator', '')
            msg = "Subtitrare aplicata! [B][COLOR FF00BFFF] '%s'[/COLOR][/B]" % trad_auto
            xbmcgui.Dialog().notification(__scriptname__, msg, xbmcgui.NOTIFICATION_INFO, 3000)
            sys.exit(0)

        log(__name__, "[AUTO] Nicio arhiva nu a fost valida. Se curata tot si se comuta pe Manual.")
        if os.path.exists(__temp__):
            try: shutil.rmtree(__temp__, ignore_errors=True)
            except: pass
        try: os.makedirs(__temp__)
        except: pass

    # =========================================================================
    #                    LOGICA MANUAL / SELECTIE (GUI)
    # =========================================================================
    
    if handle == -1:
        xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
        return

    sel = -1
    
    # MODIFICARE: La manual search afisam mereu lista, chiar daca e 1 rezultat
    if len(filtered_subs) == 1 and not item.get('mansearch'):
        sel = 0
        log(__name__, "[AUTO-SELECT] Un singur rezultat. Se intra automat in arhiva.")
    else:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in filtered_subs]
        sel = dialog.select("Selectati Arhiva", titles)
    
    if sel == -1:
        return 

    selected_sub_info = filtered_subs[sel]
    selected_lang_code = selected_sub_info["ISO639"]
    selected_rating = selected_sub_info["SubRating"]
    selected_trad = selected_sub_info.get("Traducator", "N/A")
    link = selected_sub_info["ZipDownloadLink"]
    
    s = requests.Session()
    s.headers.update({'Referer': BASE_URL})
    
    timestamp = str(int(time.time()))
    temp_file_name = "sub_%s.dat" % timestamp
    raw_path = os.path.join(__temp__, temp_file_name)
    
    # --- RETRY MANUAL (5 incercari) ---
    valid_download = False
    for attempt in range(1, 6):
        try:
            response = s.get(link, verify=False)
            with open(raw_path, 'wb') as f: 
                f.write(response.content)
                f.flush()
                os.fsync(f.fileno())
            real_type = get_file_signature(raw_path)
            if real_type == 'html':
                log(__name__, "[MANUAL] Tentativa %d/5 esuata (HTML). Astept 1 sec..." % attempt)
                time.sleep(1.0)
                continue
            else:
                valid_download = True
                break
        except Exception as e:
            log(__name__, "[MANUAL] Tentativa %d/5 esuata (Retea). Astept 1 sec..." % attempt)
            time.sleep(1.0)

    if not valid_download:
        if os.path.exists(raw_path): os.remove(raw_path)
        xbmcgui.Dialog().ok("Eroare Server", "Serverul este ocupat (HTML/Protectie).\nAm încercat de 5 ori fără succes.")
        return

    if real_type == 'unknown': real_type = 'zip'
    final_ext = 'rar' if real_type == 'rar' else 'zip'
    final_rar_name = "sub_%s.%s" % (timestamp, final_ext)
    final_rar_path = os.path.join(__temp__, final_rar_name)
    
    try:
        if os.path.exists(final_rar_path): os.remove(final_rar_path)
        shutil.move(raw_path, final_rar_path)
        raw_path = final_rar_path
        time.sleep(0.5)
    except Exception as e:
        log(__name__, "[MANUAL] Eroare la mutare fisier: %s" % str(e))
        return

    log(__name__, "[MANUAL] Arhiva salvata: %s (Tip: %s)" % (raw_path, real_type))

    all_files = []
    extract_path = ""
    
    if real_type == 'rar':
        if not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
            xbmcgui.Dialog().ok("Eroare", "Instalati 'RAR archive support'!")
            return
        all_files = scan_archive(raw_path, 'rar')
        log(__name__, "[MANUAL] RAR - Fisiere gasite: %d" % len(all_files))
    elif real_type == 'zip':
        log(__name__, "[MANUAL] ZIP - Extrag direct in temp (fara subfoldere)")
        try:
            with zipfile.ZipFile(raw_path, 'r') as zip_ref:
                zip_contents = zip_ref.namelist()
                log(__name__, "[MANUAL] ZIP contine %d intrari" % len(zip_contents))
                
                subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
                extracted_names = set()  # Pentru a evita suprascrieri
                
                for zip_entry in zip_contents:
                    # Skip directories
                    if zip_entry.endswith('/'):
                        continue
                    
                    # Verificam daca e fisier subtitrare
                    entry_ext = os.path.splitext(zip_entry)[1].lower()
                    if entry_ext not in subtitle_exts:
                        continue
                    
                    # Extragem doar numele fisierului (fara cale)
                    original_filename = os.path.basename(zip_entry)
                    
                    # Daca numele e prea lung (>150 chars), il scurtam inteligent
                    if len(original_filename) > 150:
                        name_part, ext_part = os.path.splitext(original_filename)
                        # Pastram partea cu S02E01 si sfarsitul
                        # Cautam pattern-ul sezon/episod
                        match = re.search(r'[Ss]\d+[Ee]\d+', name_part)
                        if match:
                            # Pastram de la inceput pana dupa S02E01 + ultimele 30 chars
                            prefix = name_part[:match.end() + 20] if match.end() + 20 < len(name_part) else name_part[:match.end()]
                            suffix = name_part[-30:]
                            short_name = prefix + "..." + suffix + ext_part
                        else:
                            short_name = name_part[:60] + "..." + name_part[-30:] + ext_part
                        dest_filename = short_name
                    else:
                        dest_filename = original_filename
                    
                    # Verificam daca exista deja un fisier cu acelasi nume
                    if dest_filename in extracted_names:
                        # Adaugam un sufix pentru a evita suprascrierea
                        name_part, ext_part = os.path.splitext(dest_filename)
                        dest_filename = "%s_%d%s" % (name_part, len(extracted_names), ext_part)
                    
                    extracted_names.add(dest_filename)
                    dest_path = os.path.join(__temp__, dest_filename)
                    
                    # log(__name__, "[MANUAL] Extrag: %s" % dest_filename)
                    
                    try:
                        with zip_ref.open(zip_entry) as source:
                            content = source.read()
                        with open(dest_path, 'wb') as dest:
                            dest.write(content)
                        all_files.append(dest_path)
                    except Exception as extract_err:
                        log(__name__, "[MANUAL] EROARE la extragere %s: %s" % (original_filename, str(extract_err)))
                
                log(__name__, "[MANUAL] Extragere completa. Total: %d" % len(all_files))
                
        except Exception as e:
            log(__name__, "[MANUAL] EROARE ZIP: %s" % str(e))

    log(__name__, "[MANUAL] Total fisiere subtitrare gasite: %d" % len(all_files))
    
    if not all_files:
        xbmcgui.Dialog().ok("Info", "Nu s-au găsit subtitrări în această arhivă.\nVerificați log-ul pentru detalii.")
        return

    # Filtrare episod - DOAR pentru seriale si DOAR daca NU e manual search
    original_count = len(all_files)
    
    if not item.get('mansearch') and item.get('season') and item.get('episode') and item.get('season') != "0" and item.get('episode') != "0":
        subs_list = []
        epstr = '%s:%s' % (item['season'], item['episode'])
        episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
        
        log(__name__, "[MANUAL] Filtrez pentru episod: %s | Pattern: %s" % (epstr, get_episode_pattern(epstr)))
        
        for sub_file in all_files:
            check_name = sub_file
            if sub_file.startswith('rar://'):
                try: check_name = urllib.unquote(sub_file)
                except: pass
            
            basename = os.path.basename(check_name)
            match_result = episode_regex.search(basename)
            # log(__name__, "[MANUAL] Verific: '%s' -> Match: %s" % (basename, 'DA' if match_result else 'NU'))
            
            if match_result:
                subs_list.append(sub_file)
        
        log(__name__, "[MANUAL] Dupa filtrare: %d din %d" % (len(subs_list), original_count))
        
        if subs_list:
            all_files = subs_list
        else:
            # FALLBACK: Daca filtrul nu a gasit nimic, afisam TOATE fisierele
            log(__name__, "[MANUAL] Filtrul nu a gasit episodul. Afisez TOATE cele %d fisiere (fallback)." % original_count)
            # NU modificam all_files - ramane cu toate fisierele

    all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

    log(__name__, "[MANUAL] Fisiere finale pentru afisare: %d" % len(all_files))
    for idx, f in enumerate(all_files):
        log(__name__, "[MANUAL] #%d: %s" % (idx, os.path.basename(f)))

    for ofile in all_files:
        display_name = os.path.basename(ofile)
        if ofile.startswith('rar://'):
            try: display_name = urllib.unquote(display_name)
            except: pass

        listitem = xbmcgui.ListItem(label=selected_trad, label2=display_name)
        listitem.setArt({'icon': selected_rating, 'thumb': selected_lang_code})
        listitem.setProperty("language", selected_lang_code)
        listitem.setProperty("sync", "false") 
        url = "plugin://%s/?action=setsub&link=%s&trad=%s" % (__scriptid__, urllib.quote_plus(ofile), urllib.quote_plus(selected_trad))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def get_title_variations(title):
    variations = []
    base_title = ' '.join(title.strip().split())
    if not base_title: return []

    variations.append(base_title)

    if '&' in base_title:
        with_and = base_title.replace('&', 'and')
        variations.append(' '.join(with_and.split()))

    if re.search(r'\band\b', base_title, re.IGNORECASE):
        with_amp = re.sub(r'\band\b', '&', base_title, flags=re.IGNORECASE)
        variations.append(' '.join(with_amp.split()))

    clean_base = re.sub(r'[:\-\|&]', ' ', base_title).strip()
    clean_base = ' '.join(clean_base.split())
    
    if clean_base.lower() != base_title.lower() and clean_base not in variations:
        variations.append(clean_base)

    separators_pattern = r'[&:\-]|\band\b'
    if re.search(separators_pattern, base_title, re.IGNORECASE):
        parts = re.split(separators_pattern, base_title, flags=re.IGNORECASE)
        for part in parts:
            p = part.strip()
            if len(p) > 3 and not p.isdigit():
                variations.append(p)

    match_sequel = re.search(r'^(.+?\s\d{1,2})(\s|$)', clean_base)
    if match_sequel:
        short_title = match_sequel.group(1).strip()
        if len(short_title) > 2 and short_title.lower() != clean_base.lower():
            variations.append(short_title)

    num_map = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        '10': 'ten'
    }
    rev_map = {v: k for k, v in num_map.items()}

    words = clean_base.split()
    new_words_to_text = []
    changed_to_text = False
    
    # --- FIX CRITIC: APOSTROF (DONT -> DON'T) ---
    contraction_map = {
        'dont': "don't", 'wont': "won't", 'cant': "can't", 
        'isnt': "isn't", 'arent': "aren't", 'didnt': "didn't",
        'couldnt': "couldn't", 'shouldnt': "shouldn't", 'wouldnt': "wouldn't",
        'wasnt': "wasn't", 'werent': "weren't", 'hasnt': "hasn't", 'havent': "haven't",
        'youre': "you're", 'theyre': "they're", 'weve': "we've", 'im': "I'm",
        'thats': "that's", 'whats': "what's", 'lets': "let's"
    }
    
    words_apostrophe = []
    changed_apostrophe = False
    
    for w in words:
        w_low = w.lower()
        if w_low in num_map:
            new_words_to_text.append(num_map[w_low])
            changed_to_text = True
        else:
            new_words_to_text.append(w)
            
        if w_low in contraction_map:
            words_apostrophe.append(contraction_map[w_low])
            changed_apostrophe = True
        else:
            words_apostrophe.append(w)

    if changed_to_text:
        variations.append(" ".join(new_words_to_text))
        
    if changed_apostrophe:
        variations.append(" ".join(words_apostrophe))

    new_words_to_digit = []
    changed_to_digit = False
    for w in words:
        if w.lower() in rev_map:
            new_words_to_digit.append(rev_map[w.lower()])
            changed_to_digit = True
        else:
            new_words_to_digit.append(w)
    if changed_to_digit:
        variations.append(" ".join(new_words_to_digit))

    # --- FIX CRITIC: TRUNCHIERE TITLURI LUNGI (MAX 4 CUVINTE) ---
    # Daca titlul e "Now You See Me Now You Dont" (7 cuvinte) -> cauta "Now You See Me"
    if len(words) > 5:
        truncated_title = " ".join(words[:4])
        if len(truncated_title) > 3:
            variations.append(truncated_title)

    seen = set()
    final_variations = []
    for v in variations:
        v_low = v.lower()
        if v_low not in seen and len(v_low) > 2:
            seen.add(v_low)
            final_variations.append(v)
            
    return final_variations

def parse_results(html_content, languages_to_keep, required_season=None, search_year=None, search_query_title=None, is_manual_search=False):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    download_links = soup.find_all('a', href=re.compile(r'/subtitrare/descarca/'))
    
    raw_count = len(download_links)
    result = []
    processed_links = set()

    is_searching_movie = True
    if required_season and str(required_season) not in ('0', 'None', ''):
        is_searching_movie = False

    def clean_for_compare(text):
        if not text: return ""
        t = text.lower()
        t = re.sub(r'\(.*?\)', '', t)
        if '+' in t: t = t.split('+')[0]
        t = re.sub(r'[^a-z0-9\s]', '', t)
        return ' '.join(t.split())

    clean_search_query = clean_for_compare(search_query_title) if search_query_title else ""

    for dl_link in download_links:
        try:
            legatura_raw = dl_link['href']
            if not legatura_raw.startswith('http'): 
                legatura = BASE_URL.rstrip('/') + legatura_raw
            else:
                legatura = legatura_raw

            if legatura in processed_links: continue
            processed_links.add(legatura)

            row_div = None
            parent = dl_link.parent
            for _ in range(5):
                if parent is None: break
                if parent.name == 'div' and parent.find('h2'):
                    row_div = parent
                    break
                parent = parent.parent
            
            if not row_div: continue

            nume, an_str = 'N/A', 'N/A'
            traducator, uploader = 'N/A', 'N/A'
            limba_text = 'N/A'
            
            title_tag = row_div.find('h2')
            if title_tag:
                full_text = title_tag.get_text(strip=True)
                match_an = re.search(r'\((\d{4})\)', full_text)
                if match_an:
                    an_str = match_an.group(1)
                    nume = full_text.replace('(%s)' % an_str, '').replace('()', '').strip()
                else:
                    nume = full_text

            details = row_div.find_all('span', class_='font-medium text-gray-700')
            for span in details:
                parent_text = span.parent.get_text(" ", strip=True)
                if 'Traducător:' in parent_text: traducator = parent_text.replace('Traducător:', '').strip()
                if 'Uploader:' in parent_text: uploader = parent_text.replace('Uploader:', '').strip()
                if 'Limba:' in parent_text: limba_text = parent_text.replace('Limba:', '').strip()

            if is_searching_movie and clean_search_query and not is_manual_search:
                clean_result_name = clean_for_compare(nume)
                if clean_result_name != clean_search_query:
                    tokens_search = set(clean_search_query.split())
                    tokens_result = set(clean_result_name.split())
                    diff = tokens_result - tokens_search
                    allowed_diffs = {'the', 'a', 'an', 'movie', 'film', 'part', 'vol', 'volume', 'chapter'}
                    if diff and not diff.issubset(allowed_diffs):
                        continue

            titlu_lower = nume.lower()
            
            should_skip_series_check = False
            if is_manual_search:
                 should_skip_series_check = True

            if is_searching_movie and not should_skip_series_check:
                if 'sezon' in titlu_lower or 'season' in titlu_lower or 'series' in titlu_lower:
                    continue

            if limba_text != 'N/A':
                if 'română' not in limba_text.lower() and 'romana' not in limba_text.lower():
                    continue
            
            flag_img = row_div.find('img', src=re.compile(r'flag-'))
            if flag_img and 'rom' not in flag_img['src'] and 'rum' not in flag_img['src'] and 'ro.' not in flag_img['src']:
                 continue

            if search_year and an_str and an_str.isdigit() and not is_manual_search:
                try:
                    req_y = int(search_year)
                    res_y = int(an_str)
                    if abs(res_y - req_y) > 1:
                        if is_searching_movie:
                            continue
                except: pass

            if not is_searching_movie and not is_manual_search:
                try:
                    curr_s = int(required_season)
                    is_match = False
                    match_range = re.search(r'(?:sez|seas|series)\w*\W*(\d+)\s*-\s*(\d+)', titlu_lower)
                    match_single = re.search(r'(?:sez|seas|series|s)\w*\W*0*(\d+)', titlu_lower)
                    
                    if match_range:
                        s_start, s_end = int(match_range.group(1)), int(match_range.group(2))
                        if s_start <= curr_s <= s_end: is_match = True
                    elif match_single:
                        if int(match_single.group(1)) == curr_s: is_match = True
                    
                    if not is_match:
                        continue
                except: continue

            if not traducator: traducator = 'N/A'
            if not uploader: uploader = 'N/A'
            if limba_text == 'N/A': limba_text = 'Română'

            main_part = u'[B]%s (%s)[/B]' % (nume, an_str)
            trad_part = u'Trad: [B][COLOR FFFDBD01]%s[/COLOR][/B]' % (traducator)
            lang_part = u'Limba: [B][COLOR FF00FA9A]%s[/COLOR][/B]' % (limba_text)
            upl_part = u'Up: [B][COLOR FFFF69B4]%s[/COLOR][/B]' % (uploader)
            
            display_name = u'%s | %s | %s | %s' % (main_part, trad_part, lang_part, upl_part)
            
            result.append({
                'SubFileName': display_name, 
                'ZipDownloadLink': legatura, 
                'LanguageName': 'Romanian', 
                'ISO639': 'ro', 
                'SubRating': '5', 
                'Traducator': traducator
            })
        except Exception as e:
            continue
            
    sorted_result = sorted(result, key=lambda sub: 0 if sub['ISO639'] == 'ro' else 1)
    return (sorted_result, raw_count)

def searchsubtitles(item):
    log(__name__, ">>>>>>>>>> PORNIRE CĂUTARE SUBTITRARE (SUBS.RO) <<<<<<<<<<")
    
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,ro;q=0.8', 'Origin': BASE_URL.rstrip('/'), 'Referer': BASE_URL + 'cautare'
    })
    
    languages_to_keep = item.get('languages', [])
    req_season = item.get('season', '0')
    is_manual = item.get('mansearch', False)
    
    search_year = xbmc.getInfoLabel("VideoPlayer.Year")
    if not search_year or not search_year.isdigit() or int(search_year) < 1900:
        txt_source = "%s %s" % (item.get('file_original_path', ''), item.get('title', ''))
        match_y = re.search(r'\b(19|20)\d{2}\b', txt_source)
        if match_y:
            search_year = match_y.group(0)

    # 1. MANUAL SEARCH
    if is_manual:
        manual_str = urllib.unquote(item.get('mansearchstr', '')).strip()
        log(__name__, "--- MOD MANUAL ACTIV --- Ignor ID-uri, caut text: '%s'" % manual_str)
        
        if manual_str:
            post_data = {'type': 'subtitrari', 'titlu-film': manual_str}
            html_content = fetch_subtitles_page(sess, post_data)
            if html_content:
                results, count = parse_results(html_content, languages_to_keep, req_season, search_year, search_query_title=manual_str, is_manual_search=True)
                if results:
                    log(__name__, "!!! Gasit %d rezultate manuale pentru '%s' !!!" % (len(results), manual_str))
                    return results, count
                else:
                    log(__name__, "[MANUAL] Niciun rezultat gasit pentru: %s" % manual_str)
        return [], 0

    # 2. AUTO SEARCH - ETAPA 1: ID
    tmdb_id = xbmc.getInfoLabel("VideoPlayer.TVShow.TMDbId") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    if not tmdb_id and item.get('tmdb_id_fallback'):
        tmdb_id = item.get('tmdb_id_fallback')

    if tmdb_id and str(tmdb_id).isdigit():
        log(__name__, "Incerc cautare dupa TMDb ID: %s" % tmdb_id)
        post_data = {'type': 'subtitrari', 'external_id': tmdb_id}
        html_content = fetch_subtitles_page(sess, post_data)
        if html_content:
            results, count = parse_results(html_content, languages_to_keep, req_season, search_year, is_manual_search=False)
            if results:
                log(__name__, "Gasit %d rezultate dupa TMDb ID." % len(results))
                return results, count

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
    if not imdb_id and item.get('imdb_id_fallback'):
         imdb_id = item.get('imdb_id_fallback')

    if imdb_id:
        imdb_id_numeric = str(imdb_id).replace("tt", "")
        if imdb_id_numeric.isdigit():
            log(__name__, "Incerc cautare dupa IMDb ID: %s" % imdb_id_numeric)
            post_data = {'type': 'subtitrari', 'external_id': imdb_id_numeric}
            html_content = fetch_subtitles_page(sess, post_data)
            if html_content:
                results, count = parse_results(html_content, languages_to_keep, req_season, search_year, is_manual_search=False)
                if results:
                    log(__name__, "Gasit %d rezultate dupa IMDb ID." % len(results))
                    return results, count

    # 3. AUTO SEARCH - ETAPA 2: TEXT
    log(__name__, "Trec la cautare textuala (Fallback Auto)...")
    candidates = []
    candidates.append(xbmc.getInfoLabel("VideoPlayer.TVShowTitle"))
    candidates.append(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))
    candidates.append(xbmc.getInfoLabel("VideoPlayer.Title"))
    
    path = item.get('file_original_path', '')
    if path and not path.startswith('http'):
        candidates.append(os.path.basename(path))
    else:
        candidates.append(item.get('title', ''))

    search_str = ""
    for cand in candidates:
        clean_cand = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', cand or "", flags=re.IGNORECASE).strip()
        if '.' in clean_cand: clean_cand = clean_cand.replace('.', ' ')
        match_season = re.search(r'(?i)\b(s\d+|sezon|season)', clean_cand)
        if match_season: clean_cand = clean_cand[:match_season.start()].strip()
        match_year = re.search(r'\b(19|20)\d{2}\b', clean_cand)
        if match_year: clean_cand = clean_cand[:match_year.start()].strip()
        if clean_cand and len(clean_cand) > 2:
            search_str = clean_cand
            break
    
    if not search_str: return ([], 0)

    s = search_str
    s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) 
    s = re.sub(r'\b(19|20)\d{2}\b', '', s)
    s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s)
    s = re.sub(r'(?i)\bsez.*?$', '', s)
    s = s.replace('.', ' ')
    
    spam_words = ['Marvel Studios', 'Netflix', 'Amazon', 'hdtv', 'web-dl', 'bluray']
    for word in spam_words:
        s = re.sub(r'\b' + re.escape(word) + r'\b', '', s, flags=re.IGNORECASE)

    final_search_string = ' '.join(s.split())
    if not final_search_string: return ([], 0)

    search_candidates = get_title_variations(final_search_string)
    
    for candidate in search_candidates:
        log(__name__, "Incerc cautare text Auto: '%s'" % candidate)
        post_data = {'type': 'subtitrari', 'titlu-film': candidate}
        html_content = fetch_subtitles_page(sess, post_data)
        if not html_content: continue
        results, count = parse_results(html_content, languages_to_keep, req_season, search_year, search_query_title=candidate, is_manual_search=False)
        if results:
            log(__name__, "!!! Gasit %d rezultate pentru '%s' !!!" % (len(results), candidate))
            return results, count
            
    return ([], 0)

def fetch_subtitles_page(session, post_data):
    try:
        main_page_resp = session.get(BASE_URL + 'cautare', verify=False, timeout=15)
        if main_page_resp.status_code != 200:
            log(__name__, "EROARE HTTP la accesare pagina cautare: %s" % main_page_resp.status_code)
            return None

        main_page_soup = BeautifulSoup(main_page_resp.text, 'html.parser')
        form = main_page_soup.find('form', {'id': 'search-subtitrari'})
        antispam_tag = form.find('input', {'name': 'antispam'}) if form else None
        
        if not antispam_tag or 'value' not in antispam_tag.attrs: 
            log(__name__, "EROARE: Nu am gasit token-ul antispam in pagina.")
            return None
            
        antispam_token = antispam_tag['value']
        post_data['antispam'] = antispam_token
        
        ajax_url = BASE_URL + 'ajax/search'
        response = session.post(ajax_url, data=post_data, verify=False, timeout=15)
        response.raise_for_status()
        
        return response.text
    except Exception as e:
        log(__name__, "EXCEPTIE la fetch_subtitles_page: %s" % str(e))
        return None

def natural_key(string_): return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]

def normalizeString(obj):
    if py3: return obj
    try: return unicodedata.normalize('NFKD', unicode(obj, 'utf-8')).encode('ascii', 'ignore')
    except: return unicode(str(obj).encode('string_escape'))

def get_params():
    param = {}
    try:
        paramstring = sys.argv[2]
        if len(paramstring) >= 2:
            pairs = paramstring.replace('?', '').split('&')
            for pair in pairs:
                split = pair.split('=', 1)
                if len(split) == 2:
                    param[split[0]] = split[1]
    except: pass
    return param

params = get_params()
action = params.get('action')

if action in ('search', 'manualsearch'):
    
    if params.get('searchstring'):
        action = 'manualsearch'

    file_original_path = ""
    candidate_paths = []
    
    try:
        playing_file = xbmc.Player().getPlayingFile()
        if not py3 and isinstance(playing_file, str): playing_file = playing_file.decode('utf-8', 'ignore')
        candidate_paths.append(playing_file)
    except: pass

    candidate_paths.append(xbmc.getInfoLabel("ListItem.Path"))
    candidate_paths.append(xbmc.getInfoLabel("ListItem.FolderPath"))
    candidate_paths.append(xbmc.getInfoLabel("Player.Filenameandpath"))
    candidate_paths.append(xbmc.getInfoLabel("Container.ListItem.FileNameAndPath"))
    
    log(__name__, "[DEBUG] Cai verificate pentru metadate: %s" % str(candidate_paths))

    for p in candidate_paths:
        p_str = str(p)
        if 'plugin://' in p_str and ('tmdb' in p_str or 'imdb' in p_str or 'season' in p_str):
            file_original_path = p_str
            log(__name__, "[DEBUG] Am recuperat URL-ul original cu metadate: %s" % file_original_path)
            break
            
    if not file_original_path and candidate_paths[0]:
        file_original_path = str(candidate_paths[0])

    season = str(xbmc.getInfoLabel("VideoPlayer.Season"))
    episode = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    
    tmdb_id_fallback = None
    imdb_id_fallback = None
    
    if file_original_path:
        match_tmdb = re.search(r'[?&](?:tmdb_id|tmdb)=(\d+)', file_original_path)
        if match_tmdb: tmdb_id_fallback = match_tmdb.group(1)
        
        match_imdb = re.search(r'[?&](?:imdb_id|imdb)=(tt\d+|\d+)', file_original_path)
        if match_imdb: imdb_id_fallback = match_imdb.group(1)
        
        if not season or season == "0" or season == "":
            match_s = re.search(r'[?&]season=(\d+)', file_original_path)
            if match_s: season = match_s.group(1)
            
        if not episode or episode == "0" or episode == "":
            match_e = re.search(r'[?&]episode=(\d+)', file_original_path)
            if match_e: episode = match_e.group(1)

    if tmdb_id_fallback and not imdb_id_fallback:
        media_type = 'movie'
        if 'episode' in file_original_path or (season and season != '0'):
            media_type = 'tv'
            
        log(__name__, "Detectat TMDb: %s. Convertesc in IMDb..." % tmdb_id_fallback)
        converted_imdb = get_imdb_from_tmdb(tmdb_id_fallback, media_type)
        if converted_imdb:
            imdb_id_fallback = converted_imdb

    kodi_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    if not kodi_title:
        kodi_title = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
    
    if not kodi_title or "episodul" in kodi_title.lower():
         match_title_url = re.search(r'[?&]title=([^&]+)', file_original_path)
         if match_title_url:
             decoded_t = urllib.unquote(match_title_url.group(1))
             if len(decoded_t) > 2 and "episodul" not in decoded_t.lower(): 
                 kodi_title = decoded_t

    if not season or season == "0" or not episode or episode == "0":
        match_se = re.search(r'(?i)[sS](\d{1,2})[eE](\d{1,2})', os.path.basename(file_original_path))
        if match_se:
            if not season or season == "0": season = str(int(match_se.group(1)))
            if not episode or episode == "0": episode = str(int(match_se.group(2)))
            
            clean_name = os.path.basename(file_original_path)
            match_season_pos = re.search(r'(?i)\b(s\d+|sezon|season)', clean_name)
            if match_season_pos:
                clean_name = clean_name[:match_season_pos.start()].replace('.', ' ').strip()
                if clean_name and len(clean_name) > 2:
                    kodi_title = clean_name

    item = {
        'mansearch': action == 'manualsearch',
        'file_original_path': file_original_path,
        'title': normalizeString(kodi_title),
        'season': season, 
        'episode': episode,
        'tmdb_id_fallback': tmdb_id_fallback,
        'imdb_id_fallback': imdb_id_fallback
    }
    
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    lang_param = urllib.unquote(params.get('languages', ''))
    item['languages'] = [xbmc.convertLanguage(lang, xbmc.ISO_639_1) for lang in lang_param.split(',') if lang]
    
    log(__name__, "Info Final -> Titlu: %s | S: %s | E: %s | TMDb: %s | IMDb: %s | Manual: %s" % (
        item['title'], item['season'], item['episode'], tmdb_id_fallback, imdb_id_fallback, item.get('mansearch')))
    
    Search(item)

elif action == 'list_files':
    link = urllib.unquote_plus(params.get('link', ''))
    trad = urllib.unquote_plus(params.get('trad', 'N/A'))
    ListFiles(link, trad)

elif action == 'play_file':
    link = urllib.unquote_plus(params.get('link', ''))
    PlayFile(link)

elif action == 'setsub':
    link = urllib.unquote_plus(params.get('link', ''))
    trad_name = urllib.unquote_plus(params.get('trad', '')) 
    
    final_sub_path = link
    
    if link.startswith('rar://'):
        try:
            base_filename = os.path.basename(link)
            try: base_filename = urllib.unquote(base_filename)
            except: pass
            dest_file = os.path.join(__temp__, base_filename)
            source_obj = xbmcvfs.File(link, 'rb')
            dest_obj = xbmcvfs.File(dest_file, 'wb')
            content = source_obj.readBytes() if py3 else source_obj.read()
            if not py3 and isinstance(content, unicode): dest_obj.write(content.encode('utf-8'))
            else: dest_obj.write(content)
            source_obj.close()
            dest_obj.close()
            if os.path.exists(dest_file) and os.path.getsize(dest_file) > 0: final_sub_path = dest_file
        except: pass

    if final_sub_path:
        if os.path.exists(final_sub_path):
            folder = os.path.dirname(final_sub_path)
            filename = os.path.basename(final_sub_path)
            name, ext = os.path.splitext(filename)
            if not '.ro.' in filename.lower() and not name.lower().endswith('.ro'):
                new_filename = "%s.ro%s" % (name, ext)
                new_path = os.path.join(folder, new_filename)
                try:
                    os.rename(final_sub_path, new_path)
                    final_sub_path = new_path
                except: pass

        display_name = os.path.basename(final_sub_path)
        listitem = xbmcgui.ListItem(label="Romanian", label2=display_name)
        listitem.setArt({'icon': "5", 'thumb': 'ro'})
        listitem.setProperty("language", 'ro')
        listitem.setProperty("sync", "false")
        
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=final_sub_path, listitem=listitem, isFolder=False)
        
        def set_sub_delayed():
            time.sleep(1.0)
            xbmc.Player().setSubtitles(final_sub_path)
            
            msg = "Subtitrare aplicata! [B][COLOR FF00BFFF] '%s'[/COLOR][/B]" % trad_name
            xbmcgui.Dialog().notification(__scriptname__, msg, xbmcgui.NOTIFICATION_INFO, 3000)

        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))