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
        # Detectare HTML (Eroare server/Protectie)
        # 3C21444F = <!DO | 3C68746D = <htm
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
        patterns = [ "s%#02de%#02d" % (season, epnr), "%#02dx%#02d" % (season, epnr), "%#01de%#02d" % (season, epnr) ]
        if season < 10: patterns.append("(?:\A|\D)%dx%#02d" % (season, epnr))
        return '(?:%s)' % '|'.join(patterns)
    except:
        return "%%%%%"

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

def get_best_subtitle_match(video_filename, subtitle_files):
    """
    Algoritm avansat de matching:
    1. Tip Sursa (BluRay/WEB/HDTV) - Prioritate CRITICA (+100/-100)
    2. Release Group (FLUX, SPARKS, etc) - Prioritate MARE (+50)
    3. Rezolutie/Limba/Cuvinte comune - Prioritate MICA
    """
    if not subtitle_files: return None
    if len(subtitle_files) == 1: return subtitle_files[0]

    # --- 1. PREGATIRE DATA VIDEO ---
    video_base = os.path.basename(video_filename).lower()
    
    # a) Identificare Tip Sursa Video
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

    # b) Identificare Release Group Video (dupa ultimul "-")
    # Ex: Film...-FLUX.mkv -> flux
    video_release_group = None
    # Cautam ultimul segment dupa "-" inainte de extensie
    match_group = re.search(r'-([a-zA-Z0-9]+)(?:\.[a-z0-9]{2,4})?$', os.path.basename(video_filename))
    if match_group:
        potential_group = match_group.group(1).lower()
        # Filtram chestii care nu sunt grupuri (codecuri, ani, surse)
        ignore_tags = ['x264', 'x265', 'h264', 'h265', 'hevc', '1080p', '2160p', '720p', 'web', 'bluray', 'hdtv', 'ac3', 'aac', 'ro', 'eng']
        if potential_group not in ignore_tags and len(potential_group) > 2:
            video_release_group = potential_group

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
        
        # A. SCOR SURSA (+100 / -100)
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
        
        # B. SCOR RELEASE GROUP (+50)
        # Daca am gasit un grup in video (ex: FLUX) si el exista si in numele srt-ului
        if video_release_group and video_release_group in sub_name:
            score += 50
            # log(__name__, "   -> Bonus Grup (%s) pentru: %s" % (video_release_group, sub_name))

        # C. SCOR TOKEN-URI COMUNE (1 punct per cuvant)
        common_tokens = video_tokens.intersection(sub_tokens)
        score += len(common_tokens)
        
        # D. BONUSURI SECUNDARE
        if '2160p' in video_base and '2160p' in sub_name: score += 10
        if '1080p' in video_base and '1080p' in sub_name: score += 10
        if 'ro' in sub_name or 'rum' in sub_name: score += 5 

        # log(__name__, "   -> Sub: %s | Scor: %d" % (sub_name, score))

        if score > best_score:
            best_score = score
            best_match = sub_path

    log(__name__, "[MATCH] Castigator: %s (Scor: %d)" % (os.path.basename(best_match), best_score))
    return best_match

