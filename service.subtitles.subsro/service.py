# -*- coding: utf-8 -*-

import json
from operator import itemgetter
import os
import re
import sys
import time
import unicodedata
import urllib
import platform
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
import zipfile

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
import rarfile
import requests
from bs4 import BeautifulSoup
import PTN

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def log(msg):
    log_level = xbmc.LOGINFO if py3 else xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s] - %s" % (__scriptid__, str(msg)), level=log_level)
    except Exception: pass

def get_unrar_tool_path():
    log("Detectez platforma si arhitectura pentru unealta unrar...")
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    unrar_path = ""
    
    if os.path.exists('/system/build.prop'):
        log("Platforma detectata: Android")
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'android_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'android_arm', 'unrar')
            
    elif 'linux' in system:
        log("Platforma detectata: Linux (OSMC/Desktop etc.)")
        for tool in ['/usr/bin/unrar', '/usr/bin/unrar-free']:
            if os.path.exists(tool):
                log("Am gasit unealta de sistem la: %s" % tool)
                return tool
        
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'linux_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'linux_arm', 'unrar')
            
    elif 'win' in system:
        log("Platforma detectata: Windows")
        unrar_path = os.path.join(__cwd__, 'resources', 'bin', 'windows_x64', 'UnRAR.exe')

    if unrar_path and os.path.exists(unrar_path):
        log("Am gasit unealta unrar la: %s" % unrar_path)
        if 'win' not in system:
            try: os.chmod(unrar_path, 0o755)
            except Exception as e: log("Nu am putut seta permisiuni de executie: %s" % e)
        return unrar_path

    log("EROARE: Nu am gasit nicio unealta unrar compatibila pentru platforma %s/%s" % (system, machine))
    return None

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
        if not xbmcvfs.exists(dest_physical_path):
            xbmcvfs.mkdirs(dest_physical_path)

        if archive_type == 'zip':
            log("Initializez extragerea ZIP folosind metoda directa (zipfile)...")
            with zipfile.ZipFile(archive_physical_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if os.path.splitext(member)[1].lower() in subtitle_exts:
                        try:
                            zip_ref.extract(member, dest_physical_path)
                            extracted_file_path = os.path.join(dest_physical_path, *member.replace('\\', '/').split('/'))
                            all_files.append(extracted_file_path)
                        except Exception as e:
                            log("EROARE la extragerea fisierului ZIP '%s': %s" % (member, e))

        elif archive_type == 'rar':
            log("Initializez extragerea RAR folosind metoda externa...")
            unrar_tool = get_unrar_tool_path()
            
            if not unrar_tool:
                xbmcgui.Dialog().ok("Unealta RAR lipsa", "Nu s-a gasit un program pentru dezarhivare RAR.", "Asigurati-va ca addon-ul este complet.", "Pentru Linux/OSMC, puteti rula 'sudo apt-get install unrar'.")
                return []
            
            rarfile.UNRAR_TOOL = unrar_tool
            try:
                with rarfile.RarFile(archive_physical_path) as rf:
                    rf.extractall(path=dest_physical_path)
                    log("Arhiva RAR extrasa cu succes.")
                
                log("Scanare post-extragere...")
                for root, dirs, files in os.walk(dest_physical_path):
                    for file in files:
                        if os.path.splitext(file)[1].lower() in subtitle_exts:
                            full_path = os.path.join(root, file)
                            all_files.append(full_path)
                            log("Am gasit fisierul extras: %s" % full_path)
            except Exception as e:
                log("EROARE in timpul extragerii cu rarfile: %s" % e)
                xbmcgui.Dialog().ok("Eroare la extragere RAR", "Arhiva pare a fi corupta sau formatul nu este suportat.")
                return []

        else:
            log("EROARE: Tip de arhiva necunoscut sau nesuportat: %s" % archive_type)

        return all_files

    except Exception as e:
        log("EROARE fatala in timpul extragerii arhivei: %s" % e)
        return []

def Search(item):
    temp_dir = __temp__
    try:
        if xbmcvfs.exists(temp_dir):
            log("Incep curatarea directorului temporar vechi: %s" % temp_dir)
            xbmcvfs.rmdir(temp_dir, True)

        xbmcvfs.mkdirs(temp_dir)
        log("Director temporar pregatit: %s" % temp_dir)
    except Exception as e:
        log("EROARE la initializarea directorului temporar: %s" % str(e))
        return

    filtered_subs, raw_count = searchsubtitles(item)
    
    if not filtered_subs:
        if raw_count > 0:
            log("S-au gasit %d rezultate, dar niciunul nu se potriveste cu limbile preferate." % raw_count)
            xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita dupa preferintele de limba selectate")
        else:
            log("Nicio subtitrare returnata de searchsubtitles.")
            xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita pe site pentru acest Film/Serial")
        return

    sel = 0
    if len(filtered_subs) > 0:
        dialog = xbmcgui.Dialog()
        titles = [sub["SubFileName"] for sub in filtered_subs]
        sel = dialog.select("Selectati subtitrarea", titles)
    
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
            log("EROARE: Add-on-ul 'vfs.rar' (RAR archive support) este inca necesar pentru Kodi.")
            xbmcgui.Dialog().ok("Componentă lipsă", "Instalati 'RAR archive support' din repository-ul oficial Kodi.")
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
            xbmcgui.Dialog().ok("Eroare la Salvare", "Nu s-a putut salva arhiva de subtitrări.")
            return

        extractPath = os.path.join(temp_dir, "Extracted")
        
        all_files = unpack_archive(fname, extractPath, Type)
        
        if not all_files:
            log("Extragerea a esuat sau nu s-au gasit fisiere de subtitrare.")
            xbmcgui.Dialog().ok("Eroare la extragere", "Arhiva pare goala sau corupta.")
            return
        
        valid_files = []
        for f in all_files:
            try:
                if xbmcvfs.Stat(f).st_size() > 0:
                    valid_files.append(f)
                else:
                    log("Fisier de 0 KB gasit si ignorat: %s" % f)
            except Exception as e:
                log("EROARE la verificarea marimii fisierului %s: %s" % (f, e))

        if not valid_files:
            log("EROARE: Toate fisierele extrase au 0 KB.")
            xbmcgui.Dialog().ok(__scriptname__, "Dezarhivare esuata. Fisiere corupte.")
            return

        all_files = valid_files
        
        log("S-au gasit %d fisiere de subtitrare valide dupa extragere." % len(all_files))
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
            listitem = xbmcgui.ListItem(label=selected_sub_info['SubFileName'], label2=basename)
            listitem.setArt({'icon': selected_sub_info["SubRating"], 'thumb': selected_sub_info["ISO639"]})
            
            lang_code = selected_sub_info["ISO639"]
            url = "plugin://%s/?action=setsub&link=%s&lang=%s" % (__scriptid__, urllib.quote_plus(sub_file), lang_code)
            
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,ro;q=0.8', 'Origin': BASE_URL.rstrip('/'), 'Referer': BASE_URL + 'cautare'
    })
    
    languages_to_keep = item.get('languages', [])
    log("Vom pastra doar subtitrarile pentru limbile: %s" % languages_to_keep)
    
    # Cautare prioritara dupa ID-uri
    tmdb_id = xbmc.getInfoLabel("VideoPlayer.TVShow.TMDbId") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    if tmdb_id and tmdb_id.isdigit():
        log("Prioritate 1: Am gasit TMDB ID: %s. Incercam cautarea..." % tmdb_id)
        post_data = {'type': 'subtitrari', 'external_id': tmdb_id}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content:
            return parse_results(html_content, languages_to_keep)

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
    if imdb_id and imdb_id.startswith('tt'):
        imdb_id_numeric = imdb_id.replace("tt", "")
        log("Prioritate 2: Am gasit IMDB ID: %s. Incercam cautarea cu ID numeric: %s." % (imdb_id, imdb_id_numeric))
        post_data = {'type': 'subtitrari', 'external_id': imdb_id_numeric}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content:
            return parse_results(html_content, languages_to_keep)

    # --- LOGICA DE CAUTARE FINALA, MANUAL-AGRESIVA ---
    
    # Pas 1: Obtinem cel mai bun string brut disponibil
    search_string_raw = ""
    if item.get('mansearch'):
        search_string_raw = urllib.unquote(item.get('mansearchstr', ''))
        log("Prioritate MAXIMA: Cautare manuala pentru: '%s'" % search_string_raw)
    else:
        search_string_raw = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
        if search_string_raw:
            log("Prioritate 3: Am gasit titlul serialului din InfoLabel: %s" % search_string_raw)
        
        if not search_string_raw:
            search_string_raw = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
            if search_string_raw:
                log("Prioritate 4: Am gasit titlul filmului din InfoLabel: %s" % search_string_raw)

        if not search_string_raw:
            log("Prioritate 5 (Fallback): Folosesc numele fisierului.")
            search_string_raw = os.path.basename(item.get('file_original_path', ''))
    
    if not search_string_raw:
        log("EROARE: Nu am putut determina un titlu valid pentru cautare.")
        return ([], 0)

    # Pas 2: Curatare brutala
    # Eliminam tag-urile de formatare Kodi
    temp_string = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_string_raw)
    # Eliminam informatiile din paranteze
    temp_string = re.sub(r'\(.*?\)|\[.*?\]', '', temp_string)
    
    # Cautam un indicator de sezon SAU un an si taiem tot ce e dupa
    match = re.search(r'(S[0-9]{1,2}|Season[\s\.]?[0-9]{1,2}|\b(19|20)\d{2}\b)', temp_string, re.IGNORECASE)
    if match:
        temp_string = temp_string[:match.start()]
    
    # Inlocuim punctele cu spatii si eliminam cuvintele cheie manual
    temp_string = temp_string.replace('.', ' ').strip()
    words_to_remove = ['internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb']
    for word in words_to_remove:
        temp_string = re.sub(r'\b' + re.escape(word) + r'\b', '', temp_string, flags=re.IGNORECASE)
    
    # Eliminam spatiile multiple si curatam final
    final_search_string = ' '.join(temp_string.split())
    
    log("Efectuez cautarea textuala finala pentru: '%s'" % final_search_string)
    post_data = {'type': 'subtitrari', 'titlu-film': final_search_string}
    html_content = fetch_subtitles_page(s, post_data)
    if html_content:
        return parse_results(html_content, languages_to_keep)

    return ([], 0)


