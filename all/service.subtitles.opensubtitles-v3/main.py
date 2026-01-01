import sys
import requests
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse
import os
import xbmcvfs
import re

API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL_TMDB = "https://api.themoviedb.org/3"

def log(msg):
    xbmc.log(f"### [OpenSubV3_Fix] {msg}", xbmc.LOGINFO)

def get_series_imdb_id(query):
    """
    Folosește TMDB pentru a găsi ID-ul IMDB al serialului.
    Curăță automat 'S01E01' din titlu.
    """
    try:
        clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', query, flags=re.IGNORECASE).strip()
        
        search_url = f"{BASE_URL_TMDB}/search/tv"
        params = {"api_key": API_KEY, "query": clean_name}
        r = requests.get(search_url, params=params, timeout=10).json()
        
        if r.get('results'):
            tmdb_id = r['results'][0]['id']
            ext_url = f"{BASE_URL_TMDB}/tv/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": API_KEY}, timeout=10).json()
            return ext_r.get('imdb_id')
    except Exception as e:
        log(f"Eroare TMDB: {str(e)}")
    return None

def search():
    try:
        handle = int(sys.argv[1])
    except:
        return

    imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
    season = xbmc.getInfoLabel('VideoPlayer.Season')
    episode = xbmc.getInfoLabel('VideoPlayer.Episode')
    full_title = xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or xbmc.getInfoLabel('VideoPlayer.Title')

    if not imdb_id and not full_title:
        log("Eroare: Nu s-au găsit date pentru căutare.")
        xbmcplugin.endOfDirectory(handle)
        return

    if season and episode and season != '0':
        media_type = 'series'
        tmdb_series_imdb = get_series_imdb_id(full_title)
        
        if tmdb_series_imdb:
            imdb_id = tmdb_series_imdb
            log(f"ID Serial corectat via TMDB: {imdb_id}")
        
        query_id = f"{imdb_id}:{season}:{episode}"
    else:
        media_type = 'movie'
        query_id = imdb_id

    api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
    log(f"Căutare la: {api_url}")

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.ok:
            data = response.json()
            subtitles = data.get('subtitles', [])
            
            filtered = [s for s in subtitles if s.get('lang') in ['ron', 'rum']]
            
            if not filtered:
                log(f"Niciun rezultat pentru {query_id}")

            for sub in filtered:
                label = f"RO | {sub.get('id', 'OpenSubtitles')}"
                list_item = xbmcgui.ListItem(label=label)
                list_item.setArt({'icon': 'DefaultSubtitle.png'})
                
                params = {
                    'action': 'download',
                    'url': sub.get('url'),
                    'filename': f"{sub.get('id')}.srt"
                }
                path = f"{sys.argv[0]}?{urllib.parse.urlencode(params)}"
                xbmcplugin.addDirectoryItem(handle=handle, url=path, listitem=list_item, isFolder=False)
    except Exception as e:
        log(f"Eroare API: {str(e)}")

    xbmcplugin.endOfDirectory(handle)

def download(params):
    try:
        handle = int(sys.argv[1])
        url = params.get('url')
        temp_path = os.path.join(xbmcvfs.translatePath('special://temp/'), "downloaded_sub.srt")
        
        log(f"Descarcare: {url}")
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        
        with xbmcvfs.File(temp_path, 'wb') as f:
            f.write(res.content)

        list_item = xbmcgui.ListItem(label="downloaded_sub.srt")
        xbmcplugin.addDirectoryItem(handle=handle, url=temp_path, listitem=list_item, isFolder=False)
        
    except Exception as e:
        log(f"Eroare la download: {str(e)}")
    
    xbmcplugin.endOfDirectory(handle)

if __name__ == '__main__':
    params = dict(urllib.parse.parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    action = params.get('action')

    if action == 'download':
        download(params)
    else:
        search()