def Search(item):
    
    # Curatare temp la start
    if os.path.exists(__temp__):
        try: shutil.rmtree(__temp__, ignore_errors=True)
        except: pass
    try: os.makedirs(__temp__)
    except: pass
    
    # 1. Determinare Mod Rulare
    try: handle = int(sys.argv[1])
    except: handle = -1
    is_auto_download = __addon__.getSetting('auto_download') == 'true'

    # 2. Cautare pe site
    filtered_subs, raw_count = searchsubtitles(item)
    
    # Fallback la manual daca nu gaseste niciun rezultat pe site
    if not filtered_subs:
        if handle == -1:
            log(__name__, "[AUTO] Nu s-au gasit rezultate pe site. Se deschide cautarea manuala.")
            xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
        else:
            log(__name__, "[MANUAL] Nu s-au gasit subtitrari.")
        return

    # 3. Deduplicare rezultate
    unique_subs = []
    seen_links = set()
    for sub in filtered_subs:
        link = sub["ZipDownloadLink"]
        if link not in seen_links:
            seen_links.add(link)
            unique_subs.append(sub)
    
    filtered_subs = unique_subs
    
    # Sortare rezultate
    priority_list = ['subrip', 'retail', 'retailsubs', 'netflix', 'hbo', 'amazon', 'disney', 'itunes']
    def priority_sort_key(sub_item):
        trad = sub_item.get('Traducator', '').lower()
        is_priority = any(p in trad for p in priority_list)
        return (not is_priority)
    filtered_subs.sort(key=priority_sort_key)
    
    # --- LOGGING DETALIAT ---
    log(__name__, "--- [DEBUG] LISTA ARHIVE GASITE (%d) ---" % len(filtered_subs))
    for idx, sub in enumerate(filtered_subs):
        clean_name = sub['SubFileName'].replace('[B]', '').replace('[/B]', '').replace('[COLOR FFFDBD01]', '').replace('[/COLOR]', '')
        log(__name__, "Candidat #%d: %s | Trad: %s" % (idx, clean_name, sub.get('Traducator', 'N/A')))
    log(__name__, "---------------------------------------------")

    # =========================================================================
    #                    LOGICA AUTO-DOWNLOAD (LOOP CU CURATARE)
    # =========================================================================
    
    # Ruleaza doar daca suntem in Background (handle -1) SI Auto-Download este ACTIVAT
    if handle == -1 and is_auto_download:
        log(__name__, "[AUTO] Mod Auto activ. Se verifica arhivele la rand...")
        
        for idx, candidate in enumerate(filtered_subs):
            link = candidate["ZipDownloadLink"]
            log(__name__, "[AUTO] Verific arhiva #%d: %s" % (idx, candidate['SubFileName']))
            
            # --- Descarcare ---
            s = requests.Session()
            s.headers.update({'Referer': BASE_URL})
            try:
                response = s.get(link, verify=False)
            except Exception as e:
                continue

            timestamp = str(int(time.time()))
            temp_file_name = "sub_%s_%d.dat" % (timestamp, idx)
            raw_path = os.path.join(__temp__, temp_file_name)
            
            try:
                with open(raw_path, 'wb') as f: 
                    f.write(response.content)
                    f.flush()
                    os.fsync(f.fileno())
            except: continue
            
            # --- Identificare tip (Nou: detectie HTML) ---
            real_type = get_file_signature(raw_path)
            
            if real_type == 'html':
                log(__name__, "[AUTO] Eroare: Serverul a returnat HTML (posibil protecție). Sar peste arhiva.")
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

            # --- Extragere / Scanare fisiere ---
            all_files = []
            extract_path = "" 
            
            if real_type == 'rar':
                if xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
                    all_files = scan_archive(raw_path, 'rar')
            elif real_type == 'zip':
                extract_path = os.path.join(__temp__, "Extracted_%d" % idx)
                try:
                    with zipfile.ZipFile(raw_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_path)
                    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
                    for root, dirs, files in os.walk(extract_path):
                        for file in files:
                            if os.path.splitext(file)[1].lower() in subtitle_exts:
                                all_files.append(os.path.join(root, file))
                except: pass

            if not all_files:
                # Arhiva goala -> Stergere si Next
                if os.path.exists(raw_path): os.remove(raw_path)
                if extract_path and os.path.isdir(extract_path): shutil.rmtree(extract_path, ignore_errors=True)
                continue

            # --- Validare Episod ---
            valid_episode_files = []
            if item.get('season') and item.get('episode') and item.get('season') != "0" and item.get('episode') != "0":
                epstr = '%s:%s' % (item['season'], item['episode'])
                episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
                
                for sub_file in all_files:
                    check_name = sub_file
                    if sub_file.startswith('rar://'):
                        try: check_name = urllib.unquote(sub_file)
                        except: pass
                    if episode_regex.search(os.path.basename(check_name)):
                        valid_episode_files.append(sub_file)
                
                # DACA EPISODUL NU E IN ARHIVA:
                if not valid_episode_files:
                    log(__name__, "[AUTO] Arhiva #%d NU contine episodul. STERGERE si incerc urmatoarea..." % idx)
                    if os.path.exists(raw_path): os.remove(raw_path)
                    if extract_path and os.path.isdir(extract_path): shutil.rmtree(extract_path, ignore_errors=True)
                    continue 
                else:
                    all_files = valid_episode_files
            
            # --- SUCCES AUTO ---
            all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))
            best_match = all_files[0]
            if len(all_files) > 1:
                video_file = item.get('file_original_path', '')
                if video_file:
                     match = get_best_subtitle_match(video_file, all_files)
                     if match: best_match = match
            
            final_path_auto = best_match
            # Extragere manuala RAR finala
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
            xbmcgui.Dialog().notification(__scriptname__, "Subtitrare aplicata!", xbmcgui.NOTIFICATION_INFO, 3000)
            sys.exit(0)

        # Daca bucla s-a terminat si nu am iesit, curatam temp
        log(__name__, "[AUTO] Nicio arhiva nu a fost valida. Se curata tot si se comuta pe Manual.")
        if os.path.exists(__temp__):
            try: shutil.rmtree(__temp__, ignore_errors=True)
            except: pass
        try: os.makedirs(__temp__)
        except: pass

    # =========================================================================
    #                    LOGICA MANUAL / SELECTIE (GUI)
    # =========================================================================
    
    # Daca suntem in Background si nu am rezolvat cu Auto, deschidem fereastra
    # Asta va restarta scriptul cu handle valid.
    if handle == -1:
        xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
        return

    # Aici ajungem doar in mod MANUAL (handle >= 0).
    sel = -1
    
    # 1. Selectia Arhivei (Daca sunt mai multe, afisam Dialogul cerut de tine)
    if len(filtered_subs) == 1:
        sel = 0
        log(__name__, "[MANUAL] Un singur rezultat. Se intra automat in arhiva.")
    elif len(filtered_subs) > 1:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in filtered_subs]
        sel = dialog.select("Selectati Arhiva", titles)
    
    if sel == -1:
        return # Utilizatorul a dat Cancel

    # 2. Procesarea Arhivei Selectate
    selected_sub_info = filtered_subs[sel]
    selected_lang_code = selected_sub_info["ISO639"]
    selected_rating = selected_sub_info["SubRating"]
    selected_trad = selected_sub_info.get("Traducator", "N/A")
    link = selected_sub_info["ZipDownloadLink"]
    
    # Descarcare
    s = requests.Session()
    s.headers.update({'Referer': BASE_URL})
    try:
        response = s.get(link, verify=False)
    except Exception as e:
        xbmcgui.Dialog().ok("Eroare", str(e))
        return

    timestamp = str(int(time.time()))
    temp_file_name = "sub_%s.dat" % timestamp
    raw_path = os.path.join(__temp__, temp_file_name)
    try:
        with open(raw_path, 'wb') as f: 
            f.write(response.content)
            f.flush()
            os.fsync(f.fileno())
    except: return
    
    # Identificare si verificare tip
    real_type = get_file_signature(raw_path)
    
    # --- MODIFICARE: Verificare HTML pe manual ---
    if real_type == 'html':
        xbmcgui.Dialog().ok("Eroare Server", "Limitare descărcare sau fișier invalid (HTML).\nAșteptați câteva secunde și încercați din nou.")
        if os.path.exists(raw_path): os.remove(raw_path)
        return
    # ---------------------------------------------

    if real_type == 'unknown': real_type = 'zip'
    final_ext = 'rar' if real_type == 'rar' else 'zip'
    final_rar_name = "sub_%s.%s" % (timestamp, final_ext)
    final_rar_path = os.path.join(__temp__, final_rar_name)
    
    try:
        if os.path.exists(final_rar_path): os.remove(final_rar_path)
        shutil.move(raw_path, final_rar_path)
        raw_path = final_rar_path
        time.sleep(0.5)
    except: return

    # Extragere fisiere din arhiva selectata
    all_files = []
    if real_type == 'rar':
        if not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
            xbmcgui.Dialog().ok("Eroare", "Instalati 'RAR archive support'!")
            return
        all_files = scan_archive(raw_path, 'rar')
    elif real_type == 'zip':
        extract_path = os.path.join(__temp__, "Extracted")
        try:
            with zipfile.ZipFile(raw_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
            for root, dirs, files in os.walk(extract_path):
                for file in files:
                    if os.path.splitext(file)[1].lower() in subtitle_exts:
                        all_files.append(os.path.join(root, file))
        except: pass

    # Filtrare dupa episod (SI PE MANUAL)
    if item.get('season') and item.get('episode') and item.get('season') != "0" and item.get('episode') != "0":
        subs_list = []
        epstr = '%s:%s' % (item['season'], item['episode'])
        episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
        
        for sub_file in all_files:
            check_name = sub_file
            if sub_file.startswith('rar://'):
                try: check_name = urllib.unquote(sub_file)
                except: pass
            if episode_regex.search(os.path.basename(check_name)):
                subs_list.append(sub_file)
        
        if subs_list:
            all_files = subs_list
        else:
            log(__name__, "[MANUAL] Arhiva selectata nu contine episodul. Lista devine goala.")
            all_files = [] 

    if not all_files:
        xbmcgui.Dialog().ok("Info", "Nu s-au găsit subtitrări valide (sau episodul căutat) în această arhivă.")
        return

    all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

    # Afisare Fisiere .SRT in Fereastra Principala
    for ofile in all_files:
        display_name = os.path.basename(ofile)
        if ofile.startswith('rar://'):
            try: display_name = urllib.unquote(display_name)
            except: pass

        listitem = xbmcgui.ListItem(label=selected_trad, label2=display_name)
        listitem.setArt({'icon': selected_rating, 'thumb': selected_lang_code})
        listitem.setProperty("language", selected_lang_code)
        listitem.setProperty("sync", "false") 

        # Aici link-ul este catre fisierul local/extract
        url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(ofile))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def get_title_variations(title):
    variations = []
    
    # Curatam spatiile
    base_title = ' '.join(title.strip().split())
    if not base_title: return []

    # 1. VARIANTA SUPREMA: Titlul Exact
    variations.append(base_title)

    # 2. LOGICA & <-> AND (Bidirectionala)
    if '&' in base_title:
        with_and = base_title.replace('&', 'and')
        variations.append(' '.join(with_and.split()))

    if re.search(r'\band\b', base_title, re.IGNORECASE):
        with_amp = re.sub(r'\band\b', '&', base_title, flags=re.IGNORECASE)
        variations.append(' '.join(with_amp.split()))

    # 3. Varianta Fara Semne
    clean_base = re.sub(r'[:\-\|&]', ' ', base_title).strip()
    clean_base = ' '.join(clean_base.split())
    
    if clean_base.lower() != base_title.lower() and clean_base not in variations:
        variations.append(clean_base)

    # 4. SPLIT LOGIC EXTINS (Include si 'and' ca separator)
    # Aceasta va sparge "Deadpool and Wolverine" in ["Deadpool", "Wolverine"]
    separators_pattern = r'[&:\-]|\band\b'
    if re.search(separators_pattern, base_title, re.IGNORECASE):
        parts = re.split(separators_pattern, base_title, flags=re.IGNORECASE)
        for part in parts:
            p = part.strip()
            # Adaugam partea doar daca e un cuvant relevant (> 3 litere)
            if len(p) > 3 and not p.isdigit():
                variations.append(p)

    # 5. LOGICA SEQUEL (Stree 2 Sarkate... -> Stree 2)
    match_sequel = re.search(r'^(.+?\s\d{1,2})(\s|$)', clean_base)
    if match_sequel:
        short_title = match_sequel.group(1).strip()
        if len(short_title) > 2 and short_title.lower() != clean_base.lower():
            variations.append(short_title)

    # 6. Cifre <-> Cuvinte
    num_map = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        '10': 'ten'
    }
    rev_map = {v: k for k, v in num_map.items()}

    words = clean_base.split()
    
    # Cifre in Cuvinte
    new_words_to_text = []
    changed_to_text = False
    for w in words:
        if w.lower() in num_map:
            new_words_to_text.append(num_map[w.lower()])
            changed_to_text = True
        else:
            new_words_to_text.append(w)
    if changed_to_text:
        variations.append(" ".join(new_words_to_text))

    # Cuvinte in Cifre
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

    # Eliminam duplicatele pastrand ordinea
    seen = set()
    final_variations = []
    for v in variations:
        v_low = v.lower()
        if v_low not in seen and len(v_low) > 2:
            seen.add(v_low)
            final_variations.append(v)
            
    return final_variations

