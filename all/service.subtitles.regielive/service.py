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

def perform_regielive_search(item, session):
    search_year = item.get('year', '')
    
    if item.get('mansearch'):
        search_str = urllib.unquote(item.get('mansearchstr', ''))
        parsed = PTN.parse(search_str)
        final_title = parsed.get('title', search_str).strip()
        if not search_year: search_year = str(parsed.get('year', ''))
    else:
        search_str = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
        if not search_str: search_str = os.path.basename(item.get('file_original_path', ''))
        
        clean_str = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_str)
        clean_str = re.sub(r'\(.*?\)|\[.*?\]', '', clean_str)
        parsed = PTN.parse(clean_str)
        final_title = parsed.get('title', clean_str)
        
        if not search_year: search_year = str(parsed.get('year', ''))
        if not search_year and xbmc.getInfoLabel("VideoPlayer.Year"):
             search_year = xbmc.getInfoLabel("VideoPlayer.Year")
        
        codes = ['US', 'UK', 'RO']
        words = final_title.split()
        if len(words) > 1 and words[-1].upper() in codes:
            final_title = ' '.join(words[:-1])
            
    final_title = ' '.join(final_title.replace('.', ' ').split()).strip()
    
    search_query = final_title
    if search_year and search_year.isdigit() and len(search_year) == 4:
        search_query += " " + search_year
        
    log("Cautare finala: '%s'" % search_query)

    search_url = '%scauta.html?s=%s' % (BASE_URL, urllib.quote_plus(search_query))
    html = get_search_html(search_url, session)
    if not html: return []

    regex_res = r'"imagine">.*?href="(.*?)".*?<img.*?alt="(.*?)".*?tag-.*?">(.*?)<'
    results = re.compile(regex_res, re.IGNORECASE | re.DOTALL).findall(html)
    
    if not results and search_year in search_query:
        log("Niciun rezultat cu an. Reincerc fara an.")
        search_url_simple = '%scauta.html?s=%s' % (BASE_URL, urllib.quote_plus(final_title))
        html_simple = get_search_html(search_url_simple, session)
        results = re.compile(regex_res, re.IGNORECASE | re.DOTALL).findall(html_simple)

    if not results: return []
    
    import difflib
    results.sort(key=lambda x: difflib.SequenceMatcher(None, final_title.lower(), x[1].lower()).ratio(), reverse=True)

    sel_idx = 0
    if len(results) > 1:
        match_found = False
        res_title_clean = re.sub(r'\(\d{4}\)', '', results[0][1]).strip()
        ratio = difflib.SequenceMatcher(None, final_title.lower(), res_title_clean.lower()).ratio()
        
        if search_year and search_year in results[0][1]:
             match_found = True
        
        if not match_found and ratio < 0.9:
            dialog = xbmcgui.Dialog()
            filtered_display_results = []
            for r in results:
                 r_title_clean = re.sub(r'\(\d{4}\)', '', r[1]).strip()
                 r_ratio = difflib.SequenceMatcher(None, final_title.lower(), r_title_clean.lower()).ratio()
                 if r_ratio > 0.4:
                     filtered_display_results.append(r)
            
            if not filtered_display_results: filtered_display_results = results # Fallback
            
            sel_idx = dialog.select("RegieLive - Alege", ['%s (%s)' % (x[1], x[2]) for x in filtered_display_results])
            if sel_idx < 0: return []
            results = filtered_display_results

    page_link = results[sel_idx][0]
    if not page_link.startswith('http'): page_link = BASE_URL.rstrip('/') + '/' + page_link.lstrip('/')
    
    log("Accesez pagina principala: %s" % page_link)
    page_content = get_search_html(page_link, session)
    if not page_content: return []

    req_season = item.get('season')
    
    if req_season and req_season != "0":
        season_num = int(req_season)
        season_link_regex = r'href="([^"]*sezonul-%d/?)"' % season_num
        match_season = re.search(season_link_regex, page_content, re.IGNORECASE)
        
        if match_season:
            new_link = match_season.group(1)
            if not new_link.startswith('http'):
                if new_link.startswith('/'):
                    new_link = BASE_URL.rstrip('/') + new_link
                else:
                     base_for_rel = page_link if page_link.endswith('/') else page_link + '/'
                     new_link = base_for_rel + new_link
            
            log("Navighez la Sezonul %d: %s" % (season_num, new_link))
            page_content = get_search_html(new_link, session)
            if not page_content: return [] 
        else:
            log("Link sezon specific nu a fost gasit. Raman pe pagina curenta.")

    sub_regex = r'<li class="subtitrare.*?id=".*?>(.*?)<.*?(?: |.*?title="Nota (.*?) d).*?href="(.*?descarca.*?)"'
    all_subs = re.compile(sub_regex, re.IGNORECASE | re.DOTALL).findall(page_content)
    
    filtered_subs = []
    
    if req_season and item.get('episode') and req_season != "0" and item.get('episode') != "0":
        epstr = '%s:%s' % (req_season, item.get('episode'))
        episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
        
        log("Filtrez lista pentru %s..." % epstr)
        
        for s_name, s_rate, s_link in all_subs:
            s_name_clean = cleanhtml(s_name).strip()
            
            if episode_regex.search(s_name_clean):
                filtered_subs.append({
                    'SubFileName': s_name_clean,
                    'ZipDownloadLink': s_link,
                    'SubRating': s_rate,
                    'Traducator': 'RegieLive',
                    'ISO639': 'ro',
                    'PageUrl': page_link
                })
    else:
        for s_name, s_rate, s_link in all_subs:
            filtered_subs.append({
                'SubFileName': cleanhtml(s_name).strip(),
                'ZipDownloadLink': s_link,
                'SubRating': s_rate,
                'Traducator': 'RegieLive',
                'ISO639': 'ro',
                'PageUrl': page_link
            })

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
        xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita pentru acest episod.")
        return

    for sub_info in subtitles_found:
        li = xbmcgui.ListItem(label='Romanian', label2=sub_info['SubFileName'])
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