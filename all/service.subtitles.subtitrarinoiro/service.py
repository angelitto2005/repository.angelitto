# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import unicodedata
import shutil
import binascii
import traceback
import platform

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
import zipfile

__addon__ = xbmcaddon.Addon()
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')

if py3:
    xpath = xbmcvfs.translatePath
    quote = urllib.quote
else:
    xpath = xbmc.translatePath
    quote = urllib.quote

__cwd__        = xpath(__addon__.getAddonInfo('path')) if py3 else xpath(__addon__.getAddonInfo('path')).decode("utf-8")
__profile__    = xpath(__addon__.getAddonInfo('profile')) if py3 else xpath(__addon__.getAddonInfo('profile')).decode("utf-8")
__resource__   = xpath(os.path.join(__cwd__, 'resources', 'lib')) if py3 else xpath(os.path.join(__cwd__, 'resources', 'lib')).decode("utf-8")
__temp__       = xpath(os.path.join(__profile__, 'temp', ''))

BASE_URL = "https://www.subtitrari-noi.ro/"

sys.path.append (__resource__)
import requests
from bs4 import BeautifulSoup
import PTN

try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass

def log(msg):
    if __addon__.getSetting('debug_log') != 'true':
        return

    log_level = xbmc.LOGINFO if py3 else xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s] - %s" % (__scriptid__, str(msg)), level=log_level)
    except Exception: pass

def get_file_signature(file_path):
    try:
        with open(file_path, 'rb') as f:
            header = f.read(7)
        hex_header = binascii.hexlify(header).decode('utf-8').upper()
        
        log("[SIGNATURE] Header: %s" % hex_header)
        if hex_header.startswith('52617221'): 
            return 'rar'
        if hex_header.startswith('504B'): 
            return 'zip'
        return 'unknown'
    except Exception as e:
        log("[SIGNATURE] Error reading header: %s" % str(e))
        return 'error'

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2: return "%%%%%"
    try:
        season, epnr = int(parts[0]), int(parts[1])
        patterns = []
        
        # 1. Format Standard (S01E01, s1e1)
        patterns.append(r"[Ss]%02d[Ee]%02d" % (season, epnr))
        patterns.append(r"[Ss]%d[Ee]%d" % (season, epnr))
        
        # 2. Format cu Separator (S01.E01, S01-E01, S01 E01)
        patterns.append(r"[Ss]%02d[._\-\s]+[Ee]%02d" % (season, epnr))
        patterns.append(r"[Ss]%d[._\-\s]+[Ee]%d" % (season, epnr))

        # 3. Format X (1x01, 01x01)
        patterns.append(r"%dx%02d" % (season, epnr))
        patterns.append(r"%02dx%02d" % (season, epnr))
        
        # 4. Format Romanesc (Sezonul 1 ... Episodul 1)
        patterns.append(r"sez.*?%d.*?ep.*?%d" % (season, epnr))

        return '(?:%s)' % '|'.join(patterns)
    except:
        return "%%%%%"

def scan_archive_windows(archive_physical_path, archive_type):
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
        log("[WINDOWS VFS] Scanez radacina: %s" % root_vfs_path)
        
        def recursive_scan(current_vfs_path):
            found_subs = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                
                for file_name in files:
                    if not py3 and isinstance(file_name, bytes):
                        file_name = file_name.decode('utf-8')

                    if os.path.splitext(file_name)[1].lower() in subtitle_exts:
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
                log("[WINDOWS VFS] Eroare in recursivitate la %s: %s" % (current_vfs_path, str(e)))

            return found_subs

        all_files_vfs = recursive_scan(root_vfs_path)
        log("[WINDOWS VFS] Total fisiere gasite: %d" % len(all_files_vfs))
        return all_files_vfs

    except Exception as e:
        log("[WINDOWS VFS] Eroare fatala scanare: %s" % e)
        return []

