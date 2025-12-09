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

def Search(item):
    
    # Curatare temp
    if os.path.exists(__temp__):
        try: shutil.rmtree(__temp__, ignore_errors=True)
        except: pass
    try: os.makedirs(__temp__)
    except: pass
    
    # 1. Cautare
    filtered_subs, raw_count = searchsubtitles(item)
    
    if not filtered_subs:
        return

    # 2. Deduplicare
    unique_subs = []
    seen_links = set()
    for sub in filtered_subs:
        link = sub["ZipDownloadLink"]
        if link not in seen_links:
            seen_links.add(link)
            unique_subs.append(sub)
    
    filtered_subs = unique_subs
    log(__name__, "Rezultate unice ramase dupa deduplicare: %d" % len(filtered_subs))

    # 3. Selectie (Automata sau Manuala)
    sel = -1
    if len(filtered_subs) == 1:
        log(__name__, "Un singur rezultat gasit. Se selecteaza automat.")
        sel = 0
    else:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in filtered_subs]
        sel = dialog.select("Selectati subtitrarea", titles)
    
    if sel >= 0:
        selected_sub_info = filtered_subs[sel]
        link = selected_sub_info["ZipDownloadLink"]
        
        # 4. Descarcare
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
            log(__name__, "Fisier descarcat: %s" % raw_path)
        except Exception as e:
            log(__name__, "Eroare scriere disc: %s" % str(e))
            return
        
        # 5. Identificare tip arhiva
        real_type = get_file_signature(raw_path)
        if real_type == 'unknown': real_type = 'zip'
        
        final_ext = 'rar' if real_type == 'rar' else 'zip'
        final_rar_name = "sub_%s.%s" % (timestamp, final_ext)
        final_rar_path = os.path.join(__temp__, final_rar_name)
        
        try:
            if os.path.exists(final_rar_path): os.remove(final_rar_path)
            shutil.move(raw_path, final_rar_path)
            raw_path = final_rar_path
            log(__name__, "Redenumit in: %s" % raw_path)
            time.sleep(0.5)
        except Exception as e:
            log(__name__, "Eroare la redenumire: %s" % str(e))
            return

        # 6. Extragere / Scanare
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
            except Exception as e:
                log(__name__, "[ZIP] Eroare extragere: %s" % str(e))

        if not all_files:
            xbmcgui.Dialog().ok("Eroare", "Nu s-au gasit subtitrari in arhiva.")
            return

        # 7. Filtrare dupa episod (daca e cazul)
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
                log(__name__, "Filtrat %d subtitrari pentru episod." % len(subs_list))
                all_files = subs_list
            else:
                log(__name__, "Nicio subtitrare gasita pentru episod specific. Afisez tot.")
        
        all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

        # 8. Afisare rezultate finale
        for ofile in all_files:
            lang_code = selected_sub_info["ISO639"]
            
            # --- MODIFICARE AICI: Extragem numele traducatorului ---
            traducator_name = selected_sub_info.get("Traducator", "N/A")
            if not traducator_name: traducator_name = "N/A"

            display_name = os.path.basename(ofile)
            if ofile.startswith('rar://'):
                try: display_name = urllib.unquote(display_name)
                except: pass

            # Punem Traducatorul in 'label' (apare in stanga/sub steag)
            listitem = xbmcgui.ListItem(label=traducator_name, label2=display_name)
            
            # Setam iconita si steagul
            listitem.setArt({'icon': selected_sub_info["SubRating"], 'thumb': lang_code})
            listitem.setProperty("language", lang_code)
            listitem.setProperty("sync", "false") 

            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(ofile))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def get_title_variations(title):
    """
    Genereaza variatii ale titlului.
    Include logica pentru '&', 'and', spargerea titlurilor compuse si trunchierea dupa numar (Sequel).
    """
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

        search_str = ""
        for cand in candidates:
            clean_cand = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', cand or "", flags=re.IGNORECASE).strip()
            if clean_cand and clean_cand.lower() != 'play' and not clean_cand.isdigit() and is_latin_title(clean_cand):
                search_str = clean_cand
                log(__name__, "Titlu selectat (Latin): '%s'" % search_str)
                break
        
        if not search_str: return ([], 0)

        s = search_str
        s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) 
        s = re.sub(r'\b(19|20)\d{2}\b', '', s)
        s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s)
        s = re.sub(r'(?i)\bsez.*?$', '', s)
        s = re.sub(r'\.(mkv|avi|mp4|mov)$', '', s, flags=re.IGNORECASE)
        s = s.replace('.', ' ')
        s = re.sub(r'[\(\[\)\]]', '', s)
        
        # --- FIX: ELIMINARE STUDIOURI ---
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
        log(__name__, "Încerc căutare text: '%s'" % candidate)
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

