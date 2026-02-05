import sys
import datetime
from urllib.parse import parse_qsl, urlencode
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import client

# --- Setup ---
_HANDLE = int(sys.argv[1])
_BASE_URL = sys.argv[0]
_ARGS = dict(parse_qsl(sys.argv[2][1:]))
ADDON = xbmcaddon.Addon()
TITLES_RO = (ADDON.getSetting('titles_ro') == 'true')
PLOTS_RO = (ADDON.getSetting('plots_ro') == 'true')
TITLES_EN = (ADDON.getSetting('titles_english') == 'true')


# --- Lazy-loaded Global Data ---
_MOVIE_IDS = None
_TV_IDS = None
_EPISODE_INFO = None

def get_movie_ids():
    global _MOVIE_IDS
    if _MOVIE_IDS is None:
        _MOVIE_IDS = client.get_source_movie_ids()
    return _MOVIE_IDS

def get_tv_ids():
    global _TV_IDS
    if _TV_IDS is None:
        _TV_IDS = client.get_source_tv_ids()
    return _TV_IDS

def get_episode_info():
    global _EPISODE_INFO
    if _EPISODE_INFO is None:
        _EPISODE_INFO = client.get_source_episode_info()
    return _EPISODE_INFO

# --- Constants ---
ITEMS_PER_PAGE = 50
IMG_BASE_URL = "https://image.tmdb.org/t/p/"

# --- Refactored Helper Functions: Item Creation ---

def _create_base_list_item(title, params, info_data, art_data, is_folder, is_playable=False):
    li = xbmcgui.ListItem(title)
    if is_playable:
        li.setProperty('IsPlayable', 'true')

    # Info + artwork
    li.setInfo('video', {k: v for k, v in info_data.items() if not k.startswith('_')})
    li.setArt(art_data)

    # Optional cast
    cast_list = info_data.get('_cast') or []
    try:
        if cast_list:
            li.setCast(cast_list)
    except Exception:
        pass

    # Add ratings: TMDb as primary (if available). Votes optional.
    try:
        tmdb_rating = float(info_data.get('rating') or 0)
        tmdb_votes = int(info_data.get('votes') or 0)
        if tmdb_rating > 0:
            li.setRating('tmdb', tmdb_rating, votes=tmdb_votes, defaultt=True)
    except Exception:
        pass

    url = f"{_BASE_URL}?{urlencode(params)}"
    return url, li, is_folder

def _create_movie_item(details):
    # TOGGLE_APPLIED_MOVIE
    try:
        tmdb_id = details.get('id')
        # ensure we have both RO (base) and EN when needed
        en = None
        if (not TITLES_RO) or (not PLOTS_RO):
            en = client.get_movie_details_en(tmdb_id) if tmdb_id else None
        if not TITLES_RO:
            if en and (en.get('title') or en.get('original_title')):
                details = dict(details)
                details['title'] = en.get('title') or en.get('original_title') or details.get('title')
        if not PLOTS_RO:
            if en and en.get('overview'):
                details = dict(details)
                details['overview'] = en.get('overview')
    except Exception:
        pass
    # Ensure EN title + RO plot if setting enabled
    try:
        tmdb_id_for_en = details.get('id')
        if TITLES_EN and tmdb_id_for_en:
            en = client.get_movie_details_en(tmdb_id_for_en) or {}
            if en.get('title') or en.get('original_title'):
                details = dict(details)
                details['title'] = en.get('title') or en.get('original_title') or details.get('title')
    except Exception:
        pass
    if not details or not details.get('id') or not details.get('title'):
        return None

    tmdb_id = details['id']
    title = details['title']
    
    params = {'action': 'play', 'media_type': 'movie', 'tmdb_id': tmdb_id, 'title': title}
    info = {
        'title': title,
        'originaltitle': details.get('original_title'),
        'year': int(details.get('release_date', '0').split('-')[0]),
        'plot': details.get('overview'),
        'rating': details.get('vote_average'),
        'votes': details.get('vote_count', 0),
        'duration': details.get('runtime', 0) * 60,
        'genre': ' / '.join([g['name'] for g in details.get('genres', [])]),
        'mediatype': 'movie',
        'trailer': client.get_movie_trailer_url(tmdb_id) or f'plugin://plugin.video.themoviedb.helper/play/plugin/?type=trailer&tmdb_type=movie&tmdb_id={tmdb_id}',
    }

    art = {
        'poster': f"{IMG_BASE_URL}w500{details.get('poster_path')}" if details.get('poster_path') else '',
        'fanart': f"{IMG_BASE_URL}original{details.get('backdrop_path')}" if details.get('backdrop_path') else ''
    }

    # Build cast list
    credits = client.get_movie_credits_tmdb(tmdb_id)
    cast = []
    if credits and credits.get('cast'):
        for p in credits['cast'][:20]:
            cast.append({'name': p.get('name',''), 'role': p.get('character','') or '', 'thumbnail': f"{IMG_BASE_URL}w185{p.get('profile_path')}" if p.get('profile_path') else ''})
    info['_cast'] = cast
    
    return _create_base_list_item(title, params, info, art, is_folder=False, is_playable=True)

