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
    log(__name__, ">>>>>>>>>> SEARCH SUBTITLE <<<<<<<<<<")
    
    if os.path.exists(__temp__):
        try: shutil.rmtree(__temp__, ignore_errors=True)
        except: pass
    try: os.makedirs(__temp__)
    except: pass
    
    filtered_subs, raw_count = searchsubtitles(item)
    
    if not filtered_subs:
        if raw_count > 0:
            xbmcgui.Dialog().ok(__scriptname__, "Nicio subtitrare gasita dupa preferintele de limba selectate")
        else:
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
            # Pauza scurta pentru a permite Windows sa elibereze lock-ul fisierului
            time.sleep(0.5)
        except Exception as e:
            log(__name__, "Eroare la redenumire: %s" % str(e))
            return

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

        for ofile in all_files:
            lang_code = selected_sub_info["ISO639"]
            lang_label = selected_sub_info.get("LanguageName", lang_code)

            display_name = os.path.basename(ofile)
            if ofile.startswith('rar://'):
                try: display_name = urllib.unquote(display_name)
                except: pass

            listitem = xbmcgui.ListItem(label=lang_label, label2=display_name)
            listitem.setArt({'icon': selected_sub_info["SubRating"], 'thumb': lang_code})
            listitem.setProperty("language", lang_code)
            listitem.setProperty("sync", "false") 

            url = "plugin://%s/?action=setsub&link=%s" % (__scriptid__, urllib.quote_plus(ofile))
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9,ro;q=0.8', 'Origin': BASE_URL.rstrip('/'), 'Referer': BASE_URL + 'cautare'
    })
    
    languages_to_keep = item.get('languages', [])
    req_season = item.get('season', '0')

    tmdb_id = xbmc.getInfoLabel("VideoPlayer.TVShow.TMDbId") or xbmc.getInfoLabel("VideoPlayer.TMDbId")
    if tmdb_id and tmdb_id.isdigit():
        post_data = {'type': 'subtitrari', 'external_id': tmdb_id}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content:
            return parse_results(html_content, languages_to_keep, req_season)

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
    if imdb_id and imdb_id.startswith('tt'):
        imdb_id_numeric = imdb_id.replace("tt", "")
        post_data = {'type': 'subtitrari', 'external_id': imdb_id_numeric}
        html_content = fetch_subtitles_page(s, post_data)
        if html_content:
            return parse_results(html_content, languages_to_keep, req_season)

    search_string_raw = ""
    if item.get('mansearch'):
        search_string_raw = urllib.unquote(item.get('mansearchstr', ''))
    else:
        search_string_raw = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
        if not search_string_raw:
            search_string_raw = xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title")
        if not search_string_raw:
            search_string_raw = os.path.basename(item.get('file_original_path', ''))
    
    if not search_string_raw: return ([], 0)

    temp_string = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', search_string_raw)
    temp_string = re.sub(r'\(.*?\)|\[.*?\]', '', temp_string)
    
    match = re.search(r'(S[0-9]{1,2}|Season[\s\.]?[0-9]{1,2}|\b(19|20)\d{2}\b)', temp_string, re.IGNORECASE)
    if match: temp_string = temp_string[:match.start()]
    
    temp_string = temp_string.replace('.', ' ').strip()
    words_to_remove = ['internal', 'freeleech', 'seriale hd', 'us', 'uk', 'de', 'fr', 'playweb']
    for word in words_to_remove:
        temp_string = re.sub(r'\b' + re.escape(word) + r'\b', '', temp_string, flags=re.IGNORECASE)
    
    final_search_string = ' '.join(temp_string.split())
    
    post_data = {'type': 'subtitrari', 'titlu-film': final_search_string}
    html_content = fetch_subtitles_page(s, post_data)
    if html_content:
        return parse_results(html_content, languages_to_keep, req_season)

    return ([], 0)

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

def parse_results(html_content, languages_to_keep, required_season=None):
    soup = BeautifulSoup(html_content, 'html.parser')
    results_html = soup.find_all('div', class_=re.compile(r'w-full bg-\[#F5F3E8\]'))
    raw_count = len(results_html)
    result = []

    LANG_MAP = {
        'rom': ('Romanian', 'ro', 'Română'), 'rum': ('Romanian', 'ro', 'Română'),
        'eng': ('English', 'en', 'Engleză'),
        'fra': ('French', 'fr', 'Franceză'),
        'spa': ('Spanish', 'es', 'Spaniolă'),
        'ger': ('German', 'de', 'Germană'),
        'ita': ('Italian', 'it', 'Italiană'),
        'hun': ('Hungarian', 'hu', 'Maghiară'),
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
                    uploader = parent_text.replace('Uploader:', '').strip() or 'N/A'

            download_link = res_div.find('a', href=re.compile(r'/subtitrare/descarca/'))
            if not download_link: continue
            legatura = download_link['href']
            if not legatura.startswith('http'): legatura = BASE_URL.rstrip('/') + legatura

            main_part = u'[B]%s (%s)[/B]' % (nume, an)
            trad_part = u'Trad: [B][COLOR FFFDBD01]%s[/COLOR][/B]' % (traducator)
            lang_part = u'Limba: [B][COLOR FF00FA9A]%s[/COLOR][/B]' % (limba_text)
            upl_part = u'Up: [B][COLOR FFFF69B4]%s[/COLOR][/B]' % (uploader)
            display_name = u'%s | %s | %s | %s' % (main_part, trad_part, lang_part, upl_part)
            
            result.append({
                'SubFileName': display_name, 
                'ZipDownloadLink': legatura, 
                'LanguageName': lang_name, 
                'ISO639': iso_lang, 
                'SubRating': '5', 
                'Traducator': traducator
            })
        except: continue
            
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
                except: pass

        listitem = xbmcgui.ListItem(label=os.path.basename(final_sub_path))
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=final_sub_path, listitem=listitem, isFolder=False)
        
        def set_sub_delayed():
            time.sleep(1.0)
            xbmc.Player().setSubtitles(final_sub_path)

        import threading
        t = threading.Thread(target=set_sub_delayed)
        t.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))