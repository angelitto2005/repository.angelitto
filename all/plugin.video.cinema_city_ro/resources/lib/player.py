import requests
import re
import urllib.parse
from urllib.parse import urlparse
import xbmcgui
import xbmcplugin
import json

BASE_URL = "https://api.themoviedb.org/3"
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}

def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        return r.json()
    except: return {}

def get_ids(content_type, tmdb_id):
    url = f"{BASE_URL}/{content_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    return get_json(url)

def format_size(size_bytes):
    if not size_bytes: return ""
    try:
        size_bytes = int(size_bytes)
        if size_bytes <= 0: return ""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
    except: return ""

def get_all_sources(imdb_id, content_type, season=None, episode=None):
    providers = [
        {"name": "Vflix", "url": "https://vidzee.vflix.life"},    
        {"name": "Nuviostream", "url": "https://nuviostreams.hayd.uk/stream"},
        {"name": "WebStream", "url": "https://webstreamr.hayd.uk/stream"},   
    ]
    
    temp_sources = []
    
    for srv in providers:
        try:
            if content_type == 'movie':
                api_url = f"{srv['url']}/movie/{imdb_id}.json"
            else:
                api_url = f"{srv['url']}/series/{imdb_id}:{season}:{episode}.json"
            
            r = requests.get(api_url, headers=HEADERS, timeout=15)
            data = r.json() 
            streams = data.get('streams', [])
            
            for stream in streams:
                url_raw = stream.get('url')
                # Filtrare: daca nu exista URL sau nu incepe cu http, sari peste
                if not url_raw or not str(url_raw).startswith('http'): continue
                
                stream_title = stream.get('title', '')
                stream_name = stream.get('name', '')
                full_info = (stream_title + " " + stream_name).upper()
                
                # Detectie Rezolutie
                quality_match = re.search(r'(\d{3,4})P', full_info)
                res_num = int(quality_match.group(1)) if quality_match else 0
                
                if res_num >= 2160: display_quality = "4K"
                elif res_num >= 720: display_quality = "HD"
                elif res_num > 0: display_quality = "SD"
                else: display_quality = "HD"

                # Detectie Formate Dinamice (HDR, DV, etc.)
                hdr_info = ""
                is_hdr_bool = False
                if 'DOLBY VISION' in full_info or ' DV ' in full_info or '.DV.' in full_info:
                    hdr_info = "DV"
                    is_hdr_bool = True
                elif 'HDR10' in full_info:
                    hdr_info = "HDR10"
                    is_hdr_bool = True
                elif 'HDR' in full_info:
                    hdr_info = "HDR"
                    is_hdr_bool = True
                
                # Marime Fisier
                file_size = ""
                size_bytes = stream.get('behaviorHints', {}).get('fileSize')
                if size_bytes:
                    file_size = format_size(size_bytes)
                else:
                    size_match = re.search(r'(\d+(?:\.\d+)?\s*(?:GB|MB))', full_info)
                    if size_match: file_size = size_match.group(1)

                clean_url = url_raw.replace('\\/', '/')
                domain = urlparse(clean_url).netloc.replace('www.', '')
                final_link = clean_url + "|User-Agent=" + urllib.parse.quote(HEADERS['User-Agent'])
                
                temp_sources.append({
                    'srv_name': srv['name'],
                    'quality': display_quality,
                    'hdr_type': hdr_info,
                    'is_hdr': is_hdr_bool,
                    'size': file_size,
                    'domain': domain,
                    'path': final_link,
                    'quality_val': res_num
                })
        except: continue
            
    # Sortare 1: Dupa Rezolutie (Descrescator)
    temp_sources.sort(key=lambda x: x['quality_val'], reverse=True)
    # Sortare 2: Prioritizare VIX (ramane prima daca exista in nume/domeniu)
    temp_sources.sort(key=lambda x: 0 if 'vix' in x['domain'].lower() or 'vix' in x['srv_name'].lower() else 1)

    found_sources = []
    for i, s in enumerate(temp_sources):
        # Culoare Rezolutie
        color = "yellow" if s['quality'] == "4K" else "green" if s['quality'] == "HD" else "red"
        colored_quality = f"[COLOR {color}][{s['quality']}][/COLOR]"
            
        # Eticheta HDR colorata cu Albastru (doar daca exista)
        hdr_label = f" [COLOR blue][{s['hdr_type']}][/COLOR]" if s['hdr_type'] else ""
        
        # Eticheta Marime
        size_label = f" [COLOR tan][{s['size']}][/COLOR]" if s['size'] else ""
        
        label = f"{colored_quality}{hdr_label}{size_label} {s['srv_name']} - Sursa {i + 1} ({s['domain']})"
        
        found_sources.append({
            'label': label,
            'path': s['path'],
            'quality_val': s['quality_val'],
            'is_hdr': s['is_hdr']
        })
    
    return found_sources

def play_item(params, handle):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title', 'Video')
    
    progress = xbmcgui.DialogProgress()
    progress.create("Căutare surse", "Scanăm serverele...")
    
    ids = get_ids(c_type, tmdb_id)
    imdb_id = ids.get('imdb_id')
    
    if not imdb_id:
        progress.close()
        return

    sources = get_all_sources(imdb_id, c_type, params.get('season'), params.get('episode'))
    progress.close()
    
    if not sources:
        xbmcgui.Dialog().ok("Eroare", "Nu am găsit link-uri.")
        return

    labels = [s['label'] for s in sources]
    selection = xbmcgui.Dialog().select("Servere Disponibile", labels)
    
    if selection != -1:
        selected_source = sources[selection]
        play_li = xbmcgui.ListItem(title, path=selected_source['path'])
        
        video_stream_data = {'codec': 'h264'}
        res_val = selected_source['quality_val']
        
        if res_val >= 2160: video_stream_data.update({'width': 3840, 'height': 2160})
        elif res_val >= 1080: video_stream_data.update({'width': 1920, 'height': 1080})
        else: video_stream_data.update({'width': 1280, 'height': 720})

        if selected_source['is_hdr']:
            video_stream_data.update({'hdrtype': 'hdr10'})

        play_li.setInfo('video', {'title': title, 'mediatype': 'movie' if c_type == 'movie' else 'episode'})
        play_li.addStreamInfo('video', video_stream_data)
        xbmcplugin.setResolvedUrl(handle, True, listitem=play_li)