def _create_tv_show_item(details):
    # TOGGLE_APPLIED_TV
    try:
        tmdb_id = details.get('id')
        en = None
        if (not TITLES_RO) or (not PLOTS_RO):
            en = client.get_tv_details_en(tmdb_id) if tmdb_id else None
        if not TITLES_RO:
            if en and (en.get('name') or en.get('original_name')):
                details = dict(details)
                details['title'] = en.get('name') or en.get('original_name') or details.get('title')
                details['name'] = details['title']
        if not PLOTS_RO:
            if en and en.get('overview'):
                details = dict(details)
                details['overview'] = en.get('overview')
    except Exception:
        pass
    # Ensure EN name + RO plot if setting enabled
    try:
        tmdb_id_for_en = details.get('id')
        if TITLES_EN and tmdb_id_for_en:
            en = client.get_tv_details_en(tmdb_id_for_en) or {}
            if en.get('name') or en.get('original_name'):
                details = dict(details)
                details['title'] = en.get('name') or en.get('original_name') or details.get('title')
                details['name'] = details['title']
    except Exception:
        pass
    if not details or not details.get('id') or not details.get('name'):
        return None

    tmdb_id = details['id']
    title = details['name']

    # --- Cast (TV) ---
    try:
        credits = client.get_tv_credits_tmdb(tmdb_id) if tmdb_id else None
        cast = []
        if credits and credits.get('cast'):
            for p in credits['cast'][:20]:
                cast.append({
                    'name': p.get('name', ''),
                    'role': p.get('character', '') or '',
                    'thumbnail': f"{IMG_BASE_URL}w185{p.get('profile_path')}" if p.get('profile_path') else ''
                })
    except Exception:
        cast = []

    params = {'action': 'list_seasons', 'tv_show_id': tmdb_id, 'title': title}
    info = {
        'title': title,
        'originaltitle': details.get('original_name'),
        'year': int(details.get('first_air_date', '0').split('-')[0]),
        'plot': details.get('overview'),
        'rating': details.get('vote_average'),
        'votes': details.get('vote_count', 0),
        'genre': ' / '.join([g['name'] for g in details.get('genres', [])]),
        'mediatype': 'tvshow',
        'trailer': client.get_tv_trailer_url(tmdb_id) or f"plugin://plugin.video.themoviedb.helper/play/plugin/?type=trailer&tmdb_type=tv&tmdb_id={tmdb_id}",
    }
    info['_cast'] = cast
    art = {
        'poster': f"{IMG_BASE_URL}w500{details.get('poster_path')}" if details.get('poster_path') else '',
        'fanart': f"{IMG_BASE_URL}original{details.get('backdrop_path')}" if details.get('backdrop_path') else ''
    }

    return _create_base_list_item(title, params, info, art, is_folder=True)

