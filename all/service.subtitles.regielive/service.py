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

BASE_URL = "https://subtitrari.regielive.ro/"

sys.path.append (__resource__)
import requests
import PTN
from bs4 import BeautifulSoup

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
        if hex_header.startswith('52617221'): return 'rar'
        if hex_header.startswith('504B'): return 'zip'
        return 'unknown'
    except Exception: return 'error'

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2: return "%%%%%"
    try:
        season, epnr = int(parts[0]), int(parts[1])
        patterns = []
        patterns.append(r"[Ss]%02d[Ee]%02d" % (season, epnr))
        patterns.append(r"[Ss]%d[Ee]%d" % (season, epnr))
        patterns.append(r"[Ss]%02d[._\-\s]+[Ee]%02d" % (season, epnr))
        patterns.append(r"%dx%02d" % (season, epnr))
        patterns.append(r"sez.*?%d.*?ep.*?%d" % (season, epnr))
        return '(?:%s)' % '|'.join(patterns)
    except: return "%%%%%"

def scan_archive_windows(archive_physical_path, archive_type):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    try:
        normalized_path = archive_physical_path.replace('\\', '/')
        if not normalized_path.startswith('/'): normalized_path = '/' + normalized_path
        if py3: quoted_path = urllib.quote(normalized_path, safe='')
        else: quoted_path = urllib.quote(str(normalized_path), safe='')
        root_vfs_path = '%s://%s/' % (archive_type, quoted_path)
        
        def recursive_scan(current_vfs_path):
            found = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                for f in files:
                    if not py3 and isinstance(f, bytes): f = f.decode('utf-8')
                    if os.path.splitext(f)[1].lower() in subtitle_exts:
                        if current_vfs_path.endswith('/'): full = current_vfs_path + f
                        else: full = current_vfs_path + '/' + f
                        found.append(full)
                for d in dirs:
                    if not py3 and isinstance(d, bytes): d = d.decode('utf-8')
                    if current_vfs_path.endswith('/'): next_p = current_vfs_path + d + '/'
                    else: next_p = current_vfs_path + '/' + d + '/'
                    found.extend(recursive_scan(next_p))
            except: pass
            return found
        return recursive_scan(root_vfs_path)
    except: return []

def extract_archive_android(archive_physical_path, dest_path):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    try:
        if not os.path.exists(dest_path): os.makedirs(dest_path)
        normalized_path = archive_physical_path.replace('\\', '/')
        if not normalized_path.startswith('/'): normalized_path = '/' + normalized_path
        if py3: quoted_path = urllib.quote(normalized_path, safe='')
        else: quoted_path = urllib.quote(str(normalized_path), safe='')
        root_vfs_path = 'rar://%s/' % quoted_path
        
        def recursive_copy(current_vfs_path):
            found = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                for f in files:
                    if not py3 and isinstance(f, bytes): f = f.decode('utf-8')
                    if os.path.splitext(f)[1].lower() in subtitle_exts:
                        if current_vfs_path.endswith('/'): src = current_vfs_path + f
                        else: src = current_vfs_path + '/' + f
                        dst = os.path.join(dest_path, f)
                        if xbmcvfs.copy(src, dst): found.append(dst)
                for d in dirs:
                    if not py3 and isinstance(d, bytes): d = d.decode('utf-8')
                    if current_vfs_path.endswith('/'): next_url = current_vfs_path + d + '/'
                    else: next_url = current_vfs_path + '/' + d + '/'
                    found.extend(recursive_copy(next_url))
            except: pass
            return found
        return recursive_copy(root_vfs_path)
    except: return []

def extract_file_from_archive(archive_path, dest_path, archive_type='zip'):
    found = []
    try:
        if not os.path.exists(dest_path): os.makedirs(dest_path)
        
        if archive_type == 'zip':
            with zipfile.ZipFile(archive_path, 'r') as zf:
                for member in zf.infolist():
                    if os.path.splitext(member.filename)[1].lower() in [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]:
                        zf.extract(member, dest_path)
                        extracted_path = os.path.join(dest_path, member.filename)
                        extracted_path = os.path.normpath(extracted_path)
                        found.append(extracted_path)
    except Exception: 
        traceback.print_exc()
    return found

def cleanup_temp_directory(temp_dir):
    try:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir)
    except: pass

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

def get_search_html(url, session):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36', 'Referer': BASE_URL}
    try: return session.get(url, headers=headers, verify=False, timeout=15).text
    except: return False

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

