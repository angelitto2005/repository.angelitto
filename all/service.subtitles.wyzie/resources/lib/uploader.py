# -*- coding: utf-8 -*-
import xbmc, xbmcvfs, base64, urllib.parse, urllib.request

def koofr_get_auth():
    return "Basic " + base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')

def get_folder_grup():
    """Generates path: Seriale/ttXXXX_S-02_E-11 or Filme/ttXXXX"""
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber").replace('tt','')
    imdb_id = f"tt{imdb_id}" if imdb_id else "unknown"
    
    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    
    # Verificăm dacă avem info de serial
    if season and str(season).isdigit() and episode and str(episode).isdigit():
        s_str = str(season).zfill(2)
        e_str = str(episode).zfill(2)
        return f"Seriale/{imdb_id}_S-{s_str}_E-{e_str}"
    else:
        return f"Filme/{imdb_id}"

def upload_now(local_path, filename):
    folder_path = get_folder_grup()
    auth = koofr_get_auth()
    base_dav = "https://app.koofr.net/dav/Koofr/Subtitrari/"

    # 1. Creare foldere recursiv (ex: Seriale -> apoi Episod)
    parts = folder_path.split('/')
    path_acum = ""
    for part in parts:
        path_acum += part + "/"
        url_mkcol = f"{base_dav}{path_acum}"
        req_dir = urllib.request.Request(url_mkcol, method='MKCOL', headers={"Authorization": auth})
        try: 
            with urllib.request.urlopen(req_dir, timeout=5) as r: pass
        except: pass # Folderul există deja

    # 2. Upload fișier (PUT)
    url_put = f"{base_dav}{folder_path}/{urllib.parse.quote(filename)}"
    try:
        f = xbmcvfs.File(local_path); data = f.readBytes(); f.close()
        req = urllib.request.Request(url_put, data=data, method='PUT', headers={
            "Authorization": auth,
            "Content-Type": "application/octet-stream",
            "Overwrite": "T"
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.getcode() in [200, 201, 204]:
                xbmc.executebuiltin('Notification("Cloud", "Subtitrare salvată!", 2000)')
                return True
    except: pass
    return False