def parse_results(html_content, languages_to_keep, required_season=None, search_year=None):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    download_links = soup.find_all('a', href=re.compile(r'/subtitrare/descarca/'))
    
    raw_count = len(download_links)
    result = []
    processed_links = set()

    for dl_link in download_links:
        try:
            legatura_raw = dl_link['href']
            if not legatura_raw.startswith('http'): 
                legatura = BASE_URL.rstrip('/') + legatura_raw
            else:
                legatura = legatura_raw

            if legatura in processed_links: continue
            processed_links.add(legatura)

            # Gasire container parinte
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
            
            # 1. Extragere Titlu si An
            title_tag = row_div.find('h2')
            if title_tag:
                full_text = title_tag.get_text(strip=True)
                match_an = re.search(r'\((\d{4})\)', full_text)
                if match_an:
                    an_str = match_an.group(1)
                    nume = full_text.replace('(%s)' % an_str, '').replace('()', '').strip()
                else:
                    nume = full_text

            # 2. Extragere Detalii (Traducator, Uploader, Limba) din text
            # Cautam toate span-urile cu text descriptiv
            details = row_div.find_all('span', class_='font-medium text-gray-700')
            for span in details:
                # Textul este de obicei in parintele span-ului sau span-ul urmator
                # Pe subs.ro structura e: <span>Label:</span> <span>Value</span>
                # Sau text brut in div. Luam textul parintelui span-ului pentru siguranta.
                parent_text = span.parent.get_text(" ", strip=True)
                
                if 'Traducător:' in parent_text:
                    traducator = parent_text.replace('Traducător:', '').strip()
                if 'Uploader:' in parent_text:
                    uploader = parent_text.replace('Uploader:', '').strip()
                if 'Limba:' in parent_text:
                    limba_text = parent_text.replace('Limba:', '').strip()

            # --- FILTRARE STRICTA LIMBA (BAZATA PE TEXT) ---
            # Daca am gasit textul limbii si NU este Romana, ignoram.
            # Daca nu am gasit textul, presupunem ca e RO (fallback), dar verificam daca e explicit altceva.
            if limba_text != 'N/A':
                if 'română' not in limba_text.lower() and 'romana' not in limba_text.lower():
                    # log(__name__, "SKIP: Limba straina textuala (%s) pentru %s" % (limba_text, nume))
                    continue
            
            # Fallback: Verificare steag daca textul a esuat
            flag_img = row_div.find('img', src=re.compile(r'flag-'))
            if flag_img and 'rom' not in flag_img['src'] and 'rum' not in flag_img['src'] and 'ro.' not in flag_img['src']:
                 # Daca avem steag si nu e de RO, e straina (chiar daca textul limbii n-a fost gasit)
                 # log(__name__, "SKIP: Steag strain detectat pentru %s" % nume)
                 continue

            # --- FILTRARE AN (+/- 1 an) ---
            if search_year and an_str and an_str.isdigit():
                try:
                    req_y = int(search_year)
                    res_y = int(an_str)
                    if abs(res_y - req_y) > 1:
                        continue
                except: pass

            # --- FILTRARE SEZON ---
            if required_season and str(required_season) not in ('0', 'None', ''):
                try:
                    curr_s = int(required_season)
                    titlu_lower = nume.lower()
                    is_match = False
                    match_range = re.search(r'(?:sez|seas|series)\w*\W*(\d+)\s*-\s*(\d+)', titlu_lower)
                    match_single = re.search(r'(?:sez|seas|series|s)\w*\W*0*(\d+)', titlu_lower)
                    if match_range:
                        s_start, s_end = int(match_range.group(1)), int(match_range.group(2))
                        if s_start <= curr_s <= s_end: is_match = True
                    elif match_single:
                        if int(match_single.group(1)) == curr_s: is_match = True
                    
                    if not is_match: continue
                except: continue

            if not traducator: traducator = 'N/A'
            if not uploader: uploader = 'N/A'
            if limba_text == 'N/A': limba_text = 'Română' # Presupunere finala pentru afisare

            # Construire Display Name - AM ADAUGAT LIMBA INAPOI
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
            log(__name__, "Eroare parsare rezultat individual: %s" % str(e))
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
        'title': normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")),
        'season': season, 
        'episode': episode
    }
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    lang_param = urllib.unquote(params.get('languages', ''))
    item['languages'] = [xbmc.convertLanguage(lang, xbmc.ISO_639_1) for lang in lang_param.split(',') if lang]
    Search(item)

elif action == 'setsub':
    link = urllib.unquote_plus(params.get('link', ''))
    final_sub_path = link
    
    if link.startswith('rar://'):
        try:
            base_filename = os.path.basename(link)
            try: base_filename = urllib.unquote(base_filename)
            except: pass
            
            dest_file = os.path.join(__temp__, base_filename)
            log(__name__, "[SETSUB] Extrag manual din RAR: %s" % link)
            
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
                log(__name__, "[SETSUB] Extragere reusita.")
            else:
                log(__name__, "[SETSUB] Eroare: Fisier gol.")
        except Exception as e:
            log(__name__, "[SETSUB] Eroare critica: %s" % str(e))
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
                    log(__name__, "Fisier redenumit: %s" % final_sub_path)
                except Exception as e:
                    log(__name__, "Eroare redenumire: %s" % str(e))

        listitem = xbmcgui.ListItem(label=os.path.basename(final_sub_path))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=final_sub_path, listitem=listitem, isFolder=False)
        
        def set_sub_delayed():
            time.sleep(1.0)
            xbmc.Player().setSubtitles(final_sub_path)

        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))