def perform_regielive_search(item, session):
    import difflib
    from bs4 import BeautifulSoup

    search_year = item.get('year', '')
    final_title = ""
    
    # --- FIX: DETECTARE SERIAL ---
    is_serial = False
    if item.get('season') and str(item.get('season')) != "0":
        is_serial = True
    # -----------------------------
    
    if item.get('mansearch'):
        log("--- CAUTARE MANUALA ACTIVA ---")
        search_str = urllib.unquote(item.get('mansearchstr', ''))
        final_title = search_str.strip()
    else:
        log("--- CAUTARE AUTOMATA ACTIVA ---")
        
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
            if clean_cand and is_latin_title(clean_cand):
                search_str = clean_cand
                log("Titlu selectat (Latin): '%s'" % search_str)
                break
            elif clean_cand:
                log("Titlu ignorat (non-latin): '%s'" % clean_cand)
        
        if not search_str: return []

        s = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_str, flags=re.IGNORECASE)
        s = re.sub(r'[\(\[\.\s](19|20)\d{2}[\)\]\.\s].*?$', '', s) 
        s = re.sub(r'\b(19|20)\d{2}\b', '', s)
        s = re.sub(r'(?i)[S]\d{1,2}[E]\d{1,2}.*?$', '', s)
        s = re.sub(r'(?i)\bsez.*?$', '', s)
        s = re.sub(r'\.(mkv|avi|mp4|mov)$', '', s, flags=re.IGNORECASE)
        s = s.replace('.', ' ')
        s = re.sub(r'[\(\[\)\]]', '', s)
        
        final_title = ' '.join(s.split())
        
        codes = ['US', 'UK', 'RO']
        words = final_title.split()
        if len(words) > 1 and words[-1].upper() in codes:
            final_title = ' '.join(words[:-1])

    if not final_title: return []
    
    search_candidates = get_title_variations(final_title)
    
    found_page_link = None
    found_page_title = ""
    
    all_valid_results = [] 

    for candidate in search_candidates:
        if not candidate or len(candidate) < 2: continue
        
        queries_to_try = []
        
        if search_year and search_year.isdigit():
            queries_to_try.append(candidate + " " + search_year)
            
        queries_to_try.append(candidate)
        
        candidate_found_match = False

        for query_str in queries_to_try:
            log("Încerc query: '%s'" % query_str)
            
            for page_num in range(1, 4):
                if page_num == 1:
                    search_url = '%scauta.html?s=%s' % (BASE_URL, urllib.quote_plus(query_str))
                else:
                    search_url = '%scauta.html?s=%s&pag=%d' % (BASE_URL, urllib.quote_plus(query_str), page_num)
                
                html = get_search_html(search_url, session)
                
                if not html: break
                if "Nu a fost gasit nici un rezultat" in html: break

                soup = BeautifulSoup(html, 'html.parser')
                results_divs = soup.find_all('div', class_='imagine')
                
                if not results_divs: break

                parsed_results = []
                for div in results_divs:
                    a_tag = div.find('a')
                    if not a_tag: continue
                    
                    link = a_tag.get('href')
                    img_tag = a_tag.find('img')
                    title_res = ""
                    if img_tag and img_tag.get('alt'):
                        title_res = img_tag.get('alt')
                    else:
                        title_res = a_tag.get_text(strip=True)
                    
                    if title_res and link:
                        parsed_results.append((link, title_res))
                
                for link, r_title in parsed_results:
                    r_title_clean = re.sub(r'\(\d{4}\)', '', r_title).strip()
                    
                    match_year = True
                    # --- FIX: Verificam anul DOAR daca nu este serial ---
                    if search_year and search_year.isdigit() and not is_serial:
                        years_in_res = re.findall(r'\b(19\d{2}|20\d{2})\b', r_title)
                        if years_in_res:
                            req_y_int = int(search_year)
                            tolerant_match = False
                            for y_str in years_in_res:
                                if abs(int(y_str) - req_y_int) <= 1:
                                    tolerant_match = True
                                    break
                            
                            if not tolerant_match:
                                match_year = False
                    
                    if not match_year: continue

                    base_clean_compare = re.sub(r'[:\-\|]', ' ', final_title).strip().lower()
                    res_clean_compare = re.sub(r'[:\-\|]', ' ', r_title_clean).strip().lower()
                    
                    ratio = difflib.SequenceMatcher(None, base_clean_compare, res_clean_compare).ratio()
                    
                    if ratio < 0.85:
                        words_cautat = base_clean_compare.split()
                        words_gasit = res_clean_compare.split()
                        blacklist = ['the', 'of', 'in', 'a', 'an']
                        sig_words = [w for w in words_cautat if w not in blacklist and len(w)>2]
                        
                        all_words_found = True
                        for w in sig_words:
                            if w not in "".join(words_gasit): 
                                all_words_found = False
                                break
                        
                        if not all_words_found:
                            continue
                    
                    if ratio > 0.4 or base_clean_compare in res_clean_compare:
                        if not any(x[0] == link for x in all_valid_results):
                            all_valid_results.append((link, r_title, ratio))

            if all_valid_results:
                all_valid_results.sort(key=lambda x: x[2], reverse=True)
                if all_valid_results[0][2] >= 0.95:
                    log("Gasit potrivire excelenta cu query '%s'. Stop cautare." % query_str)
                    candidate_found_match = True
                    break
        
        if candidate_found_match:
            break

    if not all_valid_results:
        log("Nu am gasit niciun rezultat relevant.")
        return []

    all_valid_results.sort(key=lambda x: x[2], reverse=True)
    
    if all_valid_results[0][2] > 0.95:
        found_page_link = all_valid_results[0][0]
        found_page_title = all_valid_results[0][1]
        log("Selectat automat: %s" % found_page_title)
    else:
        dialog = xbmcgui.Dialog()
        display_list = ["%s" % x[1] for x in all_valid_results]
        sel = dialog.select("RegieLive - Selectati rezultatul", display_list)
        if sel >= 0:
            found_page_link = all_valid_results[sel][0]
            found_page_title = all_valid_results[sel][1]
        else:
            return []

    if not found_page_link.startswith('http'): 
        found_page_link = BASE_URL.rstrip('/') + '/' + found_page_link.lstrip('/')
    
    log("Accesez pagina: %s" % found_page_link)
    page_content = get_search_html(found_page_link, session)
    if not page_content: return []

    soup_page = BeautifulSoup(page_content, 'html.parser')
    
    req_season = item.get('season')
    if req_season and str(req_season) != "0":
        s_num = int(req_season)
        season_links = soup_page.find_all('a', href=re.compile(r'sezonul-%d/?' % s_num))
        
        if season_links:
            new_link = season_links[0]['href']
            if not new_link.startswith('http'):
                new_link = BASE_URL.rstrip('/') + '/' + new_link.lstrip('/')
            
            log("Navighez la Sezonul %d: %s" % (s_num, new_link))
            page_content = get_search_html(new_link, session)
            if page_content:
                soup_page = BeautifulSoup(page_content, 'html.parser')
    
    subs_lis = soup_page.find_all('li', class_='subtitrare')
    
    filtered_subs = []
    episode_regex = None
    if req_season and item.get('episode') and str(item.get('episode')) != "0":
        epstr = '%s:%s' % (req_season, item.get('episode'))
        episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)

    for li in subs_lis:
        try:
            full_text = li.get_text(" ", strip=True)
            dl_a = li.find('a', href=re.compile(r'descarca'))
            if not dl_a: continue
            
            link_sub = dl_a['href']
            
            rating = "0"
            rate_elem = li.find(attrs={"title": re.compile(r"Nota")})
            if rate_elem and "title" in rate_elem.attrs:
                match_r = re.search(r'Nota ([\d\.]+)', rate_elem['title'])
                if match_r: rating = match_r.group(1)

            sub_name = full_text.split("Descarca")[0].strip()
            
            if episode_regex:
                if not episode_regex.search(sub_name):
                    continue
            
            filtered_subs.append({
                'SubFileName': sub_name,
                'ZipDownloadLink': link_sub,
                'SubRating': rating,
                'Traducator': 'RegieLive',
                'ISO639': 'ro',
                'PageUrl': found_page_link
            })
            
        except Exception as e:
            log("Eroare parsare linie subtitrare: %s" % e)
            continue

    return filtered_subs

