import sys
import os
import urllib.parse
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs

addon = xbmcaddon.Addon()
addon_path = xbmcvfs.translatePath(addon.getAddonInfo('path'))
lib_path = os.path.join(addon_path, 'resources', 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

try:
    import movies
    import tvshows
    import player
    import subtitles
except ImportError as e:
    xbmc.log(f"[TMDB_ERROR] Eroare import module: {str(e)}", xbmc.LOGERROR)

def get_search_query():
    keyboard = xbmc.Keyboard('', 'Introdu termenul de căutare...')
    keyboard.doModal()
    if keyboard.isConfirmed():
        return keyboard.getText()
    return None

def play_with_subtitles(params, handle):
    tmdb_id = params.get('tmdb_id')
    content_type = params.get('type')
    season = params.get('season')
    episode = params.get('episode')
    imdb_id = player.get_imdb_id(tmdb_id, content_type)
    downloaded_subs = []

    if imdb_id:
        found_subs = subtitles.search_subtitles(imdb_id, season, episode)
        if found_subs:
            profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
            subs_folder = os.path.join(profile_path, 'subs')
            if not xbmcvfs.exists(subs_folder): 
                xbmcvfs.mkdirs(subs_folder)
            
            for i, sub_data in enumerate(found_subs):
                temp_path = subtitles.download_subtitle(sub_data, subs_folder)
                if temp_path:
                    original_name = os.path.basename(temp_path)
                    new_filename = f"{i}_{original_name}"
                    new_path = os.path.join(subs_folder, new_filename)
                    xbmcvfs.rename(temp_path, new_path)
                    downloaded_subs.append(new_path)

    player.play_video(handle, params)

    if downloaded_subs:
        monitor = xbmc.Monitor()
        xbmc_player = xbmc.Player()
        retries = 30
        while not xbmc_player.isPlaying() and not monitor.abortRequested() and retries > 0:
            xbmc.sleep(500)
            retries -= 1
        
        if xbmc_player.isPlaying():
            for sub in downloaded_subs:
                xbmc_player.setSubtitles(sub)
            xbmcgui.Dialog().notification('WyzieSub', f'S-au încărcat {len(downloaded_subs)} subtitrări', xbmcgui.NOTIFICATION_INFO, 3000)

def main():
    handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    raw_params = sys.argv[2].lstrip('?') if len(sys.argv) > 2 else ""
    params = dict(urllib.parse.parse_qsl(raw_params))
    base_url = sys.argv[0]
    action = params.get('action')
    page = int(params.get('page', 1))
    query = params.get('query', '')

    if not action:
        menu_items = [
            ('Filme', 'movies'),
            ('Seriale', 'tvshows'),
            ('Căutare Filme', 'search_movies'),
            ('Căutare Seriale', 'search_tv'),
            ('Căutare (Filme + Seriale)', 'search_all')
        ]
        for label, act in menu_items:
            url = f"{base_url}?action={act}&page=1"
            li = xbmcgui.ListItem(label=label)
            xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=True)
        xbmcplugin.endOfDirectory(handle)

    elif action == 'search_movies':
        search_term = get_search_query()
        if search_term:
            movies.list_movies(handle, base_url, 1, query=search_term)

    elif action == 'search_tv':
        search_term = get_search_query()
        if search_term:
            tvshows.list_tvshows(handle, base_url, 1, query=search_term)

    elif action == 'search_all':
        search_term = get_search_query()
        if search_term:
            movies.list_movies(handle, base_url, 1, query=search_term, multi=True)

    elif action == 'movies':
        movies.list_movies(handle, base_url, page, query=query)
        
    elif action == 'tvshows':
        tvshows.list_tvshows(handle, base_url, page, query=query)

    elif action == 'list_seasons':
        tvshows.list_seasons(handle, base_url, params.get('tv_id'))

    elif action == 'list_episodes':
        tvshows.list_episodes(handle, base_url, params.get('tv_id'), params.get('season_num'))

    elif action == 'play':
        play_with_subtitles(params, handle)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        xbmc.log(f"[TMDB_FATAL] Eroare: {str(e)}", xbmc.LOGERROR)