def fetch_subtitles_page(session, post_data):
    # ... (aceasta functie ramane neschimbata)
    try:
        main_page_resp = session.get(BASE_URL + 'cautare', verify=False, timeout=15)
        main_page_soup = BeautifulSoup(main_page_resp.text, 'html.parser')
        form = main_page_soup.find('form', {'id': 'search-subtitrari'})
        antispam_tag = form.find('input', {'name': 'antispam'}) if form else None
        if not antispam_tag or 'value' not in antispam_tag.attrs: return None
        antispam_token = antispam_tag['value']
        post_data['antispam'] = antispam_token
        ajax_url = BASE_URL + 'ajax/search'
        log("Efectuez cautarea...")
        response = session.post(ajax_url, data=post_data, verify=False, timeout=15)
        response.raise_for_status()
        return response.text
    except: return None

def parse_results(html_content, languages_to_keep):
    # ... (aceasta functie ramane neschimbata, cu culoarea 'gold')
    soup = BeautifulSoup(html_content, 'html.parser')
    results_html = soup.find_all('div', class_=re.compile(r'w-full bg-\[#F5F3E8\]'))
    raw_count = len(results_html)
    log("Am gasit %d rezultate inainte de filtrare" % raw_count)
    result = []

    LANG_MAP = {
        'rom': ('Romanian', 'ro', 'Română'), 'rum': ('Romanian', 'ro', 'Română'),
        'eng': ('English', 'en', 'Engleză'),
        'fra': ('French', 'fr', 'Franceză'),
        'spa': ('Spanish', 'es', 'Spaniolă'),
        'ger': ('German', 'de', 'Germană'),
        'ita': ('Italian', 'it', 'Italiană'),
        'hun': ('Hungarian', 'hu', 'Maghiară'),
        'ara': ('Arabic', 'ar', 'Arabă'), 'bul': ('Bulgarian', 'bg', 'Bulgară'),
        'cat': ('Catalan', 'ca', 'Catalană'), 'chi': ('Chinese', 'zh', 'Chineză'),
        'hrv': ('Croatian', 'hr', 'Croată'), 'cze': ('Czech', 'cs', 'Cehă'),
        'dan': ('Danish', 'da', 'Daneză'), 'dut': ('Dutch', 'nl', 'Olandeză'),
        'est': ('Estonian', 'et', 'Estonă'), 'fin': ('Finnish', 'fi', 'Finlandeză'),
        'gre': ('Greek', 'el', 'Greacă'), 'heb': ('Hebrew', 'he', 'Ebraică'),
        'hin': ('Hindi', 'hi', 'Hindi'), 'ice': ('Icelandic', 'is', 'Islandeză'),
        'ind': ('Indonesian', 'id', 'Indoneziană'), 'jpn': ('Japanese', 'ja', 'Japoneză'),
        'kor': ('Korean', 'ko', 'Coreeană'), 'lav': ('Latvian', 'lv', 'Letonă'),
        'lit': ('Lithuanian', 'lt', 'Lituaniană'), 'mac': ('Macedonian', 'mk', 'Macedoneană'),
        'may': ('Malay', 'ms', 'Malaeză'), 'nor': ('Norwegian', 'no', 'Norvegiană'),
        'pol': ('Polish', 'pl', 'Poloneză'), 'por': ('Portuguese', 'pt', 'Portugheză'),
        'rus': ('Russian', 'ru', 'Rusă'), 'scc': ('Serbian', 'sr', 'Sârbă'),
        'slo': ('Slovak', 'sk', 'Slovacă'), 'slv': ('Slovenian', 'sl', 'Slovenă'),
        'swe': ('Swedish', 'sv', 'Suedeză'), 'tha': ('Thai', 'th', 'Thailandeză'),
        'tur': ('Turkish', 'tr', 'Turcă'), 'ukr': ('Ukrainian', 'uk', 'Ucraineană'),
        'vie': ('Vietnamese', 'vi', 'Vietnameză'),
    }

    for res_div in results_html:
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
            lang_part = u'Limba: [COLOR gold]%s[/COLOR]' % (limba_text)
            trad_part = u'Traducător: [COLOR gold]%s[/COLOR]' % (traducator)
            up_part = u'Uploader: [COLOR gold]%s[/COLOR]' % (uploader)
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
            
    log("Am extras in total %d subtitrari DUPA aplicarea filtrului de limba." % len(result))
    
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
    lang = urllib.unquote_plus(params.get('lang', 'unk'))
    if link:
        # --- METODA FINALA, STABILA SI CURATA ---
        
        # Pas 1: Cream un nume de fisier temporar in folderul temp al addon-ului
        sub_basename = os.path.basename(link)
        sub_name_part, sub_ext = os.path.splitext(sub_basename)
        
        if not sub_name_part.lower().endswith('.' + lang):
            new_sub_basename = "%s.%s%s" % (sub_name_part, lang, sub_ext)
        else:
            new_sub_basename = sub_basename
            
        safe_sub_name = re.sub(r'[\\/*?:"<>|]', "", new_sub_basename)
        final_temp_path = os.path.join(__temp__, safe_sub_name)
        log("Pregatesc subtitrarea finala in temp-ul addon-ului: %s" % final_temp_path)
        
        return_path = ""
        try:
            if xbmcvfs.copy(link, final_temp_path):
                return_path = final_temp_path
                log("Subtitrarea a fost copiata si redenumita cu succes.")
            else:
                log("EROARE: Copierea in temp a esuat. Se foloseste calea directa.")
                return_path = link
        except Exception as e:
            log("EROARE la copierea in temp. Se foloseste calea directa. Motiv: %s" % e)
            return_path = link

        # Pas 2: Returnam un ListItem care contine calea catre subtitrarea noastra.
        # Lasam Kodi sa se ocupe de activare si de salvarea langa video.
        listitem = xbmcgui.ListItem(label=os.path.basename(return_path))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=return_path, listitem=listitem, isFolder=False)

xbmcplugin.endOfDirectory(int(sys.argv[1]))