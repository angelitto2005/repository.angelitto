import sys
import urllib.parse
import urllib.request
import re
import xbmcgui
import xbmcplugin
import xbmc
from datetime import datetime

# Constante Plugin
URL = sys.argv[0]
HANDLE = int(sys.argv[1])
BASE_URL = 'https://rotv123.com'
# Sursa EPG solicitata
EPG_SOURCE_XML = 'https://www.open-epg.com/files/romania1.xml'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'

_EPG_CACHE = {}

def get_data(url):
    if not url.startswith('http'):
        url = urllib.parse.urljoin(BASE_URL + '/', url)
    req = urllib.request.Request(url)
    req.add_header('User-Agent', USER_AGENT)
    try:
        response = urllib.request.urlopen(req, timeout=20)
        return response.read()
    except:
        return None

def clean_name(text):
    """Normalizeaza numele pentru a face match intre site si EPG"""
    if not text: return ""
    text = text.lower()
    # Eliminam extensii si zgomot (ex: .ro, hd, etc)
    text = re.sub(r'\.ro|\.com|\.tv|hd|sd|fhd|romania|online', '', text)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text.strip()

def load_epg():
    """Citeste EPG-ul din GitHub si gaseste emisiunea de la ora curenta"""
    global _EPG_CACHE
    if _EPG_CACHE: return _EPG_CACHE

    xbmc.log("Rotv123: Citire EPG din GitHub...", xbmc.LOGINFO)
    data = get_data(EPG_SOURCE_XML)
    if not data: return {}

    try:
        xml = data.decode('utf-8', errors='ignore')
        # Format XMLTV: 20260111074500 +0200
        # Folosim UTC pentru comparatie, deoarece XML-ul este de obicei in UTC (+0000)
        now_str = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        
        # Regex pentru a prinde emisiunile
        pattern = re.compile(r'<programme start="([^"]+)" stop="([^"]+)" channel="([^"]+)">.*?<title[^>]*>([^<]+)</title>', re.DOTALL)
        
        for start, stop, channel, title in pattern.findall(xml):
            # Daca ora curenta (UTC) este intre start si stop
            if start[:14] <= now_str <= stop[:14]:
                key = clean_name(channel)
                _EPG_CACHE[key] = title
    except Exception as e:
        xbmc.log(f"Rotv123 EPG Error: {str(e)}", xbmc.LOGERROR)
    
    return _EPG_CACHE

def main_menu():
    data = get_data(BASE_URL)
    if not data: return
    html = data.decode('utf-8', errors='ignore')
    xbmcplugin.setContent(HANDLE, 'genres')
    
    pattern = re.compile(r'href="([^"]*categoria\.php\?cat=[^"]*)"[^>]*class="[^"]*main-category[^"]*"[^>]*>.*?category-title">([^<]+)</div>', re.DOTALL)
    for link, title in pattern.findall(html):
        url = build_url({'mode': 'category', 'url': link})
        list_item = xbmcgui.ListItem(label=title.strip())
        list_item.setArt({'icon': 'DefaultVideoPlaylists.png'})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_category(category_url):
    data = get_data(category_url)
    if not data: return
    html = data.decode('utf-8', errors='ignore')
    
    epg_data = load_epg()
    xbmcplugin.setContent(HANDLE, 'videos')
    
    blocks = re.findall(r'<a[^>]+class="channel-card"[^>]*>.*?</a>', html, re.DOTALL)
    for block in blocks:
        name_m = re.search(r'class="channel-name">([^<]+)</span>', block)
        link_m = re.search(r'href="([^"]+)"', block)
        img_m = re.search(r'src="([^"]+)"', block)
        
        if name_m and link_m:
            name = name_m.group(1).strip()
            link = link_m.group(1)
            
            # Match EPG folosind numele normalizat
            key = clean_name(name)
            program = epg_data.get(key, "")
            
            # Daca nu gaseste match exact, incearca o cautare partiala
            if not program:
                for k, v in epg_data.items():
                    if k in key or key in k:
                        program = v
                        break

            # Logo tip POSTER (Uniformizat)
            logo_orig = urllib.parse.urljoin(BASE_URL, img_m.group(1)) if img_m else ""
            clean_img = logo_orig.replace('https://', '').replace('http://', '')
            # Parametrii weserv: h=450 (inaltime), w=320 (latime) pentru aspect poster
            poster = f"https://images.weserv.nl/?url={clean_img}&w=320&h=450&fit=contain&bg=transparent"
            
            label = name
            if program:
                label = f"{name} [COLOR gold]• {program}[/COLOR]"

            url = build_url({'mode': 'play', 'url': link, 'name': name, 'logo': poster})
            list_item = xbmcgui.ListItem(label=label)
            list_item.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
            list_item.setInfo('video', {'title': name, 'plot': program if program else "Fara EPG"})
            list_item.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=False)
            
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(video_url, name, logo):
    data = get_data(video_url)
    if not data: return
    html = data.decode('utf-8', errors='ignore')
    
    # ALEGERE SURSA (SELECTORUL)
    streams_match = re.search(r'const streams\s*=\s*\{([^}]+)\}', html, re.DOTALL)
    if streams_match:
        url_matches = re.findall(r'(\w+)\s*:\s*[\'"]\s*([^\'"\s,]+)', streams_match.group(1))
        streams = [(lbl.replace('_', ' ').capitalize(), u.strip()) for lbl, u in url_matches]
        
        selected_url = ""
        if len(streams) > 1:
            labels = [s[0] for s in streams]
            idx = xbmcgui.Dialog().select(f"Alege sursa pentru {name}", labels)
            if idx > -1:
                selected_url = streams[idx][1]
            else: return
        elif streams:
            selected_url = streams[0][1]

        if selected_url:
            header = f'User-Agent={USER_AGENT}&Referer={BASE_URL}/'
            play_item = xbmcgui.ListItem(label=name)
            if logo: play_item.setArt({'thumb': logo, 'icon': logo})
            play_item.setPath(selected_url + '|' + header)
            xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)

def build_url(query):
    return URL + '?' + urllib.parse.urlencode(query)

def router(param_string):
    params = dict(urllib.parse.parse_qsl(param_string))
    mode = params.get('mode')
    if mode == 'category': list_category(params.get('url'))
    elif mode == 'play': play_video(params.get('url'), params.get('name'), params.get('logo'))
    else: main_menu()

if __name__ == '__main__':
    router(sys.argv[2][1:])