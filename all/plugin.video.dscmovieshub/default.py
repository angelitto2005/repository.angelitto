import sys
import xbmcgui
import xbmcplugin
import xbmcaddon
import requests
import urllib.parse
import re
from urllib.parse import urlencode

# Configurare Addon
ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = "https://api.themoviedb.org/3"
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
IMG_BASE = "https://image.tmdb.org/t/p/w500"

def get_json(url):
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except: return {}

def get_ids(content_type, tmdb_id):
    """Obține ID-urile externe (IMDb) necesare pentru subtitrări"""
    url = f"{BASE_URL}/{content_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    return get_json(url)

def get_stream_link(imdb_id, content_type, season=None, episode=None):
    # Listă de surse disponibile
    sources = [
        "https://nuviostreams.hayd.uk",
        "https://webstreamr.hayd.uk"
    ]
    
    pattern = r'url"\s*:\s*"(https://vixsrc.to/playlist/.*?)"'

    for base_url in sources:
        try:
            if content_type == 'movie':
                api_url = f"{base_url}/stream/movie/{imdb_id}.json"
            else:
                api_url = f"{base_url}/stream/series/{imdb_id}:{season}:{episode}.json"

            response = requests.get(api_url, timeout=10).text
            match = re.search(pattern, response)
            
            if match:
                return match.group(1).replace('\\/', '/')
        except Exception:
            continue  # Dacă crapă o sursă, trece la următoarea

    return None  # Returnează None dacă nicio sursă nu a funcționat


def add_directory(name, params, folder=True, thumb='', plot='', info=None):
    url = f"{sys.argv[0]}?{urlencode(params)}"
    li = xbmcgui.ListItem(name)
    if thumb: li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
    if info:
        li.setInfo('video', info)
    else:
        li.setInfo('video', {'plot': plot or 'Fără descriere'})
    xbmcplugin.addDirectoryItem(HANDLE, url, li, folder)

def main_menu():
    add_directory("🎬 Filme Populare", {'mode': 'list', 'type': 'movie', 'page': '1'})
    add_directory("📺 Seriale Populare", {'mode': 'list', 'type': 'tv', 'page': '1'})
    add_directory("🔍 Căutare", {'mode': 'search'})
    xbmcplugin.endOfDirectory(HANDLE)

def list_content(content_type, page=1, query=None):
    if query:
        url = f"{BASE_URL}/search/{content_type}?api_key={API_KEY}&query={urllib.parse.quote(query)}&language=ro-RO&page={page}"
    else:
        endpoint = "/movie/popular" if content_type == "movie" else "/tv/popular"
        url = f"{BASE_URL}{endpoint}?api_key={API_KEY}&language=ro-RO&page={page}"

    data = get_json(url)
    for item in data.get('results', []):
        title = item.get('title') or item.get('name', 'Fără titlu')
        year = (item.get('release_date') or item.get('first_air_date') or '0000')[:4]
        poster = IMG_BASE + item['poster_path'] if item.get('poster_path') else ''
        
        add_directory(f"{title} ({year})", 
                     {'mode': 'details', 'tmdb_id': str(item['id']), 'type': content_type}, 
                     thumb=poster, plot=item.get('overview'))

    if data.get('page', 1) < data.get('total_pages', 1):
        add_directory("➡️ Pagina Următoare", {'mode': 'list', 'type': content_type, 'page': str(data['page'] + 1), 'query': query or ''})
    xbmcplugin.endOfDirectory(HANDLE)