def Search(item):
    log(">>>>>>>>>> PORNIRE CĂUTARE SUBTITRARE (REGIELIVE) <<<<<<<<<<")
    temp_dir = __temp__
    cleanup_temp_directory(temp_dir)

    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    s.headers.update({'User-Agent': ua, 'Referer': BASE_URL})

    subtitles_found = perform_regielive_search(item, s)
    
    if not subtitles_found:
        
        return

    for sub_info in subtitles_found:
        # AFISAM TRADUCATORUL SUB STEAG (Label)
        trad = sub_info.get('Traducator', 'RegieLive')
        li = xbmcgui.ListItem(label=trad, label2=sub_info['SubFileName'])
        
        li.setArt({'icon': sub_info.get('SubRating', '0'), 'thumb': 'ro'})
        li.setProperty("sync", "false")
        li.setProperty("hearing_imp", "false")
        
        url = "plugin://%s/?action=setsub&link=%s&ref=%s" % (
            __scriptid__, 
            urllib.quote_plus(sub_info['ZipDownloadLink']),
            urllib.quote_plus(sub_info.get('PageUrl', BASE_URL))
        )
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=li, isFolder=False)

def normalizeString(obj):
    if py3: return obj
    try: return unicodedata.normalize('NFKD', unicode(obj, 'utf-8')).encode('ascii', 'ignore')
    except: return unicode(str(obj).encode('string_escape'))