def extract_archive_android(archive_physical_path, dest_path):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    extracted_files = []
    
    try:
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)

        normalized_archive_path = archive_physical_path.replace('\\', '/')
        if not normalized_archive_path.startswith('/'):
            normalized_archive_path = '/' + normalized_archive_path
        
        if py3: quoted_path = urllib.quote(normalized_archive_path, safe='')
        else: quoted_path = urllib.quote(str(normalized_archive_path), safe='')

        root_vfs_path = 'rar://%s/' % quoted_path
        log("[ANDROID OLD] Extragere totala din: %s" % root_vfs_path)

        def recursive_extract_copy(current_vfs_path):
            found = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                for f in files:
                    f_name = f
                    if not py3 and isinstance(f, str): f_name = f.decode('utf-8', 'ignore')
                    
                    if os.path.splitext(f_name)[1].lower() in subtitle_exts:
                        if current_vfs_path.endswith('/'): src = current_vfs_path + f
                        else: src = current_vfs_path + '/' + f
                        
                        dst = os.path.join(dest_path, f_name)
                        
                        if xbmcvfs.copy(src, dst):
                            found.append(dst)
                
                for d in dirs:
                    d_name = d
                    if not py3 and isinstance(d, str): d_name = d.decode('utf-8', 'ignore')
                    if current_vfs_path.endswith('/'): next_url = current_vfs_path + d + '/'
                    else: next_url = current_vfs_path + '/' + d + '/'
                    found.extend(recursive_extract_copy(next_url))
            except Exception as e:
                log("[ANDROID OLD] Eroare loop: %s" % str(e))
            return found

        extracted_files = recursive_extract_copy(root_vfs_path)
        log("[ANDROID OLD] Fisiere extrase fizic: %d" % len(extracted_files))
        return extracted_files

    except Exception as e:
        log("[ANDROID OLD] Eroare generala extragere: %s" % e)
        return []

def cleanup_temp_directory(temp_dir):
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir)
    except Exception as e:
        log("EROARE la curatarea directorului temporar: %s" % str(e))

