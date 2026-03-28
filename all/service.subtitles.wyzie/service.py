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

def show_error_dialog(response):
    """Afiseaza dialog pentru erori critice (401, 403, 500 etc.)"""
    try:
        data = response.json()
        msg = data.get('message', 'Eroare Server')
        detail = data.get('details', 'Verificati setarile.')
        xbmcgui.Dialog().ok(f"Wyzie API - Status {response.status_code}", f"{msg}\n\n{detail}")
    except:
        xbmcgui.Dialog().ok("Wyzie API Error", f"Serverul a raspuns cu eroarea: {response.status_code}")

def search():
    base_url = 'https://sub.wyzie.ru/search'
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
            
            # Daca e 400 (nu exista subtitrari), trecem peste fara dialog
            if r.status_code == 400:
                continue
                
            # Daca e alta eroare (401, 403 etc.), aratam dialogul si oprim
            if not r.ok:
                show_error_dialog(r)
                return

            for sub in r.json():
                t_code = sub.get('language', 'en')
                full_lang = lang_map.get(t_code, t_code.upper())
                display_name = sub.get('fileName') or sub.get('release') or 'sub.srt'
                
                all_results.append({
                    'language_name': full_lang,
                    'filename': display_name,
                    'url': sub['url'], 
                    'l_code': t_code, 
                    'api_filename': display_name, 
                    'is_chosen': (t_code == l_code)
                })
        except: pass

    if not all_results and robot_activat:
        try:
            r = requests.get(base_url, params={'id': v_id, 'source': 'all', 'key': user_key}, timeout=25)
            if r.ok:
                for sub in r.json():
                    t_code = sub.get('language', 'en')
                    full_lang = lang_map.get(t_code, t_code.upper())
                    display_name = sub.get('fileName') or sub.get('release') or 'sub.srt'
                    all_results.append({
                        'language_name': full_lang,
                        'filename': display_name,
                        'url': sub['url'], 
                        'l_code': t_code, 
                        'api_filename': display_name, 
                        'is_chosen': False
                    })
        except: pass

    all_results.sort(key=lambda x: (not x['is_chosen'], x['l_code']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])
        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        d_params = {'action': 'download', 'url': res['url'], 'l_code': res['l_code'], 'api_filename': res['api_filename']}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)

def download(params):
    try:
        url = unquote(params.get('url', ''))
        l_code = params.get('l_code', 'ro')
        raw_name = params.get('api_filename') or 'subtitle'
        if raw_name.lower().endswith(".srt"): raw_name = raw_name[:-4]
        api_filename = f"{raw_name}.{l_code}.srt"
        
        langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
        chosen_lang = langs[__addon__.getSettingInt('subs_languages')]
        
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files: 
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        dest_path = os.path.join(dest_dir, api_filename)
        r = requests.get(url, timeout=25)
        if r.ok:
            with open(dest_path, 'wb') as f: f.write(r.content)
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=xbmcgui.ListItem(label=api_filename))
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            xbmc.Player().setSubtitles(dest_path)
            
            if l_code != chosen_lang:
                threading.Thread(target=robot.run_translation, args=(__id__,)).start()
            else:
                threading.Thread(target=loader.run_false, args=(__id__,)).start()
    except Exception as e:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download': download(p)
    else: search()
