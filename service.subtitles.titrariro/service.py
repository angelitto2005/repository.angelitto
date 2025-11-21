# -*- coding: utf-8 -*-

import os
import re
import shutil
import sys
import unicodedata
import platform
import zipfile
import time
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
import subprocess

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

sys.path.append (__resource__)

import requests
import PTN
import rarfile

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def log(module, msg):
    try:
        if py3: xbmc.log((u"### [%s] - %s" % (module, msg,)), level=xbmc.LOGINFO)
        else: xbmc.log((u"### [%s] - %s" % (module, msg,)).encode('utf-8'), level=xbmc.LOGNOTICE)
    except: pass

def get_unrar_tool_path():
    system = platform.system().lower()
    machine = platform.machine().lower()
    unrar_path = ""
    
    bin_path = os.path.join(__cwd__, 'resources', 'bin')
    
    if xbmc.getCondVisibility('System.Platform.Android'):
        # Pe Android teoretic nu folosim binary, dar lasam logica just in case
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(bin_path, 'android_arm64', 'unrar')
        else:
            unrar_path = os.path.join(bin_path, 'android_arm', 'unrar')
            
    elif 'linux' in system:
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(bin_path, 'linux_arm64', 'unrar')
        elif 'arm' in machine:
            unrar_path = os.path.join(bin_path, 'linux_arm', 'unrar')
        else:
            unrar_path = os.path.join(bin_path, 'linux_x86', 'unrar')
            
    elif 'windows' in system:
        unrar_path = os.path.join(bin_path, 'windows_x64', 'UnRAR.exe')

    if unrar_path and os.path.exists(unrar_path):
        if 'windows' not in system:
            try: 
                st = os.stat(unrar_path)
                os.chmod(unrar_path, st.st_mode | 0o111)
            except: pass
        return unrar_path
        
    return None

