# -*- coding: utf-8 -*-
import os, sys, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading, re, unicodedata
from urllib.parse import unquote, urlencode, parse_qsl
import base64

__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
lib_path = xbmcvfs.translatePath(os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
sys.path.append(lib_path)

# --- IMPORTURI ROBOȚI ---
try: import robot
except: xbmc.log("ROBOT1 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot2
except: xbmc.log("ROBOT2 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot3
except: xbmc.log("ROBOT3 LIB NOT FOUND", xbmc.LOGERROR)
try: import robot4 # <--- ADAUGĂ ACEASTĂ LINIE
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
    # Eliminăm extensiile dacă există deja în nume
    if text.lower().endswith('.srt'): text = text[:-4]
    if text.lower().endswith('.vtt'): text = text[:-4]
    # Păstrăm doar caractere sigure pentru download
    text = re.sub(r'[^a-zA-Z0-9\s\.\-\(\)\[\]]', '', text)
    return text.strip()

def search():
    import base64, re, urllib.request, urllib.parse
    
    # Detectăm numele fișierului video curent pentru comparare
    video_path = xbmc.Player().getPlayingFile().lower()
    
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    
    if not imdb_id: 
        xbmc.log("OPENSUBS: No IMDB ID found", xbmc.LOGERROR)
        return

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    iso_mapping = {"ro": "rum", "en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita", "hu": "hun", "pt": "por", "ru": "rus", "tr": "tur", "bg": "bul", "el": "ell", "pl": "pol", "cs": "cze", "nl": "dut"}
    
    idx = __addon__.getSettingInt('subs_languages')
    l_code = langs[idx]
    robot_activat = __addon__.getSettingBool('robot_activat')

    all_results = []
    clean_imdb = imdb_id.replace('tt','')

    if season and episode:
        query_path = f"episode-{episode}/imdbid-{clean_imdb}/season-{season}"
    else:
        query_path = f"imdbid-{clean_imdb}"

    targets = [l_code]
    if l_code != "en" and robot_activat:
        targets.append("en")

    # --- 1. CĂUTARE OPENSUBTITLES ---
    for target_lang in targets:
        try:
            long_lang = iso_mapping.get(target_lang, "eng")
            os_url = f"https://rest.opensubtitles.org/search/{query_path}/sublanguageid-{long_lang}"
            
            r = requests.get(os_url, headers={'User-Agent': 'HotSubtitlesV1'}, timeout=20)
            if r.ok:
                for item in r.json():
                    t_code = item.get('ISO639', 'en')
                    sub_name_raw = item.get('SubFileName', 'subtitle')
                    match_score = sum(1 for tag in ["amzn", "amazon", "web-dl", "webrip", "bluray", "brrip", "dvdrip", "x264", "x265", "h264"] if tag in sub_name_raw.lower() and tag in video_path)

                    all_results.append({
                        'l_name': item.get('LanguageName', 'Unknown'),
                        'filename': normalize_fonts(sub_name_raw),
                        'url': f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{item.get('IDSubtitleFile')}",
                        'vtt_url': f"https://opensubtitles.stremio.homes/sub.vtt/?sub_id={item.get('IDSubtitle')}",
                        'l_code': t_code, 
                        'api_filename': clean_filename(sub_name_raw), 
                        'is_chosen': (t_code == l_code),
                        'is_hi': item.get('SubHearingImpaired', '0'),
                        'u_rank': item.get('UserRank', ''),
                        'dl_count': item.get('SubDownloadsCnt', '0'),
                        'match_score': match_score,
                        'source': 'os'
                    })
        except Exception as e:
            xbmc.log(f"OPENSUBS ERROR: {str(e)}", xbmc.LOGERROR)

    # --- 2. CĂUTARE KOOFR (LOGICĂ DIN TESTUL REUȘIT) ---
    try:
        g_folder = f"tt{clean_imdb}"
        if season and episode: g_folder += f"_S{season}E{episode}"
        
        k_auth = "Basic " + base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')
        k_url = f"https://app.koofr.net/dav/Koofr/Subtitrari/{g_folder}/"
        
        req = urllib.request.Request(k_url, method='PROPFIND', headers={"Authorization": k_auth, "Depth": "1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode('utf-8')
            files = re.findall(r'<[a-zA-Z0-9:]*displayname>([^<]+)</[a-zA-Z0-9:]*displayname>', xml_data)
            
            for f in files:
                f_clean = f.strip('/')
                if f_clean.lower().endswith(('.srt', '.sub')) and f_clean != g_folder:
                    k_match = sum(1 for tag in ["amzn", "amazon", "web-dl", "webrip", "bluray", "brrip", "x264", "x265"] if tag in f_clean.lower() and tag in video_path)
                    
                    all_results.append({
                        'l_name': 'Romanian',
                        'filename': f_clean,
                        'url': f"davs://blagoie%40gmail.com:kh445t87ds404h70@app.koofr.net/dav/Koofr/Subtitrari/{g_folder}/{urllib.parse.quote(f_clean)}",
                        'vtt_url': '',
                        'l_code': 'ro', 
                        'api_filename': f_clean, 
                        'is_chosen': (l_code == 'ro'),
                        'is_hi': '0',
                        'u_rank': 'robot',
                        'dl_count': '0',
                        'match_score': k_match,
                        'source': 'koofr'
                    })
    except: pass

    # --- 3. SORTARE ȘI AFIȘARE ---
    all_results.sort(key=lambda x: (not x['is_chosen'], -x['match_score'], -int(x.get('dl_count', 0) or 0)))

    rank_colors = {'admin': 'red', 'trusted': 'lightgreen', 'translator': 'aqua', 'platinum': 'white', 'gold': 'gold', 'silver': 'silver', 'bronze': 'orange', 'vip': 'pink', 'koofr': 'gold'}

    for res in all_results:
        li = xbmcgui.ListItem(label=res['l_name'])
        u_rank_val = res.get('u_rank') or ""
        color = rank_colors.get(u_rank_val.lower(), 'lightblue')

        prefix = "[COLOR gold]-[/COLOR] " if res.get('source') == 'koofr' else ""
        rank_str = f" [[COLOR {color}]{u_rank_val}[/COLOR]]" if u_rank_val else ""
        li.setLabel2(f"{prefix}{res['filename']}{rank_str} [COLOR yellow]{res.get('dl_count','0')}[/COLOR]")
        
        li.setProperty("sync", "true" if res['match_score'] > 0 else "false")
        li.setProperty("hearing_imp", ("false", "true")[int(res.get('is_hi', 0)) != 0])
        li.setProperty('language', res['l_name'])
        li.setProperty('filename', res['filename'])
        li.setArt({'thumb': res['l_code'], 'icon': res['l_code']})
        
        d_params = {'action': 'download', 'url': res['url'], 'vtt_url': res.get('vtt_url',''), 'l_code': res['l_code'], 'api_filename': res['api_filename']}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=f"{sys.argv[0]}?{urllib.parse.urlencode(d_params)}", listitem=li)

    xbmcplugin.endOfDirectory(HANDLE)

def download(params):
    import xbmcvfs, os, requests, urllib.request, urllib.parse, base64, threading
    try:
        url = urllib.parse.unquote(params.get('url', ''))
        vtt_url = urllib.parse.unquote(params.get('vtt_url', ''))
        l_code = params.get('l_code', 'ro')
        
        # REPARARE NUME: Ne asigurăm că avem extensia .limba.srt (ex: .ro.srt)
        raw_name = params.get('api_filename') or 'subtitle'
        if raw_name.lower().endswith(".srt"): raw_name = raw_name[:-4]
        if not raw_name.endswith(f".{l_code}"):
            api_filename = f"{raw_name}.{l_code}.srt"
        else:
            api_filename = f"{raw_name}.srt"
        
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        dest_path = os.path.join(dest_dir, api_filename)

        # Curățare fișiere vechi
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files: 
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        content = None
        # --- DOWNLOAD KOOFR ---
        if "app.koofr.net" in url:
            try:
                clean_url = "https://" + url.split("@")[-1] if "@" in url else url.replace("davs://", "https://")
                base_u, file_u = clean_url.rsplit('/', 1)
                final_url = base_u + "/" + urllib.parse.quote(file_u)
                auth = base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')
                req = urllib.request.Request(final_url, headers={"Authorization": "Basic " + auth})
                with urllib.request.urlopen(req, timeout=15) as r: content = r.read()
            except: pass

        # --- DOWNLOAD OPENSUBTITLES ---
        if not content:
            r = requests.get(url, timeout=15)
            if r.ok: content = r.content

        if content:
            with open(dest_path, 'wb') as f: f.write(content)
            
            # ÎNCHIERE FEREASTRĂ
            li = xbmcgui.ListItem(label=api_filename)
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=li)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            
            xbmc.Player().setSubtitles(dest_path)
            
            # ACTIVARE ROBOT
            langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
            user_lang = langs[__addon__.getSettingInt('subs_languages')]
            if l_code != user_lang and __addon__.getSettingBool('robot_activat'):
                r_idx = __addon__.getSettingInt('robot_selectat')
                target_robot = [robot, robot2, robot3, robot4][r_idx]
                threading.Thread(target=target_robot.run_translation, args=(__id__,)).start()
        else:
            raise Exception("No content")
               
    except Exception as e:
        xbmc.log(f"DL_ERROR: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


if __name__ == '__main__':
    # Parse arguments for the download action
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download': 
        download(p)
    else: 
        search()
