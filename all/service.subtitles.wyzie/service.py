# -*- coding: utf-8 -*-
import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
lib_path = xbmcvfs.translatePath(os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
sys.path.append(lib_path)

try: import robot
except: xbmc.log("ROBOT LIB NOT FOUND", xbmc.LOGERROR)

try: import loader
except: xbmc.log("LOADER LIB NOT FOUND", xbmc.LOGERROR)

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0

def search():
    base_url = 'https://sub.wyzie.ru/search'
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    v_id = imdb_id or tmdb_id
    
    if not v_id: return

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    
    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')

    all_results = []
    s, e = xbmc.getInfoLabel("VideoPlayer.Season"), xbmc.getInfoLabel("VideoPlayer.Episode")

    # --- PASUL 1: CĂUTARE SPECIFICĂ WYZIE (Limba Aleasă + Engleză) ---
    targets = [l_code]
    if l_code != "en" and robot_activat:
        targets.append("en")

    for target_lang in targets:
        params = {'id': v_id, 'language': target_lang}
        if s and s != "0": params.update({'season': s, 'episode': e})
        try:
            r = requests.get(base_url, params=params, timeout=10)
            if r.ok:
                for sub in r.json():
                    t_code = sub.get('language', 'en')
                    all_results.append({
                        'label': f"[{t_code.upper()}] {sub.get('fileName', 'sub.srt')}",
                        'url': sub['url'], 'l_code': t_code, 'api_filename': sub.get('fileName'), 'is_chosen': (t_code == l_code)
                    })
        except: pass

    # --- PASUL 2: FALLBACK WYZIE (DACĂ NU S-A GĂSIT NIMIC) ---
    if not all_results and robot_activat:
        try:
            r = requests.get(base_url, params={'id': v_id}, timeout=10)
            if r.ok:
                for sub in r.json():
                    t_code = sub.get('language', 'en')
                    all_results.append({
                        'label': f"[ALL:{t_code.upper()}] {sub.get('fileName', 'sub.srt')}",
                        'url': sub['url'], 'l_code': t_code, 'api_filename': sub.get('fileName'), 'is_chosen': False
                    })
        except: pass

    # --- 3. SORTARE ȘI AFIȘARE ---
    all_results.sort(key=lambda x: (not x['is_chosen'], x['l_code']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['label'])
        li.setArt({'thumb': res['l_code']})
        d_params = {'action': 'download', 'url': res['url'], 'l_code': res['l_code'], 'api_filename': res['api_filename']}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)

def download(params):
    try:
        url = unquote(params.get('url', ''))
        l_code = params.get('l_code', 'ro')
        
        # Luăm numele original sau punem un nume generic dacă lipsește
        raw_name = params.get('api_filename') or 'subtitle'
        
        # Curățăm extensia .srt dacă există deja, ca să nu se repete
        if raw_name.lower().endswith(".srt"):
            raw_name = raw_name[:-4]
            
        # Construim numele final curat: Nume.ro.srt
        api_filename = f"{raw_name}.{l_code}.srt"

        langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
        chosen_lang = langs[__addon__.getSettingInt('subs_languages')]
        
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files: 
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        dest_path = os.path.join(dest_dir, api_filename)
        
        r = requests.get(url, timeout=20)
        if r.ok:
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=xbmcgui.ListItem(label=api_filename))
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            xbmc.Player().setSubtitles(dest_path)
            
            if l_code != chosen_lang:
                xbmc.log(f"ROBOT: Traducere din {l_code} in {chosen_lang}", xbmc.LOGINFO)
                threading.Thread(target=robot.run_translation, args=(__id__,)).start()
            else:
                xbmc.log(f"LOADER: Limba OK, se incarca direct", xbmc.LOGINFO)
                threading.Thread(target=loader.run_false, args=(__id__,)).start()
                
    except Exception as e:
        xbmc.log(f"DL ERROR: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download': download(p)
    else: search()