def get_params():
    param = {}
    try:
        paramstring = sys.argv[2]
        if len(paramstring) >= 2:
            for pair in paramstring.replace('?', '').split('&'):
                split = pair.split('=')
                if len(split) == 2: param[split[0]] = split[1]
    except: pass
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
        'episode': episode,
        'year': xbmc.getInfoLabel("VideoPlayer.Year")
    }
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    Search(item)

elif action == 'setsub':
    urld = urllib.unquote_plus(params.get('link', ''))
    referer = urllib.unquote_plus(params.get('ref', BASE_URL))
    
    log("User a selectat: %s" % urld)
    
    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    dl_headers = {'User-Agent': ua, 'Referer': referer}
    
    link = re.sub('download', 'descarca', urld)
    link = re.sub('html', 'zip', link)
    if not link.startswith('http'): link = BASE_URL.rstrip('/') + '/' + link.lstrip('/')
    
    content = None
    try:
        resp = s.get(link, headers=dl_headers, verify=False, timeout=10)
        if len(resp.content) > 500: content = resp.content
        else:
             interm = s.get(BASE_URL + urld, headers=dl_headers, verify=False).text
             real = re.search(r'href="([^"]+\.zip)"', interm)
             if real:
                 rl = real.group(1)
                 if not rl.startswith('http'): rl = BASE_URL + rl
                 content = s.get(rl, headers=dl_headers, verify=False).content
    except: pass
    
    if content:
        timestamp = str(int(time.time()))
        temp_arch = os.path.join(__temp__, "sub_%s.dat" % timestamp)
        with open(temp_arch, 'wb') as f: f.write(content)
        
        sig = get_file_signature(temp_arch)
        if sig == 'unknown':
             if '.rar' in link: sig = 'rar'
             else: sig = 'zip'
        
        ext = 'rar' if sig == 'rar' else 'zip'
        real_arch = os.path.join(__temp__, "arch_%s.%s" % (timestamp, ext))
        shutil.move(temp_arch, real_arch)
        
        final_sub_path = None
        
        extract_folder = os.path.join(__temp__, "ext_%s" % timestamp)
        
        if sig == 'zip':
             extracted_files = extract_file_from_archive(real_arch, extract_folder, 'zip')
             if extracted_files: final_sub_path = extracted_files[0]
        elif sig == 'rar':
             if xbmc.getCondVisibility('System.Platform.Android'):
                 extracted_files = extract_archive_android(real_arch, extract_folder)
                 if extracted_files: final_sub_path = extracted_files[0]
             else:
                 vfs_files = scan_archive_windows(real_arch, 'rar')
                 if vfs_files:
                     vfs_f = vfs_files[0]
                     base_f = os.path.basename(vfs_f.replace('\\','/'))
                     try: base_f = urllib.unquote(base_f)
                     except: pass
                     dest = os.path.join(__temp__, base_f)
                     try:
                         sf = xbmcvfs.File(vfs_f, 'rb')
                         df = xbmcvfs.File(dest, 'wb')
                         df.write(sf.readBytes() if py3 else sf.read())
                         sf.close(); df.close()
                         final_sub_path = dest
                     except: pass

        if final_sub_path and os.path.exists(final_sub_path):
            path_no_ext, ext = os.path.splitext(final_sub_path)
            final_ro_path = path_no_ext + ".ro" + ext
            try:
                os.rename(final_sub_path, final_ro_path)
                final_sub_path = final_ro_path
            except: pass
            
            listitem = xbmcgui.ListItem(label=os.path.basename(final_sub_path))
            xbmcplugin.addDirectoryItem(handle=handle, url=final_sub_path, listitem=listitem, isFolder=False)
            
            def set_sub_delayed():
                time.sleep(1.0)
                xbmc.Player().setSubtitles(final_sub_path)

            import threading
            t = threading.Thread(target=set_sub_delayed)
            t.start()
    else:
        xbmcgui.Dialog().ok("Eroare", "Download esuat.")

xbmcplugin.endOfDirectory(handle)