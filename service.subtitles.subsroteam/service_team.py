# -*- coding: utf-8 -*-

import json
from operator import itemgetter
import os
import re
import sys
import time
import unicodedata
import urllib
try: 
    import urllib2
    import urllib
    py3 = False
except ImportError: 
    import urllib.request as urllib2
    import urllib.parse as urllib
    py3 = True
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

import platform
import stat

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

BASE_URL = "https://subs.ro/"

sys.path.append (__resource__)
import requests
from bs4 import BeautifulSoup
import rarfile

from requests.packages. urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

SEASON_WORDS_TO_NUM = {
    'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
    'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10,
    'eleventh': 11, 'twelfth': 12, 'thirteenth': 13, 'fourteenth': 14,
    'fifteenth': 15
}

def log(msg):
    log_level = xbmc.LOGINFO if py3 else xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s] - %s" % (__scriptid__, str(msg)), level=log_level)
    except Exception: pass

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

def get_unrar_path():
    if xbmc.getCondVisibility('System.Platform.Android | System.Platform.IOS | System.Platform.TVOS | System.Platform.UWP'):
        log("Metoda de rezerva nu poate continua. Platforma curenta nu este suportata.")
        return None

    platform_key = None
    system = platform.system()

    if xbmc.getCondVisibility('System.Platform.Windows'):
        platform_key = 'windows_x64'
    elif xbmc.getCondVisibility('System.Platform.OSX'):
        platform_key = 'darwin_x64'
    elif xbmc.getCondVisibility('System.Platform.Linux'):
        machine = platform.machine().lower()
        if 'x86_64' in machine or 'amd64' in machine:
            platform_key = 'linux_x86_64'
        elif 'arm' in machine or 'aarch64' in machine:
            platform_key = 'linux_arm'
    
    if not platform_key:
        log("Metoda de rezerva nu poate continua. Platforma ('%s') nu corespunde niciunei configuratii suportate." % system)
        return None

    unrar_path = os.path.join(__resource__, 'bin', platform_key, 'unrar.exe' if platform_key == 'windows_x64' else 'unrar')

    if os.path.exists(unrar_path):
        if not platform_key.startswith('windows'):
            try:
                st = os.stat(unrar_path)
                os.chmod(unrar_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            except Exception as e:
                log("EROARE la setarea permisiunilor pentru unrar: %s" % e)
                return None
        return unrar_path
    else:
        log("Metoda de rezerva nu poate continua. Fisierul unrar asteptat la '%s' nu a fost gasit." % unrar_path)
        return None

def unpack_archive_fallback(archive_physical_path, dest_physical_path, unrar_exec_path):
    rarfile.UNRAR_TOOL = unrar_exec_path
    all_files, txt_count = [], 0
    subtitle_exts = [".srt", ".sub", ".smi", ".ssa", ".ass"]
    
    try:
        log("Initializare extragere de rezerva cu rarfile...")
        log("Folosind unrar de la: %s" % unrar_exec_path)
        with rarfile.RarFile(archive_physical_path) as rf:
            if not os.path.exists(dest_physical_path):
                os.makedirs(dest_physical_path)
            rarfile.PATH_SEP = '/'
            rf.extractall(path=dest_physical_path)
            log("Arhiva extrasa cu succes (metoda de rezerva) in: %s" % dest_physical_path)
            
            for member in rf.infolist():
                if not member.isdir():
                    file_ext = os.path.splitext(member.filename)[1].lower()
                    if file_ext in subtitle_exts:
                        extracted_file_path = os.path.join(dest_physical_path, member.filename.replace('\\', '/'))
                        all_files.append(extracted_file_path)
                    elif file_ext == ".txt":
                        txt_count += 1
                        
        log("Extragerea de rezerva a finalizat. S-au gasit %d fisiere de subtitrare si %d fisiere txt." % (len(all_files), txt_count))
        return all_files, txt_count
    except Exception as e:
        log("EROARE fatala in timpul extragerii de rezerva cu rarfile: %s" % e)
        return [], 0

def unpack_archive(archive_physical_path, dest_physical_path, archive_type):
    subtitle_exts = [".srt", ".sub", ".smi", ".ssa", ".ass"]
    txt_count = 0
    all_files = []
    
    try:
        normalized_archive_path = archive_physical_path.replace('\\', '/')
        vfs_archive_path = '%s://%s' % (archive_type, urllib.quote_plus(normalized_archive_path))
        
        log("Initializez extragerea...")
        log("Copiez continutul arhivei...")
        
        def recursive_unpack(current_vfs_path, current_dest_path):
            nonlocal txt_count
            extracted_list = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                
                if not xbmcvfs.exists(current_dest_path):
                    xbmcvfs.mkdirs(current_dest_path)

                for file_name in files:
                    if not py3 and isinstance(file_name, bytes):
                        file_name = file_name.decode('utf-8')

                    file_ext = os.path.splitext(file_name)[1].lower()

                    if file_ext == ".txt":
                        txt_count += 1
                        continue
                    
                    if file_ext in subtitle_exts:
                        source_vfs_file = current_vfs_path + '/' + file_name
                        dest_physical_file = os.path.join(current_dest_path, file_name)
                        
                        try:
                            source_obj = xbmcvfs.File(source_vfs_file, 'r')
                            dest_obj = xbmcvfs.File(dest_physical_file, 'wb')
                            content = source_obj.readBytes()
                            dest_obj.write(content)
                            source_obj.close()
                            dest_obj.close()
                            extracted_list.append(dest_physical_file)
                        except Exception as e:
                            log("EROARE la copierea fisierului %s: %s" % (file_name, e))

                for dir_name in dirs:
                    if not py3 and isinstance(dir_name, bytes):
                        dir_name = dir_name.decode('utf-8')
                        
                    next_vfs_path = current_vfs_path + '/' + dir_name
                    next_dest_path = os.path.join(current_dest_path, dir_name)
                    extracted_list.extend(recursive_unpack(next_vfs_path, next_dest_path))
            
            except Exception as e:
                log("EROARE in timpul recursivitatii VFS pentru calea %s: %s" % (current_vfs_path, e))

            return extracted_list

        all_files = recursive_unpack(vfs_archive_path, dest_physical_path)
        return all_files, txt_count

    except Exception as e:
        log("EROARE fatala la initializarea extragerii arhivei: %s" % e)
        return [], 0

def Search(item):
    temp_dir = __temp__
    try:
        if xbmcvfs.exists(temp_dir):
            log("Directorul temporar vechi a fost gasit. Se incearca stergerea: %s" % temp_dir)
            deleted = xbmcvfs.rmdir(temp_dir, True)
            if not deleted:
                log("EROARE CRITICA: Nu s-a putut sterge directorul temporar vechi. Pot aparea subtitrari vechi.")
        
        log("Se creeaza un director temporar nou si gol: %s" % temp_dir)
        xbmcvfs.mkdirs(temp_dir)
    except Exception as e:
        log("EROARE la initializarea directorului temporar: %s" % str(e))
        return

    search_item = item.copy()
    definitive_sort_item = None
    
    while True:
        filtered_subs, raw_count, active_filters, original_item, is_tv_show, all_were_wrong_season, is_fallback, is_manual = searchsubtitles(search_item)
        
        if definitive_sort_item is None:
            definitive_sort_item = original_item.copy()

        if not filtered_subs:
            dialog = xbmcgui.Dialog()

            if raw_count == 0:
                if is_manual:
                    msg = "Nicio subtitrare găsită. Verificați dacă titlul este scris corect.[CR]Atenție la lipsa apostrofurilor. De exemplu: Greys vs. Grey's."
                    choice = dialog.yesno(__scriptname__, msg, yeslabel="Reîncearcă", nolabel="Închide")
                    if choice:
                        search_item['mansearch'] = True
                        search_item.pop('mansearchstr', None)
                        continue
                    else:
                        break
                
                elif not is_fallback:
                    if is_tv_show:
                        dialog.ok(__scriptname__, "Nu s-au găsit subtitrări pentru acest serial.")
                    else:
                        dialog.ok(__scriptname__, "Nu s-au găsit subtitrări pentru acest film.")
                    break
                
                else:
                    msg = "Nicio subtitrare găsită. Încercați și Căutarea Manuală.[CR]Verificați dacă titlul este scris corect. Atenție la lipsa apostrofurilor."
                    choice = dialog.yesno(__scriptname__, msg, yeslabel="Căutare Manuală", nolabel="Închide")
                    if choice:
                        search_item['mansearch'] = True
                        search_item.pop('mansearchstr', None)
                        continue
                    else:
                        break
            
            elif is_tv_show and all_were_wrong_season:
                if is_fallback and not is_manual:
                    search_year_p3 = original_item.get('search_year_p3')
                    if search_year_p3:
                        msg = "Nicio potrivire găsită pentru combinația de titlu, an și sezon extrase din fișier."
                    else:
                        msg = "Nicio potrivire găsită pentru combinația de titlu și sezon extrase din fișier."
                    msg += "[CR]Dacă optați pentru o Căutare Manuală, verificați și dacă titlul este scris corect."
                    
                    choice = dialog.yesno(__scriptname__, msg, yeslabel="Căutare Manuală", nolabel="Închide")
                    if choice:
                        search_item = original_item.copy()
                        search_item['mansearch'] = True
                        search_item.pop('mansearchstr', None)
                        continue
                    else:
                        break
                else:
                    msg_l1 = "Nu s-au găsit subtitrări pentru Sezonul %s al acestui Serial." % original_item.get('season')
                    msg_l2 = "Există însă rezultate nespecificate sau pentru alte sezoane."
                    msg_l3 = "Doriți să le afișați oricum?"

                    choice = dialog.yesno(__scriptname__, f"{msg_l1}[CR]{msg_l2}[CR]{msg_l3}", yeslabel="Afișează Rezultatele", nolabel="Închide")
                    
                    if not choice:
                        break

                    log("Utilizatorul a cerut afisarea tuturor sezoanelor. Se re-apeleaza cautarea.")
                    search_item = original_item.copy()
                    search_item['season'] = '0'
                    search_item['non_interactive'] = True
                    continue

            elif active_filters and raw_count > 0:
                msg_l1 = "Nicio subtitrare găsită conform preferințelor de limbă selectate."
                msg_l2 = "Doriți să afișați rezultatele pentru toate limbile?"

                choice = dialog.yesno(__scriptname__, f"{msg_l1}[CR]{msg_l2}", yeslabel="Afișează Rezultatele", nolabel="Închide")

                if not choice:
                    break

                log("Utilizatorul a cerut afisarea tuturor limbilor. Se re-apeleaza cautarea.")
                
                search_item = original_item.copy()
                if all_were_wrong_season:
                    search_item['season'] = '0'
                
                search_item['ignore_lang_filter'] = True
                search_item['non_interactive'] = True
                continue
            
            else:
                break

        else:
            break

    if not filtered_subs:
        return

    sel = 0
    if len(filtered_subs) > 0:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in filtered_subs]
        sel = dialog.select("Selectați subtitrarea", titles)
    
    if sel >= 0:
        selected_sub_info = filtered_subs[sel]
        link = selected_sub_info["ZipDownloadLink"]
        
        s = requests.Session()
        s.headers.update({'Referer': BASE_URL})
        response = s.get(link, verify=False)
        
        content_disp = response.headers.get('Content-Disposition', '')
        Type = 'zip'
        if 'filename=' in content_disp:
            try:
                fname_header = re.findall('filename="?([^"]+)"?', content_disp)[0]
                if fname_header.lower().endswith('.rar'): Type = 'rar'
            except: pass

        if Type == 'rar' and not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
            log("EROARE: Add-on-ul 'vfs.rar' (RAR archive support) nu este instalat.")
            xbmcgui.Dialog().ok("Componentă lipsă", "Pentru a extrage arhive RAR, instalați 'RAR archive support' din repository-ul oficial Kodi.")
            return

        timestamp = str(int(time.time()))
        fname = os.path.join(temp_dir, "subtitle_%s.%s" % (timestamp, Type))
        
        try:
            f = xbmcvfs.File(fname, 'wb')
            f.write(response.content)
            f.close()
            log("Fisier arhiva salvat la: %s" % fname)
        except Exception as e:
            log("EROARE la scrierea fisierului arhiva: %s" % e)
            xbmcgui.Dialog().ok("Eroare la Salvare", "Nu s-a putut salva arhiva de subtitrări.[CR]Verificați permisiunile sau spațiul de stocare.")
            return

        extractPath = os.path.join(temp_dir, "Extracted")
        if not xbmcvfs.exists(extractPath):
            xbmcvfs.mkdirs(extractPath)
        
        all_files, txt_count = unpack_archive(fname, extractPath, Type)
        
        if not all_files and txt_count == 0 and Type == 'zip':
            log("Extragerea a esuat sau nu s-au gasit fisiere de subtitrare.")
            xbmcgui.Dialog().ok("Eroare la extragere", "Arhiva descărcată este goală sau coruptă.[CR]Nu s-a găsit nicio subtitrare validă.")
            return
        
        valid_files = []
        zero_kb_count = 0
        if all_files:
            for f in all_files:
                try:
                    if xbmcvfs.Stat(f).st_size() > 0:
                        valid_files.append(f)
                    else:
                        zero_kb_count += 1
                except Exception as e:
                    log("EROARE la verificarea marimii fisierului %s: %s" % (f, e))
        
        if not valid_files and Type == 'rar':
            log("Metoda VFS a esuat pentru arhiva RAR (fisiere de 0 KB). Se incearca metoda de rezerva...")
            
            unrar_path_for_fallback = get_unrar_path()
            
            if unrar_path_for_fallback:
                all_files, txt_count = unpack_archive_fallback(fname, extractPath, unrar_path_for_fallback)
                
                if all_files:
                    zero_kb_count = 0
                    for f in all_files:
                        try:
                            if xbmcvfs.Stat(f).st_size() > 0:
                                valid_files.append(f)
                            else:
                                zero_kb_count += 1
                        except Exception as e:
                            log("EROARE (fallback) la verificarea marimii fisierului %s: %s" % (f, e))
            else:
                xbmcgui.Dialog().ok(__scriptname__, "Dezarhivare eșuată. Arhiva RAR nu a putut fi extrasă pe această platformă.")
                return

        if zero_kb_count > 0:
            log("S-au gasit %d fisiere de 0 KB care au fost ignorate." % zero_kb_count)

        if not valid_files:
            log("EROARE: Toate fisierele extrase au 0 KB.")
            if Type == 'rar':
                xbmcgui.Dialog().ok(__scriptname__, "Dezarhivare eșuată. Arhiva RAR este probabil coruptă.")
            elif Type == 'zip':
                xbmcgui.Dialog().ok(__scriptname__, "Dezarhivare eșuată. Arhiva ZIP este goală sau coruptă.")
            return

        all_files = valid_files
        
        log_msg = "S-au gasit %d fisiere de subtitrare valide dupa extragere." % len(all_files)
        if txt_count > 0:
            log_msg += " Am exclus %d fisiere TXT nevalide." % txt_count
        log(log_msg)
        
        subs_list = []
        season, episode = definitive_sort_item.get("season"), definitive_sort_item.get("episode")
        is_tv_show_case = (season and season != "0")

        if is_tv_show_case:
            season_int = int(season)
            
            if episode and episode != "0":
                log("Filtrez pentru Sezonul %s Episodul %s" % (season, episode))
                episode_int = int(episode)

                for sub_file in all_files:
                    s_num, e_num = extract_season_episode(os.path.basename(sub_file))
                    if s_num == season_int and e_num == episode_int:
                        subs_list.append(sub_file)

                if subs_list:
                    log("Am gasit %d subtitrari potrivite pentru S%sE%s." % (len(subs_list), season, episode))
                    all_files = sorted(subs_list, key=lambda f: natural_key(os.path.basename(f)))
                else:
                    log("Nicio potrivire gasita pentru S/E specific. Se afiseaza toate fisierele in ordine descrescatoare dupa S/E.")
                    all_files = sorted(all_files, key=lambda f: extract_season_episode(os.path.basename(f)), reverse=True)

            else:
                log("Season Pack: Filtrez fisierele doar pentru sezonul %s." % season)
                season_matches = []
                for sub_file in all_files:
                    s_num, _ = extract_season_episode(os.path.basename(sub_file))
                    if s_num == season_int:
                        season_matches.append(sub_file)
                
                if season_matches:
                    log("Am gasit %d fisiere potrivite pentru sezon. Le sortez crescator." % len(season_matches))
                    all_files = sorted(season_matches, key=lambda f: extract_season_episode(os.path.basename(f)))
                else:
                    log("Nu am gasit niciun fisier specific sezonului. Se afiseaza toate fisierele in ordine descrescatoare dupa S/E.")
                    all_files = sorted(all_files, key=lambda f: extract_season_episode(os.path.basename(f)), reverse=True)
        else:
            all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))
        
        for sub_file in all_files:
            basename = normalizeString(os.path.basename(sub_file))
            iso_lang = selected_sub_info["ISO639"]
            
            listitem = xbmcgui.ListItem(label=selected_sub_info['LanguageName'], label2=basename)
            listitem.setArt({'icon': selected_sub_info["SubRating"], 'thumb': iso_lang})
            listitem.setProperty('language', iso_lang)
            
            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(sub_file))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)
        
    return

