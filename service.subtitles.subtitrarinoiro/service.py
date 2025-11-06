# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import unicodedata
try: 
    import urllib
    import urllib2
    py3 = False
except ImportError: 
    import urllib.parse as urllib
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

def unpack_archive(archive_physical_path, dest_physical_path, archive_type):
    all_files = []
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    
    try:
        normalized_archive_path = archive_physical_path.replace('\\', '/')
        vfs_archive_path = '%s://%s' % (archive_type, urllib.quote_plus(normalized_archive_path))
        
        log("Initializez extragerea VFS pentru: %s" % vfs_archive_path)
        
        def recursive_unpack(current_vfs_path, current_dest_path):
            extracted_list = []
            try:
                dirs, files = xbmcvfs.listdir(current_vfs_path)
                
                if not xbmcvfs.exists(current_dest_path):
                    xbmcvfs.mkdirs(current_dest_path)

                for file_name in files:
                    if not py3 and isinstance(file_name, bytes):
                        file_name = file_name.decode('utf-8')

                    if os.path.splitext(file_name)[1].lower() in subtitle_exts:
                        source_vfs_file = current_vfs_path + '/' + file_name
                        dest_physical_file = os.path.join(current_dest_path, file_name)
                        
                        try:
                            if xbmcvfs.copy(source_vfs_file, dest_physical_file):
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
        return all_files

    except Exception as e:
        log("EROARE fatala la initializarea extragerii arhivei: %s" % e)
        return []

def cleanup_temp_directory(temp_dir):
    """Sterge complet continutul directorului temporar"""
    try:
        if not xbmcvfs.exists(temp_dir):
            xbmcvfs.mkdirs(temp_dir)
            return
        
        log("Incep curatarea completa a directorului temporar...")
        
        # Functie recursiva pentru stergerea subdirectoarelor
        def delete_directory_recursive(path):
            try:
                dirs, files = xbmcvfs.listdir(path)
                
                # Stergem mai intai toate fisierele din director
                for f in files:
                    file_path = os.path.join(path, f.decode('utf-8') if not py3 and isinstance(f, bytes) else f)
                    try:
                        xbmcvfs.delete(file_path)
                        log("Sters fisier: %s" % file_path)
                    except Exception as e:
                        log("Nu am putut sterge fisierul %s: %s" % (file_path, e))
                
                # Apoi stergem recursiv toate subdirectoarele
                for d in dirs:
                    subdir_path = os.path.join(path, d.decode('utf-8') if not py3 and isinstance(d, bytes) else d)
                    delete_directory_recursive(subdir_path)
                
                # La final stergem directorul insusi (daca nu e directorul principal temp)
                if path != temp_dir:
                    try:
                        xbmcvfs.rmdir(path, False)
                        log("Sters director: %s" % path)
                    except Exception as e:
                        log("Nu am putut sterge directorul %s: %s" % (path, e))
                        
            except Exception as e:
                log("EROARE la listarea directorului %s: %s" % (path, e))
        
        # Apelam functia recursiva pentru directorul temporar
        delete_directory_recursive(temp_dir)
        
        log("Directorul temporar a fost curatat complet.")
    except Exception as e:
        log("EROARE la curatarea directorului temporar: %s" % str(e))

