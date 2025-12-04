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

BASE_URL = "https://www.titrari.ro/"

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
        patterns.append(r"[Ss]%02d[Ee]%02d" % (season, epnr))
        patterns.append(r"[Ss]%d[Ee]%d" % (season, epnr))
        patterns.append(r"[Ss]%02d[._\-\s]+[Ee]%02d" % (season, epnr))
        patterns.append(r"[Ss]%d[._\-\s]+[Ee]%d" % (season, epnr))
        patterns.append(r"%dx%02d" % (season, epnr))
        patterns.append(r"%02dx%02d" % (season, epnr))
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
        
        if py3: quoted_path = urllib.quote(normalized_archive_path, safe='')
        else: quoted_path = urllib.quote(str(normalized_archive_path), safe='')

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
                        if current_vfs_path.endswith('/'): full_vfs_path = current_vfs_path + file_name
                        else: full_vfs_path = current_vfs_path + '/' + file_name
                        found_subs.append(full_vfs_path)
                for dir_name in dirs:
                    if not py3 and isinstance(dir_name, bytes):
                        dir_name = dir_name.decode('utf-8')
                    if current_vfs_path.endswith('/'): next_vfs_path = current_vfs_path + dir_name + '/'
                    else: next_vfs_path = current_vfs_path + '/' + dir_name + '/'
                    found_subs.extend(recursive_scan(next_vfs_path))
            except: pass
            return found_subs

        all_files_vfs = recursive_scan(root_vfs_path)
        return all_files_vfs
    except Exception as e:
        log("[WINDOWS VFS] Eroare scanare: %s" % e)
        return []

def extract_archive_android(archive_physical_path, dest_path):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    extracted_files = []
    try:
        if not os.path.exists(dest_path): os.makedirs(dest_path)
        normalized_archive_path = archive_physical_path.replace('\\', '/')
        if not normalized_archive_path.startswith('/'): normalized_archive_path = '/' + normalized_archive_path
        if py3: quoted_path = urllib.quote(normalized_archive_path, safe='')
        else: quoted_path = urllib.quote(str(normalized_archive_path), safe='')
        root_vfs_path = 'rar://%s/' % quoted_path
        
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
                        if xbmcvfs.copy(src, dst): found.append(dst)
                for d in dirs:
                    d_name = d
                    if not py3 and isinstance(d, str): d_name = d.decode('utf-8', 'ignore')
                    if current_vfs_path.endswith('/'): next_url = current_vfs_path + d + '/'
                    else: next_url = current_vfs_path + '/' + d + '/'
                    found.extend(recursive_extract_copy(next_url))
            except: pass
            return found
        extracted_files = recursive_extract_copy(root_vfs_path)
        return extracted_files
    except Exception as e:
        log("[ANDROID OLD] Eroare generala extragere: %s" % e)
        return []

def cleanup_temp_directory(temp_dir):
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir)
    except: pass

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

