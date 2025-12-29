import sys
import urllib.parse
from urllib.parse import urlencode
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import xbmcvfs
import os
import resources.lib.player as player_module
import resources.lib.subtitles as subs_module

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = "https://api.themoviedb.org/3"
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
IMG_BASE = "https://image.tmdb.org/t/p/w500"

def add_directory(name, params, folder=True, thumb='', plot='', info=None, is_playable=False):
    url = f"{sys.argv[0]}?{urlencode(params)}"
    li = xbmcgui.ListItem(name)
    if thumb: 
        li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
    
    video_info = info if info else {'plot': plot or 'Fără descriere'}
    li.setInfo('video', video_info)
    
    if is_playable: 
        li.setProperty('IsPlayable', 'true')
    
    xbmcplugin.addDirectoryItem(HANDLE, url, li, folder)

def get_imdb_id(tmdb_id, content_type):
    url = f"{BASE_URL}/{content_type}/{tmdb_id}/external_ids?api_key={API_KEY}"
    try:
        data = player_module.get_json(url)
        return data.get('imdb_id')
    except:
        return None

def play_with_subtitles(params):
    tmdb_id = params.get('tmdb_id')
    content_type = params.get('type')
    season = params.get('season')
    episode = params.get('episode')

    imdb_id = get_imdb_id(tmdb_id, content_type)
    downloaded_subs = []

    if imdb_id:
        found_subs = subs_module.search_subtitles(imdb_id, season, episode)
        if found_subs:
            profile_path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
            subs_folder = os.path.join(profile_path, 'subs')
            if not xbmcvfs.exists(subs_folder):
                xbmcvfs.mkdirs(subs_folder)

            for i, sub_data in enumerate(found_subs):
                temp_path = subs_module.download_subtitle(sub_data, subs_folder)
                if temp_path and xbmcvfs.exists(temp_path):
                    new_path = os.path.join(subs_folder, f"sub_{i}_{os.path.basename(temp_path)}")
                    xbmcvfs.rename(temp_path, new_path)
                    downloaded_subs.append(new_path)

    player_module.play_item(params, HANDLE)

    if downloaded_subs:
        monitor = xbmc.Monitor()
        player = xbmc.Player()
        retries = 20
        while not player.isPlaying() and not monitor.abortRequested() and retries > 0:
            xbmc.sleep(500)
            retries -= 1

        if player.isPlaying():
            for sub in downloaded_subs:
                player.setSubtitles(sub)
            xbmcgui.Dialog().notification('WyzieSub', f'S-au încărcat {len(downloaded_subs)} subtitrări', xbmcgui.NOTIFICATION_INFO, 3000)

def main_menu():
    add_directory("Filme", {'mode': 'list', 'type': 'movie', 'page': '1'})
    add_directory("Seriale", {'mode': 'list', 'type': 'tv', 'page': '1'})
    add_directory("Căutare", {'mode': 'search'})
    xbmcplugin.endOfDirectory(HANDLE)

def list_content(content_type, page=1, query=None):
    page = int(page)
    if query:
        url = f"{BASE_URL}/search/{content_type}?api_key={API_KEY}&query={urllib.parse.quote(query)}&page={page}"
    else:
        endpoint = "/movie/popular" if content_type == "movie" else "/tv/popular"
        url = f"{BASE_URL}{endpoint}?api_key={API_KEY}&page={page}"

    data = player_module.get_json(url)
    if not data: return

    results = data.get('results', [])
    for item in results:
        title = item.get('title') or item.get('name', 'Fără titlu')
        year = (item.get('release_date') or item.get('first_air_date') or '0000')[:4]
        poster = IMG_BASE + item['poster_path'] if item.get('poster_path') else ''
        
        if content_type == 'tv':
            mode = 'details'
            is_folder = True
            is_playable = False
        else:
            mode = 'play'
            is_folder = False
            is_playable = True

        add_directory(
            f"{title} ({year})", 
            {'mode': mode, 'tmdb_id': str(item['id']), 'type': content_type, 'title': title}, 
            folder=is_folder, 
            thumb=poster, 
            plot=item.get('overview'), 
            is_playable=is_playable
        )
    
    if page < data.get('total_pages', 1):
        params = {'mode': 'list', 'type': content_type, 'page': str(page + 1)}
        if query: params['query'] = query
        add_directory("Pagina Următoare", params, folder=True)
        
    xbmcplugin.endOfDirectory(HANDLE)

def show_seasons(tmdb_id):
    url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}"
    data = player_module.get_json(url)
    if not data: return

    for s in data.get('seasons', []):
        if s.get('season_number') == 0: continue
        add_directory(
            f"Sezonul {s['season_number']}", 
            {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(s['season_number']), 'tv_show_title': data.get('name')}, 
            thumb=IMG_BASE + s['poster_path'] if s.get('poster_path') else (IMG_BASE + data.get('poster_path', ''))
        )
    xbmcplugin.endOfDirectory(HANDLE)

def list_episodes(tmdb_id, season_num, tv_show_title):
    url = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}"
    data = player_module.get_json(url)
    if not data: return

    for ep in data.get('episodes', []):
        params = {
            'mode': 'play', 
            'tmdb_id': tmdb_id, 
            'type': 'tv', 
            'season': str(season_num), 
            'episode': str(ep['episode_number']), 
            'title': tv_show_title
        }
        add_directory(
            f"E{ep['episode_number']} - {ep.get('name')}", 
            params, 
            folder=False, 
            thumb=IMG_BASE + (ep.get('still_path') or ''), 
            is_playable=True
        )
    xbmcplugin.endOfDirectory(HANDLE)

def router():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    mode = params.get('mode')
    
    if not mode:
        main_menu()
    elif mode == 'list':
        list_content(params.get('type'), params.get('page', 1), params.get('query'))
    elif mode == 'details':
        show_seasons(params.get('tmdb_id'))
    elif mode == 'episodes':
        list_episodes(params.get('tmdb_id'), params.get('season'), params.get('tv_show_title'))
    elif mode == 'play':
        play_with_subtitles(params)
    elif mode == 'search':
        choice = xbmcgui.Dialog().select('Căutare', ['Filme', 'Seriale'])
        if choice != -1:
            kb = xbmc.Keyboard('', 'Căutare...')
            kb.doModal()
            if kb.isConfirmed():
                list_content(['movie', 'tv'][choice], 1, kb.getText())

if __name__ == '__main__':
    router()
