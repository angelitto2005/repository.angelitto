# -*- coding: utf-8 -*-
import xbmc, xbmcvfs, base64, urllib.parse, urllib.request, re
import requests, hashlib, uuid, datetime, threading, xbmcaddon

def clean_name(text):
    if not text: return "Unknown"
    t = re.sub(r'[^a-zA-Z0-9]', ' ', text)
    t = re.sub(r'\s+', '_', t).strip('_')
    return t

def koofr_get_auth():
    return "Basic " + base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')

def get_folder_grup():
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber").replace('tt','')
    imdb_id = f"tt{imdb_id}" if imdb_id else "unknown"
    
    show_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle")
    if not show_title: show_title = xbmc.getInfoLabel("VideoPlayer.OriginalTitle")
    if not show_title: show_title = xbmc.getInfoLabel("VideoPlayer.Title")
        
    raw_year = xbmc.getInfoLabel("VideoPlayer.Year")
    year_match = re.search(r'\d{4}', raw_year)
    ep_year = year_match.group(0) if year_match else "0000"

    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    
    if season or xbmc.getCondVisibility("VideoPlayer.Content(tvshows)"):
        title = clean_name(show_title)
        s_str = str(season).zfill(2) if (season and str(season).isdigit()) else "01"
        e_str = str(episode).zfill(2) if (episode and str(episode).isdigit()) else "01"
        return f"Seriale/{title}_S{s_str}E{e_str}_{ep_year}_{imdb_id}"
    else:
        title = clean_name(xbmc.getInfoLabel("VideoPlayer.Title"))
        return f"Filme/{title}_{ep_year}_{imdb_id}"

def send_log(info):
    """ Trimite statistici în folderul /stats/ de pe Koofr """
    def run_log():
        try:
            addon = xbmcaddon.Addon()
            friendly_name = (xbmc.getInfoLabel('System.FriendlyName').strip() or "Kodi_User").replace(' ', '_').replace('(', '').replace(')', '')
            
            try: unique_id = hashlib.md5(str(uuid.getnode()).encode()).hexdigest()[:6]
            except: unique_id = hashlib.md5(xbmc.translatePath('special://home').encode()).hexdigest()[:6]

            base_filename = "user_%s_%s" % (friendly_name, unique_id)
            auth = koofr_get_auth()
            headers = {"Authorization": auth}

            current_index = 0
            while True:
                suffix = "" if current_index == 0 else "-%s" % current_index
                filename = "%s%s.log" % (base_filename, suffix)
                file_url = "https://app.koofr.net/dav/Koofr/Subtitrari/stats/%s" % filename
                
                content = ""
                try:
                    r_get = requests.get(file_url, headers=headers, timeout=10, verify=False)
                    if r_get.status_code == 200:
                        content = r_get.text
                        if content.count('\n') >= 300:
                            current_index += 1; continue 
                except: pass
                break 

            # Info Robot
            robot_names = ["Robot1 (Google)", "Robot2 (Lingva)", "Robot3 (Gemini)", "Robot4 (DeepL)"]
            try:
                r_idx = addon.getSettingInt('robot_selectat')
                current_robot = robot_names[r_idx] if r_idx < len(robot_names) else "Robot"
            except: current_robot = "Robot"
            
            robot_log = "Robot: DA [%s] (%s -> %s)" % (current_robot, info.get('src'), info.get('dest')) if info.get('was_translated') else "Robot: NU (Originala)"
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
            
            # Geo IP
            loc = "IP/Tara: Unknown"
            try:
                r_geo = requests.get("https://ipwho.is", timeout=8, verify=False)
                if r_geo.status_code == 200 and r_geo.json().get('success'):
                    loc = "IP: %s | Tara: %s" % (r_geo.json().get('ip'), r_geo.json().get('country'))
            except: pass

            kodi_ver = xbmc.getInfoLabel('System.BuildVersion').split(' ')[0]
            platform = "Unknown"
            for p in ["Windows", "Android", "Linux", "IOS"]:
                if xbmc.getCondVisibility('System.Platform.%s' % p): platform = p; break

            line = "[%s] IMDB: %s || %s | %s\n" % (now, info.get('imdb', 'NoID'), info.get('title', 'NoTitle'), robot_log)
            line += "File: %s" % info.get('api_filename', 'NoFile')
            if info.get('s') and info.get('e'): line += " (S%sE%s)" % (info.get('s'), info.get('e'))
            line += "\n%s | [%s - %s]\n%s\n" % (loc, kodi_ver, platform, "-"*50)

            requests.put(file_url, data=(content + line).encode('utf-8'), headers=headers, timeout=10, verify=False)
        except: pass

    threading.Thread(target=run_log).start()

def upload_now(local_path, filename):
    folder_path = get_folder_grup()
    auth = koofr_get_auth()
    base_dav = "https://app.koofr.net/dav/Koofr/Subtitrari/"

    parts = folder_path.split('/')
    path_acum = ""
    for part in parts:
        path_acum += urllib.parse.quote(part) + "/" 
        url_mkcol = f"{base_dav}{path_acum}"
        req_dir = urllib.request.Request(url_mkcol, method='MKCOL', headers={"Authorization": auth})
        try: urllib.request.urlopen(req_dir, timeout=5)
        except: pass 

    url_put = f"{base_dav}{folder_path}/{urllib.parse.quote(filename)}"
    try:
        f = xbmcvfs.File(local_path); data = f.readBytes(); f.close()
        req = urllib.request.Request(url_put, data=data, method='PUT', headers={
            "Authorization": auth, "Content-Type": "application/octet-stream", "Overwrite": "T"
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.getcode() in [200, 201, 204]:
                xbmc.executebuiltin('Notification("Cloud", "Salvat: {}", 3000)'.format(folder_path.split('/')[-1]))
                return True
    except: pass
    return False