def Search(item):
    log(">>>>>>>>>> PORNIRE CĂUTARE SUBTITRARE (TITRARI.RO) <<<<<<<<<<")
    temp_dir = __temp__
    cleanup_temp_directory(temp_dir)

    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    s.headers.update({'User-Agent': ua, 'Referer': BASE_URL})

    subtitles_found = searchsubtitles(item, s)
    
    if not subtitles_found:
        return

    sel = -1
    if len(subtitles_found) == 1:
        log("Un singur rezultat valid. Se selecteaza automat.")
        sel = 0
    else:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in subtitles_found]
        sel = dialog.select("Selectati subtitrarea", titles)
    
    if sel >= 0:
        selected_sub = subtitles_found[sel]

        link = 'https://www.titrari.ro/get.php?id=' + selected_sub["ZipDownloadLink"]
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
        except: pass

        all_files = []
        extractPath = os.path.join(temp_dir, "Extracted")

        if real_type == 'zip':
            subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
            try:
                if not os.path.exists(extractPath): os.makedirs(extractPath)
                with zipfile.ZipFile(fname, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        if os.path.splitext(member)[1].lower() in subtitle_exts:
                            target_name = os.path.basename(member)
                            if not target_name: continue
                            target_path = os.path.join(extractPath, target_name)
                            try:
                                source = zip_ref.open(member)
                                with open(target_path, "wb") as target:
                                    shutil.copyfileobj(source, target)
                                all_files.append(target_path)
                            except: pass
            except Exception as e:
                log("[ZIP] Eroare: %s" % e)

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
        
        if not all_files:
             xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita pentru S%sE%s in arhiva." % (season, episode))
             return

        for sub_file in all_files:
            basename = os.path.basename(sub_file)
            if sub_file.startswith('rar://'):
                try: basename = urllib.unquote(basename)
                except: pass
            
            basename = normalizeString(basename)
            
            lang_code = 'ro'
            lang_label = 'Romanian'
            
            listitem = xbmcgui.ListItem(label=lang_label, label2=basename)
            listitem.setArt({'icon': "5", 'thumb': lang_code})
            listitem.setProperty("language", lang_code)
            listitem.setProperty("sync", "false")
            
            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(sub_file))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def get_title_variations(title):
    """
    Genereaza variatii ale titlului.
    Include logica pentru '&', 'and' si spargerea titlurilor compuse.
    """
    variations = []
    
    base_title = ' '.join(title.strip().split())
    if not base_title: return []

    variations.append(base_title)

    clean_base = re.sub(r'[:\-\|&]', ' ', base_title).strip()
    clean_base = ' '.join(clean_base.split())
    
    if clean_base.lower() != base_title.lower():
        variations.append(clean_base)
        
    if '&' in base_title:
        with_and = base_title.replace('&', 'and')
        variations.append(' '.join(with_and.split()))

    if any(c in base_title for c in ['&', ':', '-']):
        parts = re.split(r'[&:\-]', base_title)
        for part in parts:
            p = part.strip()
            if len(p) > 3 and not p.isdigit():
                variations.append(p)

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

    seen = set()
    final_variations = []
    for v in variations:
        v_low = v.lower()
        if v_low not in seen and len(v_low) > 1:
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
            elif clean_cand:
                log("Titlu ignorat (Non-Latin sau invalid): '%s'" % clean_cand)
        
        if not search_string_raw: return None

        s = search_string_raw
        s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) # An
        s = re.sub(r'\b(19|20)\d{2}\b', '', s)
        s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s) # Serial
        s = re.sub(r'(?i)\bsez.*?$', '', s)
        s = re.sub(r'\.(mkv|avi|mp4|mov)$', '', s, flags=re.IGNORECASE)
        s = s.replace('.', ' ')
        s = re.sub(r'[\(\[\)\]]', '', s)
        
        final_search_string = ' '.join(s.split())
        searched_title_for_sort = final_search_string

    if not final_search_string: return None

    base_search_title = searched_title_for_sort
    search_candidates = get_title_variations(base_search_title)
    
    req_season = 0
    if item.get('season') and str(item.get('season')).isdigit():
        req_season = int(item.get('season'))

    found_results = []

    for candidate in search_candidates:
        log("Încerc căutare cu: '%s' | Filtru An: %s" % (candidate, str(search_year)))
        
        html_content = fetch_subtitles_page(candidate, session)
        
        if html_content:
            results = parse_results(html_content, base_search_title, req_season, search_year)
            if results:
                log("!!! Găsit %d rezultate pentru '%s' !!!" % (len(results), candidate))
                found_results.extend(results)
                break 
        
        time.sleep(0.3)

    return found_results

def fetch_subtitles_page(search_string, session):
    search_url = BASE_URL + "index.php?page=cautare&z1=0&z2=" + urllib.quote_plus(search_string) + "&z3=1&z4=1"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': BASE_URL
    }
    try:
        response = session.get(search_url, headers=headers, verify=False, timeout=15)
        return response.text
    except Exception as e:
        log("EROARE conectare site: %s" % e)
        return None