def Search(item):
    temp_dir = __temp__
    
    # --- PASUL 1: CURATARE COMPLETA A DIRECTORULUI TEMPORAR ---
    cleanup_temp_directory(temp_dir)

    # --- PASUL 2: LOGICA DE RETEA CU SESIUNE UNICA ---
    s = requests.Session()
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    s.headers.update({'User-Agent': ua, 'Referer': BASE_URL})

    try:
        log("Initializez sesiunea accesand pagina principala...")
        s.get(BASE_URL, verify=False, timeout=15)
        log("Sesiunea a fost initializata cu succes (am primit cookie-uri).")
    except Exception as e:
        log("EROARE la initializarea sesiunii: %s" % e)
    
    subtitles_found = searchsubtitles(item, s)
    
    if not subtitles_found:
        log("Nicio subtitrare returnata de searchsubtitles.")
        xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita pe site")
        return

    sel = 0
    if len(subtitles_found) > 1:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in subtitles_found]
        sel = dialog.select("Selectati subtitrarea", titles)
    
    if sel >= 0:
        selected_sub_info = subtitles_found[sel]
        link = selected_sub_info["ZipDownloadLink"]
        
        log("Incerc sa descarc arhiva de la: %s" % link)
        response = s.get(link, verify=False, timeout=15)
        
        if len(response.content) < 100:
            log("EROARE: Descarcarea a esuat, serverul a returnat un fisier gol.")
            xbmcgui.Dialog().ok("Eroare la Descarcare", "Serverul a returnat un fisier invalid.")
            return

        content_disp = response.headers.get('Content-Disposition', '')
        Type = 'zip'
        if 'filename=' in content_disp:
            try:
                fname_header = re.findall('filename="?([^"]+)"?', content_disp)[0]
                if fname_header.lower().endswith('.rar'): Type = 'rar'
            except: pass

        if Type == 'rar' and not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
            xbmcgui.Dialog().ok("Componenta lipsa", "Instalati 'RAR archive support'.")
            return

        # --- PASUL 3: NUME UNIC PENTRU ARHIVA (evita cache VFS) ---
        fname = os.path.join(temp_dir, "subtitle_%s.%s" % (str(int(time.time())), Type))
        
        # --- PASUL 4: METODA CORECTA DE SCRIERE, NATIVA KODI ---
        try:
            f = xbmcvfs.File(fname, 'wb')
            f.write(response.content)
            f.close()
            log("Fisier arhiva salvat la: %s" % fname)
        except Exception as e:
            log("EROARE la scrierea fisierului arhiva: %s" % e)
            return
        
        extractPath = os.path.join(temp_dir, "Extracted")
        if not xbmcvfs.exists(extractPath):
            xbmcvfs.mkdirs(extractPath)
        
        all_files = unpack_archive(fname, extractPath, Type)
        
        if not all_files:
            log("Extragerea a esuat sau nu s-au gasit fisiere de subtitrare.")
            xbmcgui.Dialog().ok("Eroare la extragere", "Arhiva pare goala, corupta sau invalida.")
            return
        
        log("S-au gasit %d fisiere de subtitrare dupa extragere." % len(all_files))
        all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

        subs_list = []
        season, episode = item.get("season"), item.get("episode")
        if episode and season and season != "0" and episode != "0":
            epstr = '%s:%s' % (season, episode)
            log("Filtrez pentru Sezonul %s Episodul %s" % (season, episode))
            episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
            
            for sub_file in all_files:
                if episode_regex.search(os.path.basename(sub_file)):
                    subs_list.append(sub_file)

            log("Am gasit %d subtitrari potrivite pentru episod." % len(subs_list))
            all_files = sorted(subs_list, key=lambda f: natural_key(os.path.basename(f)))
        
        if not all_files and (episode and season and season != "0" and episode != "0"):
            log("Filtrul de episod nu a returnat niciun rezultat. Se afiseaza un mesaj.")
            xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita pentru S%sE%s in arhiva." % (season, episode))
            return

        for sub_file in all_files:
            basename = normalizeString(os.path.basename(sub_file))
            listitem = xbmcgui.ListItem(label=selected_sub_info['Traducator'], label2=basename)
            listitem.setArt({'icon': "DefaultSubAll.png", 'thumb': 'ro'})
            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(sub_file))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item, session):
    
    # ==================== MODIFICARE CHEIE: SEPARAREA LOGICII DE CAUTARE ====================
    # Am separat complet logica de cautare manuala de cea automata pentru a preveni erorile.
    
    # COMENTARIU: Daca este o cautare manuala, executam doar acest bloc.
    if item.get('mansearch'):
        log("--- CAUTARE MANUALA ACTIVA ---")
        # Preluam textul introdus de utilizator.
        search_string_raw = urllib.unquote(item.get('mansearchstr', ''))
        log("Text cautare: '%s'" % search_string_raw)
        
        # Curatam textul manual pentru a obtine un titlu cat mai bun.
        parsed_info = PTN.parse(search_string_raw)
        final_search_string = parsed_info.get('title', search_string_raw).strip()
        searched_title_for_sort = final_search_string # Folosit pentru sortare
        
    # COMENTARIU: Daca NU este manuala, executam logica de dinainte.
    else:
        log("--- CAUTARE AUTOMATA ACTIVA ---")
        # Prioritate 1: Titlul serialului din InfoLabel
        search_string_raw = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
        if search_string_raw:
            log("Prioritate 1: Am gasit titlul serialului din InfoLabel: %s" % search_string_raw)
        
        # Prioritate 2: OriginalTitle sau Title din InfoLabel
        if not search_string_raw:
            search_string_raw = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
            if search_string_raw:
                log("Prioritate 2: Am gasit titlul filmului din InfoLabel: %s" % search_string_raw)
        
        # Verificare pentru titluri invalide (ex: 'play')
        if search_string_raw:
            cleaned_for_check = re.sub(r'\[/?COLOR.*?\]', '', search_string_raw, flags=re.IGNORECASE).strip()
            if cleaned_for_check.lower() == 'play' or cleaned_for_check.isdigit():
                log("Titlul '%s' este invalid. Se ignora si se va folosi numele fisierului." % search_string_raw)
                search_string_raw = ""

        # Prioritate 3: Fallback la parsarea numelui de fisier
        if not search_string_raw:
            log("Prioritate 3 (Fallback): Cautare dupa text din numele fisierului.")
            original_path = item.get('file_original_path', '')
            search_string_raw = os.path.basename(original_path) if not original_path.startswith('http') else item.get('title', '')
        
        if not search_string_raw:
            log("EROARE: Nu am putut determina un sir de cautare valid.")
            return None

        # Logica de curatare avansata (inspirata din regielive)
        log("Titlu brut initial pentru curatare: '%s'" % search_string_raw)
        search_string_clean = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_string_raw, flags=re.IGNORECASE)
        search_string_clean = re.sub(r'\(.*?\)|\[.*?\]', '', search_string_clean).strip()

        if '.' in search_string_clean:
            parts = search_string_clean.replace('.', ' ').split()
            title_parts = []
            blacklist = {
                'FREELEECH', '1080P', '720P', '480P', 'BLURAY', 'WEBRIP', 'WEB-DL', 
                'HDTV', 'X264', 'X265', 'H264', 'H265', 'DTS', 'AAC', 'DDP5', '1', 
                'PROPER', 'REPACK', 'EXTENDED', 'UNRATED', 'INTERNAL', 'NF', 'NTG', 'STARZ'
            }
            for part in parts:
                if re.match(r'^[Ss]\d{1,2}([Ee]\d{1,2})?$', part): break
                if re.match(r'^(19|20)\d{2}$', part): break
                if part.upper() in blacklist: continue
                title_parts.append(part)
            search_string_clean = ' '.join(title_parts)

        parsed_info = PTN.parse(search_string_clean)
        final_search_string = parsed_info.get('title', search_string_clean).strip()
        final_search_string = ' '.join(final_search_string.split())
        searched_title_for_sort = final_search_string # Folosit pentru sortare

    # ==================== BLOC COMUN PENTRU EXECUTIA CAUTARII ====================
    if not final_search_string:
        log("EROARE: Titlul final de cautare este gol. Cautarea se anuleaza.")
        return None

    log("String initial: '%s'. Cautare finala pentru: '%s'" % (search_string_raw, final_search_string))
    
    html_content = fetch_subtitles_page(final_search_string, session)
    if html_content:
        return parse_results(html_content, searched_title_for_sort)

    return None

