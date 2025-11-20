# -*- coding: utf-8 -*-

import os
import re
import shutil
import sys
import unicodedata
import platform
import zipfile
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

sys.path.append (__resource__)

import requests
import PTN
import rarfile

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def log(module, msg):
    try:
        if py3: xbmc.log((u"### [%s] - %s" % (module, msg,)), level=xbmc.LOGDEBUG)
        else: xbmc.log((u"### [%s] - %s" % (module, msg,)).encode('utf-8'), level=xbmc.LOGDEBUG)
    except: pass

def get_unrar_tool_path():
    system = platform.system().lower()
    machine = platform.machine().lower()
    unrar_path = ""
    
    if os.path.exists('/system/build.prop'): # Android
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'android_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'android_arm', 'unrar')
    elif 'linux' in system:
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'linux_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'linux_arm', 'unrar')
    elif 'windows' in system:
        unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'windows_x64', 'UnRAR.exe')

    if unrar_path and os.path.exists(unrar_path):
        if 'windows' not in system:
            try: os.chmod(unrar_path, 0o755)
            except: pass
        log(__name__, "Am gasit unealta unrar la: %s" % unrar_path)
        return unrar_path
    log(__name__, "EROARE: Nu am gasit nicio unealta unrar compatibila.")
    return None

def unpack_archive(archive_path, dest_path, archive_type):
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    all_files = []
    
    # Ne asiguram ca folderul de destinatie exista
    if not xbmcvfs.exists(dest_path):
        xbmcvfs.mkdirs(dest_path)

    if archive_type == 'zip':
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    # Verificam extensia
                    if os.path.splitext(member)[1].lower() in subtitle_exts:
                        # --- MODIFICARE IMPORTANTA: Aplatizare ---
                        # Obtinem doar numele fisierului, ignorand folderele parinte din arhiva
                        filename = os.path.basename(member)
                        
                        # Daca filename e gol (e.g. intrarea e un folder), trecem mai departe
                        if not filename: 
                            continue

                        # Construim calea tinta direct in folderul Extracted (fara subfoldere)
                        target_path = os.path.join(dest_path, filename)
                        
                        # Citim continutul direct din memorie si il scriem in fisierul tinta
                        # Aceasta metoda evita erorile de creare a subfolderelor
                        try:
                            source = zip_ref.open(member)
                            with open(target_path, "wb") as target:
                                shutil.copyfileobj(source, target)
                            source.close()
                            all_files.append(target_path)
                        except Exception as e:
                            log(__name__, "Eroare la scrierea fisierului din ZIP %s: %s" % (filename, str(e)))

        except Exception as e:
            log(__name__, "Eroare la extragerea ZIP: %s" % str(e))
            return []
            
    elif archive_type == 'rar':
        unrar_tool = get_unrar_tool_path()
        if not unrar_tool:
            xbmcgui.Dialog().ok("Unealta RAR lipsa", "Nu s-a gasit un program pentru dezarhivare RAR.")
            return []
        
        rarfile.UNRAR_TOOL = unrar_tool
        try:
            with rarfile.RarFile(archive_path) as rf:
                rf.extractall(path=dest_path)
            
            # La RAR, pentru ca folosim unrar extern care pastreaza structura,
            # folosim os.walk pentru a gasi fisierele oriunde ar fi ele ingropate
            for root, _, files in os.walk(dest_path):
                for file_ in files:
                    if os.path.splitext(file_)[1].lower() in subtitle_exts:
                        all_files.append(os.path.join(root, file_))
        except Exception as e:
            log(__name__, "Eroare la extragerea RAR: %s" % str(e))
            xbmcgui.Dialog().ok("Eroare la extragere RAR", "Arhiva pare corupta sau formatul nu este suportat.")
            return []
            
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