def parse_results(html_content, searched_title, req_season=0, req_year=None):
    import difflib
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html_content, 'html.parser')
    clean_search = []
    
    for h1 in soup.find_all('h1'):
        try:
            link_tag = h1.find('a')
            if not link_tag: continue
            
            nume_clean = link_tag.get_text().strip()
            
            tr = h1.find_parent('tr')
            if not tr: continue
            
            download_node = tr.find('a', href=re.compile(r'get\.php\?id=(\d+)'))
            if not download_node: pass 
            if not download_node: continue
            
            id_sub_match = re.search(r'id=(\d+)', download_node['href'])
            if not id_sub_match: continue
            id_sub = id_sub_match.group(1)
            
            trad_clean = "N/A"
            trad_marker = tr.find(string=re.compile("Traducator:"))
            if trad_marker:
                parent_td = trad_marker.find_parent('td')
                if parent_td:
                    full_text = parent_td.get_text()
                    if "Traducator:" in full_text:
                        part = full_text.split("Traducator:")[1]
                        trad_clean = part.split("Uploader:")[0].strip()

            desc_clean = ""
            current_elem = tr.next_sibling
            steps = 0
            while current_elem and steps < 5:
                if hasattr(current_elem, 'find'):
                    if current_elem.find('h1'): break
                    comment_td = current_elem.find('td', attrs={'class': 'comment', 'width': '100%'})
                    if comment_td:
                        desc_clean = comment_td.get_text().strip().replace('\r', ' ').replace('\n', ' ')
                        break
                current_elem = current_elem.next_sibling
                steps += 1
            
            full_text_lower = (nume_clean + " " + desc_clean).lower()
            
            if req_year:
                found_years = re.findall(r'\b(19\d{2}|20\d{2})\b', full_text_lower)
                if found_years:
                    try:
                        req_y_int = int(req_year)
                        match_found = False
                        for year_str in found_years:
                            y_int = int(year_str)
                            if abs(y_int - req_y_int) <= 1:
                                match_found = True
                                break
                        
                        if not match_found:
                            continue
                    except:
                        if str(req_year) not in found_years:
                            continue

            if req_season == 0:
                if re.search(r'(?i)\b(sezonul|sez|season|episodul|episode|s\d{1,2}|ep\d{1,2})\b', full_text_lower):
                    continue
                if re.search(r'(?i)(?:sezoanele|seasons)', full_text_lower):
                    continue

                clean_nume_compare = re.sub(r'\(\d{4}\)', '', nume_clean).strip()
                clean_nume_compare = re.sub(r'[-–:;]', ' ', clean_nume_compare).strip()
                clean_nume_compare = ' '.join(clean_nume_compare.split())
                
                clean_search_compare = re.sub(r'[-–:;]', ' ', searched_title).strip()
                clean_search_compare = ' '.join(clean_search_compare.split())
                
                t_gasit = clean_nume_compare.lower()
                t_cautat = clean_search_compare.lower()

                ratio = difflib.SequenceMatcher(None, t_cautat, t_gasit).ratio()
                starts_with = t_gasit.startswith(t_cautat) or t_cautat.startswith(t_gasit)
                
                if t_cautat in t_gasit or t_gasit in t_cautat:
                    starts_with = True

                if ratio < 0.85:
                    words_cautat = t_cautat.split()
                    words_gasit = t_gasit.split()
                    
                    blacklist_words = ['the', 'of', 'in', 'on', 'at', 'to', 'a', 'an']
                    significant_words = [w for w in words_cautat if len(w) > 2 or w not in blacklist_words]
                    
                    if significant_words:
                        found_all_words = True
                        for w in significant_words:
                            if w not in words_gasit:
                                match_partial = False
                                for wg in words_gasit:
                                    if w in wg: match_partial = True
                                
                                if not match_partial:
                                    found_all_words = False
                                    break
                        
                        if not found_all_words:
                            continue

                if ratio < 0.6 and not starts_with: 
                    continue

            else:
                clean_nume_compare = re.sub(r'\(\d{4}\)', '', nume_clean).strip()
                clean_nume_compare = re.sub(r'(?i)sezonul\s*\d+', '', clean_nume_compare).strip()
                clean_nume_compare = re.sub(r'[-–:]', '', clean_nume_compare).strip()
                clean_search_compare = re.sub(r'[-–:]', '', searched_title).strip()
                
                ratio = difflib.SequenceMatcher(None, clean_search_compare.lower(), clean_nume_compare.lower()).ratio()
                if ratio < 0.6: continue

                season_in_title = re.search(r'(?i)(?:sezonul|season|s)\s*0*(\d+)', nume_clean)
                if season_in_title:
                    found_s = int(season_in_title.group(1))
                    if found_s != req_season: continue
                else:
                    range_in_title = re.search(r'(?i)(?:sezoanele|seasons)[\s]*(\d+)[\s]*[-][\s]*(\d+)', nume_clean)
                    if range_in_title:
                         s_s = int(range_in_title.group(1))
                         s_e = int(range_in_title.group(2))
                         if not (s_s <= req_season <= s_e): continue

            s_title = "[B]%s[/B] | Trad: [B][COLOR FFFF69B4]%s[/COLOR][/B] | %s" % (nume_clean, trad_clean, desc_clean)
            clean_search.append({
                'SubFileName': ' '.join(s_title.split()),
                'ZipDownloadLink': id_sub, 
                'Traducator': trad_clean,
                'SubRating': '5', 'ISO639': 'ro',
                'OriginalMovieTitle': nume_clean
            })
            
        except Exception as e:
            log("EROARE la parsare rezultat BS4: %s" % str(e))
            continue
    
    if clean_search:
        clean_search.sort(key=lambda sub: (
            -difflib.SequenceMatcher(None, searched_title.lower(), sub['OriginalMovieTitle'].lower()).ratio(),
            natural_key(sub['SubFileName'])
        ))

    return clean_search

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
        if 'season' in parsed_data: season = str(parsed_data['season'])
        if 'episode' in parsed_data: episode = str(parsed_data['episode'])
            
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