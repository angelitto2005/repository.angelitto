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
try: import loader
except: pass

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0

def clean_name(text):
    if not text: return "subtitle"
    text = re.split(r'<br\s*/?>|\n', text, flags=re.IGNORECASE)[0]
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    return text.strip()

def show_error_dialog(response):
    """Afiseaza dialog de eroare si ofera optiunea de a merge la setari"""
    try:
        data = response.json()
        msg = data.get('message', 'Eroare Server')
        detail = data.get('details', 'Verificati setarile.')
    except:
        msg = "Eroare Conexiune"
        detail = f"Serverul Wyzie a raspuns cu status: {response.status_code}"

    header = f"Wyzie API Error ({response.status_code})"
    message = f"{msg}\n{detail}\n\n[COLOR yellow]Vrei sa mergi la setari sa verifici cheia sau sa schimbi sursa?[/COLOR]"
    
    if xbmcgui.Dialog().yesno(header, message, yeslabel="Setări", nolabel="Închide"):
        xbmc.executebuiltin(f'Addon.OpenSettings({__id__})')

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

    # Pas 1: Cautare Limba Ta + English (pentru Robot)
    targets = [l_code]
    if l_code != "en" and robot_activat:
        targets.append("en")

    for target_lang in targets:
        params = {'id': v_id, 'language': target_lang, 'source': 'all', 'key': user_key}
        if s and s != "0": params.update({'season': s, 'episode': e})
        try:
            r = requests.get(base_url, params=params, timeout=25)
            if r.status_code == 400: continue
            
            if not r.ok:
                show_error_dialog(r)
                return

            for sub in r.json():
                t_code = sub.get('language', 'en')
                full_lang = lang_map.get(t_code, t_code.upper())
                raw_name = sub.get('release') or sub.get('fileName') or 'sub.srt'
                clean = clean_name(raw_name)
                source = sub.get('source', 'api')
                
                all_results.append({
                    'language_name': full_lang,
                    'filename': f"{clean} [COLOR green]{source}[/COLOR]",
                    'url': sub['url'], 
                    'l_code': t_code, 
                    'api_filename': clean, 
                    'is_chosen': (t_code == l_code)
                })
        except: pass

    # Pas 2: FALLBACK (Daca lista e goala, cauta toate limbile)
    if not all_results:
        try:
            r = requests.get(base_url, params={'id': v_id, 'source': 'all', 'key': user_key}, timeout=25)
            if r.ok:
                for sub in r.json():
                    t_code = sub.get('language', 'en')
                    full_lang = lang_map.get(t_code, t_code.upper())
                    raw_name = sub.get('fileName') or sub.get('release') or 'sub.srt'
                    clean = clean_name(raw_name)
                    source = sub.get('source', 'api')
                    
                    all_results.append({
                        'language_name': full_lang,
                        'filename': f"{clean} [COLOR green]{source}[/COLOR]",
                        'url': sub['url'], 
                        'l_code': t_code, 
                        'api_filename': clean, 
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

            if l_code != chosen_lang and robot_activat:
                if robot_selectat == 1: threading.Thread(target=robot2.run_translation, args=(__id__,)).start()
                elif robot_selectat == 2: threading.Thread(target=robot3.run_translation, args=(__id__,)).start()
                else: threading.Thread(target=robot.run_translation, args=(__id__,)).start()
            else:
                try: threading.Thread(target=loader.run_false, args=(__id__,)).start()
                except: pass
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
