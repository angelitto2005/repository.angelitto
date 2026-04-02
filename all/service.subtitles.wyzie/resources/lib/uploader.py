# -*- coding: utf-8 -*-
import xbmc, xbmcvfs, base64, urllib.parse, urllib.request

def koofr_get_auth():
    # Your fixed authentication data
    return "Basic " + base64.b64encode(b"blagoie@gmail.com:kh445t87ds404h70").decode('ascii')

def get_folder_grup():
    """Generates the IMDB folder name (ttXXXX_S1E1 or ttXXXX)"""
    imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber").replace('tt','')
    imdb_id = f"tt{imdb_id}" if imdb_id else "unknown"
    season = xbmc.getInfoLabel("VideoPlayer.Season")
    episode = xbmc.getInfoLabel("VideoPlayer.Episode")
    return f"{imdb_id}_S{season}E{episode}" if (season and episode) else imdb_id

def upload_now(local_path, filename):
    folder_name = get_folder_grup()
    auth = koofr_get_auth()
    
    # 1. Folder creation (MKCOL)
    url_dir = f"https://app.koofr.net/dav/Koofr/Subtitrari/{folder_name}/"
    req_dir = urllib.request.Request(url_dir, method='MKCOL', headers={"Authorization": auth})
    try: urllib.request.urlopen(req_dir, timeout=5)
    except: pass # The folder probably already exists

    # 2. Upload (PUT)
    url_put = f"https://app.koofr.net/dav/Koofr/Subtitrari/{folder_name}/{urllib.parse.quote(filename)}"
    try:
        f = xbmcvfs.File(local_path); data = f.readBytes(); f.close()
        req = urllib.request.Request(url_put, data=data, method='PUT', headers={
            "Authorization": auth,
            "Content-Type": "application/octet-stream",
            "Overwrite": "T"
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.getcode() in [200, 201, 204]:
                xbmc.executebuiltin('Notification("Cloud", "Subtitle uploaded successfully!", 3000)')
                return True
    except: pass
    return False