def _create_season_item(tv_show_id, season_details):
    season_number = season_details.get('season_number')
    title = season_details.get('name', f"Season {season_number}")

    params = {'action': 'list_episodes', 'tv_show_id': tv_show_id, 'season_number': season_number}
    info = {
        'title': title,
        'plot': season_details.get('overview'),
        'year': int(season_details.get('air_date', '0').split('-')[0]),
        'mediatype': 'season',
    }
    art = {'poster': f"{IMG_BASE_URL}w500{season_details.get('poster_path')}" if season_details.get('poster_path') else ''}

    return _create_base_list_item(title, params, info, art, is_folder=True)

def _create_episode_item(tv_show_id, episode_details):
    season_number = episode_details.get('season_number')
    episode_number = episode_details.get('episode_number')
    title = f"{episode_number}. {episode_details.get('name')}"

    params = {
        'action': 'play',
        'media_type': 'episode',
        'tmdb_id': tv_show_id,
        'season': season_number,
        'episode': episode_number,
        'title': title
    }
    info = {
        'title': title,
        'plot': episode_details.get('overview'),
        'rating': episode_details.get('vote_average'),
        'aired': episode_details.get('air_date'),
        'mediatype': 'episode',
    }
    art = {'thumb': f"{IMG_BASE_URL}w500{episode_details.get('still_path')}" if episode_details.get('still_path') else ''}

    return _create_base_list_item(title, params, info, art, is_folder=False, is_playable=True)

# --- Generic Population Function ---
def _populate_filtered_list(media_type, api_func, api_params, page, next_action_params):
    content_type = 'tvshows' if media_type == 'tv' else 'movies'
    xbmcplugin.setContent(_HANDLE, content_type)

    create_item_func = _create_tv_show_item if media_type == 'tv' else _create_movie_item
    id_key = 'id'

    items_to_skip = (page - 1) * ITEMS_PER_PAGE
    items_added = 0
    tmdb_page = 0
    has_more_results = True
    local_ids = None  # Initialize local_ids to None

    while items_added < ITEMS_PER_PAGE and has_more_results:
        tmdb_page += 1
        api_params['page'] = tmdb_page
        data = api_func(**api_params)

        if not data or not data.get('results') or data.get('page', 1) > data.get('total_pages', 1):
            has_more_results = False
            break

        # Lazy-load local IDs only after a successful API call
        if local_ids is None:
            local_ids = get_tv_ids() if media_type == 'tv' else get_movie_ids()

        for details in data['results']:
            item_id = details.get(id_key)
            if item_id in local_ids:
                if items_to_skip > 0:
                    items_to_skip -= 1
                    continue
                
                item = create_item_func(details)
                if item:
                    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2])
                    items_added += 1
                    if items_added >= ITEMS_PER_PAGE:
                        break
        
        if items_added >= ITEMS_PER_PAGE:
            break

    if has_more_results and items_added > 0:
        next_page_li = xbmcgui.ListItem(f"Pagina următoare ({page + 1})")
        next_action_params['page'] = page + 1
        url = f"{_BASE_URL}?{urlencode(next_action_params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=next_page_li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)

# --- Playback ---
def play_media():
    media_type = _ARGS.get('media_type')
    tmdb_id = _ARGS.get('tmdb_id')
    title = _ARGS.get('title', 'Necunoscut')

    if media_type == 'movie':
        stream_url = client.get_stream_url(tmdb_id)
    elif media_type == 'episode':
        season = _ARGS.get('season')
        episode = _ARGS.get('episode')
        stream_url = client.get_stream_url(tmdb_id, season, episode)
    else:
        stream_url = None

    if stream_url:
        play_item = xbmcgui.ListItem(path=stream_url)
        play_item.setInfo('video', {'title': title})
        xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=play_item)
    else:
        xbmcgui.Dialog().notification('MIAF', f'Nu am putut obține un link de stream pentru "{title}"', xbmcgui.NOTIFICATION_WARNING)

