# -*- coding: utf-8 -*-
import sys
import requests
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse
from urllib.parse import unquote
import os
import xbmcvfs
import re

# Configurații
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL_TMDB = "https://api.themoviedb.org/3"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'} 

import xbmcaddon
ADDON = xbmcaddon.Addon()

def log(msg):
    # Verificăm dacă switch-ul din setări este activat
    if ADDON.getSettingBool('debug_logging'):
        # Folosim LOGINFO ca să fie curat
        xbmc.log(f"### [OSv3] {msg}", xbmc.LOGINFO)

def get_series_imdb_id(query):
    try:
        clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', query, flags=re.IGNORECASE).strip()
        log(f"Caut serial TMDB dupa numele curatat: {clean_name}")
        search_url = f"{BASE_URL_TMDB}/search/tv"
        params = {"api_key": API_KEY, "query": clean_name}
        r = requests.get(search_url, params=params, timeout=10).json()
        
        if r.get('results'):
            tmdb_id = r['results'][0]['id']
            ext_url = f"{BASE_URL_TMDB}/tv/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": API_KEY}, timeout=10).json()
            imdb = ext_r.get('imdb_id')
            log(f"Gasit IMDB ID pt serial din TMDB: {imdb}")
            return imdb
    except Exception as e:
        log(f"Eroare TMDB TV: {str(e)}")
    return None

def get_movie_imdb_id(query):
    try:
        clean_name = re.sub(r'[\(\.\s](\d{4})[\)\.\s]?.*', '', query).strip()
        log(f"Caut film TMDB dupa numele curatat: {clean_name}")
        search_url = f"{BASE_URL_TMDB}/search/movie"
        params = {"api_key": API_KEY, "query": clean_name}
        r = requests.get(search_url, params=params, timeout=10).json()
        
        if r.get('results'):
            tmdb_id = r['results'][0]['id']
            ext_url = f"{BASE_URL_TMDB}/movie/{tmdb_id}/external_ids"
            ext_r = requests.get(ext_url, params={"api_key": API_KEY}, timeout=10).json()
            imdb = ext_r.get('imdb_id')
            log(f"Gasit IMDB ID pt film din TMDB: {imdb}")
            return imdb
    except Exception as e:
        log(f"Eroare TMDB Movie: {str(e)}")
    return None

def get_detailed_subtitle_names(imdb_id):
    mapping = {}
    if not imdb_id:
        return mapping
    
    try:
        numeric_id = imdb_id.replace('tt', '')
        rest_url = f"https://rest.opensubtitles.org/search/imdbid-{numeric_id}/sublanguageid-rum"
        log(f"Caut nume reale fisiere REST API: {rest_url}")
        
        response = requests.get(rest_url, headers=HEADERS, timeout=10)
        if response.ok:
            data = response.json()
            if isinstance(data, list):
                for item in data:
                    sub_id = str(item.get('IDSubtitle'))
                    file_name = item.get('SubFileName')
                    if sub_id and file_name:
                        mapping[sub_id] = file_name
                log(f"Am mapat {len(mapping)} nume de fisiere din API REST.")
    except Exception as e:
        log(f"Eroare API REST: {str(e)}")
    
    return mapping