def unpack_archive(archive_path, dest_path, archive_type):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    all_files = []
    
    if not os.path.exists(dest_path):
        try: os.makedirs(dest_path)
        except: pass

    if archive_type == 'zip':
        log(__name__, "[ZIP] Procesez: %s" % archive_path)
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if os.path.splitext(member)[1].lower() in subtitle_exts:
                        filename = os.path.basename(member)
                        if not filename: continue
                        target_path = os.path.join(dest_path, filename)
                        try:
                            source = zip_ref.open(member)
                            with open(target_path, "wb") as target:
                                shutil.copyfileobj(source, target)
                            all_files.append(target_path)
                        except: pass
        except Exception as e:
            log(__name__, "[ZIP] Eroare: %s" % str(e))
            return []

    elif archive_type == 'rar':
        
        is_android = xbmc.getCondVisibility('System.Platform.Android')
        is_windows = xbmc.getCondVisibility('System.Platform.Windows')

        if not is_android:
            unrar_tool = get_unrar_tool_path()
            if unrar_tool:
                log(__name__, "[RAR-BIN] Windows/Linux detectat. Executie directa (System Call)...")
                try:
                    
                    cmd = [unrar_tool, 'e', '-o+', '-y', '-r', archive_path]
                    
                    for ext in subtitle_exts:
                        cmd.append('*' + ext)
                    
                    cmd.append(dest_path) # Unrar pune backslash automat daca e folder

                    startupinfo = None
                    if is_windows:
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                    subprocess.call(cmd, startupinfo=startupinfo)
                    
                    for f in os.listdir(dest_path):
                        if os.path.splitext(f)[1].lower() in subtitle_exts:
                            full_path = os.path.join(dest_path, f)
                            if os.path.getsize(full_path) > 0:
                                all_files.append(full_path)

                    log(__name__, "[RAR-BIN] Gata! %d fisiere disponibile." % len(all_files))
                    
                except Exception as e:
                    log(__name__, "[RAR-BIN] Eroare subprocess: %s" % str(e))
            else:
                log(__name__, "[RAR-BIN] EROARE: Nu am gasit unrar!")

        else:
            log(__name__, "[RAR] Android detectat. Folosesc VFS.")
            if not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
                xbmcgui.Dialog().ok("Eroare", "Instalati 'RAR archive support'!")
                return []

            try:
                workaround_rar = os.path.join(dest_path, "temp_vfs.rar")
                if os.path.exists(workaround_rar): os.remove(workaround_rar)
                shutil.copyfile(archive_path, workaround_rar)
                
                norm_path = workaround_rar.replace('\\', '/')
                if not norm_path.startswith('/'): norm_path = '/' + norm_path
                
                if py3: encoded_base = urllib.quote(norm_path, safe='')
                else: encoded_base = urllib.quote(str(norm_path), safe='')
                
                rar_url_base = 'rar://' + encoded_base + '/'

                def scan_flatten(curr_url):
                    found = []
                    try: dirs, files = xbmcvfs.listdir(curr_url)
                    except: return []

                    for f in files:
                        f_n = f
                        if not py3 and isinstance(f, str): f_n = f.decode('utf-8','ignore')
                        if os.path.splitext(f_n)[1].lower() in subtitle_exts:
                            if curr_url.endswith('/'): src = curr_url + f_n
                            else: src = curr_url + '/' + f_n
                            dst = os.path.join(dest_path, f_n)
                            try:
                                vfs_file = xbmcvfs.File(src)
                                content = None
                                try: content = vfs_file.readBytes()
                                except: 
                                    try: content = vfs_file.read()
                                    except: pass
                                vfs_file.close()
                                if content:
                                    with open(dst, 'wb') as f_out:
                                        f_out.write(content)
                                        f_out.flush()
                                        os.fsync(f_out.fileno())
                                    if os.path.getsize(dst) > 0: found.append(dst)
                            except: pass
                    
                    for d in dirs:
                        d_n = d
                        if not py3 and isinstance(d, str): d_n = d.decode('utf-8','ignore')
                        if curr_url.endswith('/'): next_url = curr_url + d_n + '/'
                        else: next_url = curr_url + '/' + d_n + '/'
                        found.extend(scan_flatten(next_url))
                    return found

                all_files = scan_flatten(rar_url_base)
                log(__name__, "[RAR-VFS] Fisiere: %d" % len(all_files))
                try:
                    time.sleep(0.5)
                    if os.path.exists(workaround_rar): os.remove(workaround_rar)
                except: pass

            except Exception as e:
                log(__name__, "[RAR-VFS] Eroare: %s" % str(e))

    return all_files

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2: return "%%%%%"
    try:
        season, epnr = int(parts[0]), int(parts[1])
        patterns = ["s%#02de%#02d" % (season, epnr), "%#02dx%#02d" % (season, epnr), "%#01de%#02d" % (season, epnr)]
        if season < 10: patterns.append("(?:\A|\D)%dx%#02d" % (season, epnr))
        return '(?:%s)' % '|'.join(patterns)
    except: return "%%%%%"

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

