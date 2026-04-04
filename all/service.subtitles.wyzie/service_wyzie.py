# -*- coding: utf-8 -*-
import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading, re, json
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
lib_path = xbmcvfs.translatePath(os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
sys.path.append(lib_path)

try: import robot
except: pass
try: import robot2
except: pass
try: import robot3
except: pass
try: import robot4
except: pass
try: import loader
except: pass

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0

import re
import unicodedata

def normalize_fonts(text):
    """Transformă caracterele Bold/Italic Unicode în litere normale"""
    if not text: return ""
    return "".join([c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)])

def clean_name(text):
    if not text: return "subtitle"
    # Normalizăm fonturile înainte de orice
    text = normalize_fonts(text)
    text = re.split(r'<br\s*/?>|\n', text, flags=re.IGNORECASE)[0]
    # Eliminăm caracterele interzise pe disc
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    return text.strip()
def search():
    import base64, re, urllib.request, urllib.parse, requests
    from urllib.parse import urlencode

    base_url = 'https://sub.wyzie.ru/search'
    video_path = xbmc.Player().getPlayingFile().lower()

    # --- DATE METADATA PENTRU LOGGER ȘI KOOFR ---
    imdb_id_raw = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    imdb_clean = imdb_id_raw.replace('tt','') if imdb_id_raw else ""
    imdb_id = f"tt{imdb_clean}" if imdb_clean else "unknown"
    
    show_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    title_raw = show_title if show_title else xbmc.getInfoLabel("VideoPlayer.Title")
    
    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")
    
    raw_year = xbmc.getInfoLabel("VideoPlayer.Year")
    year_match = re.search(r'\d{4}', raw_year)
    ep_year = year_match.group(0) if year_match else "0000"
    
    v_id = imdb_id_raw or xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    if not v_id: return

    user_key = __addon__.getSetting('wyzie_api_key')
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    lang_map = dict(zip(langs, lang_names))

    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')

    all_results = []

    # --- 1. CĂUTARE WYZIE (RO/EN) ---
    targets = [l_code]
    if l_code != "en" and robot_activat:
        targets.append("en")

    for target_lang in targets:
        params = {'id': v_id, 'language': target_lang, 'source': 'all', 'key': user_key}
        if s and s != "0": params.update({'season': s, 'episode': e})
        try:
            r = requests.get(base_url, params=params, timeout=25)
            if r.status_code == 400: continue
            if not r.ok: continue

            for sub in r.json():
                raw_name = sub.get('release') or sub.get('fileName') or 'sub.srt'
                display_clean = clean_name(raw_name)
                disk_name = re.sub(r'[^a-zA-Z0-9\s\.\-\[\]\(\)]', '', display_clean)
                
                score = 0
                if any(tag in raw_name.lower() for tag in ["amzn", "amazon", "web-dl", "bluray", "dvdrip", "x264"]):
                    words = raw_name.lower().replace('.', ' ').split()
                    score = sum(1 for word in words if word in video_path)

                all_results.append({
                    'language_name': lang_map.get(sub.get('language'), 'Unknown'),
                    'filename': display_clean,
                    'url': sub['url'], 
                    'l_code': sub.get('language', 'en'), 
                    'api_filename': disk_name, 
                    'is_chosen': (sub.get('language') == l_code),
                    'is_hi': sub.get('isHearingImpaired', False),
                    'source': sub.get('source', 'api'),
                    'origin': sub.get('origin', ''),
                    'dl_count': sub.get('downloadCount'),
                    'match_score': score
                })
        except: pass

    # --- 2. CĂUTARE KOOFR (DOAR LIMBA TA) ---
    try:
        def clean_name_robot(text):
            if not text: return "Unknown"
            t = re.sub(r'[^a-zA-Z0-9]', ' ', text)
            return re.sub(r'\s+', '_', t).strip('_')
        t_clean = clean_name_robot(title_raw)
        
        if show_title or (s and str(s).isdigit()):
            s_str, e_str = str(s).zfill(2), str(e).zfill(2)
            g_folder = f"Seriale/{t_clean}_S{s_str}E{e_str}_{ep_year}_{imdb_id}"
        else:
            g_folder = f"Filme/{t_clean}_{ep_year}_{imdb_id}"

        k_auth = "Basic " + base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')
        safe_g_folder = "/".join([urllib.parse.quote(p) for p in g_folder.split('/')])
        k_url = f"https://app.koofr.net/dav/Koofr/Subtitrari/{safe_g_folder}/"
        
        req = urllib.request.Request(k_url, method='PROPFIND', headers={"Authorization": k_auth, "Depth": "1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode('utf-8')
            files = re.findall(r'<[a-zA-Z0-9:]*displayname>([^<]+)</[a-zA-Z0-9:]*displayname>', xml_data)
            
            f_target = f".{l_code}."
            for f in files:
                f_clean = f.strip('/')
                if f_clean.lower().endswith(('.srt', '.sub')) and f_target in f_clean.lower():
                    k_match = sum(1 for tag in ["amzn", "web-dl", "bluray", "x264"] if tag in f_clean.lower() and tag in video_path)
                    all_results.append({
                        'language_name': lang_map.get(l_code, 'Romanian'),
                        'filename': f_clean,
                        'url': f"davs://blagoie%40gmail.com:kh445t87ds404h70@app.koofr.net/dav/Koofr/Subtitrari/{safe_g_folder}/{urllib.parse.quote(f_clean)}",
                        'l_code': l_code, 
                        'api_filename': f_clean, 
                        'is_chosen': True,
                        'is_hi': False, 
                        'source': 'Tradus',
                        'origin': 'ROBOT',
                        'dl_count': 0,
                        'match_score': k_match,
                    })
    except: pass

    all_results.sort(key=lambda x: (not x['is_chosen'], -x['match_score'], -(x['dl_count'] or 0)))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        
        meta = f" [[COLOR aqua]{res['origin']}[/COLOR]]" if res['origin'] else ""
        # Prefix vizual pentru Cloud (Koofr)
        prefix = "[COLOR gold]-[/COLOR]" if res.get('source') == 'Koofr' else ""
        src = f" [[COLOR green]{res['source']}[/COLOR]]"
        dl = f" [COLOR yellow]{res['dl_count']}[/COLOR]" if res['dl_count'] else ""
        
        li.setLabel2(f"{prefix}{res['filename']}{meta}{src}{dl}")
        
        li.setProperty("sync", "true" if res['match_score'] > 2 else "false")
        li.setProperty("hearing_imp", "true" if res['is_hi'] else "false")
        li.setProperty('language', res['language_name'])
        li.setProperty('filename', res['filename'])
        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        
        d_params = {
            'action': 'download', 
            'url': res['url'], 
            'l_code': res['l_code'], 
            'api_filename': res['api_filename'],
            # ADAUGĂM DATELE PENTRU LOGGER (Trimise către uploader.py)
            'imdb': imdb_id,
            'title': title_raw,
            'season': s,
            'episode': e
        }
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)

def download(params):
    import xbmcvfs, os, requests, urllib.request, urllib.parse, base64, threading, sys
    try:
        # --- CONFIGURARE CALE LIB PENTRU UPLOADER ---
        addon_path = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
        lib_path = os.path.join(addon_path, 'lib') 
        if lib_path not in sys.path:
            sys.path.append(lib_path)

        url = urllib.parse.unquote(params.get('url', ''))
        l_code = params.get('l_code', 'ro')
        raw_name = params.get('api_filename', 'subtitle')
        
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        
        # Curățare fișiere vechi
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files: 
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        dest_path = os.path.join(dest_dir, f"{raw_name}.{l_code}.srt")
        
        # Download (Koofr sau OpenSubs)
        content = None
        if "app.koofr.net" in url:
            try:
                # REPARARE DESCARCARE KOOFR
                auth = base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')
                # Extragem doar partea de domeniu și cale, eliminând tot ce e înainte de @
                clean_url = url.split('@')[-1] if '@' in url else url.replace("davs://", "")
                if not clean_url.startswith("https://"):
                    clean_url = "https://" + clean_url
                
                req = urllib.request.Request(clean_url, headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(req, timeout=20) as r: 
                    content = r.read()
            except Exception as e:
                xbmc.log(f"KOOFR_DL_RETRY_ERR: {str(e)}", xbmc.LOGERROR)
        
        if not content:
            r = requests.get(url, timeout=25)
            if r.ok: content = r.content

        if content:
            with open(dest_path, 'wb') as f_out:
                f_out.write(content)
            
            li = xbmcgui.ListItem(label=os.path.basename(dest_path))
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=li)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            
            xbmc.Player().setSubtitles(dest_path)
            
            # Parametri Addon
            robot_activat = __addon__.getSettingBool('robot_activat')
            robot_selectat = __addon__.getSettingInt('robot_selectat')
            langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
            chosen_lang = langs[__addon__.getSettingInt('subs_languages')]

            is_translated = False
            # --- LOGICĂ ROBOT ---
            if l_code != chosen_lang and robot_activat:
                is_translated = True
                # Selectare robot (0=Robot1, 1=Robot2, etc.)
                robots = [robot, robot2, robot3, robot4]
                target_robot = robots[robot_selectat] if robot_selectat < len(robots) else robot
                threading.Thread(target=target_robot.run_translation, args=(__id__,)).start()
            else:
                try: threading.Thread(target=loader.run_false, args=(__id__,)).start()
                except: pass

            # --- TRIMITERE LOG CĂTRE UPLOADER.PY ---
            try:
                import uploader
                log_info = {
                    "imdb": params.get('imdb', 'NoID'),
                    "title": params.get('title', 'NoTitle'),
                    "s": params.get('season', ''),
                    "e": params.get('episode', ''),
                    "was_translated": is_translated,
                    "src": l_code,
                    "dest": chosen_lang,
                    "api_filename": raw_name
                }
                uploader.send_log(log_info)
            except Exception as e:
                xbmc.log(f"LOGGER_FAIL: {str(e)}", xbmc.LOGERROR)

        else:
            raise Exception("Nu s-a putut descarca continutul")
               
    except Exception as e:
        xbmc.log(f"DOWNLOAD_ERR: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)



def run():
    cmd_args = ""
    for arg in sys.argv:
        if "?" in str(arg):
            cmd_args = str(arg).partition("?")[2]
            break
            
    p = dict(parse_qsl(cmd_args)) if cmd_args else {}
    
    if p.get('action') == 'download': 
        download(p)
    else: 
        search()

if __name__ == '__main__':
    run()
