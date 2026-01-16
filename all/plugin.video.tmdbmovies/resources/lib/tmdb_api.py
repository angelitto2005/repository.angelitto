import sys
import os
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
import urllib.parse
from urllib.parse import urlencode, quote
import requests
import json
import time
import datetime

from resources.lib.config import (
    BASE_URL, API_KEY, IMG_BASE, BACKDROP_BASE, HANDLE, ADDON,
    TMDB_SESSION_FILE, TRAKT_TOKEN_FILE, FAVORITES_FILE,
    TMDB_LISTS_CACHE_FILE, LISTS_CACHE_TTL, TV_META_CACHE,
    TMDB_V4_BASE_URL, TMDB_IMAGE_BASE, IMAGE_RESOLUTION
)
from resources.lib.utils import get_json, get_language, log, paginate_list, read_json, write_json, get_genres_string
from resources.lib.cache import cache_object, MainCache
from resources.lib import menus
from resources.lib import trakt_sync
from resources.lib.config import PAGE_LIMIT


LANG = get_language()
VIDEO_LANGS = "en,null,ro,hi,ta,te,ml,kn,bn,pa,es,fr,de,it,ru,ja,ko,zh"

PAGE_LIMIT = 21

SEARCH_HISTORY_FILE = os.path.join(ADDON.getAddonInfo('profile'), 'search_history.json')
ADDON_PATH = ADDON.getAddonInfo('path')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
TMDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')


def set_metadata(li, info_data, unique_ids=None, watched_info=None):
    try:
        tag = li.getVideoInfoTag()
        if not tag: return

        # 1. SET MEDIATYPE FIRST (important pentru Estuary)
        if 'mediatype' in info_data: 
            tag.setMediaType(info_data['mediatype'])
        if 'title' in info_data: 
            tag.setTitle(str(info_data['title']))
        if 'plot' in info_data: 
            tag.setPlot(str(info_data['plot']))
        
        # Durată (importantă pentru cerculeț progres)
        duration = 0
        if 'duration' in info_data:
            try: 
                duration = int(info_data['duration'])
                tag.setDuration(duration)
            except: pass

        if 'year' in info_data:
            try: tag.setYear(int(info_data['year']))
            except: pass
        if 'rating' in info_data:
            try: tag.setRating(float(info_data['rating']))
            except: pass
        if 'votes' in info_data:
            try: tag.setVotes(int(info_data['votes']))
            except: pass
        if 'genre' in info_data and info_data['genre']:
            if isinstance(info_data['genre'], list):
                tag.setGenres(info_data['genre'])
            elif isinstance(info_data['genre'], str):
                tag.setGenres(info_data['genre'].split(', '))
        if 'tvshowtitle' in info_data: 
            tag.setTvShowTitle(str(info_data['tvshowtitle']))
        if 'season' in info_data:
            try: tag.setSeason(int(info_data['season']))
            except: pass
        if 'episode' in info_data:
            try: tag.setEpisode(int(info_data['episode']))
            except: pass
        if 'premiered' in info_data: 
            tag.setFirstAired(str(info_data['premiered']))
        if 'originaltitle' in info_data:
            tag.setOriginalTitle(info_data['originaltitle'])
        if 'tagline' in info_data:
            tag.setTagLine(info_data['tagline'])
        if 'mpaa' in info_data:
            tag.setMpaa(info_data['mpaa'])
        if 'studio' in info_data:
            if isinstance(info_data['studio'], list):
                tag.setStudios(info_data['studio'])
            elif isinstance(info_data['studio'], str):
                tag.setStudios([info_data['studio']])
        if 'director' in info_data:
            if isinstance(info_data['director'], list):
                tag.setDirectors(info_data['director'])
            elif isinstance(info_data['director'], str):
                tag.setDirectors([info_data['director']])
        if 'writer' in info_data:
            if isinstance(info_data['writer'], list):
                tag.setWriters(info_data['writer'])
            elif isinstance(info_data['writer'], str):
                tag.setWriters([info_data['writer']])
                
        if unique_ids: 
            tag.setUniqueIDs(unique_ids)
        if 'cast' in info_data:
            tag.setCast(info_data['cast'])

        # LOGICA WATCHED - SIMPLIFICATĂ
        is_fully_watched = False
        
        if isinstance(watched_info, bool): 
            is_fully_watched = watched_info
        elif isinstance(watched_info, int): 
            is_fully_watched = watched_info > 0
        elif isinstance(watched_info, dict):
            w = int(watched_info.get('watched', 0))
            t = int(watched_info.get('total', 0))
            if t > 0:
                li.setProperty('TotalEpisodes', str(t))
                li.setProperty('WatchedEpisodes', str(w))
                li.setProperty('UnWatchedEpisodes', str(max(0, t - w)))
                is_fully_watched = (w >= t)

        # ✅ DOAR PLAYCOUNT - NU SETA OVERLAY MANUAL!
        if is_fully_watched: 
            tag.setPlaycount(1)
        else: 
            tag.setPlaycount(0)
            
            # 4. CERCULEȚ PROGRES (doar dacă NU e vizionat complet)
            if 'resume_percent' in info_data and info_data['resume_percent'] > 0:
                percent = float(info_data['resume_percent'])
                
                if duration == 0:
                    duration = 7200 if info_data.get('mediatype') == 'movie' else 2700
                    try: tag.setDuration(duration)
                    except: pass
                
                resume_time = int((percent / 100.0) * duration)
                
                try: 
                    tag.setResumePoint(float(resume_time), float(duration))
                    # ELIMINAT: IsPlayable cauzează conflict cu list_sources dialog
                    # li.setProperty('IsPlayable', 'true')
                except: 
                    pass
            
    except Exception as e:
        log(f"[METADATA] Error: {e}", xbmc.LOGERROR)

def add_directory(name, params, folder=True, icon=None, thumb=None, fanart=None, cm=None, info=None, uids=None, watched_info=None):
    url = f"{sys.argv[0]}?{urlencode(params)}"
    li = xbmcgui.ListItem(name)

    # ============================================================
    # FIX: Nu setăm IsPlayable pentru mode=sources
    # Lăsăm player.py să gestioneze redarea manual
    # ============================================================
    mode = params.get('mode', '')
    if not folder and mode != 'sources':
        li.setProperty('IsPlayable', 'true')
    # Pentru mode=sources, NU setăm IsPlayable - plugin-ul gestionează singur
    # ============================================================

    art = {}
    if icon:
        art['icon'] = icon
    if thumb:
        art['thumb'] = thumb
        art['poster'] = thumb
    if fanart:
        art['fanart'] = fanart
        art['landscape'] = fanart
    if art:
        li.setArt(art)

    if info:
        set_metadata(li, info, uids, watched_info)

    if cm:
        li.addContextMenuItems(cm)

    xbmcplugin.addDirectoryItem(HANDLE, url, li, folder)