def Search(item):
    log(">>>>>>>>>> PORNIRE CĂUTARE SUBTITRARE (SUBTITRARI-NOI.RO) <<<<<<<<<<")
    
    temp_dir = __temp__
    cleanup_temp_directory(temp_dir)

    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    s.headers.update({'User-Agent': ua, 'Referer': BASE_URL})

    try:
        s.get(BASE_URL, verify=False, timeout=15)
    except: pass
    
    subtitles_found = searchsubtitles(item, s)
    
    if not subtitles_found:
        return

    sel = 0
    if len(subtitles_found) > 1:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in subtitles_found]
        sel = dialog.select("Selectati subtitrarea", titles)
    
    if sel >= 0:
        selected_sub_info = subtitles_found[sel]
        link = selected_sub_info["ZipDownloadLink"]
        
        log("Descarc arhiva: %s" % link)
        try:
            response = s.get(link, verify=False, timeout=15)
        except:
            xbmcgui.Dialog().ok("Eroare", "Conexiune esuata la descarcare.")
            return
        
        if len(response.content) < 100:
            xbmcgui.Dialog().ok("Eroare", "Serverul a returnat un fisier invalid.")
            return

        timestamp = str(int(time.time()))
        temp_file_dat = os.path.join(temp_dir, "sub_%s.dat" % timestamp)
        
        try:
            with open(temp_file_dat, 'wb') as f:
                f.write(response.content)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            log("EROARE scriere disc: %s" % e)
            return
        
        real_type = get_file_signature(temp_file_dat)
        if real_type == 'unknown': real_type = 'zip' 
        
        final_ext = 'rar' if real_type == 'rar' else 'zip'
        fname = os.path.join(temp_dir, "subtitle_%s.%s" % (timestamp, final_ext))
        
        try:
            if os.path.exists(fname): os.remove(fname)
            shutil.move(temp_file_dat, fname)
            log("Fisier redenumit in: %s" % fname)
            time.sleep(0.5)
        except Exception as e:
            log("EROARE redenumire: %s" % e)
            return

        all_files = []
        extractPath = os.path.join(temp_dir, "Extracted")

        if real_type == 'zip':
            subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
            try:
                if not os.path.exists(extractPath):
                    os.makedirs(extractPath)
                    
                with zipfile.ZipFile(fname, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        if os.path.splitext(member)[1].lower() in subtitle_exts:
                            target_name = os.path.basename(member)
                            if not target_name: continue # E un folder
                            
                            target_path = os.path.join(extractPath, target_name)
                            
                            try:
                                source = zip_ref.open(member)
                                with open(target_path, "wb") as target:
                                    shutil.copyfileobj(source, target)
                                all_files.append(target_path)
                            except Exception as e:
                                log("Eroare la extragere fisier din zip: %s" % str(e))
                                
            except Exception as e:
                log("[ZIP] Eroare generala: %s" % e)

        elif real_type == 'rar':
            if not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
                xbmcgui.Dialog().ok("Componenta lipsa", "Instalati 'RAR archive support'.")
                return

            if xbmc.getCondVisibility('System.Platform.Android'):
                all_files = extract_archive_android(fname, extractPath)
            else:
                all_files = scan_archive_windows(fname, 'rar')
        
        if not all_files:
            xbmcgui.Dialog().ok("Eroare", "Nu s-au gasit fisiere de subtitrare in arhiva.")
            return
        
        log("S-au gasit %d fisiere." % len(all_files))

        subs_list = []
        season, episode = item.get("season"), item.get("episode")
        
        if episode and season and season != "0" and episode != "0":
            epstr = '%s:%s' % (season, episode)
            episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
            
            for sub_file in all_files:
                check_name = sub_file
                if sub_file.startswith('rar://'):
                    try: check_name = urllib.unquote(sub_file)
                    except: pass
                
                base_name = os.path.basename(check_name.replace('\\', '/'))
                
                if episode_regex.search(base_name):
                    subs_list.append(sub_file)

            if subs_list:
                log("Filtrat %d subtitrari pentru episod." % len(subs_list))
                all_files = sorted(subs_list, key=lambda f: natural_key(os.path.basename(f)))
            else:
                log("Nicio subtitrare gasita specific pentru S%sE%s. Se afiseaza tot." % (season, episode))
                all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))
        else:
            all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

        for sub_file in all_files:
            basename = os.path.basename(sub_file)
            if sub_file.startswith('rar://'):
                try: basename = urllib.unquote(basename)
                except: pass
            
            basename = normalizeString(basename)
            
            lang_code = 'ro'
            
            # --- MODIFICARE AICI ---
            # 1. Extragem traducatorul din dictionarul selected_sub_info
            traducator_name = selected_sub_info.get("Traducator", "N/A")
            if not traducator_name: traducator_name = "N/A"
            
            # 2. Il punem in parametrul 'label' (care apare sub steag)
            listitem = xbmcgui.ListItem(label=traducator_name, label2=basename)
            
            listitem.setArt({'icon': "5", 'thumb': lang_code})
            listitem.setProperty("language", lang_code)
            listitem.setProperty("sync", "false")
            
            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(sub_file))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def get_title_variations(title):
    """
    Genereaza variatii ale titlului.
    Include logica pentru '&', 'and', spargerea titlurilor compuse si trunchierea dupa numar/part/chapter.
    """
    variations = []
    
    # Eliminam spatiile multiple
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

    # 5. LOGICA "PART" / "VOL" / "CHAPTER"
    match_part = re.search(r'(?i)\b(part|vol|chapter)\b', clean_base)
    if match_part:
        short_title = clean_base[:match_part.start()].strip()
        if len(short_title) > 3:
            variations.append(short_title)

    # 6. Cifre <-> Cuvinte
    num_map = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        '10': 'ten'
    }
    rev_map = {v: k for k, v in num_map.items()}

    words = clean_base.split()
    
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

    # 7. STRATEGIE: SEGMENTARE (FIRST / LAST WORDS)
    # Vital pentru titluri lungi fara semne (Mission Impossible, John Wick)
    if len(words) >= 3:
        first_two = words[:2]
        # Daca al doilea cuvant e "and", luam doar primul
        if first_two[1].lower() == 'and':
             variations.append(first_two[0])
        else:
             variations.append(" ".join(first_two))

    if len(words) >= 4:
        last_three = " ".join(words[-3:])
        variations.append(last_three)
        
        last_four = " ".join(words[-4:])
        variations.append(last_four)

    # Eliminam duplicatele pastrand ordinea
    seen = set()
    final_variations = []
    for v in variations:
        v_low = v.lower()
        if v_low not in seen and len(v_low) > 2: # Minim 3 litere pt o cautare valida
            seen.add(v_low)
            final_variations.append(v)
            
    return final_variations