def searchsubtitles(item):
    log(__name__, ">>>>>>>>>> PORNIRE CĂUTARE SUBTITRARE (SUBS.RO) <<<<<<<<<<")
    
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,ro;q=0.8', 'Origin': BASE_URL.rstrip('/'), 'Referer': BASE_URL + 'cautare'
    })
    
    languages_to_keep = item.get('languages', [])
    req_season = item.get('season', '0')
    search_year = xbmc.getInfoLabel("VideoPlayer.Year")

    # --- ETAPA 1: CAUTARE DUPA ID ---
    tmdb_id = xbmc.getInfoLabel("VideoPlayer.TVShow.TMDbId") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    if tmdb_id and tmdb_id.isdigit():
        log(__name__, "Incerc cautare dupa TMDb ID: %s" % tmdb_id)
        post_data = {'type': 'subtitrari', 'external_id': tmdb_id}
        html_content = fetch_subtitles_page(sess, post_data)
        if html_content:
            results, count = parse_results(html_content, languages_to_keep, req_season, search_year)
            if results:
                log(__name__, "Gasit %d rezultate dupa TMDb ID." % len(results))
                return results, count

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
    if imdb_id and imdb_id.startswith('tt'):
        imdb_id_numeric = imdb_id.replace("tt", "")
        log(__name__, "Incerc cautare dupa IMDb ID: %s" % imdb_id_numeric)
        post_data = {'type': 'subtitrari', 'external_id': imdb_id_numeric}
        html_content = fetch_subtitles_page(sess, post_data)
        if html_content:
            results, count = parse_results(html_content, languages_to_keep, req_season, search_year)
            if results:
                log(__name__, "Gasit %d rezultate dupa IMDb ID." % len(results))
                return results, count

    # --- ETAPA 2: CAUTARE DUPA TITLU ---
    log(__name__, "Trec la cautare textuala (Fallback)...")
    final_search_string = ""
    
    if item.get('mansearch'):
        log(__name__, "--- CAUTARE MANUALA ACTIVA ---")
        final_search_string = urllib.unquote(item.get('mansearchstr', '')).strip()
    else:
        log(__name__, "--- CAUTARE AUTOMATA ACTIVA ---")
        
        candidates = []
        # Ordinea conteaza: TVShowTitle e de obicei cel mai curat pentru seriale
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
            # Curatam candidatul de tag-uri Kodi [COLOR] etc.
            clean_cand = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', cand or "", flags=re.IGNORECASE).strip()
            
            # --- MODIFICARE: CURATARE AGRESIVA PENTRU SCENE RELEASES ---
            # Daca titlul contine puncte (ex: Tulsa.King.S01), le inlocuim cu spatii
            if '.' in clean_cand:
                clean_cand = clean_cand.replace('.', ' ')
            
            # Daca gasim pattern de sezon (S01, S01E01), taiem tot ce e dupa el
            # Ex: Tulsa King S03 1080p -> Tulsa King
            match_season = re.search(r'(?i)\b(s\d+|sezon|season)', clean_cand)
            if match_season:
                clean_cand = clean_cand[:match_season.start()].strip()
            
            # Daca gasim an, taiem tot ce e dupa el
            match_year = re.search(r'\b(19|20)\d{2}\b', clean_cand)
            if match_year:
                clean_cand = clean_cand[:match_year.start()].strip()

            if clean_cand and len(clean_cand) > 2:
                search_str = clean_cand
                log(__name__, "Titlu selectat (Clean): '%s'" % search_str)
                break
        
        if not search_str: return ([], 0)

        # Mai facem o curatare standard
        s = search_str
        s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) 
        s = re.sub(r'\b(19|20)\d{2}\b', '', s)
        s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s)
        s = re.sub(r'(?i)\bsez.*?$', '', s)
        s = s.replace('.', ' ')
        
        spam_words = [
            'Marvel Studios', 'Walt Disney', 'Disney+', 'Pixar Animation', 
            'Sony Pictures', 'Warner Bros', '20th Century Fox', 'Universal Pictures',
            'Netflix', 'Amazon Prime', 'Hulu Original', 'Apple TV+',
            'internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb', 'hdtv',
            'web-dl', 'bluray', 'repack', 'remastered', 'extended cut', 
            'unrated', 'director\'s cut', 'Tyler Perry\'s', 'Zack Snyder\'s'
        ]
        for word in spam_words:
            s = re.sub(r'\b' + re.escape(word) + r'\b', '', s, flags=re.IGNORECASE)

        final_search_string = ' '.join(s.split())

    if not final_search_string: return ([], 0)

    search_candidates = get_title_variations(final_search_string)
    
    for candidate in search_candidates:
        log(__name__, "Incerc cautare text: '%s'" % candidate)
        post_data = {'type': 'subtitrari', 'titlu-film': candidate}
        
        html_content = fetch_subtitles_page(sess, post_data)
        if not html_content: continue

        results, count = parse_results(html_content, languages_to_keep, req_season, search_year)
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

