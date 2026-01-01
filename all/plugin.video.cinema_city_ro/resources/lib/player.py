import requests
import re
import urllib.parse
import time
import json
import xbmcgui
import xbmcplugin
import xbmc
from urllib.parse import urlparse
import api_config

BASE_URL = api_config.BASE_URL
API_KEY = api_config.API_KEY
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}

import requests
import xbmcgui
import xbmcplugin
import urllib.parse
import re
import time
from urllib.parse import urlparse

def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        return r.json()
    except: return {}

def get_imdb_id(tmdb_id, content_type):
    c_type = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{c_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    data = get_json(url)
    return data.get('imdb_id')

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
    return ""

def get_all_sources(imdb_id, content_type, season=None, episode=None):
    providers = [
        {"name": "Vflix", "url": "https://vidzee.vflix.life"},    
        {"name": "Nuviostream", "url": "https://nuviostreams.hayd.uk/stream"},
        {"name": "WebStream", "url": "https://webstreamr.hayd.uk/stream"},
    ]
    
    temp_sources = []
    progress = xbmcgui.DialogProgress()
    progress.create("Căutare surse...", "Inițializare...")
    
    total_srv = len(providers)
    start_search_time = time.time()
    
    for i, srv in enumerate(providers):
        for _ in range(5): 
            elapsed = time.time() - start_search_time
            remaining_time = max(0, int(60 - elapsed))
            percent = int((i / total_srv) * 100)
            message = f"Scanăm: [COLOR deepskyblue]{srv['name']}[/COLOR]...\nTimp rămas: [COLOR yellow]{remaining_time} sec[/COLOR]"
            progress.update(percent, message)
            if progress.iscanceled(): break
            time.sleep(0.05)

        if progress.iscanceled(): break
            
        try:
            if content_type == 'movie':
                api_url = f"{srv['url']}/movie/{imdb_id}.json"
            else:
                api_url = f"{srv['url']}/series/{imdb_id}:{season}:{episode}.json"
            
            r = requests.get(api_url, headers=HEADERS, timeout=30) 
            data = r.json() 
            streams = data.get('streams', [])
            
            for stream in streams:
                url_raw = stream.get('url')
                if not url_raw or not str(url_raw).startswith('http'): continue
                
                stream_title = stream.get('title', '')
                stream_name = stream.get('name', '')
                raw_filename = stream_title.replace('\n', ' ')
                
                full_info = (stream_title + " " + stream_name).replace('\n', ' ').upper()
                
                quality_match = re.search(r'(\d{3,4})P', full_info)
                res_num = int(quality_match.group(1)) if quality_match else 0
                
                if res_num >= 2160: display_quality = "4K"
                elif res_num >= 720: display_quality = "HD"
                elif res_num > 0: display_quality = "SD"
                else: display_quality = "HD"

                codec_info = ""
                if 'HEVC' in full_info or 'H265' in full_info: codec_info = "HEVC"
                elif 'H264' in full_info or 'AVC' in full_info: codec_info = "AVC"

                audio_info = ""
                if 'ATMOS' in full_info: audio_info = "ATMOS"
                elif '7.1' in full_info: audio_info = "7.1"
                elif '5.1' in full_info or 'DDP5' in full_info: audio_info = "5.1"
                elif 'STEREO' in full_info: audio_info = "2.0"

                hdr_info = ""
                is_hdr_bool = False
                if any(x in full_info for x in ['DOLBY VISION', ' DV ', '.DV.']):
                    hdr_info = "DV"
                    is_hdr_bool = True
                elif 'HDR10' in full_info:
                    hdr_info = "HDR10"
                    is_hdr_bool = True
                elif 'HDR' in full_info:
                    hdr_info = "HDR"
                    is_hdr_bool = True

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
                    'codec': codec_info,
                    'audio': audio_info,
                    'domain': domain,
                    'path': final_link,
                    'quality_val': res_num,
                    'raw_filename': raw_filename
                })
        except: continue
    
    progress.close()
    if not temp_sources: return []

    temp_sources.sort(key=lambda x: x['quality_val'], reverse=True)
    temp_sources.sort(key=lambda x: 0 if 'vix' in x['domain'].lower() or 'vix' in x['srv_name'].lower() else 1)

    found_sources = []
    for i, s in enumerate(temp_sources):
        color = "yellow" if s['quality'] == "4K" else "green" if s['quality'] == "HD" else "red"
        
        label = f"[COLOR {color}][{s['quality']}][/COLOR]"
        if s['hdr_type']: label += f" [COLOR blue][{s['hdr_type']}][/COLOR]"
        if s['codec']:    label += f" [COLOR deeppink][{s['codec']}][/COLOR]"
        if s['audio']:    label += f" [COLOR orange][{s['audio']}][/COLOR]"
        if s['size']:     label += f" [COLOR tan][{s['size']}][/COLOR]"
        label += f" [COLOR saddlebrown]| {s['srv_name']} - Sursa {i + 1} ({s['domain']})[/COLOR]"
        
        if s['raw_filename']: 
            clean_name = s['raw_filename'][:95] + "..." if len(s['raw_filename']) > 95 else s['raw_filename']
            label += f"\n[COLOR white]{clean_name}[/COLOR]"
        
        found_sources.append({
            'label': label,
            'path': s['path'],
            'quality_val': s['quality_val'],
            'is_hdr': s['is_hdr'],
            'raw_filename': s['raw_filename']
        })
    return found_sources

def play_video(handle, params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    title = params.get('title', 'Video')
    year = params.get('year', '')
    season = params.get('season')
    episode = params.get('episode')
    
    imdb_id = get_imdb_id(tmdb_id, c_type)
    if not imdb_id:
        xbmcgui.Dialog().ok("Eroare", "Nu s-a putut găsi ID-ul IMDB.")
        return

    sources = get_all_sources(imdb_id, c_type, season, episode)
    if not sources:
        xbmcgui.Dialog().ok("Info", "Nu au fost găsite surse video.")
        return

    labels = [s['label'] for s in sources]
    selection = xbmcgui.Dialog().select(f"[COLOR deepskyblue]{title}[/COLOR]\n[COLOR yellow]Surse găsite: {len(sources)}[/COLOR]", labels)
    
    if selection != -1:
        selected = sources[selection]
        play_li = xbmcgui.ListItem(title, path=selected['path'])
        
        v_info = {
            'title': title,
            'mediatype': 'movie' if c_type == 'movie' else 'episode',
            'imdbnumber': imdb_id,
            'code': imdb_id,
            'year': int(year) if str(year).isdigit() else 0
        }
        
        if c_type != 'movie':
            v_info.update({
                'season': int(season) if season else 0,
                'episode': int(episode) if episode else 0,
                'tvshowtitle': title
            })
            
        play_li.setInfo('video', v_info)
        
        ids = {'imdb': imdb_id}
        if tmdb_id: ids['tmdb'] = str(tmdb_id)
        play_li.setUniqueIDs(ids, 'imdb')
        
        if selected.get('raw_filename'):
            play_li.setProperties({
                'filename_and_path': selected['raw_filename'],
                'path': selected['path']
            })

        res_val = selected['quality_val']
        v_stream = {'codec': 'h264'}
        if res_val >= 2160: v_stream.update({'width': 3840, 'height': 2160})
        elif res_val >= 1080: v_stream.update({'width': 1920, 'height': 1080})
        else: v_stream.update({'width': 1280, 'height': 720})
        
        if selected['is_hdr']: v_stream.update({'hdrtype': 'hdr10'})
        play_li.addStreamInfo('video', v_stream)
        

        xbmcplugin.setResolvedUrl(handle, True, listitem=play_li)
