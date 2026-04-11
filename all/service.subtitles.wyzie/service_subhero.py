import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading, re, json, base64
import urllib.request, urllib.parse
from urllib.parse import unquote, urlencode, parse_qsl, quote
import unicodedata
__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
lib_path = xbmcvfs.translatePath(os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
try: import robot
except: xbmc.log("ER_ROBOT1: Nu s-a putut incarca robot.py", xbmc.LOGDEBUG)
try: import robot2
except: pass
try: import robot3
except: pass
try: import robot4
except: pass
try: import uploader
except: pass
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
def normalize_fonts(text):
    """Transformă caracterele Bold/Italic Unicode în litere normale"""
    if not text: return ""
    return "".join([c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)])
def clean_name(text):
    if not text: return "subtitle"
    text = normalize_fonts(text)
    text = re.split(r'<br\s*/?>|\n', text, flags=re.IGNORECASE)[0]
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    return text.strip()
def search():
    video_path = xbmc.Player().getPlayingFile().lower()
    imdb_id_raw = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    if not imdb_id_raw: return
    imdb_clean = imdb_id_raw.replace('tt','')
    imdb_id = f"tt{imdb_clean}"
    show_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    title_raw = show_title if show_title else xbmc.getInfoLabel("VideoPlayer.Title")
    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")
    raw_year = xbmc.getInfoLabel("VideoPlayer.Year")
    year_match = re.search(r'\d{4}', raw_year)
    ep_year = year_match.group(0) if year_match else "0000"
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    lang_map = dict(zip(langs, lang_names))
    stremio_map = {"ron": "ro", "rum": "ro", "eng": "en", "spa": "es", "fra": "fr", "ger": "de", "ita": "it", "hun": "hu"}
    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')
    all_results = []
    v_type = "series" if (s and str(s) != "0") else "movie"
    v_id_subhero = f"{imdb_id}:{s}:{e}" if v_type == "series" else imdb_id
    def fetch_subhero(languages):
        config_dict = {"language": languages, "onlyReturnMatching": False}
        config_encoded = quote(json.dumps(config_dict, separators=(',', ':')))
        url = f"https://subhero.chromeknight.dev/{config_encoded}/subtitles/{v_type}/{v_id_subhero}/manifest.json"
        try:
            r = requests.get(url, timeout=20)
            return r.json().get('subtitles', []) if r.ok else []
        except: return []
    s_langs = [l_code]
    if l_code != "en" and robot_activat: s_langs.append("en")
    subs = fetch_subhero(",".join(s_langs))
    if not subs: subs = fetch_subhero("en,ro,bg,hu")
    for sub in subs:
        short_lang = stremio_map.get(sub.get('lang', 'eng').lower(), sub.get('lang', 'en')[:2])
        clean_rel = clean_name(sub.get('release') or sub.get('description') or 'Subtitle')
        all_results.append({
            'label': lang_map.get(short_lang, short_lang.upper()),
            'filename': f"{clean_rel} [COLOR green]SubHero[/COLOR]",
            'url': sub['url'], 'l_code': short_lang, 'api_filename': clean_rel,
            'is_chosen': (short_lang == l_code), 'source': 'subhero'
        })
    try:
        import system_core
        u, w, z = system_core.get_auth_pieces()
        if u and w and z:
            user_email = "{}.com".format(u.split('.')[0] + "@" + w.split('.')[0])
            parola = z.split('.')[0]
        def clean_k_name(text):
            t = re.sub(r'[^a-zA-Z0-9]', ' ', text)
            return re.sub(r'\s+', '_', t).strip('_')
        t_clean = clean_k_name(title_raw)
        s_str, e_str = str(s).zfill(2), str(e).zfill(2)
        g_folder = f"Seriale/{t_clean}_S{s_str}E{e_str}_{ep_year}_{imdb_id}" if v_type == "series" else f"Filme/{t_clean}_{ep_year}_{imdb_id}"
        k_auth = "Basic " + base64.b64encode(f"{user_email}:{parola}".encode()).decode('ascii')
        safe_g_folder = "/".join([quote(p) for p in g_folder.split('/')])
        k_url = f"https://app.koofr.net/dav/Koofr/Subtitrari/{safe_g_folder}/"
        req = urllib.request.Request(k_url, method='PROPFIND', headers={"Authorization": k_auth, "Depth": "1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode('utf-8')
            files = re.findall(r'displayname(?: [^>]*)?>([^<]+)', xml_data)
            f_target = f".{l_code}."
            for f in files:
                f_clean = f.strip('/')
                if f_clean.lower().endswith(('.srt', '.sub')) and f_target in f_clean.lower():
                    safe_email = urllib.parse.quote(user_email)
                    all_results.append({
                        'label': lang_map.get(l_code, 'Romanian'),
                        'filename': f"[COLOR gold]R-[/COLOR] {f_clean}[COLOR gold] ROBOT[/COLOR]",
                        'url': f"davs://{safe_email}:{parola}@app.koofr.net/dav/Koofr/Subtitrari/{safe_g_folder}/{urllib.parse.quote(f_clean)}",
                        'l_code': l_code, 'api_filename': f_clean, 'is_chosen': True, 'source': 'koofr'
                    })
    except: pass
    all_results.sort(key=lambda x: (not x['is_chosen'], x['l_code']))
    for res in all_results:
        li = xbmcgui.ListItem(label=res['label'])
        li.setLabel2(res['filename'])
        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        d_params = {'action': 'download', 'url': res['url'], 'l_code': res['l_code'], 'api_filename': res['api_filename'], 'imdb': imdb_id, 'title': title_raw, 'season': s, 'episode': e}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urlencode(d_params)}", listitem=li)
    xbmcplugin.endOfDirectory(HANDLE)
def download(params):
    import xbmcvfs, os, requests, urllib.request, urllib.parse, base64, threading, sys
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
        content = None
        if "app.koofr.net" in url:
            try:
                import system_core
                u, w, z = system_core.get_auth_pieces()
                if u and w and z:
                    user_email = "{}.com".format(u.split('.')[0] + "@" + w.split('.')[0])
                    parola = z.split('.')[0]
                    clean_url = "https://" + url.split("@")[-1] if "@" in url else url.replace("davs://", "https://")
                    base_u, file_u = clean_url.rsplit('/', 1)
                    final_url = base_u + "/" + urllib.parse.quote(file_u)
                    auth_str = f"{user_email}:{parola}"
                    auth = base64.b64encode(auth_str.encode()).decode()
                    req = urllib.request.Request(final_url, headers={"Authorization": "Basic " + auth})
                    with urllib.request.urlopen(req, timeout=15) as r: content = r.read()
            except: pass
        if not content:
            r = requests.get(url, timeout=25)
            if r.ok: content = r.content
        if content:
            with open(dest_path, 'wb') as f_out:
                f_out.write(content)
            robot_activat = __addon__.getSettingBool('robot_activat')
            robot_selectat = __addon__.getSettingInt('robot_selectat')
            langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
            chosen_lang = langs[__addon__.getSettingInt('subs_languages')]
            is_tr = False
            if l_code != chosen_lang and robot_activat:
                is_tr = True
                try:
                    import robot, robot2, robot3, robot4
                    target_func = None
                    if robot_selectat == 0: target_func = robot.run_translation
                    elif robot_selectat == 1: target_func = robot2.run_translation
                    elif robot_selectat == 2: target_func = robot3.run_translation
                    elif robot_selectat == 3: target_func = robot4.run_translation
                    if target_func:
                        t = threading.Thread(target=target_func, args=(__id__,))
                        t.daemon = True
                        t.start()
                except ImportError as ie:
                    xbmcgui.Dialog().notification("Eroare Robot", f"Lipsește fișierul: {str(ie)}", xbmcgui.NOTIFICATION_ERROR)
                    xbmc.log(f"ROBOT_IMPORT_ERR: {str(ie)}", xbmc.LOGERROR)
                except Exception as re:
                    xbmc.log(f"ROBOT_START_ERR: {str(re)}", xbmc.LOGERROR)
            else:
                try: threading.Thread(target=loader.run_false, args=(__id__,)).start()
                except: pass
            try:
                import uploader
                log_i = {"imdb": params.get('imdb', 'NoID'), "title": params.get('title', 'NoTitle'), "s": params.get('season', ''), "e": params.get('episode', ''), "was_translated": is_tr, "src": l_code, "dest": chosen_lang, "api_filename": raw_name}
                uploader.send_log(log_i)
            except: pass
            list_item = xbmcgui.ListItem(label=os.path.basename(dest_path))
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=list_item, isFolder=False)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            xbmc.Player().setSubtitles(dest_path)
        else:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    except Exception as e:
        xbmc.log(f"DOWNLOAD_ERR: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
def run():
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download': download(p)
    else: search()
if __name__ == '__main__':
    run()