def parse_results(html_content, languages_to_keep, required_season=None, search_year=None, search_query_title=None):
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

            # --- EXTRAGERE INFORMATII ---
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
                
                if 'Traducător:' in parent_text:
                    traducator = parent_text.replace('Traducător:', '').strip()
                if 'Uploader:' in parent_text:
                    uploader = parent_text.replace('Uploader:', '').strip()
                if 'Limba:' in parent_text:
                    limba_text = parent_text.replace('Limba:', '').strip()

            # --- FILTRARE STRICTA TITLU (FILME) ---
            if is_searching_movie and clean_search_query:
                clean_result_name = clean_for_compare(nume)
                if clean_result_name != clean_search_query:
                    tokens_search = set(clean_search_query.split())
                    tokens_result = set(clean_result_name.split())
                    diff = tokens_result - tokens_search
                    allowed_diffs = {'the', 'a', 'an', 'movie', 'film', 'part', 'vol', 'volume', 'chapter'}
                    if diff and not diff.issubset(allowed_diffs):
                        continue

            # --- FILTRARE FILM vs SERIAL ---
            titlu_lower = nume.lower()
            if is_searching_movie:
                if 'sezon' in titlu_lower or 'season' in titlu_lower or 'series' in titlu_lower:
                    continue

            # --- FILTRARE STRICTA LIMBA ---
            if limba_text != 'N/A':
                if 'română' not in limba_text.lower() and 'romana' not in limba_text.lower():
                    continue
            
            flag_img = row_div.find('img', src=re.compile(r'flag-'))
            if flag_img and 'rom' not in flag_img['src'] and 'rum' not in flag_img['src'] and 'ro.' not in flag_img['src']:
                 continue

            # --- FILTRARE AN (+/- 1 an) ---
            if search_year and an_str and an_str.isdigit():
                try:
                    req_y = int(search_year)
                    res_y = int(an_str)
                    if abs(res_y - req_y) > 1:
                        # Logica speciala pentru seriale care ruleaza multi ani:
                        # Daca e serial, ignoram filtrul de an strict, 
                        # pentru ca "Tulsa King (2022)" poate avea sezon in 2024.
                        if is_searching_movie:
                            continue
                except: pass

            # --- FILTRARE SEZON (SERIALE) ---
            if not is_searching_movie:
                try:
                    curr_s = int(required_season)
                    # log(__name__, "[DEBUG] Verific sezon %s in titlu: %s" % (curr_s, titlu_lower))
                    
                    is_match = False
                    match_range = re.search(r'(?:sez|seas|series)\w*\W*(\d+)\s*-\s*(\d+)', titlu_lower)
                    match_single = re.search(r'(?:sez|seas|series|s)\w*\W*0*(\d+)', titlu_lower)
                    
                    if match_range:
                        s_start, s_end = int(match_range.group(1)), int(match_range.group(2))
                        if s_start <= curr_s <= s_end: is_match = True
                    elif match_single:
                        if int(match_single.group(1)) == curr_s: is_match = True
                    
                    if not is_match:
                        # log(__name__, "[DEBUG] REJECT: Sezon nepotrivit")
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