def Search(item):
    try:
        if os.path.exists(__temp__):
            shutil.rmtree(__temp__, ignore_errors=True)
        
        os.makedirs(__temp__)

        target_name = 'vfs.rar-temp'
        
        paths_to_check = []

        path_linux_android = os.path.join(xpath('special://temp/'), 'addons', target_name)
        paths_to_check.append(path_linux_android)

        path_windows_cache = os.path.join(xpath('special://home/'), 'cache', 'addons', target_name)
        paths_to_check.append(path_windows_cache)

        path_android_home = os.path.join(xpath('special://home/'), 'temp', 'addons', target_name)
        paths_to_check.append(path_android_home)

        for p in paths_to_check:
            if p.endswith(target_name) and os.path.exists(p):
                try:
                    shutil.rmtree(p, ignore_errors=True)
                    log(__name__, "[Cleanup] Gunoi VFS sters: %s" % p)
                except Exception as e:
                    log(__name__, "[Cleanup] Nu am putut sterge VFS (%s): %s" % (p, str(e)))

    except Exception as e:
        log(__name__, "[Cleanup] Eroare la initializare temp: %s" % str(e))
        return

    search_data = searchsubtitles(item)
    if not search_data:
        xbmcplugin.endOfDirectory(int(sys.argv[1]))
        return
        
    dialog = xbmcgui.Dialog()
    sel = 0
    if len(search_data) > 1:
        sel = dialog.select("Selectati subtitrarea", [sub["SubFileName"] for sub in search_data])
    
    if sel >= 0:
        selected_sub = search_data[sel]
        s = requests.Session()
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        s.headers.update({'User-Agent': ua, 'Referer': 'https://www.titrari.ro/' + selected_sub["DetailPageLink"]})
        
        link = 'https://www.titrari.ro/get.php?id=' + selected_sub["ZipDownloadLink"]
        try:
            response = s.get(link, verify=False)
        except Exception as e:
            xbmcgui.Dialog().ok("Eroare", str(e))
            return
        
        content_disp = response.headers.get('Content-Disposition', '')
        Type = 'zip'
        if 'filename=' in content_disp and '.rar' in content_disp.lower():
            Type = 'rar'
        
        archive_path = os.path.join(__temp__, "subtitle." + Type)
        
        try:
            with open(archive_path, 'wb') as f: 
                f.write(response.content)
                f.flush()
                os.fsync(f.fileno())
            log(__name__, "Arhiva salvata: %s" % archive_path)
        except Exception as e:
            log(__name__, "Eroare scriere disc: %s" % str(e))
            xbmcgui.Dialog().ok("Eroare", "Nu s-a putut salva arhiva.")
            return
        
        extract_path = os.path.join(__temp__, "Extracted")
        all_files = unpack_archive(archive_path, extract_path, Type)

        if not all_files:
            log(__name__, "Extragerea a esuat.")
            xbmcgui.Dialog().ok("Eroare", "Nu s-au putut extrage subtitrari din arhiva.")
            return
        
        if item.get('season') and item.get('episode'):
            original_file_count = len(all_files)
            subs_list = []
            epstr = '%s:%s' % (item['season'], item['episode'])
            episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
            for sub_file in all_files:
                if episode_regex.search(os.path.basename(sub_file)):
                    subs_list.append(sub_file)
            
            if subs_list:
                all_files = subs_list
        
        for ofile in all_files:
            
            lang_code = selected_sub["ISO639"]
            lang_label = "Romanian" if lang_code == 'ro' else lang_code

            listitem = xbmcgui.ListItem(label=lang_label, label2=os.path.basename(ofile))
            
            listitem.setArt({'icon': selected_sub["SubRating"], 'thumb': lang_code})
            listitem.setProperty("language", lang_code)
            listitem.setProperty("sync", "false") 

            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(ofile))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    search_term_raw = ""
    if item.get('mansearch'):
        search_term_raw = urllib.unquote(item.get('mansearchstr'))
    else:
        search_term_raw = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
        if not search_term_raw:
            search_term_raw = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
        if not search_term_raw:
            file_path = item.get('file_original_path', '')
            search_term_raw = os.path.basename(file_path)
    
    if not search_term_raw: return []

    clean_term = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_term_raw)
    clean_term = re.sub(r'\(.*?\)|\[.*?\]', '', clean_term)
    parsed = PTN.parse(clean_term)
    final_search_string = parsed.get('title', clean_term)

    words_to_remove = ['internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb']
    for word in words_to_remove:
        final_search_string = re.sub(r'\b' + re.escape(word) + r'\b', '', final_search_string, flags=re.IGNORECASE)
    
    final_search_string = ' '.join(final_search_string.replace('.', ' ').split()).strip()
    
    search_string_encoded = urllib.quote_plus(final_search_string)
    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    headers = {'User-Agent': ua, 'Host': 'www.titrari.ro', 'Referer': 'https://www.titrari.ro/'}
    search_link = 'https://www.titrari.ro/index.php?page=cautare&z1=0&z2=' + search_string_encoded + '&z3=1&z4=1'
    
    try:
        search_code = s.get(search_link, headers=headers, verify=False).text
    except: return []
    
    regex = '''<h1><a style=color:black href=(index.php\?page=numaicautamcaneiesepenas[^>]+)>(.*?)</a></h1>.*?Traducator: <b><a href=index.php\?page=cautaretraducator.*?>(.*?)</a></b>.*?<a href=get.php\?id=(\d+)>.*?<td class=comment.*?>(.*?)</td>'''
    match = re.compile(regex, re.IGNORECASE | re.DOTALL).findall(search_code)
    
    clean_search = []
    
    req_season = item.get('season', '0')
    filter_active = False
    curr_s = 0
    if req_season and req_season not in ('0', '-1', ''):
        try:
            curr_s = int(req_season)
            filter_active = True
        except: pass

    for detail_link, nume, traducator, legatura, descriere in match:
        nume_clean = cleanhtml(nume).strip()
        trad_clean = cleanhtml(traducator).strip()
        desc_clean = cleanhtml(descriere).strip().replace('\r', ' ').replace('\n', ' ')
        
        if filter_active:
            try:
                text_to_check = (nume_clean + " " + desc_clean).lower()
                is_match = False
                match_range = re.search(r'(?:sez|seas|series)\w*\W*(\d+)\s*-\s*(\d+)', text_to_check)
                match_single = re.search(r'(?:sez|seas|series|s)\w*\W*0*(\d+)', text_to_check)

                if match_range:
                    s_start, s_end = int(match_range.group(1)), int(match_range.group(2))
                    if s_start <= curr_s <= s_end: is_match = True
                elif match_single:
                    if int(match_single.group(1)) == curr_s: is_match = True
                
                if not is_match: continue
            except: continue

        s_title = "[B]%s[/B] | Trad: [B][COLOR FF00FA9A]%s[/COLOR][/B] | %s" % (nume_clean, trad_clean, desc_clean)
        clean_search.append({
            'SubFileName': ' '.join(s_title.split()),
            'ZipDownloadLink': legatura,
            'DetailPageLink': detail_link.replace('&amp;', '&'),
            'Traducator': trad_clean,
            'SubRating': '5', 'ISO639': 'ro'
        })
    return clean_search

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
        if 'season' in parsed_data: season = str(parsed_data['season'])
        if 'episode' in parsed_data: episode = str(parsed_data['episode'])
            
    item = {
        'mansearch': action == 'manualsearch',
        'file_original_path': file_original_path,
        'season': season if season and season != "-1" else "", 
        'episode': episode if episode and episode != "-1" else ""
    }
    if item['mansearch']: item['mansearchstr'] = params.get('searchstring', '')
    Search(item)

elif action == 'setsub':
    link = urllib.unquote_plus(params.get('link', ''))
    
    if link and os.path.exists(link):
        folder = os.path.dirname(link)
        filename = os.path.basename(link)
        name, ext = os.path.splitext(filename)
        
        if not '.ro.' in filename.lower() and not name.lower().endswith('.ro'):
            new_filename = "%s.ro%s" % (name, ext)
            new_path = os.path.join(folder, new_filename)
            try:
                os.rename(link, new_path)
                link = new_path
                log(__name__, "Fisier redenumit: %s" % link)
            except Exception as e:
                log(__name__, "Eroare redenumire: %s" % str(e))

        listitem = xbmcgui.ListItem(label=os.path.basename(link))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=link, listitem=listitem, isFolder=False)
        
        def set_sub_delayed():
            time.sleep(1.5)
            xbmc.Player().setSubtitles(link)

        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))