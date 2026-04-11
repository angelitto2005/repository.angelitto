import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading, re, unicodedata
from urllib.parse import unquote, urlencode, parse_qsl
import base64
__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
lib_path = xbmcvfs.translatePath(os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
sys.path.append(lib_path)
try: import robot
except: xbmc.log("ROBOT1 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot2
except: xbmc.log("ROBOT2 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot3
except: xbmc.log("ROBOT3 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot4
except: xbmc.log("ROBOT4 LIB NOT FOUND", xbmc.LOGERROR)
try: import loader
except: xbmc.log("LOADER LIB NOT FOUND", xbmc.LOGERROR)
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
def vtt_to_srt(vtt_text):
    """Converteste formatul VTT in SRT pentru compatibilitate cu robotii"""
    lines = vtt_text.replace('\r\n', '\n').split('\n')
    srt_lines = []
    counter = 1
    for line in lines:
        if "WEBVTT" in line or "Kind:" in line or "Language:" in line: continue
        if ' --> ' in line:
            srt_lines.append(str(counter))
            srt_lines.append(line.replace('.', ','))
            counter += 1
        elif line.strip() or (srt_lines and srt_lines[-1] != ""):
            srt_lines.append(line)
    return '\n'.join(srt_lines)
def normalize_fonts(text):
    """Transformă caracterele Bold/Italic Unicode în litere normale (A-Z)"""
    if not text: return ""
    return "".join([c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c)])
def clean_filename(text):
    """Curăță numele fișierului pentru a fi valid pe disc"""
    if not text: return "subtitle"
    text = normalize_fonts(text)
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    if text.lower().endswith('.srt'): text = text[:-4]
    if text.lower().endswith('.vtt'): text = text[:-4]
    text = re.sub(r'[^a-zA-Z0-9\s\.\-\(\)\[\]]', '', text)
    return text.strip()
def search():
    import base64, re, urllib.request, urllib.parse, requests
    from urllib.parse import urlencode
    video_path = xbmc.Player().getPlayingFile().lower()
    imdb_id_raw = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    imdb_clean = imdb_id_raw.replace('tt','') if imdb_id_raw else ""
    imdb_id = f"tt{imdb_clean}" if imdb_clean else "unknown"
    show_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    title_raw = show_title if show_title else xbmc.getInfoLabel("VideoPlayer.Title")
    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    raw_year = xbmc.getInfoLabel("VideoPlayer.Year")
    year_match = re.search(r'\d{4}', raw_year)
    ep_year = year_match.group(0) if year_match else "0000"
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    iso_mapping = {"ro": "rum", "en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita", "hu": "hun", "pt": "por", "ru": "rus", "tr": "tur", "bg": "bul", "el": "ell", "pl": "pol", "cs": "cze", "nl": "dut"}
    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')
    all_results = []
    if season and episode:
        query_path = f"episode-{episode}/imdbid-{imdb_clean}/season-{season}"
    else:
        query_path = f"imdbid-{imdb_clean}"
    os_results = []
    targets = [l_code]
    if l_code != "en": targets.append("en")
    for target_lang in targets:
        try:
            long_lang = iso_mapping.get(target_lang, "eng")
            os_url = f"https://rest.opensubtitles.org/search/{query_path}/sublanguageid-{long_lang}"
            r = requests.get(os_url, headers={'User-Agent': 'HotSubtitlesV1'}, timeout=15)
            if r.ok:
                for item in r.json():
                    sub_name = item.get('SubFileName', 'subtitle')
                    m_score = sum(1 for tag in ["amzn", "web-dl", "bluray", "x264"] if tag in sub_name.lower() and tag in video_path)
                    os_results.append({
                        'l_name': item.get('LanguageName', 'Unknown'),
                        'filename': normalize_fonts(sub_name),
                        'url': f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{item.get('IDSubtitleFile')}",
                        'vtt_url': f"https://opensubtitles.stremio.homes/sub.vtt/?sub_id={item.get('IDSubtitle')}",
                        'l_code': item.get('ISO639', 'en'),
                        'api_filename': clean_filename(sub_name),
                        'is_chosen': (item.get('ISO639') == l_code),
                        'is_hi': item.get('SubHearingImpaired', '0'),
                        'u_rank': item.get('UserRank', ''),
                        'dl_count': item.get('SubDownloadsCnt', '0'),
                        'match_score': m_score, 'source': 'os'
                    })
        except: pass
    if not os_results:
        xbmc.executebuiltin('Notification("Căutare", "Căutăm global pe OpenSubs...", 2000)')
        try:
            os_url = f"https://rest.opensubtitles.org/search/{query_path}"
            r = requests.get(os_url, headers={'User-Agent': 'HotSubtitlesV1'}, timeout=15)
            if r.ok:
                for item in r.json():
                    sub_name = item.get('SubFileName', 'subtitle')
                    os_results.append({
                        'l_name': item.get('LanguageName', 'Multi'),
                        'filename': normalize_fonts(sub_name),
                        'url': f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{item.get('IDSubtitleFile')}",
                        'vtt_url': f"https://opensubtitles.stremio.homes/sub.vtt/?sub_id={item.get('IDSubtitle')}",                        'l_code': item.get('ISO639', 'en'), 'api_filename': clean_filename(sub_name),
                        'is_chosen': False, 'is_hi': item.get('SubHearingImpaired', '0'),
                        'u_rank': item.get('UserRank', ''), 'dl_count': item.get('SubDownloadsCnt', '0'),
                        'match_score': 0, 'source': 'os'
                    })
        except: pass
    all_results.extend(os_results)
    try:
        import system_core
        u, w, z = system_core.get_auth_pieces()
        if u and w and z:
            user_email = "{}.com".format(u.split('.')[0] + "@" + w.split('.')[0])
            parola = z.split('.')[0]
            def clean_name_robot(text):
                if not text: return "Unknown"
                t = re.sub(r'[^a-zA-Z0-9]', ' ', text)
                return re.sub(r'\s+', '_', t).strip('_')
            t_clean = clean_name_robot(title_raw)
            if show_title or (season and str(season).isdigit()):
                s_str, e_str = str(season).zfill(2), str(episode).zfill(2)
                g_folder = f"Seriale/{t_clean}_S{s_str}E{e_str}_{ep_year}_{imdb_id}"
            else:
                g_folder = f"Filme/{t_clean}_{ep_year}_{imdb_id}"
            k_auth = "Basic " + base64.b64encode(f"{user_email}:{parola}".encode()).decode('ascii')
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
                        safe_email = urllib.parse.quote(user_email)
                        all_results.append({
                            'l_name': 'Romanian' if l_code == 'ro' else f'Cloud ({l_code})',
                            'filename': f_clean,
                            'url': f"davs://{safe_email}:{parola}@app.koofr.net/dav/Koofr/Subtitrari/{safe_g_folder}/{urllib.parse.quote(f_clean)}",
                            'vtt_url': '',
                            'l_code': l_code,
                            'api_filename': f_clean,
                            'is_chosen': True,
                            'is_hi': '0', 'u_rank': 'ROBOT', 'dl_count': '0',
                            'match_score': k_match, 'source': 'koofr'
                        })
    except: pass
    all_results.sort(key=lambda x: (not x['is_chosen'], -x['match_score'], -int(x.get('dl_count', 0) or 0)))
    import urllib.parse
    rank_colors = {'admin': 'red', 'trusted': 'lightgreen', 'translator': 'aqua', 'platinum': 'white', 'gold': 'gold', 'silver': 'silver', 'bronze': 'orange', 'vip': 'pink', 'robot': 'gold'}
    for res in all_results:
        li = xbmcgui.ListItem(label=res['l_name'])
        u_rank_val = res.get('u_rank') or ""
        r_raw = u_rank_val.lower()
        color = 'lightblue'
        for key, val in rank_colors.items():
            if key in r_raw:
                color = val
                break
        prefix = "[COLOR gold]R-[/COLOR] " if res.get('source') == 'koofr' else ""
        rank_str = f" [[COLOR {color}]{u_rank_val}[/COLOR]]" if u_rank_val else ""
        display_name = f"{prefix}{res['filename']}{rank_str} [COLOR yellow]{res.get('dl_count','0')}[/COLOR]"
        li.setLabel2(display_name)
        try:
            is_hi_val = int(res.get('is_hi', 0))
        except:
            is_hi_val = 0
        li.setProperty("sync", "true" if res.get('match_score', 0) > 0 else "false")
        li.setProperty("hearing_imp", "true" if is_hi_val != 0 else "false")
        li.setProperty('language', res['l_name'])
        li.setProperty('filename', res['filename'])
        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        d_params = {
            'action': 'download',
            'url': res['url'],
            'vtt_url': res.get('vtt_url', ''),
            'l_code': res['l_code'],
            'api_filename': res['api_filename'],
            'imdb': imdb_id if 'imdb_id' in locals() else "unknown",
            'title': title_raw if 'title_raw' in locals() else "Unknown",
            'season': season if 'season' in locals() else "",
            'episode': episode if 'episode' in locals() else ""
        }
        url_final = f"{sys.argv[0]}?{urllib.parse.urlencode(d_params)}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url_final, listitem=li)
    xbmcplugin.endOfDirectory(HANDLE)
def download(params):
    import xbmcvfs, os, requests, urllib.request, urllib.parse, base64, threading, sys
    addon_path = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
    lib_path = os.path.join(addon_path, 'resources', 'lib')
    if lib_path not in sys.path: sys.path.append(lib_path)
    try:
        url = urllib.parse.unquote(params.get('url', ''))
        vtt_url = urllib.parse.unquote(params.get('vtt_url', ''))
        l_code = params.get('l_code', 'ro')
        raw_name = params.get('api_filename') or 'subtitle'
        if raw_name.lower().endswith(".srt"): raw_name = raw_name[:-4]
        if not raw_name.endswith(f".{l_code}"):
            api_filename = f"{raw_name}.{l_code}.srt"
        else:
            api_filename = f"{raw_name}.srt"
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        dest_path = os.path.join(dest_dir, api_filename)
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files:
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))
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
            r = requests.get(url, timeout=15)
            if r.ok: content = r.content
        if content:
            with open(dest_path, 'wb') as f: f.write(content)
            li = xbmcgui.ListItem(label=api_filename)
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=li)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            xbmc.Player().setSubtitles(dest_path)
            langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
            user_lang = langs[__addon__.getSettingInt('subs_languages')]
            is_translated = False
            if l_code != user_lang and __addon__.getSettingBool('robot_activat'):
                is_translated = True
                r_idx = __addon__.getSettingInt('robot_selectat')
                target_robot = [robot, robot2, robot3, robot4][r_idx]
                threading.Thread(target=target_robot.run_translation, args=(__id__,)).start()
            try:
                import uploader
                log_info = {
                    "title": params.get('title') or api_filename,
                    "imdb": params.get('imdb', 'NoID'),
                    "s": params.get('season'),
                    "e": params.get('episode'),
                    "was_translated": is_translated,
                    "src": l_code,
                    "dest": user_lang,
                    "api_filename": api_filename
                }
                uploader.send_log(log_info)
            except Exception as log_err:
                xbmc.log(f"LOG_ERROR: {str(log_err)}", xbmc.LOGERROR)
        else:
            raise Exception("No content")
    except Exception as e:
        xbmc.log(f"DL_ERROR: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()