def natural_key(string_): return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]

def normalizeString(obj):
    if py3: return obj
    try: return unicodedata.normalize('NFKD', unicode(obj, 'utf-8')).encode('ascii', 'ignore')
    except: return unicode(str(obj).encode('string_escape'))

def get_params():
    param = {}
    paramstring = sys.argv[2]
    if len(paramstring) >= 2:
        for pair in paramstring.replace('?', '').split('&'):
            split = pair.split('=')
            if len(split) == 2: param[split[0]] = split[1]
    return param

params = get_params()
action = params.get('action')

if action in ('search', 'manualsearch'):
    # --- FIX: EXTRAGERE MAI ROBUSTA A INFORMATIILOR VIDEO ---
    
    if py3:
        file_original_path = xbmc.Player().getPlayingFile()
    else:
        file_original_path = xbmc.Player().getPlayingFile().decode('utf-8')

    # Preluam info standard din Kodi
    season = str(xbmc.getInfoLabel("VideoPlayer.Season"))
    episode = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    
    # Prioritizam TVShowTitle pentru seriale, altfel OriginalTitle sau Title
    kodi_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    if not kodi_title:
        kodi_title = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")

    # --- FALLBACK PENTRU ELEMENTUM / TORENTI ---
    # Daca Kodi nu stie sezonul, incercam sa-l scoatem din nume fisier
    if not season or season == "0" or not episode or episode == "0":
        # Regex simplu SxxExx
        match_se = re.search(r'(?i)[sS](\d{1,2})[eE](\d{1,2})', os.path.basename(file_original_path))
        if match_se:
            if not season or season == "0": season = str(int(match_se.group(1)))
            if not episode or episode == "0": episode = str(int(match_se.group(2)))
            
            # Daca am gasit SxxExx, inseamna ca e serial.
            # Daca titlul curent (kodi_title) pare a fi titlul episodului (nu contine numele serialului),
            # incercam sa curatam numele fisierului pentru a obtine titlul serialului.
            # Ex: Tulsa.King.S03E01... -> Tulsa King
            
            # Curatam numele fisierului pana la Sxx
            clean_name = os.path.basename(file_original_path)
            match_season_pos = re.search(r'(?i)\b(s\d+|sezon|season)', clean_name)
            if match_season_pos:
                clean_name = clean_name[:match_season_pos.start()].replace('.', ' ').strip()
                # Daca titlul curat e mai relevant decat ce zice Kodi (care zice "Blood and Bourbon"), il folosim
                if clean_name and len(clean_name) > 2:
                    kodi_title = clean_name

    # Construim item-ul pentru cautare
    item = {
        'mansearch': action == 'manualsearch',
        'file_original_path': file_original_path,
        'title': normalizeString(kodi_title),
        'season': season, 
        'episode': episode
    }
    
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    lang_param = urllib.unquote(params.get('languages', ''))
    item['languages'] = [xbmc.convertLanguage(lang, xbmc.ISO_639_1) for lang in lang_param.split(',') if lang]
    
    log(__name__, "Info detectat -> Titlu: %s | Sezon: %s | Episod: %s" % (item['title'], item['season'], item['episode']))
    
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
        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))