def searchsubtitles(item, session):
    search_year = None
    final_search_string = None
    searched_title_for_sort = ""
    
    if item.get('mansearch'):
        log("--- CAUTARE MANUALA ACTIVA ---")
        search_string_raw = urllib.unquote(item.get('mansearchstr', ''))
        final_search_string = search_string_raw.strip()
        searched_title_for_sort = final_search_string
    else:
        log("--- CAUTARE AUTOMATA ACTIVA ---")
        
        search_year = xbmc.getInfoLabel("VideoPlayer.Year")
        
        def is_latin_title(t):
            if not t: return False
            return bool(re.search(r'[a-zA-Z]', t))

        candidates = []
        candidates.append(xbmc.getInfoLabel("VideoPlayer.TVShowTitle"))
        candidates.append(xbmc.getInfoLabel("VideoPlayer.Title"))
        candidates.append(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))
        
        path = item.get('file_original_path', '')
        if path and not path.startswith('http'):
            candidates.append(os.path.basename(path))
        else:
            candidates.append(item.get('title', ''))

        search_string_raw = ""
        for cand in candidates:
            clean_cand = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', cand or "", flags=re.IGNORECASE).strip()
            if clean_cand and clean_cand.lower() != 'play' and not clean_cand.isdigit() and is_latin_title(clean_cand):
                search_string_raw = clean_cand
                log("Titlu selectat (Latin): '%s'" % search_string_raw)
                break
        
        if not search_string_raw: return None

        # --- EXTRAGERE AN DIN TITLU DACA LIPSESTE ---
        if not search_year or not search_year.isdigit():
            match_year = re.search(r'\b(19|20)\d{2}\b', search_string_raw)
            if match_year:
                search_year = match_year.group(0)
                log("Am extras anul din titlu: %s" % search_year)

        s = search_string_raw
        s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) 
        s = re.sub(r'\b(19|20)\d{2}\b', '', s)
        s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s)
        s = re.sub(r'(?i)\bsez.*?$', '', s)
        s = re.sub(r'\.(mkv|avi|mp4|mov)$', '', s, flags=re.IGNORECASE)
        s = s.replace('.', ' ')
        s = re.sub(r'[\(\[\)\]]', '', s)
        
        # --- FIX: ELIMINARE STUDIOURI SI CUVINTE UMPLUTURA (SAFE MODE) ---
        spam_words = [
            'Marvel Studios', 'Walt Disney', 'Disney+', 'Pixar Animation', 
            'Sony Pictures', 'Warner Bros', '20th Century Fox', 'Universal Pictures',
            'Netflix', 'Amazon Prime', 'Hulu Original', 'Apple TV+',
            'internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb', 'hdtv',
            'web-dl', 'bluray', 'repack', 'remastered', 'extended cut', 
            'unrated', 'director\'s cut', 'Tyler Perry\'s', 'Madea\'s', 'Zack Snyder\'s'
        ]
        
        for word in spam_words:
            s = re.sub(r'\b' + re.escape(word) + r'\b', '', s, flags=re.IGNORECASE)
        
        final_search_string = ' '.join(s.split())
        searched_title_for_sort = final_search_string

    if not final_search_string: return None

    req_season = 0
    if item.get('season') and str(item.get('season')).isdigit():
        req_season = int(item.get('season'))

    search_candidates = get_title_variations(final_search_string)
    all_subtitles = []
    
    for candidate in search_candidates:
        log("Încerc căutare cu: '%s' | Filtru An: %s" % (candidate, str(search_year)))
        
        found_for_candidate = False
        
        for page_num in range(1, 4):
            html_content = fetch_subtitles_page(candidate, session, page_num)
            
            if not html_content or len(html_content) < 100:
                break

            subs_on_page = parse_results(html_content, searched_title_for_sort, req_season, search_year)
            
            if subs_on_page:
                log("Gasit %d rezultate pe pagina %d pentru '%s'." % (len(subs_on_page), page_num, candidate))
                all_subtitles.extend(subs_on_page)
                found_for_candidate = True
            else:
                if "content-main" not in html_content:
                    break
        
        if found_for_candidate:
            break

    unique_subs = []
    seen_links = set()
    for sub in all_subtitles:
        if sub['ZipDownloadLink'] not in seen_links:
            seen_links.add(sub['ZipDownloadLink'])
            unique_subs.append(sub)
            
    return unique_subs

