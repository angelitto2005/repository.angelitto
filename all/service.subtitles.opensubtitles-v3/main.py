import sys
import requests
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse
import os
import xbmcvfs
import re

# Configurații
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL_TMDB = "https://api.themoviedb.org/3"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'} 

def log(msg):
    xbmc.log(f"### [OpenSubV3_Fix] {msg}", xbmc.LOGINFO)

def get_series_imdb_id(query):
    """Găsește ID-ul IMDB al serialului folosind TMDB."""
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

def get_detailed_subtitle_names(imdb_id):
    """Interoghează API-ul REST OpenSubtitles pentru a obține SubFileName."""
    mapping = {}
    if not imdb_id:
        return mapping
    
    try:
        numeric_id = imdb_id.replace('tt', '')
        rest_url = f"https://rest.opensubtitles.org/search/imdbid-{numeric_id}/sublanguageid-rum"
        
        response = requests.get(rest_url, headers=HEADERS, timeout=10)
        if response.ok:
            data = response.json()
            for item in data:
                sub_id = str(item.get('IDSubtitle'))
                file_name = item.get('SubFileName')
                if sub_id and file_name:
                    mapping[sub_id] = file_name
    except Exception as e:
        log(f"Eroare API REST: {str(e)}")
    
    return mapping

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
        xbmcplugin.endOfDirectory(handle)
        return

    if season and episode and season != '0':
        media_type = 'series'
        tmdb_series_imdb = get_series_imdb_id(full_title)
        if tmdb_series_imdb:
            imdb_id = tmdb_series_imdb
        query_id = f"{imdb_id}:{season}:{episode}"
    else:
        media_type = 'movie'
        query_id = imdb_id

    detailed_names = get_detailed_subtitle_names(imdb_id)
    api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
    
    try:
        response = requests.get(api_url, headers=HEADERS, timeout=10)
        if response.ok:
            data = response.json()
            subtitles = data.get('subtitles', [])
            filtered = [s for s in subtitles if s.get('lang') in ['ron', 'rum']]

            for sub in filtered:
                sub_id = str(sub.get('id'))
                file_display_name = detailed_names.get(sub_id, f"{sub_id}.srt")
                
                # APLICARE MODIFICĂRI AFIȘARE (METODA DIN EXEMPLU)
                # Label 1: Limba, Label 2: Nume fișier
                list_item = xbmcgui.ListItem(label="Romanian", label2=file_display_name)
                
                # Setează iconița (rating fictiv) și thumb (steagul limbii)
                list_item.setArt({
                    'icon': '5', 
                    'thumb': 'Romanian'
                })
                
                # Proprietăți pentru Sync și Hearing Impaired
                list_item.setProperty("sync", "true")
                list_item.setProperty("hearing_imp", "false")
                
                # Păstrare LanguageName pentru compatibilitate motor Kodi
                list_item.setProperty('LanguageName', 'Romanian')
                
                params = {
                    'action': 'download',
                    'url': sub.get('url'),
                    'filename': file_display_name
                }
                path = f"{sys.argv[0]}?{urllib.parse.urlencode(params)}"
                xbmcplugin.addDirectoryItem(handle=handle, url=path, listitem=list_item, isFolder=False)
    except Exception as e:
        log(f"Eroare search: {str(e)}")

    xbmcplugin.endOfDirectory(handle)

def download(params):
    try:
        handle = int(sys.argv[1])
        url = params.get('url')
        filename = params.get('filename', 'subtitle.srt')
        temp_path = os.path.join(xbmcvfs.translatePath('special://temp/'), filename)
        
        log(f"Descarcare: {url}")
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        
        f = xbmcvfs.File(temp_path, 'wb')
        f.write(res.content)
        f.close()

        list_item = xbmcgui.ListItem(label=temp_path)
        xbmcplugin.addDirectoryItem(handle=handle, url=temp_path, listitem=list_item, isFolder=False)
        xbmc.Player().setSubtitles(temp_path)
        
    except Exception as e:
        log(f"Eroare download: {str(e)}")
    
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

if __name__ == '__main__':
    # Parsare parametri conform structurii Kodi
    param_string = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    params = dict(urllib.parse.parse_qsl(param_string))
    action = params.get('action')

    if action == 'download':
        download(params)
    else:
        search()