def show_details(tmdb_id, content_type):
    url = f"{BASE_URL}/{content_type}/{tmdb_id}?api_key={API_KEY}&language=ro-RO"
    data = get_json(url)
    poster = IMG_BASE + data.get('poster_path', '')
    
    if content_type == 'movie':
        title = data.get('title')
        year = int(data.get('release_date', '0000')[:4])
        li = xbmcgui.ListItem(f"▶ Redă Filmul: {title}")
        li.setArt({'thumb': poster})
        li.setInfo('video', {'title': title, 'year': year})
        li.setProperty('IsPlayable', 'true')
        params = {'mode': 'play', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
        url = f"{sys.argv[0]}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(HANDLE, url, li, False)
    else:
        for s in data.get('seasons', []):
            if s['season_number'] == 0: continue
            add_directory(f"Sezonul {s['season_number']} ({s.get('episode_count')} ep)", 
                         {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(s['season_number']), 'tv_show_title': data.get('name')}, thumb=poster)
    xbmcplugin.endOfDirectory(HANDLE)

def list_episodes(tmdb_id, season_num, tv_show_title):
    url = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language=ro-RO"
    data = get_json(url)
    for ep in data.get('episodes', []):
        name = f"E{ep['episode_number']} - {ep.get('name')}"
        thumb = IMG_BASE + ep.get('still_path', '') if ep.get('still_path') else ''
        
        li = xbmcgui.ListItem(name)
        li.setArt({'thumb': thumb})
        li.setInfo('video', {
            'title': ep.get('name'),
            'tvshowtitle': tv_show_title,
            'season': int(season_num),
            'episode': int(ep['episode_number']),
            'mediatype': 'episode'
        })
        li.setProperty('IsPlayable', 'true')
        
        play_params = {
            'mode': 'play', 'tmdb_id': tmdb_id, 'type': 'tv', 
            'season': season_num, 'episode': ep['episode_number'],
            'title': ep.get('name'), 'tv_show_title': tv_show_title
        }
        play_url = f"{sys.argv[0]}?{urlencode(play_params)}"
        xbmcplugin.addDirectoryItem(HANDLE, play_url, li, False)
    xbmcplugin.endOfDirectory(HANDLE)

def play_item(params):
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type')
    
    xbmcgui.Dialog().notification("Căutare", "Se obțin datele pentru subtitrări...")
    ids = get_ids(c_type, tmdb_id)
    imdb_id = ids.get('imdb_id')
    
    if not imdb_id:
        xbmcgui.Dialog().ok("Eroare", "Acest titlu nu are ID IMDb (necesar pentru subtitrări).")
        return

    link = get_stream_link(imdb_id, c_type, params.get('season'), params.get('episode'))
    
    if link:
        # CREARE LISTITEM PENTRU REDARE
        play_li = xbmcgui.ListItem(params.get('title'))
        play_li.setPath(link)
        
        # METADATE CRITICE PENTRU ADDON-URILE DE SUBTITRĂRI
        meta = {
            'imdbnumber': imdb_id,
            'title': params.get('title')
        }
        
        if c_type == 'movie':
            meta['mediatype'] = 'movie'
            if params.get('year'): meta['year'] = int(params.get('year'))
        else:
            meta.update({
                'mediatype': 'episode',
                'tvshowtitle': params.get('tv_show_title'),
                'season': int(params.get('season')),
                'episode': int(params.get('episode'))
            })
            
        play_li.setInfo('video', meta)
        
        # Această proprietate forțează Kodi să trateze link-ul ca pe un stream video direct
        play_li.setProperty('IsPlayable', 'true')
        
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_li)
    else:
        xbmcgui.Dialog().ok("Eroare", "Sursa video nu a putut fi găsită.")

def search():
    kb = xbmcgui.Keyboard('', 'Caută un film sau serial...')
    kb.doModal()
    if kb.isConfirmed() and kb.getText():
        # Căutăm implicit în filme, dar poți adăuga un dialog de selecție
        list_content('movie', 1, kb.getText())

def router():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    mode = params.get('mode')
    
    if not mode: main_menu()
    elif mode == 'list': list_content(params.get('type'), int(params.get('page', 1)), params.get('query'))
    elif mode == 'details': show_details(params.get('tmdb_id'), params.get('type'))
    elif mode == 'episodes': list_episodes(params.get('tmdb_id'), params.get('season'), params.get('tv_show_title'))
    elif mode == 'play': play_item(params)
    elif mode == 'search': search()

if __name__ == '__main__':
    router()