def fetch_subtitles_page(search_string, session):
    search_url = BASE_URL + "paginare_filme.php"
    data = {
        'search_q': '1', 'cautare': search_string, 'tip': '2',
        'an': 'Toti anii', 'gen': 'Toate', 'page_nr': '1'
    }
    ajax_headers = {
        'accept': 'text/html, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': BASE_URL.rstrip('/')
    }
    
    try:
        log("Trimit cerere POST catre: %s" % search_url)
        response = session.post(search_url, headers=ajax_headers, data=data, verify=False, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        log("EROARE la conectarea la site: %s" % e)
        return None

def parse_results(html_content, searched_title):
    import difflib

    soup = BeautifulSoup(html_content, 'html.parser')
    results_html = soup.find_all('div', id='round')
    log("Am gasit %d rezultate in HTML" % len(results_html))
    
    subtitles = []
    for res_div in results_html:
        try:
            main_content = res_div.find('div', id='content-main')
            right_content = res_div.find('div', id='content-right')
            release_info_div = res_div.find_next_sibling('div', style=re.compile(r'font-weight:bold'))
            
            if not main_content or not right_content:
                continue

            nume_tag = main_content.find('a')
            nume = nume_tag.get_text(strip=True) if nume_tag else 'N/A'
            
            traducator = 'N/A'
            traducator_raw = main_content.find(string=re.compile(r'Traducator:'))
            if traducator_raw:
                traducator = traducator_raw.replace('Traducator:', '').strip()
            
            descriere = release_info_div.get_text(strip=True) if release_info_div else ''
            
            download_tag = right_content.find('a', href=re.compile(r'\.zip$|\.rar$'))
            if not download_tag:
                continue
            
            legatura = download_tag['href']
            if not legatura.startswith('http'):
                legatura = BASE_URL + legatura.lstrip('/')

            display_name = u'%s - %s (Trad: %s)' % (nume, descriere, traducator)
            
            subtitles.append({
                'SubFileName': display_name,
                'ZipDownloadLink': legatura,
                'LanguageName': 'Romanian',
                'ISO639': 'ro',
                'SubRating': '5',
                'Traducator': traducator,
                'OriginalMovieTitle': nume
            })
        except Exception as e:
            log("EROARE la parsarea unui rezultat: %s" % e)
            continue
            
    log("Am extras %d subtitrari. Incep sortarea cu ordine mixta." % len(subtitles))

    # ==================== MODIFICARE CHEIE: SORTARE CU ORDINE MIXTA ====================
    # Am schimbat complet logica de sortare pentru a permite ordine diferite:
    # Criteriul 1 (similaritate_titlu): Se sorteaza DESC. Facem asta negand valoarea. 
    #   Un scor mai mare (ex: 1.0 -> -1.0) va fi considerat mai "mic" si va aparea primul 
    #   intr-o sortare ascendenta.
    # Criteriul 2 (cheie_naturala_nume_subtitrare): Se sorteaza ASC. Se pastreaza 
    #   neschimbata pentru a sorta sezoanele in ordine naturala (1, 2, 3...).
    # Se elimina `reverse=True` pentru ca sortarea generala este acum ascendenta.
    if subtitles:
        subtitles.sort(
            key=lambda sub: (
                -difflib.SequenceMatcher(None, searched_title.lower(), sub['OriginalMovieTitle'].lower()).ratio(),
                natural_key(sub['SubFileName'])
            )
        )
    # ==================== SFARSIT MODIFICARE ====================

    log("Sortare finalizata. Returnez %d subtitrari valide si sortate." % len(subtitles))
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
    
    # Daca season/episode sunt goale, incearca parsarea din nume fisier
    if not season or season == "0" or not episode or episode == "0":
        log("Sezon/Episod lipsa din infolabels. Incerc parsarea din numele fisierului...")
        parsed_data = PTN.parse(os.path.basename(file_original_path))
        
        if (not season or season == "0") and 'season' in parsed_data:
            season = str(parsed_data['season'])
            log("Sezon gasit din nume fisier: %s" % season)
        
        if (not episode or episode == "0") and 'episode' in parsed_data:
            episode = str(parsed_data['episode'])
            log("Episod gasit din nume fisier: %s" % episode)
            
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
    if link:
        log("Am selectat subtitrarea sursa: %s" % link)
        
        # --- NUME CONSTANT PENTRU FISIERUL FINAL (se suprascrie mereu) ---
        kodi_temp_path = xpath('special://temp/')
        final_sub_path = os.path.join(kodi_temp_path, 'subtitrari-noi_current.srt')

        log("Copiez subtitrarea in locatia finala: %s" % final_sub_path)
        
        try:
            if xbmcvfs.copy(link, final_sub_path):
                log("Copia a reusit. Setez subtitrarea in player.")
                xbmc.Player().setSubtitles(final_sub_path)
                xbmcplugin.addDirectoryItem(handle=handle, url=final_sub_path, listitem=xbmcgui.ListItem(label="Subtitrare activata"), isFolder=False)
                xbmcplugin.endOfDirectory(handle)
            else:
                log("EROARE: Copierea subtitrarii in temp-ul Kodi a esuat.")
                xbmcgui.Dialog().ok("Eroare", "Nu s-a putut pregati fisierul de subtitrare.")
        except Exception as e:
            log("EROARE fatala la setarea subtitrarii: %s" % e)
            xbmcgui.Dialog().ok("Eroare", "O eroare neasteptata a avut loc la copierea subtitrarii.")

xbmcplugin.endOfDirectory(handle)