def Search(item):
    try:
        if xbmcvfs.exists(__temp__): shutil.rmtree(__temp__)
        xbmcvfs.mkdirs(__temp__)
    except Exception as e:
        log(__name__, "Eroare la curatarea folderului temp: %s" % str(e))

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
        response = s.get(link, verify=False)
        
        if 'Content-Disposition' not in response.headers:
            log(__name__, "Eroare la descarcare. Antet 'Content-Disposition' lipsa.")
            xbmcgui.Dialog().ok("Eroare", "Descarcarea de pe site a esuat.")
            return

        Type = 'zip'
        content_disp = response.headers['Content-Disposition']
        if 'filename=' in content_disp and '.rar' in content_disp.lower():
            Type = 'rar'
        
        archive_path = os.path.join(__temp__, "subtitle." + Type)
        with open(archive_path, 'wb') as f: f.write(response.content)
        
        extract_path = os.path.join(__temp__, "Extracted")
        all_files = unpack_archive(archive_path, extract_path, Type)

        if not all_files:
            log(__name__, "Extragerea a esuat sau arhiva este goala.")
            xbmcgui.Dialog().ok("Eroare", "Extragerea arhivei a esuat.")
            return
        
        if item.get('season') and item.get('episode'):
            original_file_count = len(all_files)
            subs_list = []
            epstr = '%s:%s' % (item['season'], item['episode'])
            episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
            for sub_file in all_files:
                if episode_regex.search(os.path.basename(sub_file)):
                    subs_list.append(sub_file)
            
            if not subs_list and original_file_count > 0:
                log(__name__, "Nicio subtitrare gasita in arhiva pentru S%sE%s." % (item['season'], item['episode']))
                xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita in arhiva pentru S%sE%s." % (item['season'], item['episode']))
                return

            all_files = subs_list
        
        for ofile in all_files:
            listitem = xbmcgui.ListItem(label=selected_sub["Traducator"], label2=os.path.basename(ofile))
            listitem.setArt({'icon': selected_sub["SubRating"], 'thumb': selected_sub["ISO639"]})
            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(ofile))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    search_term_raw = ""
    # --- START LOGICA DE CAUTARE FINALA, MODELATA DUPA SUBS.RO ---
    if item.get('mansearch'):
        search_term_raw = urllib.unquote(item.get('mansearchstr'))
        log(__name__, "Sursa Cautare: Manuala ('%s')" % search_term_raw)
    else:
        # Prioritatea 1: InfoLabels (TVShowTitle are prioritate maxima)
        search_term_raw = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
        if search_term_raw:
            log(__name__, "Sursa Cautare: InfoLabel TVShowTitle ('%s')" % search_term_raw)
        
        if not search_term_raw:
            search_term_raw = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
            if search_term_raw:
                log(__name__, "Sursa Cautare: InfoLabel OriginalTitle/Title ('%s')" % search_term_raw)

        # Prioritatea 2: Nume Fisier (fallback)
        if not search_term_raw:
            file_path = item.get('file_original_path', '')
            search_term_raw = os.path.basename(file_path)
            log(__name__, "Sursa Cautare: Nume Fisier (fallback) ('%s')" % search_term_raw)
    
    if not search_term_raw:
        log(__name__, "EROARE: Nu am putut determina un termen de cautare.")
        return []

    # --- INCEPUT CURATARE AGRESIVA ---
    # Pas 1: Eliminam tag-urile de formatare Kodi
    clean_term = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_term_raw)
    
    # Pas 2: Eliminam tot ce e in paranteze rotunde sau drepte
    clean_term = re.sub(r'\(.*?\)|\[.*?\]', '', clean_term)
    
    # Pas 3: Folosim PTN pentru a extrage titlul din ce a mai ramas
    parsed = PTN.parse(clean_term)
    final_search_string = parsed.get('title', clean_term)

    # Pas 4: Curatare finala de cuvinte cheie si spatii multiple
    words_to_remove = ['internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb']
    for word in words_to_remove:
        final_search_string = re.sub(r'\b' + re.escape(word) + r'\b', '', final_search_string, flags=re.IGNORECASE)
    
    final_search_string = ' '.join(final_search_string.replace('.', ' ').split()).strip()
    log(__name__, "Termen final de cautare dupa curatare: '%s'" % final_search_string)
    # --- FINAL CURATARE AGRESIVA ---

    search_string_encoded = urllib.quote_plus(final_search_string)
    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    headers = {'User-Agent': ua, 'Host': 'www.titrari.ro', 'Referer': 'https://www.titrari.ro/'}
    search_link = 'https://www.titrari.ro/index.php?page=cautare&z1=0&z2=' + search_string_encoded + '&z3=1&z4=1'
    search_code = s.get(search_link, headers=headers, verify=False).text
    
    regex = '''<h1><a style=color:black href=(index.php\?page=numaicautamcaneiesepenas[^>]+)>(.*?)</a></h1>.*?Traducator: <b><a href=index.php\?page=cautaretraducator.*?>(.*?)</a></b>.*?<a href=get.php\?id=(\d+)>.*?<td class=comment.*?>(.*?)</td>'''
    match = re.compile(regex, re.IGNORECASE | re.DOTALL).findall(search_code)
    
    clean_search = []
    for detail_link, nume, traducator, legatura, descriere in match:
        nume_clean = cleanhtml(nume).strip()
        trad_clean = cleanhtml(traducator).strip()
        desc_clean = cleanhtml(descriere).strip().replace('\r', ' ').replace('\n', ' ')
        
        s_title = "[B]%s[/B] | Trad: [COLOR gold]%s[/COLOR] | %s" % (nume_clean, trad_clean, desc_clean)
        clean_search.append({
            'SubFileName': ' '.join(s_title.split()),
            'ZipDownloadLink': legatura,
            'DetailPageLink': detail_link.replace('&amp;', '&'),
            'Traducator': trad_clean,
            'SubRating': '5', 'ISO639': 'ro'
        })
    return clean_search

def cleanhtml(raw_html): return re.sub(re.compile('<.*?>'), '', raw_html)

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
    
    sub_basename = os.path.basename(link)
    sub_name_part, sub_ext = os.path.splitext(sub_basename)
    lang = "ro"
    
    if not sub_name_part.lower().endswith('.' + lang):
        new_sub_basename = "%s.%s%s" % (sub_name_part, lang, sub_ext)
    else:
        new_sub_basename = sub_basename
            
    safe_sub_name = re.sub(r'[\\/*?:"<>|]', "", new_sub_basename)
    final_temp_path = os.path.join(__temp__, safe_sub_name)
    
    return_path = link
    try:
        if xbmcvfs.copy(link, final_temp_path):
            return_path = final_temp_path
    except: pass
    
    listitem = xbmcgui.ListItem(label=os.path.basename(return_path))
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=return_path, listitem=listitem, isFolder=False)

xbmcplugin.endOfDirectory(int(sys.argv[1]))