def searchsubtitles(item):
    import PTN
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,ro;q=0.8', 'Origin': BASE_URL.rstrip('/'), 'Referer': BASE_URL + 'cautare'
    })
    
    languages_to_keep = []
    
    if item.get('ignore_lang_filter'):
        log("Filtrul de limba a fost ignorat la cerere.")
        languages_to_keep = []
    else:
        filter_mode = __addon__.getSetting('filter_mode')

        if filter_mode == '0':
            log("Modul de filtrare este 'Oricare'. Se vor afisa toate limbile.")
            languages_to_keep = []
        else:
            log("Modul de filtrare este 'Selecteaza Manual'.")
            defined_languages = [
                ('ro', 'lang_ro'), ('en', 'lang_en'), ('fr', 'lang_fr'), ('it', 'lang_it'),
                ('es', 'lang_es'), ('pt', 'lang_pt'), ('de', 'lang_de'), ('hu', 'lang_hu'),
                ('el', 'lang_el')
            ]
            
            for lang_code, setting_id in defined_languages:
                if __addon__.getSettingBool(setting_id):
                    languages_to_keep.append(lang_code)
            
            log("Vom pastra doar subtitrarile pentru limbile: %s" % languages_to_keep)

    season_str = item.get('season', '0')
    is_tv_show = bool(season_str and season_str.isdigit() and season_str != '0')
    required_season = int(season_str) if season_str.isdigit() else 0

    tmdb_id = xbmc.getInfoLabel("VideoPlayer.TVShow.TMDbId") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    if tmdb_id and tmdb_id.isdigit():
        log("Prioritate 1: Am gasit TMDB ID: %s. Incercam cautarea..." % tmdb_id)
        post_data = {'type': 'subtitrari', 'external_id': tmdb_id}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content is not None:
            soup = BeautifulSoup(html_content, 'html.parser')
            results_html = soup.find_all('div', class_=re.compile(r'w-full bg-\[#F5F3E8\]'))
            log("Am gasit in total %d rezultate unice." % len(results_html))
            subs, raw_count, all_wrong = parse_results(results_html, languages_to_keep, is_tv_show, required_season)
            return subs, raw_count, bool(languages_to_keep), item, is_tv_show, all_wrong, False, False

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
    if imdb_id and imdb_id.startswith('tt'):
        imdb_id_numeric = imdb_id.replace("tt", "")
        log("Prioritate 2: Am gasit IMDB ID: %s. Incercam cautarea cu ID numeric: %s." % (imdb_id, imdb_id_numeric))
        post_data = {'type': 'subtitrari', 'external_id': imdb_id_numeric}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content is not None:
            soup = BeautifulSoup(html_content, 'html.parser')
            results_html = soup.find_all('div', class_=re.compile(r'w-full bg-\[#F5F3E8\]'))
            log("Am gasit in total %d rezultate unice." % len(results_html))
            subs, raw_count, all_wrong = parse_results(results_html, languages_to_keep, is_tv_show, required_season)
            return subs, raw_count, bool(languages_to_keep), item, is_tv_show, all_wrong, False, False

    if item.get('mansearch') and item.get('mansearchstr'):
        search_string_raw = urllib.unquote_plus(item.get('mansearchstr', ''))
    else:
        original_path = item.get('file_original_path', '')
        search_string_raw = os.path.basename(original_path) if not original_path.startswith('http') else item.get('title', '')
    
    cleaned_string = re.sub(r'\[.*?\]', '', search_string_raw)
    cleaned_string = cleaned_string.replace('.', ' ').replace('_', ' ')
    
    noise_tags = ['FREELEECH', 'INTERNAL', 'PROPER', 'REPACK', 'READNFO', 'SUBS', '2XUPLOAD', 'ROMANIAN']
    noise_pattern = r'\b(' + '|'.join(noise_tags) + r')\b'
    cleaned_string = re.sub(noise_pattern, '', cleaned_string, flags=re.IGNORECASE)
    cleaned_string = re.sub(r'\s+', ' ', cleaned_string).strip()

    parsed = PTN.parse(cleaned_string)
    
    initial_search_title = parsed.get('title')
    if not initial_search_title:
        initial_search_title = cleaned_string

    country_codes_to_check = ['AL', 'AD', 'AT', 'BY', 'BE', 'BA', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IS', 'IE', 'IT', 'LV', 'LI', 'LT', 'LU', 'MT', 'MD', 'MC', 'ME', 'NL', 'MK', 'NO', 'PL', 'PT', 'RO', 'RU', 'SM', 'RS', 'SK', 'SI', 'ES', 'SE', 'CH', 'TR', 'UA', 'UK', 'VA', 'US', 'CA', 'AU', 'NZ', 'JP', 'KR', 'CN', 'IN', 'BR', 'MX']
    title_words = initial_search_title.split()
    if len(title_words) > 1:
        last_word = title_words[-1]
        if last_word.isupper() and last_word in country_codes_to_check:
            initial_search_title = ' '.join(title_words[:-1])
    
    search_year = parsed.get('year')
    
    item['search_year_p3'] = search_year
    
    if not is_tv_show:
        if parsed.get('season'): is_tv_show = True
    
    if not item.get('season') or item.get('season') == '0':
        item['season'] = str(parsed.get('season', '0'))
    if not item.get('episode') or item.get('episode') == '0':
        item['episode'] = str(parsed.get('episode', '0'))
    
    season_str = item.get('season', '0')
    is_tv_show = bool(season_str and season_str.isdigit() and season_str != '0')
    required_season = int(season_str) if season_str.isdigit() else 0
    
    log_season = item.get('season')
    log_episode = item.get('episode')
    log_msg = "Prioritate 3: Am extras din fisier titlul %s" % initial_search_title
    if search_year: log_msg += " anul %s" % search_year
    if log_season and log_season != "0": log_msg += " Sezonul %s" % log_season
    if log_episode and log_episode != "0": log_msg += " Episodul %s" % log_episode
    log(log_msg + ".")

    choice_is_manual = False
    if not item.get('non_interactive') and not item.get('mansearch') and __addon__.getSetting('search_mode') == '0':
        dialog = xbmcgui.Dialog()
        dialog_message = (
            "Nu se poate efectua căutarea după TMDB/IMDB ID.\n"
            "Vom folosi căutarea după denumirea torrentului/fișierului."
        )
        choice_is_manual = dialog.yesno(__scriptname__, dialog_message, yeslabel="Căutare Manuală", nolabel="Căutare Automată")

    is_manual_search_active = item.get('mansearch') or choice_is_manual

    if is_manual_search_active:
        if item.get('mansearch') and item.get('mansearchstr'):
            search_title = urllib.unquote_plus(item.get('mansearchstr'))
            log("Folosesc cautarea manuala anterioara: '%s'" % search_title)
        else:
            log("Utilizatorul a ales Cautare Manuala.")
            keyboard = xbmc.Keyboard(initial_search_title, "Introduceți titlul pentru căutare")
            keyboard.doModal()
            if keyboard.isConfirmed() and keyboard.getText():
                search_title = keyboard.getText()
                item['mansearch'] = True
                item['mansearchstr'] = urllib.quote_plus(search_title)
                search_year = None
                log("Cautare manuala cu titlul: '%s'" % search_title)
            else:
                log("Cautare manuala anulata.")
                return ([], 0, False, item, is_tv_show, False, True, True)
    else:
        log("Utilizatorul a ales Cautare Automata.")
        search_title = initial_search_title
    
    search_terms_set = {search_title}
    if re.search(r'\band\b', search_title, re.IGNORECASE):
        search_terms_set.add(re.sub(r'\band\b', '&', search_title, flags=re.IGNORECASE))
    elif ' & ' in search_title:
        search_terms_set.add(search_title.replace(' & ', ' and '))

    ROMAN_TO_ARABIC = {'II': '2', 'III': '3', 'IV': '4', 'V': '5', 'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10'}
    ARABIC_TO_ROMAN = {v: k for k, v in ROMAN_TO_ARABIC.items()}

    for roman, arabic in ROMAN_TO_ARABIC.items():
        pattern = r'\b' + re.escape(roman) + r'\b'
        if re.search(pattern, search_title, re.IGNORECASE):
            search_terms_set.add(re.sub(pattern, arabic, search_title, flags=re.IGNORECASE))
    
    for arabic, roman in ARABIC_TO_ROMAN.items():
        pattern = r'\b' + re.escape(arabic) + r'\b'
        if re.search(pattern, search_title):
            search_terms_set.add(re.sub(pattern, roman, search_title))
    
    search_terms = list(search_terms_set)
    combined_results_html = []
    seen_links = set()

    for term in search_terms:
        log_msg_search = "Efectuez cautarea pentru varianta de titlu: '%s'" % term
        if search_year:
            log_msg_search += " (an: %s)" % search_year
        log(log_msg_search)
        
        post_data = {'type': 'subtitrari', 'titlu-film': term}
        if search_year:
            post_data['an'] = search_year
        
        html_content = fetch_subtitles_page(s, post_data)
        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            results_divs = soup.find_all('div', class_=re.compile(r'w-full bg-\[#F5F3E8\]'))
            for div in results_divs:
                link_tag = div.find('a', href=re.compile(r'/subtitrare/descarca/'))
                if link_tag and link_tag['href']:
                    if link_tag['href'] not in seen_links:
                        seen_links.add(link_tag['href'])
                        combined_results_html.append(div)
    
    if len(search_terms) > 1:
        log("Am gasit in total %d rezultate unice combinate." % len(combined_results_html))
    else:
        log("Am gasit in total %d rezultate unice." % len(combined_results_html))

    subs, raw_count, all_wrong = parse_results(combined_results_html, languages_to_keep, is_tv_show, required_season, is_manual_search=is_manual_search_active)
    
    return subs, raw_count, bool(languages_to_keep), item, is_tv_show, all_wrong, True, is_manual_search_active

def fetch_subtitles_page(session, post_data):
    try:
        main_page_resp = session.get(BASE_URL + 'cautare', verify=False, timeout=15)
        main_page_soup = BeautifulSoup(main_page_resp.text, 'html.parser')
        form = main_page_soup.find('form', {'id': 'search-subtitrari'})
        antispam_tag = form.find('input', {'name': 'antispam'}) if form else None
        if not antispam_tag or 'value' not in antispam_tag.attrs: return None
        antispam_token = antispam_tag['value']
        post_data['antispam'] = antispam_token
        ajax_url = BASE_URL + 'ajax/search'
        response = session.post(ajax_url, data=post_data, verify=False, timeout=15)
        response.raise_for_status()
        return response.text
    except: return None

FLAG_COLORS = {
    'ro': ['blue', 'yellow', 'red'],
    'en': ['red', 'white', 'blue'],
    'fr': ['blue', 'white', 'red'],
    'it': ['green', 'white', 'red'],
    'es': ['red', 'yellow', 'red'],
    'pt': ['green', 'red'],
    'de': ['black', 'red', 'yellow'],
    'hu': ['red', 'white', 'green'],
    'el': ['blue', 'white'],
    'xx': ['grey']
}

def colorize_by_segment(text, colors):
    if not colors or not text:
        return text

    n_colors = len(colors)
    n_chars = len(text)
    
    chunk_size = n_chars // n_colors
    remainder = n_chars % n_colors
    
    colored_text = ''
    start_index = 0
    
    for i in range(n_colors):
        size = chunk_size + 1 if i < remainder else chunk_size
        end_index = start_index + size
        segment = text[start_index:end_index]
        colored_text += '[COLOR %s]%s[/COLOR]' % (colors[i], segment)
        start_index = end_index
        
    return colored_text

def parse_results(results_html, languages_to_keep, is_tv_show=False, required_season=0, is_manual_search=False):
    raw_count = len(results_html)
    
    if not results_html:
        return ([], 0, False)
    
    results_to_process = results_html

    if is_tv_show and raw_count > 0 and not is_manual_search:
        log("Titlul este Serial. Procesez %d rezultate pentru Sezonul %d." % (raw_count, required_season))
        pre_filtered_results = []
        for res_div in results_html:
            title_tag = res_div.find('h2')
            if not title_tag: continue
            
            title_container = title_tag.find('span', class_='flex-1')
            if not title_container: continue
            
            nume = title_container.get_text(strip=True)
            keep_result = False
            
            match_single = re.search(r'(?:sezonul|season)\s+(\d+)', nume, re.IGNORECASE)
            match_range = re.search(r'(?:sezoanele|seasons)\s+(\d+)\s*-\s*(\d+)', nume, re.IGNORECASE)
            season_words_pattern = r'\b(' + '|'.join(SEASON_WORDS_TO_NUM.keys()) + r')\s+season\b'
            match_word = re.search(season_words_pattern, nume, re.IGNORECASE)

            if match_range:
                start_season = int(match_range.group(1))
                end_season = int(match_range.group(2))
                if start_season <= required_season <= end_season:
                    keep_result = True
            elif match_single:
                season_found = int(match_single.group(1))
                if season_found == required_season:
                    keep_result = True
            elif match_word:
                season_word = match_word.group(1).lower()
                season_found = SEASON_WORDS_TO_NUM.get(season_word)
                if season_found and season_found == required_season:
                    keep_result = True
            
            if keep_result:
                pre_filtered_results.append(res_div)

        if not pre_filtered_results and raw_count > 0:
            log("Niciun rezultat nu s-a potrivit cu sezonul %d. Se returneaza eroare specifica." % required_season)
            return ([], raw_count, True)

        log("Au ramas %d rezultate dupa filtrul de sezon." % len(pre_filtered_results))
        results_to_process = pre_filtered_results

    result = []
    LANG_MAP = {
        'rom': ('Romanian', 'ro', 'Română'), 'rum': ('Romanian', 'ro', 'Română'),
        'eng': ('English', 'en', 'Engleză'),
        'fra': ('French', 'fr', 'Franceză'),
        'ita': ('Italian', 'it', 'Italiană'),
        'spa': ('Spanish', 'es', 'Spaniolă'),
        'por': ('Portuguese', 'pt', 'Portugheză'),
        'ger': ('German', 'de', 'Germană'),
        'hun': ('Hungarian', 'hu', 'Maghiară'),
        'gre': ('Greek', 'el', 'Greacă'),
        'alt': ('Other', 'xx', 'N/A'),
    }

    for res_div in results_to_process:
        try:
            nume, an, limba_text = 'N/A', 'N/A', 'N/A'
            traducator, uploader = 'N/A', 'N/A'
            lang_name, iso_lang = 'Romanian', 'ro'

            title_tag = res_div.find('h2')
            if not title_tag: continue
            
            title_year_container = title_tag.find('span', class_='flex-1')
            if title_year_container:
                year_span = title_year_container.find('span')
                if year_span:
                    an = year_span.get_text(strip=True).strip('()')
                    year_span.extract()
                nume = title_year_container.get_text(strip=True)

            flag_img = title_tag.find('img')
            if flag_img and 'src' in flag_img.attrs:
                src_parts = flag_img['src'].split('-')
                if len(src_parts) > 1:
                    lang_code = src_parts[1]
                    lang_data = LANG_MAP.get(lang_code)
                    if lang_data:
                        lang_name, iso_lang, limba_text = lang_data
                    else:
                        limba_text, iso_lang, lang_name = (lang_code.upper(), lang_code, lang_code.upper())
            
            if languages_to_keep and iso_lang not in languages_to_keep:
                continue

            details = res_div.find_all('span', class_='font-medium text-gray-700')
            for span in details:
                parent_text = span.parent.get_text(strip=True)
                if 'Traducător:' in parent_text:
                    traducator = parent_text.replace('Traducător:', '').strip() or 'N/A'
                elif 'Uploader:' in parent_text:
                    uploader_link = span.parent.find('a')
                    uploader_text = uploader_link.get_text(strip=True) if uploader_link else parent_text.replace('Uploader:', '').strip()
                    uploader = uploader_text or 'N/A'

            download_link = res_div.find('a', href=re.compile(r'/subtitrare/descarca/'))
            if not download_link: continue
            legatura = download_link['href']
            if not legatura.startswith('http'): legatura = BASE_URL.rstrip('/') + legatura

            main_part = u'[B]%s (%s)[/B]' % (nume, an)
            
            prefix = limba_text[:3].upper()
            
            if iso_lang in FLAG_COLORS:
                colored_prefix = colorize_by_segment(prefix, FLAG_COLORS[iso_lang])
                colored_lang_text = '[B]%s[/B]' % colored_prefix
            else:
                colored_lang_text = '[B][COLOR FFC53822]%s[/COLOR][/B]' % prefix
            
            lang_part = u'Lb: %s' % colored_lang_text
            trad_part = u'Tr: [B][COLOR FFC53822]%s[/COLOR][/B]' % (traducator)
            up_part = u'Up: [B][COLOR FFC53822]%s[/COLOR][/B]' % (uploader)
            
            display_name = u'%s | %s | %s | %s' % (main_part, lang_part, trad_part, up_part)
            
            result.append({
                'SubFileName': display_name, 
                'ZipDownloadLink': legatura, 
                'LanguageName': lang_name, 
                'ISO639': iso_lang, 
                'SubRating': '5', 
                'Traducator': traducator
            })
        except Exception as e:
            log("EROARE la parsarea unui rezultat: %s" % e)
            continue
    
    if languages_to_keep:
        log("Au ramas %d rezultate dupa filtrul de limba." % len(result))
    
    SORT_ORDER = {
        'ro': 0, 'en': 1, 'fr': 2, 'it': 3, 'es': 4,
        'pt': 5, 'de': 6, 'hu': 7, 'el': 8
    }
    sorted_result = sorted(result, key=lambda sub: SORT_ORDER.get(sub['ISO639'], 10 if sub['ISO639'] == 'xx' else 9))
    
    return (sorted_result, raw_count, False)

def extract_season_episode(filename):
    match = re.search(r'(?:[sS](\d+)[eE](\d+))|(\d+)[xX](\d+)', filename)
    if match:
        if match.group(1) is not None:
            return (int(match.group(1)), int(match.group(2)))
        else:
            return (int(match.group(3)), int(match.group(4)))
    return (-1, -1)

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
    item = {
        'mansearch': action == 'manualsearch',
        'file_original_path': xbmc.Player().getPlayingFile() if py3 else xbmc.Player().getPlayingFile().decode('utf-8'),
        'title': normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")),
        'season': str(xbmc.getInfoLabel("VideoPlayer.Season")), 'episode': str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    }
    if item.get('mansearch'): item['mansearchstr'] = params.get('searchstring', '')
    
    Search(item)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

elif action == 'setsub':
    link = urllib.unquote_plus(params.get('link', ''))
    if link:
        try:
            xbmc.Player().setSubtitles(link)
        except:
            pass

        listitem = xbmcgui.ListItem(label=os.path.basename(link))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=link, listitem=listitem, isFolder=False)

    xbmcplugin.endOfDirectory(int(sys.argv[1]))