def search():
    log("=== FUNCTIA SEARCH A PORNIT ===")
    try:
        handle = int(sys.argv[1])
    except Exception as e:
        log(f"Eroare extragere handle din sys.argv[1]: {e}")
        return

    junk_ids = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')
    
    # 1. Etichete Standard
    imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
    if not imdb_id or str(imdb_id) in junk_ids:
        imdb_id = xbmc.getInfoLabel("ListItem.Property(imdb_id)")
    log(f"ID din InfoLabels: {imdb_id}")

    # 2. Window Properties
    home_window = xbmcgui.Window(10000)
    if not imdb_id or str(imdb_id) in junk_ids:
        imdb_id = home_window.getProperty("IMDb") or home_window.getProperty("imdb_id")
        log(f"ID din Window Properties: {imdb_id}")

    # 3. Din Link
    try:
        file_path = unquote(xbmc.Player().getPlayingFile())
        if not imdb_id or str(imdb_id) in junk_ids:
            match_imdb = re.search(r'(?:media_id|imdb|imdb_id|title)=([^&]+)', file_path, re.IGNORECASE)
            if match_imdb and match_imdb.group(1).startswith('tt'):
                imdb_id = match_imdb.group(1)
                log(f"ID Extras din Link: {imdb_id}")
    except Exception as e:
        log(f"Eroare la citirea link-ului: {e}")

    # Curățare
    if str(imdb_id) in junk_ids: imdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt') and str(imdb_id).isdigit(): 
        imdb_id = f"tt{imdb_id}"

    season = xbmc.getInfoLabel('VideoPlayer.Season')
    episode = xbmc.getInfoLabel('VideoPlayer.Episode')
    full_title = xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or xbmc.getInfoLabel('VideoPlayer.Title')

    log(f"Detalii extrase -> ID: {imdb_id} | S: {season} | E: {episode} | Titlu: {full_title}")

    is_series = bool(season and episode and season != '0')

    # 4. Fallback TMDB
    if not imdb_id and full_title:
        log("Nu am IMDB ID, initiez Fallback TMDB...")
        if is_series:
            imdb_id = get_series_imdb_id(full_title)
        else:
            imdb_id = get_movie_imdb_id(full_title)

    if not imdb_id:
        log("CRITIC: Nu s-a putut gasi IMDB ID sub nicio forma. Opresc cautarea.")
        xbmcplugin.endOfDirectory(handle)
        return

    # Creare URL Stremio V3
    if is_series:
        media_type = 'series'
        query_id = f"{imdb_id}:{season}:{episode}"
    else:
        media_type = 'movie'
        query_id = imdb_id

    detailed_names = get_detailed_subtitle_names(imdb_id)
    api_url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/{query_id}.json"
    log(f"Fac cerere spre: {api_url}")
    
    try:
        response = requests.get(api_url, headers=HEADERS, timeout=10)
        log(f"Raspuns Stremio API HTTP Code: {response.status_code}")
        
        if response.ok:
            data = response.json()
            subtitles = data.get('subtitles', [])
            log(f"S-au gasit {len(subtitles)} subtitrari totale in JSON.")
            
            filtered = [s for s in subtitles if s.get('lang') in ['ron', 'rum', 'ro']]
            log(f"S-au filtrat {len(filtered)} subtitrari in Limba Romana.")

            for sub in filtered:
                sub_id = str(sub.get('id', ''))
                file_display_name = detailed_names.get(sub_id, f"OpenSubtitles_{sub_id}.srt")
                
                list_item = xbmcgui.ListItem(label="Romanian", label2=file_display_name)
                list_item.setArt({'icon': '5', 'thumb': 'ro'})
                list_item.setProperty("sync", "true")
                list_item.setProperty("hearing_imp", "false")
                list_item.setProperty('LanguageName', 'Romanian')
                
                params = {
                    'action': 'download',
                    'url': sub.get('url'),
                    'filename': file_display_name
                }
                path = f"{sys.argv[0]}?{urllib.parse.urlencode(params)}"
                xbmcplugin.addDirectoryItem(handle=handle, url=path, listitem=list_item, isFolder=False)
    except Exception as e:
        log(f"Eroare la parcurgerea subtitrarilor: {str(e)}")

    log("=== FINALIZARE ADAUGARE IN DIRECTOR ===")
    xbmcplugin.endOfDirectory(handle)

def download(params):
    log("=== FUNCTIA DOWNLOAD A PORNIT ===")
    try:
        handle = int(sys.argv[1])
        url = params.get('url')
        filename = params.get('filename', 'subtitle.srt')
        temp_path = os.path.join(xbmcvfs.translatePath('special://temp/'), filename)
        
        log(f"Descarcare de la: {url}")
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        
        f = xbmcvfs.File(temp_path, 'wb')
        f.write(res.content)
        f.close()
        log(f"Salvat in: {temp_path}")

        list_item = xbmcgui.ListItem(label=temp_path)
        xbmcplugin.addDirectoryItem(handle=handle, url=temp_path, listitem=list_item, isFolder=False)
        xbmc.Player().setSubtitles(temp_path)
        
    except Exception as e:
        log(f"Eroare download: {str(e)}")
    
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

if __name__ == '__main__':
    log(f"=== SCRIPT APELAT CU sys.argv = {sys.argv} ===")
    try:
        param_string = sys.argv[2][1:] if len(sys.argv) > 2 else ""
        params = dict(urllib.parse.parse_qsl(param_string))
        action = params.get('action')

        if action == 'download':
            download(params)
        else:
            search()
    except Exception as e:
        log(f"Eroare FATALA la parsarea argumentelor: {e}")