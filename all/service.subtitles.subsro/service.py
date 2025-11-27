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
import subprocess
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

# SSL Context fix
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
import rarfile

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def log(module, msg):
    try:
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', 'ignore')
        full_msg = "### [%s] - %s" % (module, msg)
        if py3: xbmc.log(full_msg, level=xbmc.LOGINFO)
        else: xbmc.log(full_msg.encode('utf-8'), level=xbmc.LOGNOTICE)
    except: pass

def get_file_signature(file_path):
    """
    Citeste primii bytes pentru a determina tipul real al fisierului (ZIP vs RAR)
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(7)
            
        hex_header = binascii.hexlify(header).decode('utf-8').upper()
        log(__name__, "[SIGNATURE] Header Hex: %s" % hex_header)
        
        if hex_header.startswith('52617221'): 
            return 'rar'
        
        # MODIFICARE: Acceptam orice incepe cu 504B (PK) ca fiind ZIP
        # Asta rezolva cazul tau cu header 504B0708
        if hex_header.startswith('504B'): 
            return 'zip'
            
        return 'unknown'
    except Exception as e:
        log(__name__, "[SIGNATURE] Error reading header: %s" % str(e))
        return 'error'

def get_unrar_tool_path():
    system = platform.system().lower()
    machine = platform.machine().lower()
    unrar_path = ""
    bin_path = os.path.join(__cwd__, 'resources', 'bin')
    
    if xbmc.getCondVisibility('System.Platform.Android'):
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

def unpack_archive(archive_path, dest_path, forced_type=None):
    
    subtitle_exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    all_files = []
    
    real_type = get_file_signature(archive_path)
    log(__name__, ">>> START UNPACK <<<")
    log(__name__, "Detected Signature Type: %s" % real_type)
    
    # MODIFICARE: Daca semnatura e necunoscuta, fortam ZIP 
    # (deoarece numele e downloaded_file.dat si nu ne putem lua dupa extensie)
    if real_type == 'unknown':
        log(__name__, "[FALLBACK] Semnatura necunoscuta. Fortam extragerea ca ZIP.")
        real_type = 'zip'
        
    archive_type = real_type

    if os.path.exists(dest_path):
        try: shutil.rmtree(dest_path)
        except: pass
    try: os.makedirs(dest_path)
    except: pass

    if archive_type == 'zip':
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
            log(__name__, "[ZIP] Error: %s" % str(e))
            return []

    elif archive_type == 'rar':
        # ACEASTA SECTIUNE ESTE NEATINSA - EXACT CUM ERA IN SCRIPTUL TAU
        is_android = xbmc.getCondVisibility('System.Platform.Android')
        
        if not is_android:
            unrar_tool = get_unrar_tool_path()
            if unrar_tool:
                try:
                    cmd = [unrar_tool, 'e', '-o+', '-y', '-r', archive_path]
                    for ext in subtitle_exts: cmd.append('*' + ext)
                    cmd.append(dest_path)
                    
                    startupinfo = None
                    if xbmc.getCondVisibility('System.Platform.Windows'):
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                    subprocess.call(cmd, startupinfo=startupinfo)
                    
                    for f in os.listdir(dest_path):
                        full = os.path.join(dest_path, f)
                        if os.path.getsize(full) > 0 and os.path.splitext(f)[1].lower() in subtitle_exts:
                            all_files.append(full)
                except Exception as e:
                    log(__name__, "[RAR-BIN] Error: %s" % str(e))

        else:
            log(__name__, "[RAR-VFS] Android mode.")
            if not xbmc.getCondVisibility('System.HasAddon(vfs.rar)'):
                xbmcgui.Dialog().ok("Eroare", "Instalati 'RAR archive support'!")
                return []

            try:
                unique_id = str(int(time.time())) + str(random.randint(100, 999))
                unique_name = "sub_%s.rar" % unique_id
                workaround_rar = os.path.join(dest_path, unique_name)
                
                log(__name__, "[RAR-VFS] Unique temp name: %s" % unique_name)

                shutil.copyfile(archive_path, workaround_rar)

                norm_path = workaround_rar.replace('\\', '/')
                if not norm_path.startswith('/'): norm_path = '/' + norm_path
                
                if py3: encoded_base = urllib.quote(norm_path, safe='')
                else: encoded_base = urllib.quote(str(norm_path), safe='')
                
                rar_url_base = 'rar://' + encoded_base + '/'
                
                def scan_copy_vfs(curr_url, depth=0):
                    if depth > 10: return []
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
                            is_ok = False
                            
                            try:
                                if os.path.exists(dst): os.remove(dst)
                                if xbmcvfs.copy(src, dst):
                                    if os.path.exists(dst) and os.path.getsize(dst) > 0:
                                        is_ok = True
                                        found.append(dst)
                            except: pass

                            if not is_ok:
                                try:
                                    vfs_file = xbmcvfs.File(src, 'rb')
                                    content = vfs_file.readBytes() if py3 else vfs_file.read()
                                    vfs_file.close()

                                    if content:
                                        with open(dst, 'wb') as f_out:
                                            if not py3 and isinstance(content, unicode):
                                                f_out.write(content.encode('utf-8'))
                                            else:
                                                f_out.write(content)
                                            f_out.flush()
                                            os.fsync(f_out.fileno())
                                        
                                        if os.path.getsize(dst) > 0:
                                            found.append(dst)
                                except: pass
                    
                    for d in dirs:
                        d_n = d
                        if not py3 and isinstance(d, str): d_n = d.decode('utf-8','ignore')
                        if curr_url.endswith('/'): next_url = curr_url + d_n + '/'
                        else: next_url = curr_url + '/' + d_n + '/'
                        found.extend(scan_copy_vfs(next_url, depth + 1))
                    
                    return found

                all_files = scan_copy_vfs(rar_url_base)
                log(__name__, "[RAR-VFS] Extracted files: %d" % len(all_files))
                
                try:
                    time.sleep(0.5)
                    if os.path.exists(workaround_rar): os.remove(workaround_rar)
                except: pass

            except Exception as e:
                log(__name__, "[RAR-VFS] Critical: %s" % str(e))
                traceback.print_exc()

    return all_files

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
    log(__name__, ">>>>>>>>>> STARTING NUCLEAR CLEANUP <<<<<<<<<<")
    
    kodi_temp = xpath('special://temp/')
    
    folder_targets = [
        os.path.join(kodi_temp, 'addons'),
        os.path.join(kodi_temp, 'archive_cache'),
        __temp__
    ]

    for target in folder_targets:
        if os.path.exists(target):
            try:
                shutil.rmtree(target, ignore_errors=True)
                log(__name__, "[CLEAN-DIR] DELETED: %s" % target)
            except Exception as e:
                log(__name__, "[CLEAN-DIR] FAIL %s: %s" % (target, str(e)))
    
    try:
        subtitle_garbage_exts = ('.srt', '.sub', '.txt', '.ssa', '.ass', '.smi')
        if os.path.exists(kodi_temp):
            for f_name in os.listdir(kodi_temp):
                full_path = os.path.join(kodi_temp, f_name)
                if os.path.isfile(full_path):
                    if f_name.lower().endswith(subtitle_garbage_exts):
                        try:
                            os.remove(full_path)
                            log(__name__, "[CLEAN-FILE] DELETED LOOSE SUBTITLE: %s" % f_name)
                        except Exception as e:
                            log(__name__, "[CLEAN-FILE] FAIL %s: %s" % (f_name, str(e)))
    except Exception as e:
        log(__name__, "[CLEAN-FILE] Global error scanning temp files: %s" % str(e))

    try:
        os.makedirs(__temp__)
    except: pass
    
    time.sleep(0.5)
    log(__name__, ">>>>>>>>>> CLEANUP COMPLETE <<<<<<<<<<")
    # ------------------------------------------------------------

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

        raw_path = os.path.join(__temp__, "downloaded_file.dat")
        
        try:
            with open(raw_path, 'wb') as f: 
                f.write(response.content)
                f.flush()
                os.fsync(f.fileno())
            
            f_size = os.path.getsize(raw_path)
            log(__name__, "Fisier descarcat. Size: %d bytes" % f_size)
            if f_size < 100:
                xbmcgui.Dialog().ok("Eroare", "Fisier invalid (prea mic)!")
                return

        except Exception as e:
            log(__name__, "Eroare scriere disc: %s" % str(e))
            return
        
        extract_path = os.path.join(__temp__, "Extracted")
        
        all_files = unpack_archive(raw_path, extract_path)

        if not all_files:
            log(__name__, "Nu s-au extras fisiere. Abort.")
            xbmcgui.Dialog().ok("Eroare", "Nu s-au putut extrage subtitrari.")
            return
        
        if item.get('season') and item.get('episode') and item.get('season') != "0" and item.get('episode') != "0":
            subs_list = []
            epstr = '%s:%s' % (item['season'], item['episode'])
            episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
            for sub_file in all_files:
                if episode_regex.search(os.path.basename(sub_file)):
                    subs_list.append(sub_file)
            
            if subs_list:
                all_files = subs_list
        
        all_files = sorted(all_files, key=lambda f: natural_key(os.path.basename(f)))

        for ofile in all_files:
            lang_code = selected_sub_info["ISO639"]
            
            lang_label = selected_sub_info.get("LanguageName", lang_code)

            listitem = xbmcgui.ListItem(label=lang_label, label2=os.path.basename(ofile))
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