# --- Main Menu & Navigation ---
def list_main_menu():
    xbmcplugin.setPluginCategory(_HANDLE, 'MIAF')
    
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_search_menu", listitem=xbmcgui.ListItem('Caută'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_movies_menu", listitem=xbmcgui.ListItem('Filme'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_tv_menu", listitem=xbmcgui.ListItem('Seriale'), isFolder=True)
    
    xbmcplugin.endOfDirectory(_HANDLE)

def list_search_menu():
    xbmcplugin.setPluginCategory(_HANDLE, 'Caută')
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=search&media_type=movie", listitem=xbmcgui.ListItem('Caută Filme'), isFolder=False)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=search&media_type=tv", listitem=xbmcgui.ListItem('Caută Seriale'), isFolder=False)
    xbmcplugin.endOfDirectory(_HANDLE)

def list_movies_menu():
    xbmcplugin.setPluginCategory(_HANDLE, 'Filme')
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_popular&media_type=movie", listitem=xbmcgui.ListItem('Cele mai populare'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_years&media_type=movie", listitem=xbmcgui.ListItem('După an'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_genres&media_type=movie", listitem=xbmcgui.ListItem('După gen'), isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)

def list_tv_menu():
    xbmcplugin.setPluginCategory(_HANDLE, 'Seriale')
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_popular&media_type=tv", listitem=xbmcgui.ListItem('Cele mai populare'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_years&media_type=tv", listitem=xbmcgui.ListItem('După an'), isFolder=True)
    xbmcplugin.addDirectoryItem(handle=_HANDLE, url=f"{_BASE_URL}?action=list_genres&media_type=tv", listitem=xbmcgui.ListItem('După gen'), isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)

# --- Listing Functions (Movies & TV) ---
def list_popular():
    media_type = _ARGS.get('media_type')
    page = int(_ARGS.get('page', '1'))
    api_func = client.get_popular_tv_tmdb if media_type == 'tv' else client.get_popular_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f'Cele mai populare (Pagina {page})')
    _populate_filtered_list(media_type, api_func, {}, page, {'action': 'list_popular', 'media_type': media_type})

def list_years():
    media_type = _ARGS.get('media_type')
    xbmcplugin.setPluginCategory(_HANDLE, 'Selectați Anul')
    current_year = datetime.datetime.now().year
    for year in range(current_year, 1980 - 1, -1):
        li = xbmcgui.ListItem(str(year))
        params = {'action': 'list_by_year', 'media_type': media_type, 'year': str(year)}
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)

def list_by_year():
    media_type = _ARGS.get('media_type')
    year = _ARGS.get('year')
    page = int(_ARGS.get('page', '1'))
    if not year: return
    api_func = client.get_tv_by_year_tmdb if media_type == 'tv' else client.get_movies_by_year_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f'Din anul {year} (Pagina {page})')
    _populate_filtered_list(media_type, api_func, {'year': year}, page, {'action': 'list_by_year', 'media_type': media_type, 'year': year})

def list_genres():
    media_type = _ARGS.get('media_type')
    xbmcplugin.setPluginCategory(_HANDLE, 'Selectați Genul')
    api_func = client.get_tv_genres_tmdb if media_type == 'tv' else client.get_genres_tmdb
    data = api_func()
    if data and 'genres' in data:
        for genre in data['genres']:
            li = xbmcgui.ListItem(genre['name'])
            params = {'action': 'list_by_genre', 'media_type': media_type, 'genre_id': genre['id'], 'genre_name': genre['name']}
            url = f"{_BASE_URL}?{urlencode(params)}"
            xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)

