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
    base_url = 'https://sub.wyzie.ru/search'
    video_path = xbmc.Player().getPlayingFile().lower()

    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    v_id = imdb_id or tmdb_id
    
    if not v_id: return

    user_key = __addon__.getSetting('wyzie_api_key')
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    lang_map = dict(zip(langs, lang_names))

    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')

    all_results = []
    s, e = xbmc.getInfoLabel("VideoPlayer.Season"), xbmc.getInfoLabel("VideoPlayer.Episode")

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
                
                # 1. Nume curat pentru AFIȘARE
                display_clean = clean_name(raw_name)
                
                # 2. Nume ultra-curat pentru DISC (api_filename) - eliminăm tot ce e dubios
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

    all_results.sort(key=lambda x: (not x['is_chosen'], -x['match_score'], -(x['dl_count'] or 0)))

    for res in all_results:
        # Folosim numele limbii ca Label principal pentru a evita rândurile duble
        li = xbmcgui.ListItem(label=res['language_name'])
        
        meta = f" [[COLOR aqua]{res['origin']}[/COLOR]]" if res['origin'] else ""
        src = f" [[COLOR green]{res['source']}[/COLOR]]"
        dl = f" [COLOR yellow]{res['dl_count']}[/COLOR]" if res['dl_count'] else ""
        
        # Setează restul detaliilor pe rândul al doilea
        li.setLabel2(f"{res['filename']}{meta}{src}{dl}")
        
        # PROPRIETĂȚI SYNC și HI
        li.setProperty("sync", "true" if res['match_score'] > 2 else "false")
        li.setProperty("hearing_imp", "true" if res['is_hi'] else "false")
        
        # Proprietăți tehnice pentru skin-ul default
        li.setProperty('language', res['language_name'])
        li.setProperty('filename', res['filename'])

        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        
        d_params = {
            'action': 'download', 
            'url': res['url'], 
            'l_code': res['l_code'], 
            'api_filename': res['api_filename']
        }
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)





def download(params):
    try:
        url = unquote(params.get('url', ''))
        l_code = params.get('l_code', 'ro')
        raw_name = params.get('api_filename', 'subtitle')
        
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files: 
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        dest_path = os.path.join(dest_dir, f"{raw_name}.{l_code}.srt")
        r = requests.get(url, timeout=25)
        if r.ok:
            f = xbmcvfs.File(dest_path, 'w')
            f.write(r.content)
            f.close()
            
            li = xbmcgui.ListItem(label=os.path.basename(dest_path))
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=li)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            
            xbmc.Player().setSubtitles(dest_path)
            
            robot_activat = __addon__.getSettingBool('robot_activat')
            robot_selectat = __addon__.getSettingInt('robot_selectat')
            idx = __addon__.getSettingInt('subs_languages')
            langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
            chosen_lang = langs[idx]

                        # --- COD CORECTAT PENTRU PORNIRE ROBOT 4 ---
            if l_code != chosen_lang and robot_activat:
                if robot_selectat == 1: 
                    threading.Thread(target=robot2.run_translation, args=(__id__,)).start()
                elif robot_selectat == 2: 
                    threading.Thread(target=robot3.run_translation, args=(__id__,)).start()
                elif robot_selectat == 3: # <--- ADAUGĂ ACEASTĂ LINIE PENTRU ROBOT 4
                    threading.Thread(target=robot4.run_translation, args=(__id__,)).start()
                else: 
                    threading.Thread(target=robot.run_translation, args=(__id__,)).start()
            else:
                try: threading.Thread(target=loader.run_false, args=(__id__,)).start()
                except: pass
            # --- FINAL COD CORECTAT ---

        else:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    except:
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