def fetch_subtitles_page(search_string, session, page_num=1):
    search_url = BASE_URL + "paginare_filme.php"
    data = {
        'search_q': '1', 'cautare': search_string, 'tip': '2',
        'an': 'Toti anii', 'gen': 'Toate', 'page_nr': str(page_num)
    }
    headers = {
        'accept': 'text/html, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': BASE_URL.rstrip('/')
    }
    try:
        response = session.post(search_url, headers=headers, data=data, verify=False, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        log("EROARE conectare site (pg %d): %s" % (page_num, e))
        return None

def parse_results(html_content, searched_title, req_season=0, search_year=None):
    import difflib
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html_content, 'html.parser')
    results_html = soup.find_all('div', id='round')
    
    subtitles = []
    for res_div in results_html:
        try:
            main_content = res_div.find('div', id='content-main')
            right_content = res_div.find('div', id='content-right')
            # Descrierea e in urmatorul div, bold
            release_info_div = res_div.find_next_sibling('div', style=re.compile(r'font-weight:bold'))
            
            if not main_content or not right_content: continue

            nume = main_content.find('a').get_text(strip=True) if main_content.find('a') else 'N/A'
            traducator = 'N/A'
            # FIX: string=...
            trad_raw = main_content.find(string=re.compile(r'Traducator:'))
            if trad_raw: traducator = trad_raw.replace('Traducator:', '').strip()
            
            descriere = release_info_div.get_text(strip=True) if release_info_div else ''
            
            # --- CURATARE AGRESIVA PENTRU UN SINGUR RAND ---
            # Eliminam caracterele de linie noua si spatiile multiple
            nume = nume.replace('\n', ' ').replace('\r', ' ')
            nume = ' '.join(nume.split())
            
            descriere = descriere.replace('\n', ' ').replace('\r', ' ')
            descriere = ' '.join(descriere.split())
            
            # Optional: Taiem descrierea daca e extrem de lunga (peste 100 caractere) ca sa nu forteze wrap in skin
            if len(descriere) > 120:
                descriere = descriere[:117] + "..."

            full_text_lower = (nume + " " + descriere).lower()

            # --- FILTRARE AN CU TOLERANTA +/- 1 ---
            if search_year:
                # Cautam an in textul complet
                found_years_str = re.findall(r'\b(19\d{2}|20\d{2})\b', full_text_lower)
                found_years_int = [int(y) for y in found_years_str]
                
                if found_years_int:
                    try:
                        req_y_int = int(search_year)
                        match_found = False
                        # Toleranta +/- 1 an
                        for fy in found_years_int:
                            if abs(fy - req_y_int) <= 1:
                                match_found = True
                                break
                        if not match_found:
                            continue
                    except: pass 

            # --- FILTRARE TITLU ---
            clean_nume = re.sub(r'\(\d{4}\)', '', nume).strip()
            clean_nume = re.sub(r'[-–:;]', ' ', clean_nume).strip()
            clean_nume = ' '.join(clean_nume.split()).lower()
            
            clean_search = re.sub(r'[-–:;]', ' ', searched_title).strip()
            clean_search = ' '.join(clean_search.split()).lower()

            t_gasit = clean_nume
            t_cautat = clean_search

            if req_season == 0:
                # FILM
                if re.search(r'(?i)\b(sezonul|sez|season|episodul|episode|s\d{1,2}|ep\d{1,2})\b', full_text_lower):
                    continue

                ratio = difflib.SequenceMatcher(None, t_cautat, t_gasit).ratio()
                starts_with = t_gasit.startswith(t_cautat) or t_cautat.startswith(t_gasit)
                
                # Check sufix
                if t_cautat in t_gasit or t_gasit in t_cautat:
                    starts_with = True

                # REGULA CUVINTE
                if ratio < 0.85:
                    words_cautat = t_cautat.split()
                    words_gasit = t_gasit.split()
                    
                    blacklist_words = ['the', 'of', 'in', 'on', 'at', 'to', 'a', 'an']
                    significant_words = [w for w in words_cautat if len(w) > 2 or w not in blacklist_words]
                    
                    if significant_words:
                        found_all_words = True
                        for w in significant_words:
                            # Cautam cuvantul chiar si partial (substring)
                            if not any(w in wg for wg in words_gasit):
                                found_all_words = False
                                break
                        
                        if not found_all_words:
                            continue

                if ratio < 0.6 and not starts_with: 
                    continue

            else:
                # SERIAL
                ratio = difflib.SequenceMatcher(None, t_cautat, t_gasit).ratio()
                if ratio < 0.6: 
                    continue

                season_pattern = r'(?:sezonul|sez|season|s)[\s\.]*0*(\d+)\b'
                found_seasons = re.findall(season_pattern, full_text_lower)
                range_match = re.search(r'(?:sezoanele|seasons)[\s]*(\d+)[\s]*[-][\s]*(\d+)', full_text_lower)
                
                is_valid_season = False
                if found_seasons:
                    found_seasons_ints = [int(s) for s in found_seasons]
                    if req_season in found_seasons_ints:
                        is_valid_season = True
                
                if range_match:
                    s_start = int(range_match.group(1))
                    s_end = int(range_match.group(2))
                    if s_start <= req_season <= s_end:
                        is_valid_season = True
                
                if not is_valid_season:
                    continue

            download_tag = right_content.find('a', href=re.compile(r'\.zip$|\.rar$'))
            if not download_tag: continue
            
            legatura = download_tag['href']
            if not legatura.startswith('http'): legatura = BASE_URL + legatura.lstrip('/')

            # Format Afisare - fortat pe o singura linie
            display_name = u'[B]%s[/B] | Trad: [B][COLOR FF00FA9A]%s[/COLOR][/B] | %s' % (nume, traducator, descriere)
            
            subtitles.append({
                'SubFileName': display_name,
                'ZipDownloadLink': legatura,
                'Traducator': traducator,
                'OriginalMovieTitle': nume
            })
        except: continue
            
    if subtitles:
        subtitles.sort(key=lambda sub: (
            -difflib.SequenceMatcher(None, searched_title.lower(), sub['OriginalMovieTitle'].lower()).ratio(),
            natural_key(sub['SubFileName'])
        ))
    return subtitles

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
handle = int(sys.argv[1])
action = params.get('action')