def build_menu(menu_list):
    addon_path = ADDON.getAddonInfo('path')
    icons_path = os.path.join(addon_path, 'resources', 'media')

    for item in menu_list:
        mode = item.get('mode')
        action = item.get('action')
        name = item.get('name')
        icon_name = item.get('iconImage', 'DefaultFolder.png')

        icon_path = os.path.join(icons_path, icon_name)
        if not os.path.exists(icon_path):
            icon_path = icon_name

        url_params = {'mode': mode}
        if action:
            url_params['action'] = action
        if 'menu_type' in item:
            url_params['menu_type'] = item['menu_type']

        add_directory(name, url_params, icon=icon_path, thumb=icon_path, folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def main_menu():
    build_menu(menus.root_list)


def movies_menu():
    build_menu(menus.movie_list)


def tv_menu():
    build_menu(menus.tvshow_list)


def get_search_history():
    """Citește istoricul de căutare."""
    data = read_json(SEARCH_HISTORY_FILE)
    if not data or not isinstance(data, list):
        return []
    return data

def add_search_to_history(query, search_type):
    """Adaugă o căutare nouă la începutul listei (Max 20)."""
    history = get_search_history()
    
    # Creăm obiectul nou
    new_item = {'query': query, 'type': search_type}
    
    # Eliminăm duplicatele (dacă exista deja, îl ștergem ca să-l punem primul)
    history = [h for h in history if not (h['query'] == query and h['type'] == search_type)]
    
    # Adăugăm la început
    history.insert(0, new_item)
    
    # Păstrăm doar ultimele 20
    history = history[:20]
    
    write_json(SEARCH_HISTORY_FILE, history)

def remove_search_from_history(query, search_type):
    """Șterge o căutare specifică."""
    history = get_search_history()
    history = [h for h in history if not (h['query'] == query and h['type'] == search_type)]
    write_json(SEARCH_HISTORY_FILE, history)

def clear_search_history_action():
    """Șterge tot istoricul."""
    if xbmcvfs.exists(SEARCH_HISTORY_FILE):
        xbmcvfs.delete(SEARCH_HISTORY_FILE)
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Istoric șters", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def delete_search_item(params):
    """Funcția apelată din meniul contextual pentru ștergere."""
    query = params.get('query')
    search_type = params.get('type')
    remove_search_from_history(query, search_type)
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Șters din istoric", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def edit_search_item(params):
    """Funcția apelată din meniul contextual pentru editare."""
    old_query = params.get('query')
    search_type = params.get('type')
    
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Editează căutarea", defaultt=old_query, type=xbmcgui.INPUT_ALPHANUM)
    
    # Verificăm dacă utilizatorul a scris ceva și dacă e diferit de ce era înainte
    if new_query and new_query != old_query:
        # 1. Ștergem vechea intrare
        remove_search_from_history(old_query, search_type)
        
        # 2. Adăugăm noua intrare (ACESTA ERA PASUL LIPSĂ)
        add_search_to_history(new_query, search_type)
        
        # 3. Dăm Refresh la listă ca să apară modificarea vizual
        xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Modificare salvată", TMDbmovies_ICON, 2000, False)
        xbmc.executebuiltin("Container.Refresh")


def search_menu():
    SEARCH_MOVIE_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_movie.png')
    SEARCH_TV_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_tv.png')
    
    # Iconița pentru istoric (search.png)
    SEARCH_HISTORY_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_history.png')
    # Fallback dacă nu există search.png, folosim default
    if not os.path.exists(SEARCH_HISTORY_ICON):
        SEARCH_HISTORY_ICON = 'DefaultIconSearch.png'

    # 1. Butoanele principale de căutare
    add_directory("[B][COLOR FFFDBD01]Search Movies[/COLOR][/B]", {'mode': 'perform_search', 'type': 'movie'}, icon=SEARCH_MOVIE_ICON, thumb=SEARCH_MOVIE_ICON, folder=True)
    add_directory("[B][COLOR FFFDBD01]Search TV Shows[/COLOR][/B]", {'mode': 'perform_search', 'type': 'tv'}, icon=SEARCH_TV_ICON, thumb=SEARCH_TV_ICON, folder=True)
    
    # 2. Istoricul de căutare
    history = get_search_history()
    
    if history:
        
        for item in history:
            query = item.get('query')
            stype = item.get('type')
            
            # Formatam tipul (Movie sau TV Show)
            type_label = "Movie" if stype == 'movie' else "TV Show"
            
            # FORMATUL CERUT: History: titlu(Type) bold+inclinat
            label = f"History: [B][I][COLOR FFCA762B]{query} [/COLOR][/I][/B] ({type_label})"
            
            # Context Menu pentru Edit și Delete
            cm = [
                ('Edit Search', f"RunPlugin({sys.argv[0]}?mode=edit_search&query={quote(query)}&type={stype})"),
                ('Delete Search', f"RunPlugin({sys.argv[0]}?mode=delete_search&query={quote(query)}&type={stype})")
            ]
            
            # Parametrii pentru a rula din nou căutarea la click
            url_params = {'mode': 'perform_search_query', 'query': query, 'type': stype}
            
            # Adăugăm cu iconița search.png
            add_directory(label, url_params, icon=SEARCH_HISTORY_ICON, thumb=SEARCH_HISTORY_ICON, cm=cm, folder=True)

        # 3. Buton Clear Historyadd_directory("------------------------------------------------", {'mode': 'noop'}, folder=False)
        add_directory("[B][COLOR FFFF0000]Clear Search History[/COLOR][/B]", {'mode': 'clear_search_history'}, icon='DefaultIconError.png', folder=False)
    
    xbmcplugin.endOfDirectory(HANDLE)


def my_lists_menu():
    add_directory("[B][COLOR pink]Trakt Lists[/COLOR][/B]", {'mode': 'trakt_my_lists'}, icon=TRAKT_ICON, thumb=TRAKT_ICON, folder=True)
    add_directory("[B][COLOR FF00CED1]TMDB Lists[/COLOR][/B]", {'mode': 'tmdb_my_lists'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def favorites_menu():
    MOVIES_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'movies.png')
    TV_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tv.png')

    add_directory("[B][COLOR FFFF69B4]Movies[/COLOR][/B]", {'mode': 'list_favorites', 'type': 'movie'}, icon=MOVIES_ICON, thumb=MOVIES_ICON, folder=True)
    add_directory("[B][COLOR FFFF69B4]TV Shows[/COLOR][/B]", {'mode': 'list_favorites', 'type': 'tv'}, icon=TV_ICON, thumb=TV_ICON, folder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)


def settings_menu():
    from resources.lib import trakt_api

    session = get_tmdb_session()
    if session:
        add_directory(f"[B][COLOR FF00CED1]TMDB: {session.get('username', 'Conectat')}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Deconectare TMDB[/COLOR]", {'mode': 'tmdb_logout'}, folder=False, icon='DefaultIconError.png')
    else:
        add_directory("[B][COLOR FF00CED1]Conectare TMDB[/COLOR][/B]", {'mode': 'tmdb_auth'}, folder=False, icon='DefaultUser.png')

    trakt_token = read_json(TRAKT_TOKEN_FILE)
    if trakt_token and trakt_token.get('access_token'):
        user = trakt_api.get_trakt_username(trakt_token['access_token'])
        ADDON.setSetting('trakt_status', f"Conectat: {user}")
        add_directory(f"[B][COLOR pink]Trakt: {user}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Deconectare Trakt[/COLOR]", {'mode': 'trakt_revoke'}, folder=False, icon='DefaultIconError.png')
        add_directory("[COLOR cyan]Sincronizare Trakt[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultAddonService.png')
    else:
        add_directory("[B][COLOR pink]Conectare Trakt[/COLOR][/B]", {'mode': 'trakt_auth'}, folder=False, icon='DefaultUser.png')

    add_directory("Setări Addon", {'mode': 'settings'}, folder=False, icon='DefaultAddonService.png')
    add_directory("[COLOR orange]Șterge Tot Cache-ul[/COLOR]", {'mode': 'clear_all_cache'}, folder=False, icon='DefaultAddonNone.png')

    xbmcplugin.endOfDirectory(HANDLE)


def get_dates(days, reverse=True):
    current_date = datetime.date.today()
    if reverse:
        new_date = (current_date - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    else:
        new_date = (current_date + datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    return str(current_date), new_date


def get_tmdb_movies_standard(action, page_no):
    import requests # Lazy loading
    
    url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&region=US"

    if action == 'tmdb_movies_popular':
        url = f"{BASE_URL}/movie/popular?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_now_playing':
        url = f"{BASE_URL}/movie/now_playing?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_top_rated':
        url = f"{BASE_URL}/movie/top_rated?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_upcoming':
        current_date, future_date = get_dates(31, reverse=False)
        url += f"&release_date.gte={current_date}&release_date.lte={future_date}&with_release_type=3|2|1"
        
    elif action == 'tmdb_movies_premieres':
        current_date, previous_date = get_dates(31, reverse=True)
        url += f"&release_date.gte={previous_date}&release_date.lte={current_date}&with_release_type=1|3|2&sort_by=popularity.desc"
        
    elif action == 'tmdb_movies_latest_releases':
        current_date, previous_date = get_dates(31, reverse=True)
        url += f"&release_date.gte={previous_date}&release_date.lte={current_date}&with_release_type=4|5&sort_by=primary_release_date.desc"
    
    elif action == 'tmdb_movies_trending_day':
        url = f"{BASE_URL}/trending/movie/day?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_trending_week':
        url = f"{BASE_URL}/trending/movie/week?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_blockbusters':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&sort_by=revenue.desc&vote_count.gte=300&page={page_no}"

    elif action == 'tmdb_movies_box_office':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&sort_by=revenue.desc&page={page_no}"

    return requests.get(url, timeout=15)


def get_tmdb_tv_standard(action, page_no):
    import requests # Lazy loading
    
    url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&page={page_no}&with_original_language=en&region=US"

    if action == 'tmdb_tv_popular':
        url += "&sort_by=popularity.desc&without_genres=10763,10767"
        
    elif action == 'tmdb_tv_premieres':
        current_date, previous_date = get_dates(31, reverse=True)
        url += f"&sort_by=popularity.desc&first_air_date.gte={previous_date}&first_air_date.lte={current_date}"
        
    elif action == 'tmdb_tv_airing_today':
        url = f"{BASE_URL}/tv/airing_today?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_on_the_air':
        url = f"{BASE_URL}/tv/on_the_air?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_top_rated':
        url = f"{BASE_URL}/tv/top_rated?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_upcoming':
        current_date, future_date = get_dates(31, reverse=False)
        url += f"&sort_by=popularity.desc&first_air_date.gte={current_date}&first_air_date.lte={future_date}"
    
    elif action == 'tmdb_tv_trending_day':
        url = f"{BASE_URL}/trending/tv/day?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_trending_week':
        url = f"{BASE_URL}/trending/tv/week?api_key={API_KEY}&language={LANG}&page={page_no}"

    return requests.get(url, timeout=15)


def build_movie_list(params):
    action = params.get('action')
    page = int(params.get('new_page', '1'))

    # Trakt redirection
    if action and 'trakt_movies_' in action:
        from resources.lib import trakt_api
        list_type = action.replace('trakt_movies_', '')
        params['list_type'] = list_type
        params['media_type'] = 'movies'
        trakt_api.trakt_discovery_list(params)
        return

    # 1. Încercăm SQL
    results = trakt_sync.get_tmdb_from_db(action, page)
    
    # 2. Fallback API
    if not results:
        string = f"{action}_{page}_{LANG}"
        expiration = 24 # Ore
        data = cache_object(get_tmdb_movies_standard, string, [action, page], expiration=expiration)
        if data:
            results = data.get('results', [])
    
    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return
        
    # --- FIX PAGINARE ---
    # Când luăm din SQL sau din get_tmdb_... (cu page specific), 
    # rezultatele sunt DEJA pentru pagina curentă. NU trebuie să le tăiem cu paginate_list.
    
    current_items = results 
    
    # Asumăm că există pagini următoare dacă am primit rezultate (până la o limită rezonabilă)
    # API-ul TMDB are multe pagini.
    has_next = len(results) > 0 and page < 500

    for item in current_items:
        _process_movie_item(item)

    if has_next:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}) >>[/COLOR]",
            {'mode': 'build_movie_list', 'action': action, 'new_page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE)


def build_tvshow_list(params):
    action = params.get('action')
    page = int(params.get('new_page', '1'))

    if action and 'trakt_tv_' in action:
        from resources.lib import trakt_api
        list_type = action.replace('trakt_tv_', '')
        params['list_type'] = list_type
        params['media_type'] = 'shows'
        trakt_api.trakt_discovery_list(params)
        return

    # 1. SQL
    results = trakt_sync.get_tmdb_from_db(action, page)
    
    # 2. Fallback API
    if not results:
        string = f"{action}_{page}_{LANG}"
        expiration = 24
        data = cache_object(get_tmdb_tv_standard, string, [action, page], expiration=expiration)
        if data:
            results = data.get('results', [])

    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # --- FIX PAGINARE ---
    current_items = results
    has_next = len(results) > 0 and page < 500

    for item in current_items:
        _process_tv_item(item)

    if has_next:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}) >>[/COLOR]",
            {'mode': 'build_tvshow_list', 'action': action, 'new_page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )

    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def _get_full_context_menu(tmdb_id, content_type, title='', is_in_favorites_view=False):
    cm = []
    # info_params = urlencode({'mode': 'show_info', 'type': content_type, 'tmdb_id': tmdb_id})
    # cm.append(('[B][COLOR FFFDBD01]TMDb Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{info_params})"))
    
    # --- ADĂUGAT EXTENDED INFO (Metoda cu argumente explicite) ---
    # Folosim calea specială pentru a fi siguri că găsește scriptul
    # Trimitem id și type ca argumente separate prin virgulă
    # import xbmcaddon
    # my_addon_id = xbmcaddon.Addon().getAddonInfo('id')
    # script_path = f"special://home/addons/{my_addon_id}/context_extended.py"
    
    # RunScript(script, arg1, arg2...)
    # run_cmd = f"RunScript({script_path}, tmdb_id={tmdb_id}, type={content_type})"
    
    # cm.append(('[B][COLOR FF33CCFF]Extended Info[/COLOR][/B]', run_cmd))
    # -------------------------------------------------------------

    trakt_params = urlencode({'mode': 'trakt_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title})
    cm.append(('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{trakt_params})"))

    tmdb_params = urlencode({'mode': 'tmdb_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title})
    cm.append(('[B][COLOR FF00CED1]My TMDB[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{tmdb_params})"))

    # --- MODIFICARE: DOAR PENTRU FILME (nu seriale/foldere) ---
    if content_type == 'movie':
        clear_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_params})"))
    # ----------------------------------------------------------
    
    if is_in_favorites_view:
        rem_params = urlencode({'mode': 'remove_favorite', 'type': content_type, 'tmdb_id': tmdb_id})
        cm.append(('[B][COLOR yellow]Remove from My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{rem_params})"))
    else:
        fav_params = urlencode({'mode': 'add_favorite', 'type': content_type, 'tmdb_id': tmdb_id, 'title': title})
        cm.append(('[B][COLOR yellow]Add to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

    return cm


def _process_movie_item(item, is_in_favorites_view=False):
    from resources.lib import trakt_api
    
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return

    # MODIFICARE: Am eliminat apelul catre get_title_with_fallback.
    # Luam titlul direct. Fiind setat LANG='en-US', TMDb ne da deja titlul in engleza.
    title = item.get('title') or 'Unknown'
    
    year = str(item.get('release_date', ''))[:4]
    plot = item.get('overview', '')
    
    # --- FIX: ÎNCĂRCARE DETALII COMPLETE PENTRU METADATE ---
    full_details = get_tmdb_item_details(tmdb_id, 'movie') or {}
    
    # 1. Studio
    studio = ''
    if full_details.get('production_companies'):
        studio = full_details['production_companies'][0].get('name', '')
        
    # 2. Rating & Votes
    rating = full_details.get('vote_average', item.get('vote_average', 0))
    votes = full_details.get('vote_count', item.get('vote_count', 0))
    
    # 3. Data exactă (Premiered)
    premiered = full_details.get('release_date', item.get('release_date', ''))
    if not premiered or premiered.endswith('-01-01'):
        if full_details.get('release_date'):
            premiered = full_details.get('release_date')
            
    # 4. Durata
    duration = full_details.get('runtime', 0)
    if duration:
        duration = int(duration) * 60
        
    # 5. Plot
    if full_details.get('overview'):
        plot = full_details.get('overview')

    # --- CALCUL RESUME (SUPORTĂ FORMAT NOU: POZIȚIE ÎN SECUNDE) ---
    from resources.lib import trakt_sync
    
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'movie')
    resume_percent = 0
    resume_seconds = 0
    
    # Detectăm formatul: poziție (>= 1000000) sau procent (<100)
    if progress_value >= 1000000:
        # Format nou: poziție în secunde
        resume_seconds = int(progress_value - 1000000)
        # Calculăm procentul pentru cerculeț (folosim duration calculat mai jos)
    elif progress_value > 0 and progress_value < 95:
        # Format vechi: procent
        resume_percent = progress_value
    # --- SFARSIT ---

    # --- LOGICA IMAGINI (Self Healing) ---
    poster_path_db = item.get('poster_path', '')
    if not poster_path_db and full_details.get('poster_path'):
        poster_path_db = full_details.get('poster_path')
        
    backdrop_path_db = item.get('backdrop_path', '')
    if not backdrop_path_db and full_details.get('backdrop_path'):
        backdrop_path_db = full_details.get('backdrop_path')
    
    poster = ''
    backdrop = ''
    needs_update = False

    if poster_path_db:
        poster = f"{IMG_BASE}{poster_path_db}" if not poster_path_db.startswith('http') else poster_path_db
    else:
        poster_path_new = _get_poster_path(tmdb_id, 'movie')
        if poster_path_new:
            poster = f"{IMG_BASE}{poster_path_new}"
            needs_update = True

    if backdrop_path_db:
        backdrop = f"{BACKDROP_BASE}{backdrop_path_db}" if not backdrop_path_db.startswith('http') else backdrop_path_db

    if needs_update and (poster or backdrop):
        trakt_sync.update_item_images(tmdb_id, 'movie', poster, backdrop)
    
    is_watched = trakt_api.get_watched_counts(tmdb_id, 'movie') > 0

    # ============================================================
    # CALCULĂM resume_percent DIN resume_seconds (dacă e format nou)
    # ============================================================
    if resume_seconds > 0 and duration > 0:
        resume_percent = (resume_seconds / duration) * 100
    # ============================================================
    
    info = {
        'mediatype': 'movie',
        'title': title,
        'year': year,
        'plot': plot,
        'rating': rating,
        'votes': votes,
        'genre': get_genres_string(item.get('genre_ids', [])),
        'premiered': premiered,
        'studio': studio,
        'duration': duration,
        'resume_percent': resume_percent
    }
    cm = _get_full_context_menu(tmdb_id, 'movie', title, is_in_favorites_view)

    # --- INCEPUT FIX RESUME ---
    url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
    
    # Dacă avem resume, adăugăm parametrul
    resume_seconds = 0
    if resume_percent > 0 and resume_percent < 95 and duration > 0:
        resume_seconds = int((resume_percent / 100.0) * duration)
        url_params['resume_time'] = resume_seconds
    
    url = f"{sys.argv[0]}?{urlencode(url_params)}"
    li = xbmcgui.ListItem(f"{title} ({year})" if year else title)
    
    # Setare art
    li.setArt({'icon': poster or TMDbmovies_ICON, 'thumb': poster or TMDbmovies_ICON, 'poster': poster or TMDbmovies_ICON, 'fanart': backdrop})
    
    # Setare metadata
    set_metadata(li, info, watched_info=is_watched)
    
    # SETARE RESUME EXPLICITĂ (pentru cerculeț)
    if resume_seconds > 0 and duration > 0:
        li.setProperty('resumetime', str(resume_seconds))
        li.setProperty('totaltime', str(duration))
    
    # Context menu
    if cm:
        li.addContextMenuItems(cm)
    
    # Adăugare în listă
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
    # --- SFARSIT FIX RESUME ---


def _process_tv_item(item, is_in_favorites_view=False):
    from resources.lib import trakt_api
    
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return

    if 'name' not in item and 'title' in item:
        item['name'] = item['title']

    # MODIFICARE: Eliminat fallback-ul. Luam titlul direct.
    title = item.get('name') or 'Unknown'
    
    year = str(item.get('first_air_date', ''))[:4]
    plot = item.get('overview', '')

    # --- FIX: ÎNCĂRCARE DETALII COMPLETE PENTRU METADATE ---
    full_details = get_tmdb_item_details(tmdb_id, 'tv') or {}

    # 1. Studio (Networks)
    studio = ''
    if full_details.get('networks'):
        studio = full_details['networks'][0].get('name', '')
        
    # 2. Rating & Votes
    rating = full_details.get('vote_average', item.get('vote_average', 0))
    votes = full_details.get('vote_count', item.get('vote_count', 0))

    # 3. Data exactă
    premiered = full_details.get('first_air_date', item.get('first_air_date', ''))
    if not premiered or premiered.endswith('-01-01'):
        if full_details.get('first_air_date'):
            premiered = full_details.get('first_air_date')

    # 4. Durata (media episoadelor)
    duration = 0
    runtimes = full_details.get('episode_run_time', [])
    if runtimes:
        duration = int(runtimes[0]) * 60
        
    if full_details.get('overview'):
        plot = full_details.get('overview')
    
    # --- LOGICA IMAGINI ---
    poster_path_db = item.get('poster_path', '')
    if not poster_path_db and full_details.get('poster_path'):
        poster_path_db = full_details.get('poster_path')

    backdrop_path_db = item.get('backdrop_path', '')
    if not backdrop_path_db and full_details.get('backdrop_path'):
        backdrop_path_db = full_details.get('backdrop_path')

    poster = ''
    backdrop = ''
    needs_update = False

    if poster_path_db:
        poster = f"{IMG_BASE}{poster_path_db}" if not poster_path_db.startswith('http') else poster_path_db
    else:
        cached_poster = trakt_sync.get_poster_from_db(tmdb_id, 'tv')
        if cached_poster:
            poster = cached_poster if cached_poster.startswith('http') else f"{IMG_BASE}{cached_poster}"
            needs_update = True
        else:
            poster_path_new = _get_poster_path(tmdb_id, 'tv')
            if poster_path_new:
                poster = f"{IMG_BASE}{poster_path_new}"
                needs_update = True
    
    if backdrop_path_db:
        backdrop = f"{BACKDROP_BASE}{backdrop_path_db}" if not backdrop_path_db.startswith('http') else backdrop_path_db

    if needs_update and poster:
        poster_save = poster.replace(IMG_BASE, '')
        backdrop_save = backdrop.replace(BACKDROP_BASE, '') if backdrop else ''
        trakt_sync.update_item_images(tmdb_id, 'show', poster_save, backdrop_save)
    # -------------------------------------

    watched_info = get_watched_status_tvshow(tmdb_id)

    info = {
        'mediatype': 'tvshow',
        'title': title,
        'year': year,
        'plot': plot,
        'rating': rating,
        'votes': votes,
        'genre': get_genres_string(item.get('genre_ids', [])),
        'premiered': premiered,
        'studio': studio,
        'duration': duration
    }

    cm = _get_full_context_menu(tmdb_id, 'tv', title, is_in_favorites_view)

    add_directory(
        f"{title} ({year})" if year else title,
        {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': title},
        icon=poster or TMDbmovies_ICON, thumb=poster or TMDbmovies_ICON, fanart=backdrop, info=info, cm=cm,
        watched_info=watched_info, folder=True
    )


def get_watched_status_tvshow(tmdb_id):
    from resources.lib import trakt_api
    from resources.lib import trakt_sync
    import requests # Lazy

    watched_count = trakt_api.get_watched_counts(tmdb_id, 'tv')
    str_id = str(tmdb_id)
    
    # 1. Încercăm cache RAM (pentru sesiune curentă)
    if str_id in TV_META_CACHE:
        total_eps = TV_META_CACHE[str_id]
        
    else:
        # 2. Încercăm SQL (VITEZĂ INSTANTĂ)
        # Acum funcția există în trakt_sync (adăugată la pasul 1)
        total_eps = trakt_sync.get_tv_meta_from_db(str_id)
        
        # 3. Fallback: Dacă nu e nici în SQL, luăm de pe net
        if not total_eps:
            try:
                url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={LANG}"
                data = requests.get(url, timeout=5).json()
                total_eps = data.get('number_of_episodes', 0)
                
                # Salvăm în SQL pentru data viitoare
                trakt_sync.set_tv_meta_to_db(str_id, total_eps)
            except:
                total_eps = 0

        # Salvăm în RAM
        TV_META_CACHE[str_id] = total_eps

    return {'watched': watched_count, 'total': total_eps}


def get_tmdb_session():
    data = read_json(TMDB_SESSION_FILE)
    if data.get('session_id') and data.get('account_id'):
        return data
    return None


def tmdb_auth():
    dialog = xbmcgui.Dialog()
    
    try:
        url = f"{BASE_URL}/authentication/token/new?api_key={API_KEY}"
        r = requests.get(url, timeout=10)
        request_token = r.json().get('request_token')
        if not request_token:
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare inițializare token", xbmcgui.NOTIFICATION_ERROR)
            return False
    except:
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare conexiune server", xbmcgui.NOTIFICATION_ERROR)
        return False

    username = dialog.input("Introdu Username-ul TMDB", type=xbmcgui.INPUT_ALPHANUM)
    if not username: return False

    password = dialog.input("Introdu Parola TMDB", type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT)
    if not password: return False

    try:
        validate_url = f"{BASE_URL}/authentication/token/validate_with_login?api_key={API_KEY}"
        payload = {
            'username': username,
            'password': password,
            'request_token': request_token
        }
        r = requests.post(validate_url, json=payload, timeout=15)
        
        if r.status_code != 200:
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "User sau parolă incorectă!", xbmcgui.NOTIFICATION_ERROR)
            return False
            
    except Exception as e:
        log(f"[TMDB] Login Error: {e}", xbmc.LOGERROR)
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare la validare", xbmcgui.NOTIFICATION_ERROR)
        return False

    return create_tmdb_session(request_token)

def create_tmdb_session(request_token):
    dialog = xbmcgui.Dialog()
    try:
        session_url = f"{BASE_URL}/authentication/session/new?api_key={API_KEY}"
        r = requests.post(session_url, json={'request_token': request_token}, timeout=10)

        if r.status_code != 200:
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare creare sesiune!", xbmcgui.NOTIFICATION_ERROR)
            return False

        session_id = r.json().get('session_id')
        if not session_id:
            return False

        account_url = f"{BASE_URL}/account?api_key={API_KEY}&session_id={session_id}"
        r = requests.get(account_url, timeout=10)
        account_data = r.json()
        username = account_data.get('username', 'User')

        write_json(TMDB_SESSION_FILE, {
            'session_id': session_id,
            'account_id': account_data.get('id'),
            'username': username
        })

        ADDON.setSetting('tmdb_status', f"Conectat: {username}")

        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"Conectat: [B][COLOR FFF70D1A]{username}[/COLOR][/B]", TMDB_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
        return True

    except Exception as e:
        log(f"[TMDB] Session Error: {e}", xbmc.LOGERROR)
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare sesiune", xbmcgui.NOTIFICATION_ERROR)
        return False

def tmdb_logout():
    session_data = get_tmdb_session()
    
    if session_data:
        try:
            url = f"{BASE_URL}/authentication/session?api_key={API_KEY}"
            requests.delete(url, json={'session_id': session_data['session_id']}, timeout=10)
        except:
            pass

    if xbmcvfs.exists(TMDB_SESSION_FILE):
        xbmcvfs.delete(TMDB_SESSION_FILE)
    if xbmcvfs.exists(TMDB_LISTS_CACHE_FILE):
        xbmcvfs.delete(TMDB_LISTS_CACHE_FILE)

    ADDON.setSetting('tmdb_status', "Neconectat")

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "User Deconectat", TMDB_ICON, 3000, False)
    xbmc.executebuiltin("Container.Refresh")

def tmdb_v4_request(endpoint, method='GET', data=None):
    session = get_tmdb_session()
    if not session:
        return None
    
    url = f"{TMDB_V4_BASE_URL}{endpoint}"
    
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json;charset=utf-8'
    }
    
    try:
        if method == 'GET':
            r = requests.get(url, headers=headers, timeout=15)
        elif method == 'POST':
            r = requests.post(url, headers=headers, json=data, timeout=15)
        elif method == 'DELETE':
            r = requests.delete(url, headers=headers, json=data, timeout=15)
        else:
            return None
        
        if r.status_code in [200, 201]:
            return r.json()
        else:
            log(f"[TMDB-V4] Request failed: {r.status_code} {r.text}", xbmc.LOGERROR)
            return None
    except Exception as e:
        log(f"[TMDB-V4] Request error: {e}", xbmc.LOGERROR)
        return None


def get_tmdb_user_lists_v4():
    session = get_tmdb_session()
    if not session:
        return []
    
    account_id = session.get('account_id')
    all_lists = []
    page = 1
    
    while True:
        data = tmdb_v4_request(f"/account/{account_id}/lists?page={page}")
        
        if not data or 'results' not in data:
            break
        
        results = data.get('results', [])
        if not results:
            break
        
        all_lists.extend(results)
        
        total_pages = data.get('total_pages', 1)
        if page >= total_pages:
            break
        page += 1
    
    return all_lists


def get_tmdb_list_details_v4(list_id):
    return tmdb_v4_request(f"/list/{list_id}?page=1")


def get_tmdb_lists_cache():
    cache = read_json(TMDB_LISTS_CACHE_FILE)
    if cache and isinstance(cache, dict) and cache.get('timestamp'):
        if int(time.time()) - cache['timestamp'] < LISTS_CACHE_TTL:
            data = cache.get('data', [])
            if data and len(data) > 0:
                return data
    return None


def save_tmdb_lists_cache(data):
    cache = {
        'timestamp': int(time.time()),
        'data': data
    }
    write_json(TMDB_LISTS_CACHE_FILE, cache)


def clear_tmdb_lists_cache(params=None):
    if xbmcvfs.exists(TMDB_LISTS_CACHE_FILE):
        xbmcvfs.delete(TMDB_LISTS_CACHE_FILE)
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Cache liste șters", TMDB_ICON, 3000, False)
    xbmc.executebuiltin("Container.Refresh")


def get_tmdb_lists_with_details():
    session = get_tmdb_session()
    if not session:
        return []

    lists_v4 = get_tmdb_user_lists_v4()

    if not lists_v4:
        lists_v3 = get_tmdb_user_lists_v3()
        return lists_v3

    lists_with_details = []

    for lst in lists_v4:
        list_id = str(lst.get('id'))
        
        poster_path = lst.get('poster_path', '')
        backdrop_path = lst.get('backdrop_path', '')
        
        if poster_path:
            poster = TMDB_IMAGE_BASE % (IMAGE_RESOLUTION['poster'], poster_path)
        else:
            poster = ''
        
        if backdrop_path:
            backdrop = TMDB_IMAGE_BASE % (IMAGE_RESOLUTION['fanart'], backdrop_path)
        else:
            backdrop = ''
        
        if not poster and list_id:
            list_details = get_tmdb_list_details_v4(list_id)
            if list_details and list_details.get('results'):
                first_item = list_details['results'][0]
                item_poster = first_item.get('poster_path', '')
                item_backdrop = first_item.get('backdrop_path', '')
                if item_poster:
                    poster = TMDB_IMAGE_BASE % (IMAGE_RESOLUTION['poster'], item_poster)
                if item_backdrop and not backdrop:
                    backdrop = TMDB_IMAGE_BASE % (IMAGE_RESOLUTION['fanart'], item_backdrop)

        lists_with_details.append({
            'id': list_id,
            'name': lst.get('name', 'Unknown'),
            'description': lst.get('description', ''),
            'item_count': lst.get('number_of_items', lst.get('item_count', 0)),
            'poster': poster,
            'backdrop': backdrop,
            'public': lst.get('public', False)
        })

    return lists_with_details


def get_tmdb_user_lists_v3():
    session = get_tmdb_session()
    if not session:
        return []

    lists_url = f"{BASE_URL}/account/{session['account_id']}/lists?api_key={API_KEY}&session_id={session['session_id']}"
    lists_data = get_json(lists_url)

    if not lists_data or 'results' not in lists_data:
        return []

    lists_with_details = []

    for lst in lists_data['results']:
        list_id = str(lst.get('id'))
        poster_path = ''
        backdrop_path = ''
        
        list_details_url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&language={LANG}"
        list_details = get_json(list_details_url)
        
        if list_details and list_details.get('items'):
            first_item = list_details['items'][0]
            poster_path = first_item.get('poster_path', '')
            backdrop_path = first_item.get('backdrop_path', '')

        lists_with_details.append({
            'id': list_id,
            'name': lst.get('name', 'Unknown'),
            'description': lst.get('description', ''),
            'item_count': lst.get('item_count', 0),
            'poster': f"{IMG_BASE}{poster_path}" if poster_path else '',
            'backdrop': f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''
        })
    return lists_with_details


def tmdb_my_lists():
    session = get_tmdb_session()
    if not session:
        add_directory("[COLOR yellow]Login TMDB[/COLOR]", {'mode': 'tmdb_auth'}, icon='DefaultUser.png', folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    add_directory("Watchlist", {'mode': 'tmdb_watchlist_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("Favorites", {'mode': 'tmdb_favorites_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("Recommendations", {'mode': 'tmdb_recommendations_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    
    add_directory("[B][COLOR FF00CED1]--- My Lists ---[/COLOR][/B]", {'mode': 'noop'}, folder=False)

    # ✅ Citim listele personale din SQL
    lists = trakt_sync.get_tmdb_custom_lists_from_db()
    
    log(f"[TMDB] Found {len(lists) if lists else 0} custom lists in SQL")

    if lists:
        for lst in lists:
            list_id = str(lst.get('list_id'))
            name = lst.get('name', 'Unknown')
            count = lst.get('item_count', 0)
            poster_path = lst.get('poster', '')
            
            poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDB_ICON
            
            cm = [
                ('Refresh Lists', f"RunPlugin({sys.argv[0]}?mode=trakt_sync_db)"), 
                ('Delete List', f"RunPlugin({sys.argv[0]}?mode=delete_tmdb_list&list_id={list_id})"),
                ('Clear List Items', f"RunPlugin({sys.argv[0]}?mode=clear_tmdb_list&list_id={list_id})"),
            ]

            add_directory(
                f"{name} [COLOR gray]({count})[/COLOR]",
                {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': name},
                icon=poster, thumb=poster, cm=cm, folder=True
            )
    else:
        add_directory("[COLOR gray]Nu ai liste personale sau sincronizează din nou[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)

    xbmcplugin.endOfDirectory(HANDLE)


def tmdb_watchlist_menu():
    add_directory("Movies Watchlist", {'mode': 'tmdb_watchlist', 'type': 'movie'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("TV Shows Watchlist", {'mode': 'tmdb_watchlist', 'type': 'tv'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def tmdb_favorites_menu():
    add_directory("Movies Favorites", {'mode': 'tmdb_favorites', 'type': 'movie'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("TV Shows Favorites", {'mode': 'tmdb_favorites', 'type': 'tv'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def tmdb_recommendations_menu():
    add_directory("Movies Recommendations", {'mode': 'tmdb_account_recommendations', 'type': 'movie'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("TV Shows Recommendations", {'mode': 'tmdb_account_recommendations', 'type': 'tv'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def tmdb_account_recommendations(params):
    content_type = params.get('type', 'movie')
    page = int(params.get('page', '1'))
    
    # 1. Încercăm SQL
    results = trakt_sync.get_recommendations_from_db(content_type)
    
    # 2. Fallback: dacă SQL e gol, forțăm sync și reîncărcăm
    if not results:
        try:
            log("[TMDB] Recommendations goale în SQL, forțăm sync...")
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            trakt_sync._sync_tmdb_recommendations_fast(c)
            conn.commit()
            conn.close()
            
            # Reîncărcăm după sync
            results = trakt_sync.get_recommendations_from_db(content_type)
        except Exception as e:
            log(f"[TMDB] Eroare sync recommendations: {e}", xbmc.LOGERROR)
    
    if not results:
        add_directory("[COLOR gray]Nu sunt recomandări disponibile[/COLOR]", {'mode': 'noop'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total_pages = paginate_list(results, page, PAGE_LIMIT)
    
    for item in paginated:
        if content_type == 'movie': 
            _process_movie_item(item)
        else: 
            _process_tv_item(item)
    
    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]", 
            {'mode': 'tmdb_account_recommendations', 'type': content_type, 'page': str(page+1)}, 
            folder=True
        )
    
    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def fetch_tmdb_list_items_all(list_id):
    all_items = []
    page = 1
    while True:
        url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&language={LANG}&page={page}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get('items', [])
            if not items:
                break
            all_items.extend(items)
            if len(items) < 20: 
                break
            page += 1
            if page > 100: 
                break
        except Exception as e:
            log(f"[TMDB] Error fetching list items for {list_id}: {e}", xbmc.LOGERROR)
            break
    return all_items


def tmdb_list_items(params):
    list_id = params.get('list_id')
    list_name = params.get('list_name', '')
    page = int(params.get('page', '1'))
    
    items_raw = trakt_sync.get_tmdb_custom_list_items_from_db(list_id)
    
    if not items_raw:
        string = f"tmdb_list_full_{list_id}"
        items = cache_object(fetch_tmdb_list_items_all, string, list_id, json_output=False, expiration=24)
        if items:
            conn = trakt_sync.get_connection()
            trakt_sync._sync_single_tmdb_custom_list_items(conn.cursor(), list_id, items)
            conn.commit()
            conn.close()
    else:
        items = items_raw

    if not items:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total = paginate_list(items, page, PAGE_LIMIT)
    for item in paginated:
        m_type = item.get('media_type', 'movie') 
        if m_type == 'movie': _process_movie_item(item)
        else: _process_tv_item(item)

    if page < total:
        add_directory(f"[COLOR yellow]Next Page ({page+1}) >>[/COLOR]", {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': list_name, 'page': str(page+1)}, icon='DefaultFolder.png', folder=True)
    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE)


def clear_list_cache(params):
    list_id = params.get('list_id')
    cache = MainCache()
    cache.delete(f"tmdb_list_full_{list_id}") 
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "List Cache Cleared!", TMDbmovies_ICON, 3000, False)
    xbmc.executebuiltin("Container.Refresh")


def get_tmdb_account_list(endpoint, page_no, session):
    url = f"{BASE_URL}/account/{session['account_id']}/{endpoint}?api_key={API_KEY}&session_id={session['session_id']}&language={LANG}&page={page_no}&sort_by=created_at.desc"
    return requests.get(url, timeout=10)


def tmdb_watchlist(params):
    content_type = params.get('type')
    page = int(params.get('page', '1'))
    
    results_raw = trakt_sync.get_tmdb_account_list_from_db('watchlist', content_type)
    
    if not results_raw:
        session = get_tmdb_session()
        if not session: 
            xbmcplugin.endOfDirectory(HANDLE)
            return

        endpoint = f"watchlist/{'movies' if content_type == 'movie' else 'tv'}"
        string = f"tmdb_watchlist_{content_type}_{page}"
        data = cache_object(get_tmdb_account_list, string, [endpoint, page, session], expiration=1) 
        if data: 
            results = data.get('results', [])
            conn = trakt_sync.get_connection()
            trakt_sync._sync_tmdb_account_list_single(conn.cursor(), 'watchlist', content_type, results)
            conn.commit()
            conn.close()
        else:
            results = []
    else:
        results = results_raw

    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total = paginate_list(results, page, PAGE_LIMIT)
    
    for item in paginated:
        if content_type == 'movie': _process_movie_item(item)
        else: _process_tv_item(item)

    if page < total:
        add_directory(f"[COLOR yellow]Next Page ({page+1}) >>[/COLOR]", {'mode': 'tmdb_watchlist', 'type': content_type, 'page': str(page+1)}, icon='DefaultFolder.png', folder=True)
    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)

def tmdb_favorites(params):
    content_type = params.get('type')
    page = int(params.get('page', '1'))
    
    results_raw = trakt_sync.get_tmdb_account_list_from_db('favorite', content_type)
    
    if not results_raw:
        session = get_tmdb_session()
        if not session: 
            xbmcplugin.endOfDirectory(HANDLE)
            return

        endpoint = f"favorite/{'movies' if content_type == 'movie' else 'tv'}"
        string = f"tmdb_favorites_{content_type}_{page}"
        data = cache_object(get_tmdb_account_list, string, [endpoint, page, session], expiration=1) 
        if data: 
            results = data.get('results', [])
            conn = trakt_sync.get_connection()
            trakt_sync._sync_tmdb_account_list_single(conn.cursor(), 'favorite', content_type, results)
            conn.commit()
            conn.close()
        else:
            results = []
    else:
        results = results_raw

    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    paginated, total = paginate_list(results, page, PAGE_LIMIT)
    
    for item in paginated:
        if content_type == 'movie': _process_movie_item(item)
        else: _process_tv_item(item)

    if page < total:
        add_directory(f"[COLOR yellow]Next Page ({page+1}) >>[/COLOR]", {'mode': 'tmdb_favorites', 'type': content_type, 'page': str(page+1)}, icon='DefaultFolder.png', folder=True)
    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def add_to_tmdb_watchlist(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", xbmcgui.NOTIFICATION_WARNING)
        return False

    url = f"{BASE_URL}/account/{session['account_id']}/watchlist?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'watchlist': True}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Adăugat în [B][COLOR FF00CED1]Watchlist[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            return True
    except:
        pass
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare", xbmcgui.NOTIFICATION_ERROR)
    return False


def remove_from_tmdb_watchlist(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        return False

    url = f"{BASE_URL}/account/{session['account_id']}/watchlist?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'watchlist': False}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din [B][COLOR FF00CED1]Watchlist[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass
    return False


def add_to_tmdb_favorites(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", TMDB_ICON, 3000, False)
        return False

    url = f"{BASE_URL}/account/{session['account_id']}/favorite?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'favorite': True}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Adăugat la [B][COLOR FF00CED1]Favorite[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            return True
    except:
        pass
    return False


def remove_from_tmdb_favorites(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        return False

    url = f"{BASE_URL}/account/{session['account_id']}/favorite?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'favorite': False}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din [B][COLOR FF00CED1]Favorite[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass
    return False


def add_to_tmdb_list(list_id, tmdb_id):
    session = get_tmdb_session()
    if not session:
        return False

    url = f"{BASE_URL}/list/{list_id}/add_item?api_key={API_KEY}&session_id={session['session_id']}"
    try:
        r = requests.post(url, json={'media_id': int(tmdb_id)}, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Adăugat în listă", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            return True
    except:
        pass
    return False


def remove_from_tmdb_list(list_id, tmdb_id):
    session = get_tmdb_session()
    if not session:
        return False

    url = f"{BASE_URL}/list/{list_id}/remove_item?api_key={API_KEY}&session_id={session['session_id']}"
    try:
        r = requests.post(url, json={'media_id': int(tmdb_id)}, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din listă", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass
    return False


def is_in_tmdb_watchlist(tmdb_id, content_type):
    return trakt_sync.is_in_tmdb_account_list('watchlist', content_type, tmdb_id)


def is_in_tmdb_favorites(tmdb_id, content_type):
    return trakt_sync.is_in_tmdb_account_list('favorite', content_type, tmdb_id)


def get_tmdb_user_lists():
    session = get_tmdb_session()
    if not session:
        return []

    url = f"{BASE_URL}/account/{session['account_id']}/lists?api_key={API_KEY}&session_id={session['session_id']}"
    try:
        data = get_json(url)
        return data.get('results', [])
    except:
        return []


def show_tmdb_context_menu(tmdb_id, content_type, title=''):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", xbmcgui.NOTIFICATION_WARNING)
        return

    options = []
    
    in_watchlist = is_in_tmdb_watchlist(tmdb_id, content_type)
    if in_watchlist:
        options.append(('Remove from [B][COLOR FF00CED1]Watchlist[/COLOR][/B]', 'remove_watchlist'))
    else:
        options.append(('Add to [B][COLOR FF00CED1]Watchlist[/COLOR][/B]', 'add_watchlist'))

    in_favorites = is_in_tmdb_favorites(tmdb_id, content_type)
    if in_favorites:
        options.append(('Remove from [B][COLOR FF00CED1]Favorites[/COLOR][/B]', 'remove_favorites'))
    else:
        options.append(('Add to [B][COLOR FF00CED1]Favorites[/COLOR][/B]', 'add_favorites'))

    options.append(('Add to [B][COLOR FF00CED1]My Lists[/COLOR][/B]', 'add_to_list'))
    options.append(('Remove from [B][COLOR FF00CED1]My Lists[/COLOR][/B]', 'remove_from_list'))

    options.append(('Add [B][COLOR FF00CED1]Rating[/COLOR][/B]', 'rate_item'))

    dialog = xbmcgui.Dialog()
    display_options = [opt[0] for opt in options]
    ret = dialog.contextmenu(display_options)

    if ret < 0:
        return

    action = options[ret][1]

    if action == 'add_watchlist':
        if add_to_tmdb_watchlist(content_type, tmdb_id):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'remove_watchlist':
        if remove_from_tmdb_watchlist(content_type, tmdb_id):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'add_favorites':
        if add_to_tmdb_favorites(content_type, tmdb_id):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'remove_favorites':
        if remove_from_tmdb_favorites(content_type, tmdb_id):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'add_to_list':
        show_tmdb_add_to_list_dialog(tmdb_id, content_type)
    elif action == 'remove_from_list':
        show_tmdb_remove_from_list_dialog(tmdb_id, content_type)
    elif action == 'rate_item':
        if rate_tmdb_item(tmdb_id, content_type):
            xbmc.executebuiltin("Container.Refresh")


def show_tmdb_add_to_list_dialog(tmdb_id, content_type):
    lists = trakt_sync.get_tmdb_custom_lists_from_db() 
    if not lists:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ai liste", TMDB_ICON, 3000, False)
        return

    display_items = []
    for lst in lists:
        raw_name = lst.get('name', 'Unknown')
        styled_name = f"[B][COLOR FF00CED1]{raw_name}[/COLOR][/B]"
        li = xbmcgui.ListItem(styled_name)
        li.setLabel2(f"[B][COLOR yellow]{lst.get('item_count', 0)}[/COLOR][/B] items")
        poster = lst.get('poster', '')
        if poster:
            li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        else:
            li.setArt({'thumb': TMDB_ICON, 'icon': TMDB_ICON})
        display_items.append(li)

    dialog = xbmcgui.Dialog()
    ret = dialog.select("[B][COLOR FF00CED1]TMDB[/COLOR][/B]: Add to List", display_items, useDetails=True)

    if ret >= 0:
        selected_list = lists[ret]
        add_to_tmdb_list(selected_list['list_id'], tmdb_id)


def show_tmdb_remove_from_list_dialog(tmdb_id, content_type):
    lists = trakt_sync.get_tmdb_custom_lists_from_db() 
    if not lists:
        return

    lists_with_item = []
    for lst in lists:
        list_id = lst.get('list_id')
        if trakt_sync.is_in_tmdb_custom_list(list_id, tmdb_id):
            lists_with_item.append(lst)

    if not lists_with_item:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu e în nicio listă", TMDB_ICON, 3000, False)
        return

    display_items = []
    for lst in lists_with_item:
        raw_name = lst.get('name', 'Unknown')
        styled_name = f"[B][COLOR FF00CED1]{raw_name}[/COLOR][/B]"
        li = xbmcgui.ListItem(styled_name)
        li.setLabel2(f"[B][COLOR yellow]{lst.get('item_count', 0)}[/COLOR][/B] items")
        poster = lst.get('poster', '')
        if poster:
            li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        else:
            li.setArt({'thumb': TMDB_ICON, 'icon': TMDB_ICON})
        display_items.append(li)

    dialog = xbmcgui.Dialog()
    ret = dialog.select("Remove from List", display_items, useDetails=True)

    if ret >= 0:
        selected_list = lists_with_item[ret]
        remove_from_tmdb_list(selected_list['list_id'], tmdb_id)


def add_favorite(params):
    favs = read_json(FAVORITES_FILE)
    if not favs:
        favs = {'movie': [], 'tv': []}

    c_type = params.get('type')
    tmdb_id = params.get('tmdb_id')
    title = params.get('title', '')

    if c_type not in favs:
        favs[c_type] = []

    for f in favs[c_type]:
        if str(f.get('tmdb_id')) == str(tmdb_id):
            xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Deja în favorite", TMDbmovies_ICON, 2000, False)
            return

    new_item = {
        'tmdb_id': tmdb_id,
        'title': title,
        'added': time.strftime('%Y-%m-%d %H:%M:%S')
    }

    favs[c_type].insert(0, new_item)
    write_json(FAVORITES_FILE, favs)
    xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", f"Adăugat: [B][COLOR yellow]{title}[/COLOR][/B]", TMDbmovies_ICON, 2000, False)


def remove_favorite(params):
    favs = read_json(FAVORITES_FILE)
    if not favs:
        return

    c_type = params.get('type')
    tmdb_id = params.get('tmdb_id')

    if c_type not in favs:
        return

    initial_len = len(favs[c_type])
    favs[c_type] = [f for f in favs[c_type] if str(f.get('tmdb_id')) != str(tmdb_id)]

    if len(favs[c_type]) < initial_len:
        write_json(FAVORITES_FILE, favs)
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Șters din favorite", TMDbmovies_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")


def list_favorites(content_type):
    favs = read_json(FAVORITES_FILE)
    
    if not favs or not isinstance(favs, dict):
        favs = {'movie': [], 'tv': []}
    
    items = favs.get(content_type, [])
    local_items = [f for f in items if f.get('added')]

    if not local_items:
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Lista e goală", TMDbmovies_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    for fav in local_items:
        tmdb_id = fav.get('tmdb_id')
        if not tmdb_id:
            continue

        endpoint = 'movie' if content_type == 'movie' else 'tv'
        data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, endpoint)
        if not data:
            url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
            data = get_json(url)
            if data:
                conn = trakt_sync.get_connection()
                trakt_sync.set_tmdb_item_details_to_db(conn.cursor(), tmdb_id, endpoint, data)
                conn.commit()
                conn.close()

        if data:
            if content_type == 'movie':
                _process_movie_item(data, is_in_favorites_view=True)
            else:
                _process_tv_item(data, is_in_favorites_view=True)

    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)

def show_details(tmdb_id, content_type):
    xbmcplugin.setContent(HANDLE, 'seasons')

    string = f"tv_details_{tmdb_id}_{LANG}"
    
    data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, content_type)
    if not data:
        url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={LANG}"
        def get_details_worker(u):
            return requests.get(u, timeout=10)
        data = cache_object(get_details_worker, string, url, expiration=168)
        if data:
            conn = trakt_sync.get_connection()
            trakt_sync.set_tmdb_item_details_to_db(conn.cursor(), tmdb_id, content_type, data)
            conn.commit()
            conn.close()

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    poster = f"{IMG_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else ''
    backdrop = f"{BACKDROP_BASE}{data.get('backdrop_path', '')}" if data.get('backdrop_path') else ''
    tv_title = data.get('name', '')
    
    # --- INCEPUT COD MODIFICAT (SALVARE PLOT PRINCIPAL) ---
    # Salvam descrierea principala a serialului pentru a o folosi daca sezonul nu are descriere
    main_show_plot = data.get('overview', '')
    # --- SFARSIT COD MODIFICAT ---
    
    # Studio Show
    studio = ''
    if data.get('networks'):
        studio = data['networks'][0].get('name', '')

    from resources.lib import trakt_api

    for s in data.get('seasons', []):
        s_num = s['season_number']
        if s_num == 0:
            continue

        name = f"Season {s_num}"
        ep_count = s.get('episode_count', 0)
        s_poster = f"{IMG_BASE}{s.get('poster_path', '')}" if s.get('poster_path') else poster
        
        # Data lansare sezon
        premiered = s.get('air_date', '')

        # --- INCEPUT COD MODIFICAT (FALLBACK PLOT SEZON) ---
        # Verificam daca sezonul are descriere. Daca nu, punem descrierea serialului.
        season_plot = s.get('overview', '')
        if not season_plot:
            season_plot = main_show_plot
        # --- SFARSIT COD MODIFICAT ---

        watched_count = trakt_api.get_watched_counts(tmdb_id, 'season', s_num)
        watched_info = {'watched': watched_count, 'total': ep_count}

        info = {
            'mediatype': 'season',
            'title': name,
            # Folosim variabila calculata mai sus
            'plot': season_plot,
            'tvshowtitle': tv_title,
            'season': s_num,
            'premiered': premiered,
            'studio': studio # Mostenim studioul serialului
        }

        add_directory(
            name,
            {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(s_num), 'tv_show_title': tv_title},
            thumb=s_poster, fanart=backdrop, info=info, watched_info=watched_info, folder=True
        )

    xbmcplugin.endOfDirectory(HANDLE)


def list_episodes(tmdb_id, season_num, tv_show_title):
    from resources.lib import trakt_sync
    from resources.lib import trakt_api
    xbmcplugin.setContent(HANDLE, 'episodes')

    string = f"tv_episodes_{tmdb_id}_{season_num}_{LANG}"
    
    data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, season_num)
    if not data:
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language={LANG}"
        def get_eps_worker(u):
            return requests.get(u, timeout=10)
        data = cache_object(get_eps_worker, string, url, expiration=168)
        if data:
            conn = trakt_sync.get_connection()
            trakt_sync.set_tmdb_season_details_to_db(conn.cursor(), tmdb_id, season_num, data)
            conn.commit()
            conn.close()

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # --- FIX: Definim posterul sezonului inainte de a parcurge episoadele ---
    poster = f"{IMG_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else ''
    # ------------------------------------------------------------------------
    
    from resources.lib import trakt_api

    for ep in data.get('episodes', []):
        ep_num = ep['episode_number']
        
        # --- CALCUL RESUME (SUPORTĂ FORMAT NOU: POZIȚIE ÎN SECUNDE) ---
        original_ep_name = ep.get('name', '')
        name = f"{ep_num}. {original_ep_name}"
        
        from resources.lib import trakt_sync
        progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'tv', season_num, ep_num)
        resume_percent = 0
        resume_seconds = 0
        
        # Detectăm formatul: poziție (>= 1000000) sau procent (<100)
        if progress_value >= 1000000:
            # Format nou: poziție în secunde
            resume_seconds = int(progress_value - 1000000)
        elif progress_value > 0 and progress_value < 95:
            # Format vechi: procent
            resume_percent = progress_value
        # --- SFARSIT ---

        thumb = f"{IMG_BASE}{ep.get('still_path', '')}" if ep.get('still_path') else ''

        is_watched = trakt_api.check_episode_watched(tmdb_id, season_num, ep_num)
        
        # Durata episod (runtime)
        duration = ep.get('runtime', 0)
        if duration:
            duration = int(duration) * 60

        # ============================================================
        # CALCULĂM resume_percent DIN resume_seconds (dacă e format nou)
        # ============================================================
        if resume_seconds > 0 and duration > 0:
            resume_percent = (resume_seconds / duration) * 100
        # ============================================================

        info = {
            'mediatype': 'episode',
            # --- INCEPUT COD CORECTAT (METADATA) ---
            'title': original_ep_name,
            'resume_percent': resume_percent, # Asta declanseaza cerculetul nativ al skin-ului
            # --- SFARSIT COD CORECTAT ---
            'plot': ep.get('overview', ''),
            'rating': ep.get('vote_average', 0),
            'premiered': ep.get('air_date', ''),
            'season': int(season_num),
            'episode': int(ep_num),
            'tvshowtitle': tv_show_title,
            'duration': duration,
            'votes': ep.get('vote_count', 0)
        }

        cm = trakt_api.get_watched_context_menu(tmdb_id, 'tv', season_num, ep_num)
        
        fav_params = urlencode({'mode': 'add_favorite', 'type': 'tv', 'tmdb_id': tmdb_id, 'title': tv_show_title})
        cm.append(('[COLOR yellow]Add TV Show to Favorites[/COLOR]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

        # --- MODIFICARE: CLEAR CACHE PENTRU EPISOD ---
        clear_ep_params = urlencode({
            'mode': 'clear_sources_context', 
            'tmdb_id': tmdb_id, 
            'type': 'tv', 
            'season': str(season_num), 
            'episode': str(ep_num),
            'title': f"{tv_show_title} S{season_num}E{ep_num}"
        })
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_ep_params})"))
        # -------------------------------
        
        # --- INCEPUT FIX RESUME ---
        url_params = {
            'mode': 'sources',
            'tmdb_id': tmdb_id,
            'type': 'tv',
            'season': str(season_num),
            'episode': str(ep_num),
            'title': ep.get('name', ''),
            'tv_show_title': tv_show_title
        }
        
        # Calculare resume
        resume_seconds = 0
        if resume_percent > 0 and resume_percent < 95 and duration > 0:
            resume_seconds = int((resume_percent / 100.0) * duration)
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(name)
        
        # Art
        li.setArt({'thumb': thumb, 'icon': thumb, 'poster': poster, 'fanart': thumb})
        
        # Metadata
        set_metadata(li, info, watched_info=is_watched)
        
        # SETARE RESUME EXPLICITĂ
        if resume_seconds > 0 and duration > 0:
            li.setProperty('resumetime', str(resume_seconds))
            li.setProperty('totaltime', str(duration))
        
        # Context menu
        if cm:
            li.addContextMenuItems(cm)
        
        # Adăugare
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        # --- SFARSIT FIX RESUME ---

    xbmcplugin.endOfDirectory(HANDLE)


def show_info_dialog(params):
    tmdb_id = params.get('tmdb_id')
    content_type = params.get('type')

    data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, content_type)
    if not data:
        # --- MODIFICARE: Am adaugat include_video_language ---
        url = f"{BASE_URL}/{content_type}/{tmdb_id}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=credits,videos,release_dates,external_ids"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare la încărcare", xbmcgui.NOTIFICATION_ERROR)
                return
            data = r.json()
            if data:
                conn = trakt_sync.get_connection()
                trakt_sync.set_tmdb_item_details_to_db(conn.cursor(), tmdb_id, content_type, data)
                conn.commit()
                conn.close()
        except Exception as e:
            log(f"[TMDB-INFO] Error: {e}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare conexiune", xbmcgui.NOTIFICATION_ERROR)
            return

    if not data:
        return 

    title = data.get('title') or data.get('name', 'Unknown')
    li = xbmcgui.ListItem(title)

    cast = []
    for p in data.get('credits', {}).get('cast', [])[:20]:
        if not p.get('name'):
            continue
        thumb = f"{IMG_BASE}{p['profile_path']}" if p.get('profile_path') else ''
        cast.append(xbmc.Actor(p['name'], p.get('character', ''), p.get('order', 0), thumb))

    # --- LOGICA TRAILER ---
    trailer_url = ''
    # Cautam intai trailer oficial, apoi orice clip
    videos = data.get('videos', {}).get('results', [])
    for v in videos:
        if v.get('site') == 'YouTube' and v.get('type') == 'Trailer':
            trailer_url = f"plugin://plugin.video.youtube/play/?video_id={v.get('key')}"
            break
    
    # Fallback: daca nu e trailer, luam primul clip
    if not trailer_url and videos:
        if videos[0].get('site') == 'YouTube':
            trailer_url = f"plugin://plugin.video.youtube/play/?video_id={videos[0].get('key')}"

    try:
        tag = li.getVideoInfoTag()
        tag.setMediaType('movie' if content_type == 'movie' else 'tvshow')
        tag.setTitle(title)
        tag.setPlot(data.get('overview', ''))

        if data.get('vote_average'):
            tag.setRating(float(data['vote_average']))
        if data.get('vote_count'):
            tag.setVotes(int(data['vote_count']))

        date_str = data.get('release_date') or data.get('first_air_date')
        if date_str:
            tag.setPremiered(date_str)
            try:
                tag.setYear(int(date_str[:4]))
            except:
                pass

        if data.get('genres'):
            tag.setGenres([g['name'] for g in data['genres']])

        if cast:
            tag.setCast(cast)

        dirs = [p['name'] for p in data.get('credits', {}).get('crew', []) if p.get('job') == 'Director']
        if dirs:
            tag.setDirectors(dirs)

        writers = [p['name'] for p in data.get('credits', {}).get('crew', []) if p.get('job') in ['Screenplay', 'Writer']]
        if writers:
            tag.setWriters(writers)

        if trailer_url:
            tag.setTrailer(trailer_url)

        if data.get('runtime'):
            tag.setDuration(int(data['runtime']) * 60)

        ext_ids = data.get('external_ids', {})
        unique_ids = {'tmdb': str(tmdb_id)}
        if ext_ids.get('imdb_id'):
            unique_ids['imdb'] = ext_ids['imdb_id']
        if ext_ids.get('tvdb_id'):
            unique_ids['tvdb'] = str(ext_ids['tvdb_id'])
        tag.setUniqueIDs(unique_ids)

    except Exception as e:
        log(f"[TMDB-INFO] Tag Error: {e}", xbmc.LOGERROR)

    art = {}
    if data.get('poster_path'):
        art['poster'] = f"{IMG_BASE}{data['poster_path']}"
        art['thumb'] = f"{IMG_BASE}{data['poster_path']}"
    if data.get('backdrop_path'):
        art['fanart'] = f"{BACKDROP_BASE}{data['backdrop_path']}"
    li.setArt(art)

    xbmcgui.Dialog().info(li)


def show_global_info(params):
    """
    Handler robust pentru meniul contextual global (Filme, Seriale, Sezoane, Episoade).
    """
    log(f"[GLOBAL-INFO] Params: {params}")

    tmdb_id = params.get('tmdb_id')
    imdb_id = params.get('imdb_id')
    tvdb_id = params.get('tvdb_id')
    
    # Tipuri posibile: movie, tv, season, episode
    content_type = params.get('type', 'movie')
    
    title = params.get('title', '') # Acesta va fi TV Show Title daca e serial
    year = params.get('year', '')
    season = params.get('season')
    episode = params.get('episode')

    # Validare ID
    if tmdb_id and (not str(tmdb_id).isdigit() or str(tmdb_id) == '0'): tmdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt'): imdb_id = None

    # 1. Găsirea ID-ului Principal (Film sau Serial)
    found_id = tmdb_id
    found_media = 'tv' if content_type in ['tv', 'season', 'episode'] else 'movie'

    # Dacă nu avem TMDb ID, îl căutăm
    if not found_id:
        # A. Căutare prin External IDs
        if imdb_id:
            url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
            data = get_json(url)
            if data.get('movie_results'):
                found_id = data['movie_results'][0]['id']; found_media = 'movie'
            elif data.get('tv_results'):
                found_id = data['tv_results'][0]['id']; found_media = 'tv'
            elif data.get('tv_episode_results'):
                # Dacă IMDb ID e direct de episod, luăm ID-ul serialului
                found_id = data['tv_episode_results'][0]['show_id']; found_media = 'tv'
        
        # B. Căutare prin TVDb
        if not found_id and tvdb_id and str(tvdb_id).isdigit():
            url = f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id"
            data = get_json(url)
            if data.get('tv_results'):
                found_id = data['tv_results'][0]['id']; found_media = 'tv'

        # C. Căutare prin Titlu (Fallback)
        if not found_id and title:
            clean_title = title.split('(')[0].strip()
            # Dacă căutăm un Sezon/Episod, căutăm de fapt Serialul (found_media e setat mai sus)
            url = f"{BASE_URL}/search/{found_media}?api_key={API_KEY}&query={quote(clean_title)}"
            
            # Adăugăm anul doar dacă e film sau serial (nu sezon, ca poate serialul e vechi)
            if year and str(year).isdigit() and content_type in ['movie', 'tv']:
                if found_media == 'movie': url += f"&primary_release_year={year}"
                else: url += f"&first_air_date_year={year}"
                    
            data = get_json(url)
            if data.get('results'):
                found_id = data['results'][0]['id']
                log(f"[GLOBAL-INFO] Found parent ID by title: {found_id}")

    # 2. Afișare Info
    if found_id:
        # Dacă e Sezon sau Episod, apelăm funcția specializată
        if content_type == 'season' and season:
            show_specific_info_dialog(found_id, 'season', season=season)
        elif content_type == 'episode' and season and episode:
            show_specific_info_dialog(found_id, 'episode', season=season, episode=episode)
        else:
            # Info standard (Film sau Serial întreg)
            show_info_dialog({'tmdb_id': str(found_id), 'type': found_media})
    else:
        import xbmcgui
        xbmcgui.Dialog().notification("TMDb Info", "Nu am identificat titlul", TMDbmovies_ICON, 3000, False)

def show_specific_info_dialog(tmdb_id, specific_type, season=1, episode=1):
    """
    Afișează info dialog pentru un Sezon sau Episod specific.
    """
    import xbmcgui
    
    url = ""
    # --- MODIFICARE: Adaugat include_video_language SI videos in append ---
    if specific_type == 'season':
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
    elif specific_type == 'episode':
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
    
    data = get_json(url)
    if not data:
        xbmcgui.Dialog().notification("TMDb Info", "Eroare detalii specifice", xbmcgui.NOTIFICATION_ERROR)
        return

    # Metadata mapping
    title = data.get('name', 'Unknown')
    overview = data.get('overview', '')
    
    # Fallback Plot de la Serial
    if not overview:
        try:
            show_data = get_json(f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={LANG}")
            if show_data:
                overview = show_data.get('overview', '')
        except:
            pass

    poster_path = data.get('poster_path') or data.get('still_path')
    
    # Construim ListItem
    li = xbmcgui.ListItem(title)
    tag = li.getVideoInfoTag()
    
    tag.setTitle(title)
    tag.setPlot(overview)
    tag.setMediaType(specific_type) 
    
    if 'air_date' in data and data['air_date']:
        tag.setPremiered(data['air_date'])
        try: tag.setYear(int(data['air_date'][:4]))
        except: pass
        
    if 'vote_average' in data: tag.setRating(float(data['vote_average']))
    if 'season_number' in data: tag.setSeason(int(data['season_number']))
    if 'episode_number' in data: tag.setEpisode(int(data['episode_number']))
    
    # --- LOGICA TRAILER (NOU) ---
    videos = data.get('videos', {}).get('results', [])
    trailer_url = ''
    for v in videos:
        if v.get('site') == 'YouTube' and v.get('type') == 'Trailer':
            trailer_url = f"plugin://plugin.video.youtube/play/?video_id={v.get('key')}"
            break
    if trailer_url:
        tag.setTrailer(trailer_url)
    # ----------------------------

    # Cast
    cast = []
    source_cast = data.get('guest_stars', []) + data.get('credits', {}).get('cast', [])
    for p in source_cast[:15]:
        thumb = f"{IMG_BASE}{p['profile_path']}" if p.get('profile_path') else ''
        cast.append(xbmc.Actor(p['name'], p.get('character', ''), p.get('order', 0), thumb))
    if cast:
        tag.setCast(cast)

    # Imagini
    art = {}
    if poster_path:
        full_poster = f"{IMG_BASE}{poster_path}"
        art['poster'] = full_poster
        art['thumb'] = full_poster
        art['icon'] = full_poster
        
    try:
        show_data = get_json(f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}")
        if show_data and show_data.get('backdrop_path'):
            art['fanart'] = f"{BACKDROP_BASE}{show_data['backdrop_path']}"
            if not art.get('poster') and show_data.get('poster_path'):
                art['poster'] = f"{IMG_BASE}{show_data['poster_path']}"
            tag.setTvShowTitle(show_data.get('name', ''))
    except: pass

    li.setArt(art)
    xbmcgui.Dialog().info(li)

def perform_search(params):
    """Cere input de la tastatură și caută."""
    search_type = params.get('type')
    dialog = xbmcgui.Dialog()
    query = dialog.input("Căutare...", type=xbmcgui.INPUT_ALPHANUM)

    if query:
        # Salvăm în istoric
        add_search_to_history(query, search_type)
        # Executăm căutarea
        build_search_result(search_type, query)

def perform_search_query(params):
    """Execută direct o căutare (folosită din istoric)."""
    search_type = params.get('type')
    query = params.get('query')
    
    if query:
        # Re-aducem în topul istoricului (opțional, dar util UX)
        add_search_to_history(query, search_type)
        build_search_result(search_type, query)

def get_tmdb_search_results(query, search_type, page):
    url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&language={LANG}&query={quote(query)}&page={page}"
    return requests.get(url, timeout=10)


def build_search_result(search_type, query):
    data = cache_object(get_tmdb_search_results, f"search_{search_type}_{query}_1", [query, search_type, 1], expiration=1)

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data.get('results', [])
    for item in results:
        if search_type == 'movie':
            _process_movie_item(item)
        else:
            _process_tv_item(item)

    xbmcplugin.setContent(HANDLE, 'movies' if search_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def list_recommendations(params):
    tmdb_id = params.get('tmdb_id')
    menu_type = params.get('menu_type', 'movie')
    page = int(params.get('page', '1'))

    endpoint = 'movie' if menu_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/recommendations?api_key={API_KEY}&language={LANG}&page={page}"

    data = get_json(url)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data.get('results', [])
    total_pages = min(data.get('total_pages', 1), 500)

    for item in results:
        if menu_type == 'movie':
            _process_movie_item(item)
        else:
            _process_tv_item(item)

    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {'mode': 'list_recommendations', 'tmdb_id': tmdb_id, 'menu_type': menu_type, 'page': str(page + 1)},
            folder=True
        )

    xbmcplugin.setContent(HANDLE, 'movies' if menu_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def tmdb_edit_list(params):
    list_id = params.get('list_id')
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Funcție în dezvoltare", TMDB_ICON, 3000, False)


def create_tmdb_list():
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", xbmcgui.NOTIFICATION_WARNING)
        return None

    dialog = xbmcgui.Dialog()
    list_name = dialog.input("Nume listă", type=xbmcgui.INPUT_ALPHANUM)
    if not list_name:
        return None

    description = dialog.input("Descriere (opțional)", type=xbmcgui.INPUT_ALPHANUM)

    url = f"{BASE_URL}/list?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {
        'name': list_name,
        'description': description,
        'language': LANG[:2]
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        result = r.json()

        if result.get('success'):
            list_id = result.get('list_id')
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"Listă creată: [B][COLOR yellow]{list_name}[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return list_id
        else:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare la creare", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[TMDB] Create List Error: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare conexiune", xbmcgui.NOTIFICATION_ERROR)

    return None


def delete_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirmare", "Sigur vrei să ștergi această listă?"):
        return False

    url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.delete(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Listă ștearsă", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare la ștergere", xbmcgui.NOTIFICATION_ERROR)
    return False


def clear_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirmare", "Sigur vrei să golești această listă?"):
        return False

    url = f"{BASE_URL}/list/{list_id}/clear?api_key={API_KEY}&session_id={session['session_id']}&confirm=true"

    try:
        r = requests.post(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Listă golită", TMDB_ICON, 3000, False)
            trakt_sync.sync_full_library(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass

    return False


def rate_tmdb_item(tmdb_id, content_type):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", xbmcgui.NOTIFICATION_WARNING)
        return False

    ratings = [str(i) for i in range(1, 11)]

    dialog = xbmcgui.Dialog()
    
    ret = dialog.contextmenu(ratings)

    if ret < 0:
        return False

    rating_value = float(ratings[ret])

    endpoint = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/rating?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.post(url, json={'value': rating_value}, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification(
                "[B][COLOR FF00CED1]TMDB[/COLOR][/B]", 
                f"Rating trimis: [B][COLOR yellow]{int(rating_value)}/10[/COLOR][/B]", 
                TMDB_ICON, 
                3000, 
                False
            )
            return True
    except:
        pass

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Eroare la rating", xbmcgui.NOTIFICATION_ERROR)
    return False


def delete_tmdb_rating(tmdb_id, content_type):
    session = get_tmdb_session()
    if not session:
        return False

    endpoint = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/rating?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.delete(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Rating șters", TMDB_ICON, 3000, False)
            return True
    except:
        pass

    return False


def get_similar_items(tmdb_id, content_type, page=1):
    endpoint = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/similar?api_key={API_KEY}&language={LANG}&page={page}"
    return get_json(url)


def get_recommendations_items(tmdb_id, content_type, page=1):
    endpoint = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/recommendations?api_key={API_KEY}&language={LANG}&page={page}"
    return get_json(url)


def refresh_container():
    xbmc.executebuiltin("Container.Refresh")


def go_back():
    xbmc.executebuiltin("Action(Back)")


def get_tmdb_item_details(tmdb_id, content_type):
    endpoint = 'movie' if content_type == 'movie' else 'tv'
    # --- MODIFICARE: Am adaugat include_video_language ---
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=credits,videos,external_ids,images"

    string = f"details_{content_type}_{tmdb_id}"

    def worker(u):
        return requests.get(u, timeout=10)

    data = cache_object(worker, string, url, expiration=168)
    if data:
        conn = trakt_sync.get_connection()
        trakt_sync.set_tmdb_item_details_to_db(conn.cursor(), tmdb_id, content_type, data)
        conn.commit()
        conn.close()
    return data


def check_tmdb_connection():
    try:
        url = f"{BASE_URL}/configuration?api_key={API_KEY}"
        r = requests.get(url, timeout=5)
        return r.status_code == 200
    except:
        return False


def get_watched_status_movie(tmdb_id):
    from resources.lib import trakt_api
    return trakt_api.get_watched_counts(tmdb_id, 'movie') > 0


def get_watched_status_season(tmdb_id, season_num):
    from resources.lib import trakt_api

    watched_count = trakt_api.get_watched_counts(tmdb_id, 'season', season_num)

    try:
        data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, season_num)
        if not data: 
            url = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language={LANG}"
            data = get_json(url)
            if data: 
                conn = trakt_sync.get_connection()
                trakt_sync.set_tmdb_season_details_to_db(conn.cursor(), tmdb_id, season_num, data)
                conn.commit()
                conn.close()

        total_eps = len(data.get('episodes', [])) if data else 0
    except:
        total_eps = 0

    return {'watched': watched_count, 'total': total_eps}


def export_local_favorites():
    favs = read_json(FAVORITES_FILE)
    if not favs:
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Nu ai favorite de exportat", TMDbmovies_ICON, 2000, False)
        return

    dialog = xbmcgui.Dialog()
    path = dialog.browseSingle(3, "Alege locația pentru export", 'files', '.json')

    if path:
        export_file = os.path.join(path, 'tmdbmovies_favorites_backup.json')
        write_json(export_file, favs)
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Export complet!", TMDbmovies_ICON, 2000, False)


def import_local_favorites():
    dialog = xbmcgui.Dialog()
    path = dialog.browseSingle(1, "Selectează fișierul de import", 'files', '.json')

    if path:
        try:
            imported = read_json(path)
            if imported:
                current = read_json(FAVORITES_FILE) or {'movie': [], 'tv': []}

                for c_type in ['movie', 'tv']:
                    existing_ids = {str(f.get('tmdb_id')) for f in current.get(c_type, [])}
                    for item in imported.get(c_type, []):
                        if str(item.get('tmdb_id')) not in existing_ids:
                            current[c_type].append(item)

                write_json(FAVORITES_FILE, current)
                xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Import complet!", TMDbmovies_ICON, 2000, False)
                xbmc.executebuiltin("Container.Refresh")
        except Exception as e:
            log(f"[IMPORT] Error: {e}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Eroare la import", TMDbmovies_ICON, 2000, False)


def debug_info():
    session = get_tmdb_session()
    from resources.lib import trakt_api
    trakt_token = trakt_api.get_trakt_token()

    info = []
    info.append(f"TMDB Connected: {'Yes' if session else 'No'}")
    if session:
        info.append(f"TMDB User: {session.get('username', 'N/A')}")

    info.append(f"Trakt Connected: {'Yes' if trakt_token else 'No'}")
    if trakt_token:
        info.append(f"Trakt User: {trakt_api.get_trakt_username()}")

    info.append(f"Language: {LANG}")
    info.append(f"Cache DB: {os.path.exists(os.path.join(ADDON.getAddonInfo('profile'), 'maincache.db'))}")
    info.append(f"Sync DB: {os.path.exists(trakt_sync.DB_PATH)}")

    dialog = xbmcgui.Dialog()
    dialog.textviewer("Debug Info", "\n".join(info))


def test_api_connection():
    results = []

    try:
        r = requests.get(f"{BASE_URL}/configuration?api_key={API_KEY}", timeout=5)
        results.append(f"TMDB API: {'OK' if r.status_code == 200 else 'FAIL'}")
    except:
        results.append("TMDB API: FAIL (timeout)")

    try:
        from resources.lib import trakt_api
        headers = trakt_api.get_trakt_headers()
        r = requests.get(f"{trakt_api.TRAKT_API_URL}/movies/trending", headers=headers, timeout=5)
        results.append(f"Trakt API: {'OK' if r.status_code == 200 else 'FAIL'}")
    except:
        results.append("Trakt API: FAIL (timeout)")

    xbmcgui.Dialog().ok("API Test", "\n".join(results))

# =============================================================================
# FUNCȚII IN PROGRESS (Corectate)
# =============================================================================

def _get_poster_path(tmdb_id, media_type):
    cached_poster = trakt_sync.get_poster_from_db(tmdb_id, media_type)
    if cached_poster:
        return cached_poster.replace(IMG_BASE, '').replace(BACKDROP_BASE, '')

    import requests
    def worker(u): return requests.get(u, timeout=5)
    string = f"meta_poster_{media_type}_{tmdb_id}_{LANG}"
    url = f"{BASE_URL}/{media_type}/{tmdb_id}?api_key={API_KEY}&language={LANG}"
    data = cache_object(worker, string, url, expiration=168)
    if data and data.get('poster_path'):
        full_poster_url = f"{IMG_BASE}{data.get('poster_path')}"
        trakt_sync.set_poster_to_db(tmdb_id, media_type, full_poster_url)
        return data.get('poster_path')
    return ''


def in_progress_movies(params):
    """Afișează filmele cu resume point + PLOT + METADATA COMPLETE."""
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    
    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'player.png')
    except: icon = 'DefaultIcon.png'
    
    page = int(params.get('page', '1'))
    all_results = trakt_sync.get_in_progress_movies_from_db()
    
    if not all_results:
        add_directory("[COLOR cyan]Nu ai filme începute. Sincronizează Trakt.[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    results, total_pages = paginate_list(all_results, page, PAGE_LIMIT)
        
    for item in results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        title = item.get('title', 'Unknown')
        year = str(item.get('year', ''))
        progress = float(item.get('progress', 0))
        
        # --- MODIFICARE: Obtinem detaliile complete pentru PLOT și METADATE ---
        details = get_tmdb_item_details(tmdb_id, 'movie')
        
        plot = item.get('overview', '')
        poster_path_api = ''
        
        # Variabile pentru metadate
        rating = 0
        votes = 0
        premiered = ''
        studio = ''
        duration = 0

        if details:
            plot = details.get('overview', plot)
            poster_path_api = details.get('poster_path', '')
            
            # Extragem metadatele
            rating = details.get('vote_average', 0)
            votes = details.get('vote_count', 0)
            premiered = details.get('release_date', '')
            
            if details.get('production_companies'):
                studio = details['production_companies'][0].get('name', '')
                
            dur_mins = details.get('runtime', 0)
            if dur_mins:
                duration = int(dur_mins) * 60 # Convertim in secunde

        # Imagine
        poster_path_db = _get_poster_path(tmdb_id, 'movie')
        if poster_path_db:
             poster = f"{IMG_BASE}{poster_path_db}"
        elif poster_path_api:
             poster = f"{IMG_BASE}{poster_path_api}"
        else:
             poster = icon

        # Construim plot-ul combinat
        display_plot = f"[B]Progres: {int(progress)}%[/B]\n\n{plot}"

        info = {
            'mediatype': 'movie',
            'title': title,
            'year': year,
            'plot': display_plot,
            'resume_percent': progress,
            'rating': rating,
            'votes': votes,
            'premiered': premiered,
            'studio': studio,
            'duration': duration
        }
        
        cm = _get_full_context_menu(tmdb_id, 'movie', title)
        
        cm.append(('[B][COLOR lime]Mark Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=movie)"))
        cm.append(('[B][COLOR red]Remove from In Progress[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=remove_progress&tmdb_id={tmdb_id}&type=movie)"))

        # --- INCEPUT FIX RESUME ---
        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
        
        # Calculare resume
        resume_seconds = 0
        if progress > 0 and duration > 0:
            resume_seconds = int((progress / 100.0) * duration)
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(f"{title} ({year})")
        
        # Art
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster})
        
        # Metadata
        set_metadata(li, info, watched_info=False)
        
        # SETARE RESUME EXPLICITĂ (CRUCIAL pentru cerculeț!)
        if resume_seconds > 0 and duration > 0:
            li.setProperty('resumetime', str(resume_seconds))
            li.setProperty('totaltime', str(duration))
        
        # Context menu
        if cm:
            li.addContextMenuItems(cm)
        
        # Adăugare
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        # --- SFARSIT FIX RESUME ---
    
    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {'mode': 'in_progress_movies', 'page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE)



def in_progress_tvshows(params):
    """Afișează serialele cu PLOT și METADATA COMPLETE."""
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    
    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'in_progress_tvshow.png')
    except: icon = 'DefaultIcon.png'
    
    page = int(params.get('page', '1'))
    all_results = trakt_sync.get_in_progress_tvshows_from_db()
    
    if not all_results:
        add_directory("[COLOR cyan]Nu ai seriale în progres. Sincronizează Trakt.[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    valid_items = []
    
    for item in all_results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        # --- MODIFICARE: Fetch detalii pentru PLOT și METADATE ---
        details = get_tmdb_item_details(tmdb_id, 'tv')
        item['overview'] = details.get('overview', '') if details else ''
        
        # Salvam metadatele in dictionarul item pentru a le folosi mai jos
        if details:
            item['rating'] = details.get('vote_average', 0)
            item['votes'] = details.get('vote_count', 0)
            item['premiered'] = details.get('first_air_date', '')
            
            if details.get('networks'):
                item['studio'] = details['networks'][0].get('name', '')
            
            runtimes = details.get('episode_run_time', [])
            if runtimes:
                item['duration'] = int(runtimes[0]) * 60
        
        # Logica existenta de filtrare
        try: total_eps = int(item.get('total_eps', 0))
        except: total_eps = 0
        
        if total_eps == 0 and details:
             total_eps = details.get('number_of_episodes', 0)
             item['total_eps'] = total_eps
             trakt_sync.set_tv_meta_to_db(tmdb_id, total_eps)

        watched_eps = int(item.get('watched_eps', 0))
        if total_eps > 0 and watched_eps >= total_eps:
            continue
            
        valid_items.append(item)

    results, total_pages = paginate_list(valid_items, page, PAGE_LIMIT)
        
    for item in results:
        tmdb_id = item['tmdb_id']
        name = item.get('name')
        year = str(item.get('first_air_date', ''))[:4]
        plot = item.get('overview', '') 
        
        curr_watched = item.get('watched_eps', 0)
        curr_total = item.get('total_eps', 0)

        if curr_total > 0:
            progress_pct = int((curr_watched / curr_total) * 100)
            display_total = str(curr_total)
        else:
            progress_pct = 0
            display_total = "?"
        
        poster_path = _get_poster_path(tmdb_id, 'tv')
        poster = f"{IMG_BASE}{poster_path}" if poster_path else icon

        info = {
            'mediatype': 'tvshow',
            'title': name,
            'year': year,
            'plot': f"[B]Vizionat: {curr_watched}/{display_total} ({progress_pct}%)[/B]\n\n{plot}",
            'tvshowtitle': name,
            'rating': item.get('rating', 0),
            'votes': item.get('votes', 0),
            'premiered': item.get('premiered', ''),
            'studio': item.get('studio', ''),
            'duration': item.get('duration', 0)
        }
        
        watched_info = {'watched': curr_watched, 'total': curr_total}
        cm = _get_full_context_menu(tmdb_id, 'tv', name)

        label = f"{name} ({year})" if year else name
        label += f" [COLOR gray]({curr_watched}/{display_total})[/COLOR]"

        add_directory(
            label,
            {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': name},
            icon=poster, thumb=poster, info=info, cm=cm,
            watched_info=watched_info, folder=True
        )
    
    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {'mode': 'in_progress_tvshows', 'page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def in_progress_episodes(params):
    """Afișează episoadele cu PLOT și METADATA COMPLETE."""
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    
    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'player.png')
    except: icon = 'DefaultIcon.png'
    
    page = int(params.get('page', '1'))
    all_results = trakt_sync.get_in_progress_episodes_from_db()
    
    if not all_results:
        add_directory("[COLOR cyan]Nu ai episoade începute. Sincronizează Trakt.[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    results, total_pages = paginate_list(all_results, page, PAGE_LIMIT)
        
    for item in results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        season = int(item.get('season', 0))
        episode = int(item.get('episode', 0))
        title = item.get('title') or item.get('name', 'Unknown')
        progress = float(item.get('progress', 0))
        
        # Variabile metadate
        ep_plot = ''
        rating = 0
        premiered = ''
        duration = 0
        studio = ''

        # 1. Luăm datele SERIALULUI pentru STUDIO (pentru că ep nu are studio direct)
        show_details = get_tmdb_item_details(tmdb_id, 'tv')
        if show_details and show_details.get('networks'):
            studio = show_details['networks'][0].get('name', '')

        # 2. Luăm datele SEZONULUI pentru detalii EPISOD (rating, durata, data)
        season_data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, season)
        
        if not season_data:
            import requests
            url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}"
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    season_data = r.json()
                    conn = trakt_sync.get_connection()
                    trakt_sync.set_tmdb_season_details_to_db(conn.cursor(), tmdb_id, season, season_data)
                    conn.commit()
                    conn.close()
            except: pass

        if season_data:
            for ep in season_data.get('episodes', []):
                if ep.get('episode_number') == episode:
                    ep_plot = ep.get('overview', '')
                    if 'Unknown' in title or 'Episode' in title:
                        title = f"{ep.get('name', title)}"
                    
                    # Extragem metadatele episodului
                    rating = ep.get('vote_average', 0)
                    premiered = ep.get('air_date', '')
                    
                    dur_mins = ep.get('runtime', 0)
                    if dur_mins:
                        duration = int(dur_mins) * 60
                    break

        poster_path = _get_poster_path(tmdb_id, 'tv') 
        poster = f"{IMG_BASE}{poster_path}" if poster_path else icon
        
        show_title = title.split(' - ')[0] if ' - ' in title else "TV Show"
        
        info = {
            'mediatype': 'episode',
            'title': title,
            'plot': f"[B]Progres: {int(progress)}%[/B]\n\n{ep_plot}",
            'tvshowtitle': show_title,
            'season': season,
            'episode': episode,
            'resume_percent': progress,
            'rating': rating,
            'premiered': premiered,
            'duration': duration,
            'studio': studio # Acum avem si studioul
        }
        
        cm = [
            ('[B][COLOR lime]Mark Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})"),
            ('[B][COLOR red]Remove from In Progress[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=remove_progress&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})")
        ]
        
        cm.append(('[B][COLOR FFFDBD01]TMDb Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_info&tmdb_id={tmdb_id}&type=tv)"))

        # --- MODIFICARE: CLEAR CACHE ---
        clear_p_params = urlencode({
            'mode': 'clear_sources_context', 
            'tmdb_id': tmdb_id, 
            'type': 'tv', 
            'season': str(season), 
            'episode': str(episode),
            'title': title
        })
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
        # -------------------------------
        
        # --- INCEPUT FIX RESUME ---
        url_params = {
            'mode': 'sources',
            'tmdb_id': tmdb_id,
            'type': 'tv',
            'season': str(season),
            'episode': str(episode),
            'title': title
        }
        
        # Calculare resume
        resume_seconds = 0
        if progress > 0 and duration > 0:
            resume_seconds = int((progress / 100.0) * duration)
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(title)
        
        # Art
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster})
        
        # Metadata
        set_metadata(li, info, watched_info=False)
        
        # SETARE RESUME EXPLICITĂ
        if resume_seconds > 0 and duration > 0:
            li.setProperty('resumetime', str(resume_seconds))
            li.setProperty('totaltime', str(duration))
        
        # Context menu
        if cm:
            li.addContextMenuItems(cm)
        
        # Adăugare
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        # --- SFARSIT FIX RESUME ---
    
    if page < total_pages:
        add_directory(
            f"[COLOR yellow]Next Page ({page+1}/{total_pages}) >>[/COLOR]",
            {'mode': 'in_progress_episodes', 'page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE)