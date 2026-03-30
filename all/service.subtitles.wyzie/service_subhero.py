# -*- coding: utf-8 -*-
import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading, re, json
from urllib.parse import unquote, urlencode, parse_qsl, quote

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
        detail = f"Serverul SubHero a raspuns cu status: {response.status_code}"

    header = f"SubHero Error ({response.status_code})"
    message = f"{msg}\n{detail}\n\n[COLOR yellow]Vrei sa mergi la setari sa schimbi sursa?[/COLOR]"
    
    if xbmcgui.Dialog().yesno(header, message, yeslabel="Setări", nolabel="Închide"):
        xbmc.executebuiltin(f'Addon.OpenSettings({__id__})')

def search():
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    if not imdb_id: return
    if not imdb_id.startswith('tt'): imdb_id = 'tt' + imdb_id

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    lang_map = dict(zip(langs, lang_names))
    stremio_map = {"ron": "ro", "rum": "ro", "eng": "en", "spa": "es", "fra": "fr", "ger": "de", "ita": "it", "hun": "hu"}

    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')

    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    v_type = "series" if (season and season != "0") else "movie"
    v_id = f"{imdb_id}:{season}:{episode}" if v_type == "series" else imdb_id

    def fetch_data(languages):
        config_dict = {"language": languages, "onlyReturnMatching": False}
        config_encoded = quote(json.dumps(config_dict, separators=(',', ':')))
        url = f"https://subhero.chromeknight.dev/{config_encoded}/subtitles/{v_type}/{v_id}/manifest.json"
        try:
            r = requests.get(url, timeout=25)
            if r.status_code == 400: return None, r
            if not r.ok: return None, r
            return r.json().get('subtitles', []), r
        except: return None, None

    # Pas 1: Cautare Limba Ta + English
    search_langs = [l_code]
    if l_code != "en" and robot_activat: search_langs.append("en")
    
    subs, response = fetch_data(",".join(search_langs))

    # Pas 2: Fallback la toate limbile daca nu s-a gasit nimic
    if not subs and response and response.ok:
        all_langs = "en,ar,bg,bn,bs,ca,cs,da,de,el,es,et,fa,fi,fr,he,hi,hr,hu,id,it,ja,ko,lt,lv,mk,ms,nl,no,pb,pl,pt,ro,ru,sk,sl,sq,sr,sv,th,tr,uk,vi,zh"
        subs, _ = fetch_data(all_langs)

    if subs is None and response:
        show_error_dialog(response)
        return

    all_results = []
    if subs:
        for sub in subs:
            s_lang = sub.get('lang', 'eng').lower()
            short_lang = stremio_map.get(s_lang, s_lang[:2])
            raw_release = sub.get('release') or sub.get('description') or 'Subtitle'
            clean_release = clean_name(raw_release)
            
            display_label = f"{clean_release} [COLOR green]SubHero[/COLOR]"
            is_chosen = (short_lang == l_code)
            
            all_results.append({
                'label': lang_map.get(short_lang, short_lang.upper()),
                'filename': display_label,
                'url': sub['url'],
                'l_code': short_lang,
                'api_filename': clean_release,
                'is_chosen': is_chosen
            })

    all_results.sort(key=lambda x: (not x['is_chosen'], x['l_code']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['label'])
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