if action in ('search', 'manualsearch'):
    file_original_path = xbmc.Player().getPlayingFile() if py3 else xbmc.Player().getPlayingFile().decode('utf-8')
    season = str(xbmc.getInfoLabel("VideoPlayer.Season"))
    episode = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    
    if not season or season == "0" or not episode or episode == "0":
        parsed_data = PTN.parse(os.path.basename(file_original_path))
        if (not season or season == "0") and 'season' in parsed_data: season = str(parsed_data['season'])
        if (not episode or episode == "0") and 'episode' in parsed_data: episode = str(parsed_data['episode'])
            
    item = {
        'mansearch': action == 'manualsearch',
        'file_original_path': file_original_path,
        'title': normalizeString(xbmc.getInfoLabel("VideoPlayer.Title")),
        'season': season, 
        'episode': episode
    }
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    
    Search(item)
    xbmcplugin.endOfDirectory(handle)

elif action == 'setsub':
    link = urllib.unquote_plus(params.get('link', ''))
    final_sub_path = link 

    if link.startswith('rar://'):
        try:
            base_filename = os.path.basename(link)
            try: base_filename = urllib.unquote(base_filename)
            except: pass
            
            dest_file = os.path.join(__temp__, base_filename)
            log("[SETSUB] Extrag manual din RAR: %s" % link)
            
            source_obj = xbmcvfs.File(link, 'rb')
            dest_obj = xbmcvfs.File(dest_file, 'wb')
            
            content = source_obj.readBytes() if py3 else source_obj.read()
            
            if not py3 and isinstance(content, unicode):
                dest_obj.write(content.encode('utf-8'))
            else:
                dest_obj.write(content)
                
            source_obj.close()
            dest_obj.close()
            
            if os.path.exists(dest_file) and os.path.getsize(dest_file) > 0:
                final_sub_path = dest_file
                log("[SETSUB] Extragere reusita.")
            else:
                log("[SETSUB] Eroare: Fisier gol.")
        except Exception as e:
            log("[SETSUB] Eroare critica: %s" % str(e))
            traceback.print_exc()

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
                    log("Fisier redenumit: %s" % final_sub_path)
                except Exception as e:
                    log("Eroare redenumire: %s" % str(e))

        listitem = xbmcgui.ListItem(label=os.path.basename(final_sub_path))
        xbmcplugin.addDirectoryItem(handle=handle, url=final_sub_path, listitem=listitem, isFolder=False)
        
        def set_sub_delayed():
            time.sleep(1.0)
            xbmc.Player().setSubtitles(final_sub_path)

        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(handle)