def list_by_genre():
    media_type = _ARGS.get('media_type')
    genre_id = _ARGS.get('genre_id')
    genre_name = _ARGS.get('genre_name', 'Gen necunoscut')
    page = int(_ARGS.get('page', '1'))
    if not genre_id: return
    api_func = client.get_tv_by_genre_tmdb if media_type == 'tv' else client.get_movies_by_genre_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f'Genul "{genre_name}" (Pagina {page})')
    next_params = {'action': 'list_by_genre', 'media_type': media_type, 'genre_id': genre_id, 'genre_name': genre_name}
    _populate_filtered_list(media_type, api_func, {'genre_id': genre_id}, page, next_params)

def search():
    media_type = _ARGS.get('media_type')
    keyboard = xbmc.Keyboard('', f'Introduceți termenul de căutare pentru {media_type}')
    keyboard.doModal()
    if keyboard.isConfirmed() and keyboard.getText():
        query = keyboard.getText()
        params = {'action': 'list_search_results', 'media_type': media_type, 'query': query}
        xbmc.executebuiltin(f"Container.Update({_BASE_URL}?{urlencode(params)})")

def list_search_results():
    media_type = _ARGS.get('media_type')
    query = _ARGS.get('query')
    page = int(_ARGS.get('page', '1'))
    if not query: return
    api_func = client.search_tv_tmdb if media_type == 'tv' else client.search_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f'Rezultate căutare pentru "{query}" (Pagina {page})')
    next_params = {'action': 'list_search_results', 'media_type': media_type, 'query': query}
    _populate_filtered_list(media_type, api_func, {'query': query}, page, next_params)

# --- TV Show Specific Listing ---
def list_seasons():
    tv_show_id = int(_ARGS.get('tv_show_id'))
    title = _ARGS.get('title')
    xbmcplugin.setPluginCategory(_HANDLE, title)
    
    show_details = client.get_tv_details_tmdb(tv_show_id)
    if not show_details or 'seasons' not in show_details:
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    available_seasons = get_episode_info().get(tv_show_id, {})

    for season_summary in show_details['seasons']:
        season_number = season_summary.get('season_number')
        if season_number in available_seasons:
            item = _create_season_item(tv_show_id, season_summary)
            if item:
                xbmcplugin.addDirectoryItem(handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2])

    xbmcplugin.endOfDirectory(_HANDLE)

def list_episodes():
    tv_show_id = int(_ARGS.get('tv_show_id'))
    season_number = int(_ARGS.get('season_number'))
    xbmcplugin.setPluginCategory(_HANDLE, f"Sezonul {season_number}")
    xbmcplugin.setContent(_HANDLE, 'episodes')

    season_details = client.get_season_details_tmdb(tv_show_id, season_number)
    if not season_details or 'episodes' not in season_details:
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    available_episodes = get_episode_info().get(tv_show_id, {}).get(season_number, set())

    for episode_details in season_details['episodes']:
        episode_number = episode_details.get('episode_number')
        if episode_number in available_episodes:
            item = _create_episode_item(tv_show_id, episode_details)
            if item:
                xbmcplugin.addDirectoryItem(handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2])

    xbmcplugin.endOfDirectory(_HANDLE)

# --- Router ---
def router():
    if not client.get_api_key():
        xbmcgui.Dialog().notification('Vix Movie', 'Cheia API TMDb lipsește.', xbmcgui.NOTIFICATION_ERROR)
        xbmc.executebuiltin('Addon.OpenSettings(plugin.video.vixmovie)')
        return

    action = _ARGS.get('action', 'main_menu')
    
    actions = {
        'play': play_media,
        'main_menu': list_main_menu,
        'list_search_menu': list_search_menu,
        'list_movies_menu': list_movies_menu,
        'list_tv_menu': list_tv_menu,
        'list_popular': list_popular,
        'list_years': list_years,
        'list_by_year': list_by_year,
        'list_genres': list_genres,
        'list_by_genre': list_by_genre,
        'search': search,
        'list_search_results': list_search_results,
        'list_seasons': list_seasons,
        'list_episodes': list_episodes
    }

    if action in actions:
        actions[action]()
    else:
        list_main_menu()

if __name__ == '__main__':
    router()