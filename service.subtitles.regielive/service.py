# -*- coding: utf-8 -*-

try:
    from cStringIO import StringIO
    py3 = False
except:
    from io import BytesIO as StringIO
    py3 = True
import os
import re
import shutil
import sys
import unicodedata
import urllib
try: 
    import urllib
    import urllib2
except ImportError: 
    import urllib.parse as urllib
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
import platform

# ==================================================================================================
# 1. DEFINIREA CAILOR (PATHS)
# ==================================================================================================

def ensure_str(string, encoding='utf-8'):
    if py3:
        return string
    if isinstance(string, unicode):
        string = string.encode(encoding)
    if not isinstance(string, str):
        string = str(string)
    return string

__addon__ = xbmcaddon.Addon()
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')

if py3:
    xpath = xbmcvfs.translatePath
    __cwd__        = xpath(__addon__.getAddonInfo('path'))
else:
    xpath = xbmc.translatePath
    __cwd__        = xpath(__addon__.getAddonInfo('path')).decode("utf-8")
    
__profile__    = ensure_str(xpath(__addon__.getAddonInfo('profile')))
__resource__   = ensure_str(xpath(os.path.join(__cwd__, 'resources', 'lib')))
__temp__       = ensure_str(xpath(os.path.join(__profile__, 'temp', '')))

# ==================================================================================================
# 2. ADAUGAREA DIRECTORULUI 'lib' LA CALEA DE CAUTARE A LUI PYTHON
# ==================================================================================================
sys.path.append(__resource__)

# ==================================================================================================
# 3. ACUM PUTEM IMPORTA MODULELE DIN DIRECTORUL 'lib'
# ==================================================================================================
from zipfile import ZipFile
import rarfile
import zipfile
import requests

# Restul codului ramane neschimbat

s = requests.Session()
ua = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:50.0) Gecko/20100101 Firefox/50.0'

BASE_URL = "https://subtitrari.regielive.ro/cauta.html?s="

if xbmcvfs.exists(__temp__):
    shutil.rmtree(__temp__)
xbmcvfs.mkdirs(__temp__)

def log(msg):
    if py3:
        loginfo = xbmc.LOGINFO
    else:
        loginfo = xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s]: %s" % (__scriptname__, msg), level=loginfo )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % (__scriptname__, msg.encode("utf-8", "ignore")), level=loginfo )
    except:
        xbmc.log("### [%s]: %s" % (__scriptname__, 'ERROR LOG'), level=loginfo )

def get_unrar_tool_path():
    log("Detectez platforma si arhitectura pentru unealta unrar...")
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    unrar_path = ""
    
    bin_dir = os.path.join(__cwd__, 'resources', 'bin')

    if os.path.exists('/system/build.prop'):
        log("Platforma detectata: Android")
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(bin_dir, 'android_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(bin_dir, 'android_arm', 'unrar')
            
    elif 'linux' in system:
        log("Platforma detectata: Linux (OSMC/Desktop etc.)")
        for tool in ['/usr/bin/unrar', '/usr/bin/unrar-free']:
            if os.path.exists(tool):
                log("Am gasit unealta de sistem la: %s" % tool)
                return tool
        
        if 'aarch64' in machine or 'arm64' in machine:
            unrar_path = os.path.join(bin_dir, 'linux_arm64', 'unrar')
        if not os.path.exists(unrar_path):
            unrar_path = os.path.join(bin_dir, 'linux_arm', 'unrar')
            
    elif 'win' in system:
        log("Platforma detectata: Windows")
        unrar_path = os.path.join(bin_dir, 'windows_x64', 'UnRAR.exe')

    if unrar_path and os.path.exists(unrar_path):
        log("Am gasit unealta unrar la: %s" % unrar_path)
        if 'win' not in system:
            try: os.chmod(unrar_path, 0o755)
            except Exception as e: log("Nu am putut seta permisiuni de executie: %s" % e)
        return unrar_path

    log("EROARE: Nu am gasit nicio unealta unrar compatibila pentru platforma %s/%s" % (system, machine))
    return None

def unpack_archive(archive_physical_path, dest_physical_path, archive_type):
    all_files = []
    
    try:
        if not xbmcvfs.exists(dest_physical_path):
            xbmcvfs.mkdirs(dest_physical_path)

        if archive_type == 'zip':
            log("Initializez extragerea ZIP folosind metoda directa (zipfile)...")
            with zipfile.ZipFile(archive_physical_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
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

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2:
        return "%%%%%"
    season = int(parts[0])
    epnr = int(parts[1])
    patterns = [
        "s%#02de%#02d" % (season, epnr),
        "%#02dx%#02d" % (season, epnr),
        "%#01de%#02d" % (season, epnr),
    ]
    if season < 10:
        patterns.append("(?:\A|\D)%dx%#02d" % (season, epnr))
    return '(?:%s)' % '|'.join(patterns)

def Search(item):
    search_data = []
    search_data = searchsubtitles(item)
    if search_data != None:
        for item_data in search_data:
            listitem = xbmcgui.ListItem(label=item_data["LanguageName"],
                                        label2=item_data["SubFileName"])
            listitem.setArt({'icon': str(item_data["SubRating"]),
                             'thumb': str(item_data["ISO639"])})

            listitem.setProperty("sync", ("false", "true")[str(item_data["MatchedBy"]) == "moviehash"])
            listitem.setProperty("hearing_imp", ("false", "true")[int(item_data["SubHearingImpaired"]) != 0])
            url = "plugin://%s/?action=download&link=%s&filename=%s&format=%s&promo=%s" % (__scriptid__,
                                                                                  item_data["ZipDownloadLink"],
                                                                                  item_data["SubFileName"],
                                                                                  item_data["SubFormat"],
                                                                                  item_data["promo"]
                                                                                  )
            
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    import PTN

    if item.get('mansearch'):
        search_string_manual = urllib.unquote(item['mansearchstr'])
        parsed_manual = PTN.parse(search_string_manual)
        
        search_title = parsed_manual.get('title', search_string_manual)
        search_season = str(parsed_manual.get('season', ''))
        search_episode = str(parsed_manual.get('episode', ''))
        search_year = str(parsed_manual.get('year', ''))

        log("Cautare Manuala: Titlu('%s') Sezon('%s') Episod('%s')" % (search_title, search_season, search_episode))
        return search_links(search_title, search_year, search_season, search_episode)

    # --- Logica pentru cautare automata ---
    search_season = item.get('season')
    search_episode = item.get('episode')
    search_year = item.get('year')
    
    # Obtinem cel mai bun titlu brut, indiferent de sursa
    raw_title_str = item.get('tvshow') or item.get('title') or os.path.basename(item.get('file_original_path', ''))
    log("Titlu brut initial: %s" % raw_title_str)
    
    # Daca metadatele de la Kodi/TMDb Helper lipsesc, incercam sa le extragem din NUMELE FISIERULUI
    if (not search_season or not search_episode) and item.get('file_original_path'):
        filename = os.path.basename(item.get('file_original_path', ''))
        log("Metadate incomplete de la Kodi. Se parseaza numele fisierului: %s" % filename)
        parsed_meta = PTN.parse(filename)
        if not search_season: search_season = str(parsed_meta.get('season', ''))
        if not search_episode: search_episode = str(parsed_meta.get('episode', ''))
        if not search_year: search_year = str(parsed_meta.get('year', ''))
        
        # Extragem titlul curat din numele fisierului, NU din raw_title_str
        raw_title_str = filename

    # Curatare Agresiva a titlului pentru cautare
    # Inlaturam tag-urile Kodi [COLOR] etc.
    search_title = re.sub(r'\[/?(COLOR|B|I)[^\]]*\]', '', raw_title_str, flags=re.IGNORECASE)
    # Inlaturam tot ce se afla in paranteze si brackets
    search_title = re.sub(r'\(.*?\)|\[.*?\]', '', search_title)
    
    # NOUA LOGICA: Daca avem puncte in titlu, presupunem ca e format de release
    if '.' in search_title:
        # Inlocuim punctele cu spatii
        parts = search_title.replace('.', ' ').split()
        title_parts = []
        found_year = False
        
        for part in parts:
            part_upper = part.upper()
            
            # Stop la indicatori de sezon/episod
            if re.match(r'^[Ss]\d{1,2}([Ee]\d{1,2})?$', part):
                break
            
            # Verificam daca e an (4 cifre)
            if re.match(r'^(19|20)\d{2}$', part):
                if not search_year:
                    search_year = part
                found_year = True
                break  # Ne oprim la an
            
            # Skip tag-uri comune care nu fac parte din titlu
            if part_upper in ['FREELEECH', '1080P', '720P', '480P', 'BLURAY', 'WEBRIP', 
                             'HDTV', 'X264', 'X265', 'H264', 'H265', 'DTS', 'AAC', 
                             'DD5', 'DD2', 'PROPER', 'REPACK', 'EXTENDED', 'UNRATED']:
                continue
            
            title_parts.append(part)
        
        search_title = ' '.join(title_parts).strip()
    else:
        # Daca nu sunt puncte, folosim logica de cautare pattern
        match = re.search(r'\b(S[0-9]{1,2}|Season[\s\.]?[0-9]{1,2}|(19|20)\d{2})\b', search_title, re.IGNORECASE)
        if match:
            search_title = search_title[:match.start()]
    
    # Curatare finala - eliminam spatii multiple
    search_title = ' '.join(search_title.split()).strip()

    if not search_title:
        log("Eroare Critica: Nu am putut extrage un titlu valid. Cautarea se anuleaza.")
        return []

    log("Date finale pentru cautare: Titlu('%s') An('%s') Sezon('%s') Episod('%s')" % (search_title, search_year, search_season, search_episode))
    return search_links(search_title, search_year, search_season, search_episode)


def search_links(nume='', an='', sezon='', episod=''):
    # ADAUGAT IMPORT PENTRU LOGICA DE SORTARE
    import difflib

    urlcautare = '%s%s' % (BASE_URL, nume.replace(" ", "+"))
    log("URL Cautare: %s" % urlcautare)
    continuturl = get_search(urlcautare)
    if not continuturl:
        log("Nu am putut accesa pagina de cautare.")
        return []

    first_search = re.compile('"imagine">.*?href="(.*?)".*?<img.*?alt="(.*?)".*?tag-.*?">(.*?)<', re.IGNORECASE | re.DOTALL).findall(continuturl)
    if not first_search:
        log("Niciun film/serial gasit pe site pentru '%s'" % nume)
        return []

    # ==================== MODIFICARE CHEIE: SORTAREA REZULTATELOR ====================
    # Sortam lista 'first_search' pe baza similaritatii dintre titlul rezultatului (x[1])
    # si numele cautat ('nume'). Rezultatul cel mai similar va fi primul.
    first_search.sort(
        key=lambda x: difflib.SequenceMatcher(None, nume.lower(), x[1].lower()).ratio(),
        reverse=True
    )
    # ==================== SFARSIT MODIFICARE ====================

    if len(first_search) > 1:
        dialog = xbmcgui.Dialog()
        # Dialogul 'select' va folosi acum lista sortata, afisand cel mai bun rezultat primul.
        sel = dialog.select("RegieLive",['%s - %s' % (x[1], x[2]) for x in first_search])
    else:
        sel = 0

    if sel >= 0:
        if sezon and sezon != "0":
            try:
                sezon_numar = str(int(sezon))
                pagina_url = '%ssezonul-%s/' % (first_search[sel][0], sezon_numar)
                log("Navighez direct la pagina sezonului: %s" % pagina_url)
            except (ValueError, TypeError):
                 pagina_url = first_search[sel][0]
                 log("Sezon invalid, navighez la pagina principala: %s" % pagina_url)
        else:
            pagina_url = first_search[sel][0]
            log("Nu este serial sau sezonul e 0, navighez la pagina principala: %s" % pagina_url)

        continuturl = get_search(pagina_url)
        
        if not continuturl:
            log("Nu am putut accesa pagina serialului/filmului.")
            return []

        all_subs_found = []
        regex = '''<li class="subtitrare.*?id=".*?>(.*?)<.*?(?: |.*?title="Nota (.*?) d).*?href="(.*?descarca.*?)"'''
        search_results = re.compile(regex, re.IGNORECASE | re.DOTALL).findall(continuturl)
        if search_results:
            for item_search in search_results:
                rate = int(float(item_search[1])) if item_search[1] else 0
                subfilename = item_search[0].strip()
                item_data = {'SeriesSeason': sezon, 'SeriesEpisode': episod, 'LanguageName': 'Romanian',
                        'promo': '', 'SubFileName': subfilename, 'SubRating': rate,
                        'ZipDownloadLink': item_search[2], 'ISO639': 'ro', 'SubFormat': 'srt', 'MatchedBy': 'fulltext', 'SubHearingImpaired': '0'}
                all_subs_found.append(item_data)
            
            if sezon and episod and sezon != "0" and episod != "0":
                final_list = []
                epstr = '{season}:{episode}'.format(season=sezon, episode=episod)
                episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
                for subs in all_subs_found:
                    if episode_regex.search(subs.get('SubFileName')):
                        final_list.append(subs)
                log("Am gasit %d subtitrari potrivite pentru S%sE%s" % (len(final_list), sezon, episod))
                return final_list
            else:
                return all_subs_found
    return []

def Download(link, urld, format, stack=False):
    url = re.sub('download', 'descarca', urld)
    url = re.sub('html', 'zip', url)
    headers = {'User-Agent': ua}
    if ((__addon__.getSetting("OSuser") and
        __addon__.getSetting("OSpass"))):
        payload = {'l_username':__addon__.getSetting("OSuser"), 'l_password':__addon__.getSetting("OSpass")}
        s.post('https://www.regielive.ro/membri/login.html', data=payload, headers=headers)
    headers['Host'] =  'subtitrari.regielive.ro'
    headers['Referer'] =  urld
    
    try:
        f = s.get(url, headers=headers, verify=False, timeout=15)
        f.raise_for_status()
        archive_content = f.content
    except Exception as e:
        log("Eroare la descarcare arhiva: %s" % e)
        return [], []

    if not archive_content:
        log("Descarcarea a esuat sau fisierul este gol.")
        return [], []

    archive_type = None
    if archive_content.startswith(b'PK\x03\x04'):
        archive_type = 'zip'
    elif archive_content.startswith(b'Rar!\x1a\x07'):
        archive_type = 'rar'

    if not archive_type:
        log("Nu am putut determina tipul arhivei sau formatul nu este suportat.")
        return [], []

    temp_archive_path = os.path.join(__temp__, "downloaded_archive.%s" % archive_type)
    temp_archive_path = ensure_str(temp_archive_path)
    try:
        with open(temp_archive_path, 'wb') as archive_file:
            archive_file.write(archive_content)
    except Exception as e:
        log("Eroare la scrierea fisierului arhiva temporar: %s" % e)
        return [], []
    
    extract_path = os.path.join(__temp__, "extracted")
    extracted_files = unpack_archive(temp_archive_path, extract_path, archive_type)

    if not extracted_files:
        log("Extragerea a esuat sau nu a rezultat niciun fisier.")
        return [], []

    subtitle_list = []
    pub_list = []
    exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    ext_pub = [".url"]

    extracted_files.sort(key=natural_key)

    for file_path in extracted_files:
        if os.path.splitext(file_path)[1].lower() in exts:
            subtitle_list.append(ensure_str(file_path))
        elif __addon__.getSetting("nopop") == "false" and os.path.splitext(file_path)[1].lower() in ext_pub:
            pub_name = os.path.splitext(os.path.basename(file_path))[0]
            pub_list.append(pub_name)

    if subtitle_list and xbmcvfs.exists(subtitle_list[0]):
        if len(subtitle_list) > 1:
            dialog = xbmcgui.Dialog()
            sel = dialog.select("%s" % ('Selecteaza o subtitrare'),
                                [os.path.basename(x) for x in subtitle_list])
            if sel >= 0:
                return [subtitle_list[sel]], pub_list
            else:
                return [], []
        else:
            return subtitle_list, pub_list
    else:
        return [], []


def normalizeString(str):
    if py3:
        return str
    return unicodedata.normalize('NFKD', unicode(unicode(str, 'utf-8'))).encode('ascii', 'ignore')

def natural_key(string_):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]

def get_search(url):
    headers = {'User-Agent': ua, 'Content-type': 'application/x-www-form-urlencoded', 'Host': 'subtitrari.regielive.ro'}
    try:
        continut = s.get(url, headers=headers, verify=False)
        return continut.text
    except:
        return False

def get_params(string=""):
    param = []
    if string == "":
        paramstring = sys.argv[2]
    else:
        paramstring = string
    if len(paramstring) >= 2:
        params = paramstring
        cleanedparams = params.replace('?', '')
        if (params[len(params)-1] == '/'):
            params = params[0:len(params)-2]
        pairsofparams = cleanedparams.split('&')
        param = {}
        for i in range(len(pairsofparams)):
            splitparams = {}
            splitparams = pairsofparams[i].split('=')
            if (len(splitparams)) == 2:
                param[splitparams[0]] = splitparams[1]

    return param

params = get_params()
#log(params)

if params['action'] == 'search' or params['action'] == 'manualsearch':
    item = {}
    item['mansearch']          = params['action'] == 'manualsearch'
    if item['mansearch']:
        item['mansearchstr'] = params.get('searchstring', '')
    
    item['year']               = xbmc.getInfoLabel("VideoPlayer.Year")
    item['season']             = str(xbmc.getInfoLabel("VideoPlayer.Season"))
    item['episode']            = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
    item['tvshow']             = normalizeString(xbmc.getInfoLabel("VideoPlayer.TVshowtitle"))
    item['title']              = normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))
    item['file_original_path'] = xbmc.Player().getPlayingFile() if py3 else xbmc.Player().getPlayingFile().decode('utf-8')
    
    if not item['title']:
        item['title']  = normalizeString(xbmc.getInfoLabel("VideoPlayer.Title"))

    Search(item)

elif params['action'] == 'download':
    subs, pubs = Download(params["link"], params["link"], params["format"])
    if len(pubs) > 0:
        promo = pubs[0]
    else:
        promo = params.get('promo', '')
    if subs:
        try:
            xbmc.Player().setSubtitles(subs[0])
        except: pass
        for sub in subs:
            listitem = xbmcgui.ListItem(label=sub)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=sub, listitem=listitem, isFolder=False)
        if promo and xbmc.getCondVisibility('Player.HasVideo') and __addon__.getSetting("nopop") == "false":
            from threading import Thread
                    
            class PubRegie(xbmcgui.WindowDialog):
                def __init__(self):
                    self.background = xbmcgui.ControlImage(10, 70, 1000, 100, "")
                    self.text = xbmcgui.ControlLabel(10, 70, 1000, 100, '', textColor='0xff000000', alignment=0)
                    self.text2 = xbmcgui.ControlLabel(8, 68, 1000, 100, '', alignment=0)
                    self.addControls((self.text, self.text2))
                def sP(self, promo):
                    self.show()
                    self.text.setLabel(chr(10) + "[B]%s[/B]" % promo)
                    self.text2.setLabel(chr(10) + "[B]%s[/B]" % promo)
                    self.text.setAnimations([('WindowOpen', 'effect=fade start=0 end=100 time=250 delay=125 condition=true'),
                                            ('WindowClose', 'effect=fade start=100 end=0 time=250 condition=true')])
                    self.background.setAnimations([('WindowOpen', 'effect=fade start=0 end=100 time=250 delay=125 condition=true'),
                                            ('WindowClose', 'effect=fade start=100 end=0 time=250 condition=true')])
                    xbmc.sleep(4500)
                    self.close()
                    del self
            t1 = Thread(target=(PubRegie().sP), args=(str(promo),))
            t1.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))