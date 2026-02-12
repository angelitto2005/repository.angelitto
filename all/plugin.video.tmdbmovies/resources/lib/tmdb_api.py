import sys
import os
import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
import urllib.parse
from urllib.parse import urlencode, quote, quote_plus
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
from resources.lib.utils import get_json, get_language, log, paginate_list, read_json, write_json, get_genres_string, set_resume_point
from resources.lib.cache import cache_object, MainCache, get_fast_cache, set_fast_cache
from resources.lib import menus
from resources.lib import trakt_sync
from resources.lib.config import PAGE_LIMIT
from concurrent.futures import ThreadPoolExecutor

LANG = get_language()
VIDEO_LANGS = "en,null,xx,ro,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ru,ja,ko,zh"

PAGE_LIMIT = 21

SEARCH_HISTORY_FILE = os.path.join(ADDON.getAddonInfo('profile'), 'search_history.json')
ADDON_PATH = ADDON.getAddonInfo('path')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
TMDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')


def render_from_fast_cache(items):
    """Desenează lista instantaneu din datele cached folosind Batch Add."""
    items_to_add = [] 
    
    for item in items:
        # Reconstrucție ListItem dacă vine din JSON (warmup)
        if 'li' in item and isinstance(item['li'], xbmcgui.ListItem):
            li = item['li']
        else:
            li = xbmcgui.ListItem(item['label'])
            li.setArt(item['art'])
            
            tag = li.getVideoInfoTag()
            info = item['info']
            
            tag.setMediaType(info.get('mediatype', 'video'))
            tag.setTitle(info.get('title', ''))
            tag.setPlot(info.get('plot', '')) # Aici va pune 'Next Page' la buton
            
            if info.get('year'): tag.setYear(int(info['year']))
            if info.get('rating'): tag.setRating(float(info['rating']))
            if info.get('votes'): tag.setVotes(int(info['votes']))
            if info.get('duration'): tag.setDuration(int(info['duration']))
            if info.get('premiered'): tag.setPremiered(info['premiered'])
            if info.get('studio'): tag.setStudios([info['studio']])
            if info.get('genre'): tag.setGenres(info['genre'].split(', '))
            
            # APLICĂM BIFA DIN CACHE
            if info.get('playcount'): 
                tag.setPlaycount(int(info['playcount']))
                tag.setResumePoint(0.0, 0.0) # <--- ADAUGĂ ASTA (Resetează cerculețul)
            else:
                tag.setPlaycount(0)
# --------------------------------------------
            
            if item.get('resume_time') and item.get('total_time'):
                set_resume_point(li, item['resume_time'], item['total_time'])
                
            # Adăugăm context menu din datele salvate
            if item.get('cm'):
                li.addContextMenuItems(item['cm'])

        items_to_add.append((item['url'], li, item['is_folder']))
    
    xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    
    if items:
        xbmcplugin.setContent(HANDLE, items[0]['info'].get('mediatype', 'movies') + 's')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    

# === THREADING PREFETCHER ===
def prefetch_metadata_parallel(items, media_type):
    """Încarcă metadatele în cache (SQL) pentru o listă întreagă folosind fire de execuție."""
    if not items: return
    
    def fetch_task(item):
        tid = str(item.get('id') or item.get('tmdb_id') or '')
        if tid and tid != 'None':
            m_type = item.get('media_type') or ('movie' if media_type == 'movie' else 'tv')
            # Această funcție scrie în cache-ul SQL, deci următoarele apeluri vor fi instantanee
            get_tmdb_item_details(tid, m_type)

    with ThreadPoolExecutor(max_workers=15) as executor:
        executor.map(fetch_task, items)


# =============================================================================
# FUNCȚIE PENTRU PLOT TRADUS (VERSIUNE CORECTĂ)
# =============================================================================
def get_translated_plot(tmdb_id, media_type, original_plot='', season=None, episode=None):
    """
    Returnează plotul în limba selectată din setări.
    
    Args:
        tmdb_id: ID-ul TMDb
        media_type: 'movie' sau 'tv'
        original_plot: Plotul original (fallback)
        season: Numărul sezonului (opțional, pentru sezoane/episoade)
        episode: Numărul episodului (opțional, pentru episoade)
    """
    from resources.lib.config import ADDON
    
    # Verificăm setarea
    try:
        setting = ADDON.getSetting('plot_language')
        if setting != '1':  # Dacă nu e Română (1), returnăm original
            return original_plot
    except:
        return original_plot
    
    # Limba pentru traducere
    plot_lang = 'ro-RO'
    
    try:
        # Construim URL-ul corect bazat pe tip
        if media_type == 'movie':
            url = f"{BASE_URL}/movie/{tmdb_id}?api_key={API_KEY}&language={plot_lang}"
            cache_key = f"plot_movie_{tmdb_id}_{plot_lang}"
        elif episode is not None and season is not None:
            # Episod specific
            url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={plot_lang}"
            cache_key = f"plot_ep_{tmdb_id}_s{season}e{episode}_{plot_lang}"
        elif season is not None:
            # Sezon specific
            url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={plot_lang}"
            cache_key = f"plot_season_{tmdb_id}_s{season}_{plot_lang}"
        else:
            # Serial (overview general)
            url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={plot_lang}"
            cache_key = f"plot_tv_{tmdb_id}_{plot_lang}"
        
        # Folosim MainCache
        from resources.lib.cache import MainCache
        cache = MainCache()
        
        # Verificăm cache-ul
        cached = cache.get(cache_key)
        if cached is not None:
            # cached poate fi string gol "" dacă nu există traducere
            return cached if cached else original_plot
        
        # Facem request
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            translated_plot = data.get('overview', '')
            
            # Salvăm în cache (24 ore) - expiration e în ORE
            cache.set(cache_key, translated_plot, expiration=24)
            
            if translated_plot:
                return translated_plot
        
        # Dacă request-ul a eșuat, salvăm string gol în cache pentru a nu repeta
        cache.set(cache_key, '', expiration=24)
        
        # Fallback la original
        return original_plot
        
    except Exception as e:
        log(f"[PLOT] Error getting translation: {e}", xbmc.LOGWARNING)
        return original_plot

# =============================================================================
# HELPER PENTRU IMAGINI LISTE TMDB
# =============================================================================
def get_list_image_url(image_path, image_type='poster'):
    """
    Construiește URL-ul complet pentru imaginile listelor TMDb.
    """
    if not image_path:
        return None
    
    # Dacă e deja URL complet, returnăm direct
    if image_path.startswith('http'):
        return image_path
    
    # Alegem rezoluția bazată pe tip
    if image_type in ['fanart', 'backdrop']:
        return f"{BACKDROP_BASE}{image_path}"
    else:
        return f"{IMG_BASE}{image_path}"


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
    # ✅ FIX: Lista de moduri care sunt ACȚIUNI (nu playable, nu folder)
    ACTION_MODES = [
        'sources',  # Gestionat separat de player
        'tmdb_auth', 'tmdb_logout', 'tmdb_auth_action', 'tmdb_logout_action',
        'trakt_auth', 'trakt_revoke', 'trakt_auth_action', 'trakt_revoke_action',
        'trakt_sync', 'trakt_sync_db', 'trakt_sync_action',
        'clear_cache', 'clear_cache_action', 'clear_all_cache',
        'clear_search_history', 'clear_tmdb_lists_cache', 'clear_list_cache',
        'open_settings', 'settings', 'noop',
        'add_favorite', 'remove_favorite',
        'mark_watched', 'mark_unwatched', 'remove_progress',
        'tmdb_add_watchlist', 'tmdb_remove_watchlist',
        'tmdb_add_favorites', 'tmdb_remove_favorites',
        'tmdb_add_to_list', 'tmdb_remove_from_list',
        'delete_search', 'edit_search',
        'delete_tmdb_list', 'clear_tmdb_list',
        'tmdb_context_menu', 'trakt_context_menu',
        'clear_sources_context'
    ]
    
    mode = params.get('mode', '')
    if not folder and mode not in ACTION_MODES:
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

    # --- MODIFICARE NOUĂ ---
    if uids and 'tmdb' in uids:
        li.setProperty('tmdb_id', str(uids['tmdb']))
    # -----------------------
    
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
    import requests
    import datetime
    
    # Toate limbile indiene
    INDIAN_LANGS = "hi|ta|te|ml|kn|pa|bn|mr"
    
    # Baza URL
    url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&region=US"

    if action == 'tmdb_movies_popular':
        url = f"{BASE_URL}/movie/popular?api_key={API_KEY}&language={LANG}&page={page_no}"
    elif action == 'tmdb_movies_now_playing':
        url = f"{BASE_URL}/movie/now_playing?api_key={API_KEY}&language={LANG}&page={page_no}"
    elif action == 'tmdb_movies_top_rated':
        url = f"{BASE_URL}/movie/top_rated?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_movies_upcoming':
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        max_date = (datetime.date.today() + datetime.timedelta(days=120)).strftime('%Y-%m-%d')
        
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}"
            f"&language=en-US"
            f"&with_original_language=en"            # ✅ Doar limba engleză (corect)
            f"&page={page_no}"
            f"&region=US"
            f"&primary_release_date.gte={tomorrow}"
            f"&primary_release_date.lte={max_date}"  # ✅ Max 120 zile (nu filme din 2028)
            f"&sort_by=primary_release_date.asc"             # ✅ Cele mai populare primele
            f"&with_runtime.gte=60"                  # ✅ Fără scurtmetraje
            f"&popularity.gte=40"                    # ✅ Moderat - nu pierzi filme bune
            f"&with_release_type=2|3"                # ✅ Doar cinema (Limited + Wide)
            f"&include_adult=false"                  # ✅ OK
        )

    elif action == 'tmdb_movies_anticipated':
        # Anticipated = Filme viitoare sortate după POPULARITATE (cele cu hype)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        max_date = (datetime.date.today() + datetime.timedelta(days=120)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&language={LANG}"
            f"&primary_release_date.gte={tomorrow}"
            f"&primary_release_date.lte={max_date}"  # ✅ Max 120 zile (nu filme din 2028)
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )

    elif action == 'tmdb_movies_blockbusters':
        # LOGICĂ BLOCKBUSTERS: Toate timpurile, încasări gigantice, minim 500 voturi
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&sort_by=revenue.desc&vote_count.gte=500"

    elif action == 'tmdb_movies_box_office':
        # LOGICĂ TOP BOX OFFICE: Cele mai mari încasări din ULTIMUL AN
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&primary_release_date.gte={year_ago}&sort_by=revenue.desc"
        
    elif action == 'tmdb_movies_premieres':
        current_date, previous_date = get_dates(31, reverse=True)
        url += f"&release_date.gte={previous_date}&release_date.lte={current_date}&with_release_type=1|3|2&sort_by=popularity.desc"
        
    elif action == 'tmdb_movies_latest_releases':
        current_date, previous_date = get_dates(31, reverse=True)
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US&region=US"
            f"&release_date.gte={previous_date}"
            f"&release_date.lte={current_date}"
            f"&with_release_type=4|5"
            f"&page={page_no}"
        )
    elif action == 'tmdb_movies_trending_day':
        url = f"{BASE_URL}/trending/movie/day?api_key={API_KEY}&language={LANG}&page={page_no}"
    elif action == 'tmdb_movies_trending_week':
        url = f"{BASE_URL}/trending/movie/week?api_key={API_KEY}&language={LANG}&page={page_no}"

    # =========================================================================
    # HINDI MOVIES (toate limbile indiene)
    # =========================================================================
    elif action == 'hindi_movies_trending':
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&primary_release_date.gte={year_ago}"
            f"&sort_by=popularity.desc"
            f"&vote_count.gte=10"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_popular':
        # Popular = Cele mai populare all-time
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&sort_by=popularity.desc"
            f"&vote_count.gte=50"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_premieres':
        # Premieres = Digital releases din ultima lună
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        previous_date = (datetime.date.today() - datetime.timedelta(days=31)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&release_date.gte={previous_date}"
            f"&release_date.lte={current_date}"
            f"&with_release_type=4|5"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_in_theaters':
        # In Theaters = În cinematografe acum
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        previous_date = (datetime.date.today() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&release_date.gte={previous_date}"
            f"&release_date.lte={current_date}"
            f"&with_release_type=3"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_upcoming':
        # Upcoming = Filme care urmează, sortate CRONOLOGIC (cele mai apropiate primele)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&primary_release_date.gte={tomorrow}"
            f"&sort_by=primary_release_date.asc"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_anticipated':
        # Anticipated = Filme viitoare sortate după POPULARITATE (cele cu hype)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&primary_release_date.gte={tomorrow}"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )

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
    # --- PRIORITATE FOREGROUND ---
    window = xbmcgui.Window(10000)
    window.setProperty('tmdbmovies_loading_active', 'true')
    
    # Adăugăm un mic delay dacă fundalul era ocupat, să-i dăm timp să se oprească
    if xbmcgui.Window(10000).getProperty('tmdbmovies_warmup_busy') == 'true':
        xbmc.sleep(100)
# -----------------------------------------
    action = params.get('action')
    page = int(params.get('new_page', '1'))

# --- FAST CACHE CHECK (RAM) ---
    cache_key = f"list_movie_{action}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        # Chiar dacă am încărcat instant din RAM, pregătim pagina următoare
        # trigger_next_page_warmup(action, page, 'movie') 
        return
    # ---------------------------------

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
        data = cache_object(get_tmdb_movies_standard, string, [action, page], expiration=24)
        if data:
            results = data.get('results', [])
    
    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return
        
    current_items = results 
    has_next = len(results) > 0 and page < 500

# AICI ADAUGAM VITEZA (RAMANE THREADING PENTRU METADATA)
    prefetch_metadata_parallel(current_items, 'movie')

    cache_list = []
    items_to_add = [] # Lista pentru afisare instanta

    for item in current_items:
        # Procesăm item-ul
        processed = _process_movie_item(item, return_data=True)
        if processed:
            # Salvăm pentru Cache RAM
            cache_list.append(processed)
            # Salvăm pentru afișare Kodi (URL, ListItem, isFolder)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

# --- FIX PAGINARE SI CACHE ---
    if has_next:
        # Creăm manual item-ul de Next Page
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'build_movie_list', 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        
        # 1. Adăugăm la afișare imediată
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adăugăm la Cache RAM (STRUCTURA CORECTATĂ PENTRU A EVITA KeyError 'li')
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADĂUGAT (CRITIC PENTRU CACHE)
            'is_folder': True,
            'info': {'mediatype': 'video'}, # Minim necesar
            'art': {'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'},
            'cm_items': [],         # <--- RENUMIT DIN 'cm' IN 'cm_items'
            'resume_time': 0,
            'total_time': 0
        })

# --- BATCH ADD ---
    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies')
    
    # --- PRE-FETCH NEXT PAGE IN BACKGROUND ---
    # Indiferent dacă am încărcat din cache sau rețea, pornim încălzirea pentru pagina următoare
    # trigger_next_page_warmup(action, page, 'movie')
    # -----------------------------------------

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    # Important: Curățăm proprietatea ca să știe fundalul că am terminat
    window.clearProperty('tmdbmovies_loading_active')
    
    # Save to RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'], 
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 
                                'resume_time': i['resume_time'], 'total_time': i['total_time']} for i in cache_list])


def build_tvshow_list(params):
    # --- PRIORITATE FOREGROUND ---
    window = xbmcgui.Window(10000)
    window.setProperty('tmdbmovies_loading_active', 'true')
    
    # Adăugăm un mic delay dacă fundalul era ocupat, să-i dăm timp să se oprească
    if xbmcgui.Window(10000).getProperty('tmdbmovies_warmup_busy') == 'true':
        xbmc.sleep(100)
# -----------------------------------------
    action = params.get('action')
    page = int(params.get('new_page', '1'))

# --- FAST CACHE CHECK (RAM) ---
    cache_key = f"list_tv_{action}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        # Pregătim pagina următoare
        # trigger_next_page_warmup(action, page, 'tv')
        return
    # ---------------------------------

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
        data = cache_object(get_tmdb_tv_standard, string, [action, page], expiration=24)
        if data:
            results = data.get('results', [])

    if not results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = results
    has_next = len(results) > 0 and page < 500

# AICI ADAUGAM VITEZA
    prefetch_metadata_parallel(current_items, 'tv')

    cache_list = []
    items_to_add = [] # Lista pentru afisare instanta

    for item in current_items:
        processed = _process_tv_item(item, return_data=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

# --- FIX PAGINARE SI CACHE ---
    if has_next:
        # Creăm manual item-ul de Next Page
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'build_tvshow_list', 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        
        # 1. Adăugăm la afișare
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adăugăm la Cache RAM (STRUCTURA CORECTATĂ)
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADĂUGAT (CRITIC)
            'is_folder': True,
            'info': {'mediatype': 'video'},
            'art': {'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'},
            'cm_items': [],         # <--- RENUMIT
            'resume_time': 0,
            'total_time': 0
        })

# --- BATCH ADD ---
    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'tvshows')

    # --- PRE-FETCH NEXT PAGE IN BACKGROUND ---
    # trigger_next_page_warmup(action, page, 'tv')
    # -----------------------------------------

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    # Important: Curățăm proprietatea ca să știe fundalul că am terminat
    window.clearProperty('tmdbmovies_loading_active')
    
    # Save to RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'], 
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 
                                'resume_time': 0, 'total_time': 0} for i in cache_list])

def _get_full_context_menu(tmdb_id, content_type, title='', is_in_favorites_view=False, year='', season=None, episode=None, imdb_id=''):
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

    # --- INCEPUT MODIFICARE: MY PLAYS MENU ---
    plays_params = {
        'mode': 'show_my_plays_menu',
        'tmdb_id': tmdb_id,
        'type': content_type,
        'title': title,
        'year': year,
        'imdb_id': imdb_id  # <--- TRIMITEM IMDB ID
    }
    if season: plays_params['season'] = season
    if episode: plays_params['episode'] = episode
    
    cm.append(('[B][COLOR FFFF69B4]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
    # --- SFARSIT MODIFICARE ---
    
    # --- MODIFICARE: DOAR PENTRU FILME (nu seriale/foldere) ---
    if content_type == 'movie':
        clear_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_params})"))
    # ----------------------------------------------------------
    
    # --- ADĂUGAT: DOWNLOAD CONTEXT MENU ---
    dl_params = urlencode({
        'mode': 'initiate_download', 
        'tmdb_id': tmdb_id, 
        'type': content_type, 
        'title': title
    })
    
    # --- DOWNLOAD LOGIC (FILME) ---
    if content_type == 'movie':
        import xbmcgui
        # Asigură-te că e string: str(tmdb_id)
        dl_key = f"dl_movie_{str(tmdb_id)}" 
        is_downloading = xbmcgui.Window(10000).getProperty(dl_key) == 'active'
        
        if is_downloading:
            # Afișăm STOP
            stop_params = urlencode({
                'mode': 'stop_download_action',
                'tmdb_id': tmdb_id,
                'type': 'movie'
            })
            cm.append(('[B][COLOR red]■ Stop Download[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{stop_params})"))
        else:
            # Afișăm DOWNLOAD
            dl_params = urlencode({
                'mode': 'initiate_download', 
                'tmdb_id': tmdb_id, 
                'type': 'movie', 
                'title': title
            })
            cm.append(('[B][COLOR cyan]Download Movie[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{dl_params})"))
    # ------------------------------
    
    if is_in_favorites_view:
        rem_params = urlencode({'mode': 'remove_favorite', 'type': content_type, 'tmdb_id': tmdb_id})
        cm.append(('[B][COLOR yellow]Remove from My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{rem_params})"))
    else:
        fav_params = urlencode({'mode': 'add_favorite', 'type': content_type, 'tmdb_id': tmdb_id, 'title': title})
        cm.append(('[B][COLOR yellow]Add to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

    return cm


def _process_movie_item(item, is_in_favorites_view=False, return_data=False):
    from resources.lib import trakt_api
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return None  # Returnam None daca nu e ID valid

    title = item.get('title') or 'Unknown'
    year = str(item.get('release_date', ''))[:4]
    plot = item.get('overview', '')
    
    full_details = get_tmdb_item_details(tmdb_id, 'movie') or {}
    
    # --- MODIFICARE: EXTRAGERE IMDB ID ---
    imdb_id = full_details.get('external_ids', {}).get('imdb_id', '')
    # -------------------------------------
    
    studio = ''
    if full_details.get('production_companies'):
        studio = full_details['production_companies'][0].get('name', '')
        
    rating = full_details.get('vote_average', item.get('vote_average', 0))
    votes = full_details.get('vote_count', item.get('vote_count', 0))
    premiered = full_details.get('release_date', item.get('release_date', ''))
    
    duration = full_details.get('runtime', 0)
    if duration: duration = int(duration) * 60
    plot = get_translated_plot(tmdb_id, 'movie', full_details.get('overview', plot))

    # --- LOGICA CULOARE ROȘIE FILME NELANSATE ---
    display_title = f"{title} ({year})" if year else title
    if premiered:
        try:
            if datetime.datetime.strptime(premiered, '%Y-%m-%d').date() > datetime.date.today():
                display_title = f"[B][COLOR FFE238EC]{display_title}[/COLOR] (Nelansat)[/B]"
        except: pass

    # --- CALCUL RESUME ---
    from resources.lib import trakt_sync
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'movie')
    resume_percent = progress_value if (0 < progress_value < 90) else 0

    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDbmovies_ICON
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    backdrop = f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''

    is_watched = trakt_api.get_watched_counts(tmdb_id, 'movie') > 0

    info = {
        'mediatype': 'movie', 'title': title, 'year': year, 'plot': plot, 
        'rating': rating, 'votes': votes, 'premiered': premiered, 
        'studio': studio, 'duration': duration, 'resume_percent': resume_percent,
        'genre': get_genres_string(item.get('genre_ids', [])),
        'playcount': 1 if is_watched else 0 # <--- ADĂUGAT DIRECT AICI
    }
    
    # --- MODIFICARE: Trimitem imdb_id in context menu ---
    cm = _get_full_context_menu(tmdb_id, 'movie', title, is_in_favorites_view, year=year, imdb_id=imdb_id)
    # ----------------------------------------------------
    url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
    
    li = xbmcgui.ListItem(display_title)
    li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop})
    li.setProperty('tmdb_id', tmdb_id)
    set_metadata(li, info, unique_ids={'tmdb': tmdb_id}, watched_info=is_watched)
    
    resume_time = 0
    if resume_percent > 0 and duration > 0:
        resume_time = int((resume_percent / 100.0) * duration)
        set_resume_point(li, resume_time, duration)

    if cm: li.addContextMenuItems(cm)
    
    # --- LOGICA DE RETURNARE PENTRU CACHE ---
    if return_data:
        return {
            'url': f"{sys.argv[0]}?{urlencode(url_params)}",
            'li': li,
            'is_folder': False,
            'info': info,
            'art': {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop},
            'cm_items': cm,
            'resume_time': resume_time,
            'total_time': duration,
            'label': display_title
        }
    # ----------------------------------------

    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{urlencode(url_params)}", li, False)


def _process_tv_item(item, is_in_favorites_view=False, return_data=False):
    from resources.lib import trakt_api
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return None

    title = item.get('name', item.get('title', 'Unknown'))
    year = str(item.get('first_air_date', ''))[:4]
    plot = item.get('overview', '')

    full_details = get_tmdb_item_details(tmdb_id, 'tv') or {}
    # --- MODIFICARE: EXTRAGERE IMDB ID ---
    imdb_id = full_details.get('external_ids', {}).get('imdb_id', '')
    # -------------------------------------
    studio = full_details['networks'][0].get('name', '') if full_details.get('networks') else ''
    rating = full_details.get('vote_average', item.get('vote_average', 0))
    votes = full_details.get('vote_count', item.get('vote_count', 0))
    premiered = full_details.get('first_air_date', item.get('first_air_date', ''))
    
    duration = (int(full_details.get('episode_run_time', [0])[0]) * 60) if full_details.get('episode_run_time') else 0
    plot = get_translated_plot(tmdb_id, 'tv', full_details.get('overview', plot))

    # --- LOGICA CULOARE ROȘIE SERIALE NELANSATE ---
    display_name = f"{title} ({year})" if year else title
    if premiered:
        try:
            if datetime.datetime.strptime(premiered, '%Y-%m-%d').date() > datetime.date.today():
                display_name = f"[B][COLOR FFE238EC]{display_name}[/COLOR] (Nelansat)[/B]"
        except: pass

    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDbmovies_ICON
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    backdrop = f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''

    watched_info = get_watched_status_tvshow(tmdb_id)
    
    # Verificăm dacă serialul este văzut complet pentru bifă
    is_watched = watched_info['watched'] >= watched_info['total'] if watched_info['total'] > 0 else False
    
    info = {
        'mediatype': 'tvshow', 'title': title, 'year': year, 'plot': plot, 
        'rating': rating, 'votes': votes, 'premiered': premiered, 
        'studio': studio, 'duration': duration, 'genre': get_genres_string(item.get('genre_ids', [])),
        'playcount': 1 if is_watched else 0 # <--- ADĂUGAT DIRECT AICI
    }

    # --- MODIFICARE: Trimitem parametrul year catre _get_full_context_menu ---
    cm = _get_full_context_menu(tmdb_id, 'tv', title, is_in_favorites_view, year=year, imdb_id=imdb_id)
    # -------------------------------------------------------------------------
    url_params = {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': title}
    
    li = xbmcgui.ListItem(display_name)
    li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop})
    li.setProperty('tmdb_id', tmdb_id)
    set_metadata(li, info, unique_ids={'tmdb': tmdb_id}, watched_info=watched_info)
    
    if cm: li.addContextMenuItems(cm)
    
    # --- LOGICA DE RETURNARE PENTRU CACHE ---
    if return_data:
        return {
            'url': f"{sys.argv[0]}?{urlencode(url_params)}",
            'li': li,
            'is_folder': True,
            'info': info,
            'art': {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop},
            'cm_items': cm,
            'label': display_name
        }
    # ----------------------------------------

    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{urlencode(url_params)}", li, True)


# --- MODIFICARE: get_watched_status_tvshow OPTIMIZAT (VITEZĂ POV) ---
def get_watched_status_tvshow(tmdb_id):
    from resources.lib import trakt_api, trakt_sync
    # Folosim SESSION pentru viteză dacă fallback-ul chiar e necesar
    from resources.lib.config import SESSION, get_headers
    
    str_id = str(tmdb_id)
    
    # 1. Încercăm cache RAM (Viteză maximă)
    if str_id in TV_META_CACHE:
        total_eps = TV_META_CACHE[str_id]
    else:
        # 2. Încercăm tabelul dedicat tv_meta din SQL
        total_eps = trakt_sync.get_tv_meta_from_db(str_id)
        
        # 3. FALLBACK INTELIGENT:
        if not total_eps:
            # În loc de request nou, apelăm get_tmdb_item_details
            # Aceasta va citi INSTANT din SQL (meta_cache_items) dacă prefetcher-ul a lucrat deja
            details = get_tmdb_item_details(str_id, 'tv')
            if details:
                total_eps = details.get('number_of_episodes', 0)
                # Salvăm în tv_meta pentru a nu mai procesa JSON-ul mare data viitoare
                trakt_sync.set_tv_meta_to_db(str_id, total_eps)
            else:
                total_eps = 0

        # Salvăm în RAM pentru sesiunea curentă
        TV_META_CACHE[str_id] = total_eps

    # Luăm numărul de episoade vizionate (deja rapid, din SQL)
    watched_count = trakt_api.get_watched_counts(tmdb_id, 'tv')
    return {'watched': watched_count, 'total': total_eps}
# --------------------------------------------------------------------


def get_tmdb_session():
    data = read_json(TMDB_SESSION_FILE)
    # Verificăm întâi dacă data există și este un dicționar
    if data and isinstance(data, dict):
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
        
        # ✅ FIX: Folosim helper-ul pentru URL-uri corecte
        poster = get_list_image_url(poster_path, 'poster') or ''
        backdrop = get_list_image_url(backdrop_path, 'fanart') or ''
        
        # Fallback: dacă lista nu are poster propriu, luăm de la primul item
        if not poster and list_id:
            list_details = get_tmdb_list_details_v4(list_id)
            if list_details and list_details.get('results'):
                first_item = list_details['results'][0]
                item_poster = first_item.get('poster_path', '')
                item_backdrop = first_item.get('backdrop_path', '')
                if item_poster:
                    poster = get_list_image_url(item_poster, 'poster')
                if item_backdrop and not backdrop:
                    backdrop = get_list_image_url(item_backdrop, 'fanart')

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
        add_directory("[B][COLOR FF00CED1]Conectare TMDB[/COLOR][/B]", {'mode': 'tmdb_auth'}, icon='DefaultUser.png', folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    add_directory("[B]Watchlist[/B]", {'mode': 'tmdb_watchlist_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("[B]Favorites[/B]", {'mode': 'tmdb_favorites_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("[B]Recommendations[/B]", {'mode': 'tmdb_recommendations_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    
    add_directory("[B][COLOR FF00CED1]--- My Lists ---[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')

    # ✅ Citim listele personale din SQL
    lists = trakt_sync.get_tmdb_custom_lists_from_db()
    
    log(f"[TMDB] Found {len(lists) if lists else 0} custom lists in SQL")

    if lists:
        for lst in lists:
            list_id = str(lst.get('list_id'))
            name = lst.get('name', 'Unknown')
            count = lst.get('item_count', 0)
            description = lst.get('description', '')  # ✅ ADĂUGAT
            
            # Citim poster și backdrop din SQL
            poster_path = lst.get('poster', '')
            backdrop_path = lst.get('backdrop', '')
            
            # Construim URL-urile complete
            poster = get_list_image_url(poster_path, 'poster') if poster_path else TMDB_ICON
            fanart = get_list_image_url(backdrop_path, 'fanart') if backdrop_path else ''
            
            cm = [
                ('Refresh Lists', f"RunPlugin({sys.argv[0]}?mode=trakt_sync_db)"), 
                ('Delete List', f"RunPlugin({sys.argv[0]}?mode=delete_tmdb_list&list_id={list_id})"),
                ('Clear List Items', f"RunPlugin({sys.argv[0]}?mode=clear_tmdb_list&list_id={list_id})"),
            ]

            # ✅ ADĂUGAT: info cu plot (description)
            info = {
                'mediatype': 'video',
                'title': name,
                'plot': description if description else f"TMDb List: {name}\n{count} items"
            }

            add_directory(
                f"[B]{name} [COLOR FFFDBD01]({count})[/COLOR][/B]",
                {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': name},
                icon=poster, thumb=poster, fanart=fanart, cm=cm, info=info, folder=True
            )
    else:
        add_directory("[COLOR gray]Nu ai liste personale sau sincronizează din nou[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)

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
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]", 
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

    # --- FAST CACHE CHECK (RAM) ---
    cache_key = f"tmdb_custom_list_{list_id}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ------------------------------

    items_raw = trakt_sync.get_tmdb_custom_list_items_from_db(list_id)
    if not items_raw:
        xbmcplugin.endOfDirectory(HANDLE); return

    paginated, total = paginate_list(items_raw, page, PAGE_LIMIT)
    
    # REPARAT NameError: folosim variabila m_type determinată corect
    if paginated:
        m_type = paginated[0].get('media_type', 'movie')
        prefetch_metadata_parallel(paginated, m_type)

    for item in paginated:
        if item.get('media_type') == 'movie': _process_movie_item(item)
        else: _process_tv_item(item)

    if page < total:
        add_directory(f"[B]Next Page ({page+1}) >>[/B]", {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': list_name, 'page': str(page+1)}, icon='DefaultFolder.png', folder=True)
    xbmcplugin.setContent(HANDLE, 'movies'); xbmcplugin.endOfDirectory(HANDLE)


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

    # --- 1. FAST CACHE CHECK (RAM) ---
    cache_key = f"tmdb_watchlist_{content_type}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

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
    prefetch_metadata_parallel(paginated, content_type)
    
    # --- 2. BATCH RENDERING & CACHE PREP ---
    items_to_add = []
    cache_list = []
    
    for item in paginated:
        if content_type == 'movie': 
            processed = _process_movie_item(item, return_data=True)
        else: 
            processed = _process_tv_item(item, return_data=True)
            
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    if page < total:
        # Adăugăm butonul Next Page manual pentru Batch/Cache
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'tmdb_watchlist', 'type': content_type, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': 'DefaultFolder.png'}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    # Salvăm în RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def tmdb_favorites(params):
    content_type = params.get('type')
    page = int(params.get('page', '1'))

    # --- FAST CACHE CHECK (RAM) ---
    cache_key = f"tmdb_favorites_{content_type}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ------------------------------

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
    prefetch_metadata_parallel(paginated, content_type)
    
    for item in paginated:
        if content_type == 'movie': _process_movie_item(item)
        else: _process_tv_item(item)

    if page < total:
        add_directory(f"[B]Next Page ({page+1}) >>[/B]", {'mode': 'tmdb_favorites', 'type': content_type, 'page': str(page+1)}, icon='DefaultFolder.png', folder=True)
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
            
            # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
            try:
                # 1. Update SQL Instant
                details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                d_title = details.get('title') or details.get('name', 'Unknown')
                d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
                d_poster = details.get('poster_path', '')
                d_overview = details.get('overview', '')
                c.execute("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", 
                          ('watchlist', content_type, str(tmdb_id), d_title, d_year, d_poster, '', d_overview))
                conn.commit()
                conn.close()
            except: pass

            # 2. Refresh UI Imediat (ca să dispară rotița)
            xbmc.executebuiltin("Container.Refresh")

            # 3. Pornire Sync în fundal cu întârziere (ca să nu blocheze DB în timpul refresh-ului)
            def delayed_sync():
                time.sleep(3) # Așteaptă 3 secunde să se termine refresh-ul UI
                trakt_sync.sync_full_library(silent=True)
            
            import threading
            threading.Thread(target=delayed_sync).start()
            
            return True
            # -------------------------------------------------
    except: pass
    return False

def remove_from_tmdb_watchlist(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session: return False
    url = f"{BASE_URL}/account/{session['account_id']}/watchlist?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'watchlist': False}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din [B][COLOR FF00CED1]Watchlist[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
            try:
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                          ('watchlist', content_type, str(tmdb_id)))
                conn.commit()
                conn.close()
            except: pass
            
            xbmc.executebuiltin("Container.Refresh")

            def delayed_sync():
                time.sleep(3)
                trakt_sync.sync_full_library(silent=True)
            
            import threading
            threading.Thread(target=delayed_sync).start()
            
            return True
            # -------------------------------------------------
    except: pass
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
            
            # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
            try:
                details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                d_title = details.get('title') or details.get('name', 'Unknown')
                d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
                d_poster = details.get('poster_path', '')
                d_overview = details.get('overview', '')
                c.execute("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", 
                          ('favorite', content_type, str(tmdb_id), d_title, d_year, d_poster, '', d_overview))
                conn.commit()
                conn.close()
            except: pass

            xbmc.executebuiltin("Container.Refresh")

            def delayed_sync():
                time.sleep(3)
                trakt_sync.sync_full_library(silent=True)
            
            import threading
            threading.Thread(target=delayed_sync).start()
            
            return True
            # -------------------------------------------------
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
            
            # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
            try:
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                          ('favorite', content_type, str(tmdb_id)))
                conn.commit()
                conn.close()
            except: pass

            xbmc.executebuiltin("Container.Refresh")

            def delayed_sync():
                time.sleep(3)
                trakt_sync.sync_full_library(silent=True)
            
            import threading
            threading.Thread(target=delayed_sync).start()

            return True
            # -------------------------------------------------
    except:
        pass
    return False


def add_to_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: 
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Nu ești conectat", TMDB_ICON, 3000, False)
        return False

    success = False
    media_type_normalized = 'tv' if content_type in ['tv', 'tvshow'] else 'movie'
    
    # Dacă e serial (tv), folosim API-ul V4
    if content_type == 'tv' or content_type == 'tvshow':
        url = f"{TMDB_V4_BASE_URL}/list/{list_id}/items"
        headers = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json;charset=utf-8'}
        payload = {"items": [{"media_type": "tv", "media_id": int(tmdb_id)}]}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Serial adăugat în listă", TMDB_ICON, 3000, False)
                success = True
        except: pass
    else:
        # Default pentru Filme (V3)
        url = f"{BASE_URL}/list/{list_id}/add_item?api_key={API_KEY}&session_id={session['session_id']}"
        try:
            r = requests.post(url, json={'media_id': int(tmdb_id)}, timeout=10)
            if r.status_code in [200, 201]:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Adăugat în listă", TMDB_ICON, 3000, False)
                success = True
        except: pass

    if success:
        # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
        try:
            details = get_tmdb_item_details(str(tmdb_id), media_type_normalized) or {}
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            d_title = details.get('title') or details.get('name', 'Unknown')
            d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            d_poster = details.get('poster_path', '')
            d_overview = details.get('overview', '')
            
            # Folosim tabelul EXISTENT: tmdb_custom_list_items
            c.execute("""INSERT OR REPLACE INTO tmdb_custom_list_items 
                        (list_id, tmdb_id, media_type, title, year, poster, overview) 
                        VALUES (?,?,?,?,?,?,?)""", 
                      (str(list_id), str(tmdb_id), media_type_normalized, d_title, d_year, d_poster, d_overview))
            conn.commit()
            conn.close()
        except: pass

        xbmc.executebuiltin("Container.Refresh")

        def delayed_sync():
            import time
            time.sleep(3)
            trakt_sync.sync_full_library(silent=True)
        
        import threading
        threading.Thread(target=delayed_sync).start()
        
        return True
    
    return False


def remove_from_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: 
        return False

    success = False
    media_type_normalized = 'tv' if content_type in ['tv', 'tvshow'] else 'movie'

    if content_type == 'tv' or content_type == 'tvshow':
        url = f"{TMDB_V4_BASE_URL}/list/{list_id}/items"
        headers = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json;charset=utf-8'}
        payload = {"items": [{"media_type": "tv", "media_id": int(tmdb_id)}]}
        try:
            r = requests.delete(url, json=payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din listă", TMDB_ICON, 3000, False)
                success = True
        except: pass
    else:
        url = f"{BASE_URL}/list/{list_id}/remove_item?api_key={API_KEY}&session_id={session['session_id']}"
        try:
            r = requests.post(url, json={'media_id': int(tmdb_id)}, timeout=10)
            if r.status_code in [200, 201]:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Șters din listă", TMDB_ICON, 3000, False)
                success = True
        except: pass

    if success:
        # --- FIX BUFFERING: SQL INSTANT + DELAYED SYNC ---
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            # Folosim tabelul EXISTENT: tmdb_custom_list_items
            c.execute("""DELETE FROM tmdb_custom_list_items 
                        WHERE list_id=? AND tmdb_id=?""", 
                      (str(list_id), str(tmdb_id)))
            conn.commit()
            conn.close()
        except: pass

        xbmc.executebuiltin("Container.Refresh")

        def delayed_sync():
            import time
            time.sleep(3)
            trakt_sync.sync_full_library(silent=True)
        
        import threading
        threading.Thread(target=delayed_sync).start()

        return True
    
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
        styled_name = f"[B][COLOR FF00CED1]{lst.get('name', 'Unknown')}[/COLOR][/B]"
        li = xbmcgui.ListItem(styled_name)
        li.setLabel2(f"[B][COLOR yellow]{lst.get('item_count', 0)}[/COLOR][/B] items")
        poster = get_list_image_url(lst.get('poster', ''), 'poster') or TMDB_ICON
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        display_items.append(li)

    ret = xbmcgui.Dialog().select("[B][COLOR FF00CED1]TMDB[/COLOR][/B]: Add to List", display_items, useDetails=True)
    if ret >= 0:
        add_to_tmdb_list(lists[ret]['list_id'], tmdb_id, content_type)


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
        
        # ✅ FIX: Construire corectă URL imagini
        poster_path = lst.get('poster', '')
        backdrop_path = lst.get('backdrop', '')
        
        poster = get_list_image_url(lst.get('poster', ''), 'poster') or TMDB_ICON
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        
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
    main_show_plot = data.get('overview', '')
    # --- SFARSIT COD MODIFICAT ---
    
    studio = ''
    if data.get('networks'):
        studio = data['networks'][0].get('name', '')

    from resources.lib import trakt_api
    import datetime
    today = datetime.date.today()

    for s in data.get('seasons', []):
        s_num = s['season_number']
        if s_num == 0:
            continue

        name = f"Season {s_num}"
        ep_count = s.get('episode_count', 0)
        s_poster = f"{IMG_BASE}{s.get('poster_path', '')}" if s.get('poster_path') else poster
        
        premiered = s.get('air_date', '')

        # --- LOGICA CULOARE ROȘIE SEZON (INJECTATĂ) ---
        display_name = name
        if premiered:
            try:
                if datetime.datetime.strptime(premiered, '%Y-%m-%d').date() > today:
                    display_name = f"[B][COLOR FFE238EC]{name}[/COLOR] (Lansare: {premiered}[/B])"
            except: pass
        # ----------------------------------------------

        season_plot = s.get('overview', '')
        if not season_plot:
            season_plot = main_show_plot

        season_plot = get_translated_plot(tmdb_id, 'tv', season_plot, season=s_num)

        watched_count = trakt_api.get_watched_counts(tmdb_id, 'season', s_num)
        watched_info = {'watched': watched_count, 'total': ep_count}

        info = {
            'mediatype': 'season',
            'title': name,
            'plot': season_plot,
            'tvshowtitle': tv_title,
            'season': s_num,
            'premiered': premiered,
            'studio': studio 
        }

        add_directory(
            display_name, # MODIFICAT DIN 'name'
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

    poster = f"{IMG_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else ''
    
    # --- MODIFICARE: Obținem IMDb ID al SERIALULUI (Parent) ---
    # Încercăm să luăm detaliile serialului din DB sau API pentru a găsi IMDb ID
    show_imdb_id = ''
    show_details = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, 'tv')
    if show_details:
        show_imdb_id = show_details.get('external_ids', {}).get('imdb_id', '')
    
    if not show_imdb_id:
         # Fallback API rapid doar pentru external_ids daca nu e in DB
         try:
             ext_url = f"{BASE_URL}/tv/{tmdb_id}/external_ids?api_key={API_KEY}"
             ext_data = requests.get(ext_url, timeout=3).json()
             show_imdb_id = ext_data.get('imdb_id', '')
         except: pass
    # -----------------------------------------------------------

    from resources.lib import trakt_api
    import datetime
    today = datetime.date.today()

    for ep in data.get('episodes', []):
        ep_num = ep['episode_number']
        original_ep_name = ep.get('name', '')
        name = f"{ep_num}. {original_ep_name}"
        
        # --- LOGICA CULOARE ROȘIE EPISOD (INJECTATĂ) ---
        display_label = name
        ep_air_date = ep.get('air_date', '')
        if ep_air_date:
            try:
                if datetime.datetime.strptime(ep_air_date, '%Y-%m-%d').date() > today:
                    display_label = f"[B][COLOR FFE238EC]{ep_num}. {original_ep_name}[/COLOR] (Lansare: {ep_air_date})[/B]"
            except: pass
        # -----------------------------------------------
        
        from resources.lib import trakt_sync
        progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'tv', season_num, ep_num)
        resume_percent = 0
        resume_seconds = 0
        
        if progress_value >= 1000000:
            resume_seconds = int(progress_value - 1000000)
        elif progress_value > 0 and progress_value < 90:
            resume_percent = progress_value

        thumb = f"{IMG_BASE}{ep.get('still_path', '')}" if ep.get('still_path') else ''

        is_watched = trakt_api.check_episode_watched(tmdb_id, season_num, ep_num)
        
        duration = ep.get('runtime', 0)
        if duration:
            duration = int(duration) * 60

        if resume_seconds > 0 and duration > 0:
            resume_percent = (resume_seconds / duration) * 100

        ep_plot = ep.get('overview', '')
        ep_plot = get_translated_plot(tmdb_id, 'tv', ep_plot, season=int(season_num), episode=ep_num)

        info = {
            'mediatype': 'episode',
            'title': original_ep_name,
            'resume_percent': resume_percent,
            'plot': ep_plot,
            'rating': ep.get('vote_average', 0),
            'premiered': ep_air_date,
            'season': int(season_num),
            'episode': int(ep_num),
            'tvshowtitle': tv_show_title,
            'duration': duration,
            'votes': ep.get('vote_count', 0)
        }
        
        cm = trakt_api.get_watched_context_menu(tmdb_id, 'tv', season_num, ep_num)
        
        # --- MODIFICARE: MY PLAYS MENU (Cu date complete pentru luc_kodi) ---
        plays_params = {
            'mode': 'show_my_plays_menu',
            'tmdb_id': tmdb_id,
            'type': 'episode',
            'title': tv_show_title,       # Numele Serialului
            'ep_name': original_ep_name,  # Numele Episodului (NOU - Critic pentru luc_kodi)
            'premiered': ep_air_date,     # Data premierei (NOU - Critic pentru luc_kodi)
            'season': season_num,
            'episode': ep_num,
            'imdb_id': show_imdb_id       # IMDB ID al serialului
        }
        cm.append(('[B][COLOR FFFDBD01]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
        # --------------------------------------------------------------------
        
        import xbmcgui
        dl_key = f"dl_tv_{str(tmdb_id)}_{season_num}_{ep_num}"
        is_downloading = xbmcgui.Window(10000).getProperty(dl_key) == 'active'
        
        if is_downloading:
            stop_params = urlencode({'mode': 'stop_download_action', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num)})
            cm.append(('[B][COLOR FFFF69B4]■ Stop Download[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{stop_params})"))
        else:
            dl_ep_params = urlencode({'mode': 'initiate_download', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num), 'title': original_ep_name, 'tv_show_title': tv_show_title})
            cm.append(('[B][COLOR cyan]Download Episode[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{dl_ep_params})"))
        
        fav_params = urlencode({'mode': 'add_favorite', 'type': 'tv', 'tmdb_id': tmdb_id, 'title': tv_show_title})
        cm.append(('[B][COLOR yellow]Add TV Show to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

        clear_ep_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num), 'title': f"{tv_show_title} S{season_num}E{ep_num}"})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_ep_params})"))
        
        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num), 'title': ep.get('name', ''), 'tv_show_title': tv_show_title}
        
        if resume_percent > 0 and resume_percent < 90 and duration > 0:
            resume_seconds = int((resume_percent / 100.0) * duration)
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(display_label) # MODIFICAT DIN 'name'
        
        li.setArt({'thumb': thumb, 'icon': thumb, 'poster': poster, 'fanart': thumb})
        li.setProperty('tmdb_id', tmdb_id)
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id}, watched_info=is_watched)
        set_resume_point(li, resume_seconds, duration)
        
        if cm: li.addContextMenuItems(cm)
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)

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

    # --- INCEPUT MODIFICARE: Logica Trailer (V5 - FINAL FIX & DEEP SCAN) ---
    trailer_url = ''
    found_video = None
    priority_types = ['Trailer', 'Teaser'] # Prioritate: Trailer, apoi Teaser

    # 1. Verificare initiala (in datele deja descarcate prin append_to_response)
    videos = data.get('videos', {}).get('results', [])
    for vid_type in priority_types:
        for v in videos:
            if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                found_video = v
                break
        if found_video: break
    
    # 2. FALLBACK: Deep Search Iterativ (Daca nu am gasit nimic in lista standard)
    if not found_video:
        log(f"[TMDB-INFO] Trailer missing. Starting Deep Search for ID: {tmdb_id}")
        
        # Lista de regiuni critice. Adaugat ta-IN, te-IN, hi-IN, etc.
        try_locales = ['ta-IN', 'te-IN', 'hi-IN', 'ml-IN', 'kn-IN', 'pa-IN', 'en-US', 'xx']
        
        # Lista extinsa pentru include
        safe_include = "en,null,xx,hi,ta,te,ml,kn,bn,gu,mr,ur,or,as,es,fr,de,it,ro"
        
        for locale in try_locales:
            # Construim URL-ul manual pentru a forta regiunea
            vid_url = f"{BASE_URL}/{content_type}/{tmdb_id}/videos?api_key={API_KEY}&language={locale}&include_video_language={safe_include}"
            
            try:
                # log(f"[TMDB-INFO] Trying locale: {locale} ...") # Decomenteaza pentru debug
                r_vid = requests.get(vid_url, timeout=2) 
                if r_vid.status_code == 200:
                    data_vid = r_vid.json()
                    temp_res = data_vid.get('results', [])
                    
                    if temp_res:
                        # Cautam Trailer sau Teaser in rezultatele regionale
                        for vid_type in priority_types:
                            for v in temp_res:
                                if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                                    found_video = v
                                    log(f"[TMDB-INFO] SUCCESS! Found {vid_type} in locale: {locale}")
                                    break
                            if found_video: break
                        
                        # Daca am gasit un video valid, ne oprim din cautat in alte regiuni
                        if found_video: break
                        
                        # Daca e lista dar nu e trailer, luam primul ca backup (dar continuam cautarea poate gasim trailer in alta parte)
                        # Daca vrei sa fii agresiv si sa te opresti la orice video, decomenteaza linia de mai jos:
                        # if temp_res: found_video = temp_res[0]; break 

            except Exception as e:
                log(f"[TMDB-INFO] Error checking {locale}: {e}", xbmc.LOGWARNING)

    # 3. Fallback final: Daca tot nu am gasit Trailer/Teaser, luam orice video disponibil din lista initiala
    if not found_video and videos:
        for v in videos:
            if v.get('site') == 'YouTube':
                found_video = v
                break

    # Construire URL Final
    if found_video:
        trailer_url = f"plugin://plugin.video.youtube/play/?video_id={found_video.get('key')}"
    # --- SFARSIT MODIFICARE ---


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

        # --- FIX STATUS: Folosim "Studios" pentru a afisa Statusul in dreapta ---
        # Estuary afiseaza lista de Studiouri (Networks) sub Rating/An.
        studios_list = []
        
        # 1. Calculam Statusul
        if content_type in ['tv', 'tvshow'] and 'status' in data:
            st = data['status']
            status_text = st
            # Nota: Estuary s-ar putea sa ignore culorile in campul Studio, dar textul va aparea.
            if st == 'Returning Series': status_text = "Status: Continuing" 
            elif st == 'Ended': status_text = "Status: Ended"
            elif st == 'Canceled': status_text = "Status: Canceled"
            elif st == 'In Production': status_text = "Status: In Production"
            
            # Adaugam statusul ca PRIMUL element in lista de studiouri
            if status_text:
                studios_list.append(status_text)

        # 2. Adaugam Studiourile reale
        if data.get('production_companies'):
            studios_list.extend([c.get('name') for c in data['production_companies']])
        elif data.get('networks'):
            studios_list.extend([n.get('name') for n in data['networks']])

        # 3. Setam lista combinata
        if studios_list:
            tag.setStudios(studios_list)
        # ------------------------------------------------------------------------
        
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
    
    title = params.get('title', '')
    year = params.get('year', '')
    
    # IMPORTANT: Citim season si episode din params
    season = params.get('season')
    episode = params.get('episode')
    
    # Convertim la int daca exista
    if season:
        try:
            season = int(season)
        except:
            season = None
    if episode:
        try:
            episode = int(episode)
        except:
            episode = None

    log(f"[GLOBAL-INFO] Parsed: type={content_type}, tmdb_id={tmdb_id}, season={season}, episode={episode}")

    # Validare ID
    if tmdb_id and (not str(tmdb_id).isdigit() or str(tmdb_id) == '0'): 
        tmdb_id = None
    if imdb_id and not str(imdb_id).startswith('tt'): 
        imdb_id = None

    # 1. Găsirea ID-ului Principal (Film sau Serial)
    found_id = tmdb_id
    
    # Determinam media type pentru cautare
    if content_type in ['tv', 'season', 'episode']:
        found_media = 'tv'
    else:
        found_media = 'movie'

    # Dacă nu avem TMDb ID, îl căutăm
    if not found_id:
        # A. Căutare prin External IDs
        if imdb_id:
            url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
            data = get_json(url)
            if data:
                if data.get('movie_results') and found_media == 'movie':
                    found_id = data['movie_results'][0]['id']
                elif data.get('tv_results'):
                    found_id = data['tv_results'][0]['id']
                    found_media = 'tv'
                elif data.get('tv_episode_results'):
                    found_id = data['tv_episode_results'][0]['show_id']
                    found_media = 'tv'
        
        # B. Căutare prin TVDb
        if not found_id and tvdb_id and str(tvdb_id).isdigit():
            url = f"{BASE_URL}/find/{tvdb_id}?api_key={API_KEY}&external_source=tvdb_id"
            data = get_json(url)
            if data:
                if data.get('tv_results'):
                    found_id = data['tv_results'][0]['id']
                    found_media = 'tv'
                elif data.get('tv_episode_results'):
                    found_id = data['tv_episode_results'][0]['show_id']
                    found_media = 'tv'

        # C. Căutare prin Titlu (Fallback)
        if not found_id and title:
            clean_title = title.split('(')[0].strip()
            url = f"{BASE_URL}/search/{found_media}?api_key={API_KEY}&query={quote(clean_title)}"
            
            if year and str(year).isdigit() and found_media == 'movie':
                url += f"&primary_release_year={year}"
                    
            data = get_json(url)
            if data.get('results'):
                found_id = data['results'][0]['id']
                log(f"[GLOBAL-INFO] Found parent ID by title: {found_id}")

    # 2. Afișare Info bazat pe tipul cerut
    if found_id:
        log(f"[GLOBAL-INFO] Showing info: type={content_type}, id={found_id}, season={season}, episode={episode}")
        
        # Logica de decizie bazata pe TYPE primit SAU prezenta season/episode
        if content_type == 'episode' or (season is not None and episode is not None and episode > 0):
            # Afisam info pentru EPISOD
            if season is not None and episode is not None:
                log(f"[GLOBAL-INFO] -> Episode info dialog")
                show_specific_info_dialog(str(found_id), 'episode', season=season, episode=episode)
            else:
                # Fallback la serial daca nu avem season/episode valid
                show_info_dialog({'tmdb_id': str(found_id), 'type': 'tv'})
                
        elif content_type == 'season' or (season is not None and season >= 0 and (episode is None or episode <= 0)):
            # Afisam info pentru SEZON
            if season is not None:
                log(f"[GLOBAL-INFO] -> Season info dialog")
                show_specific_info_dialog(str(found_id), 'season', season=season)
            else:
                # Fallback la serial
                show_info_dialog({'tmdb_id': str(found_id), 'type': 'tv'})
                
        else:
            # Info standard (Film sau Serial întreg)
            log(f"[GLOBAL-INFO] -> Standard info dialog for {found_media}")
            show_info_dialog({'tmdb_id': str(found_id), 'type': found_media})
    else:
        import xbmcgui
        xbmcgui.Dialog().notification("TMDb Info", "Nu am identificat titlul", xbmcgui.NOTIFICATION_WARNING, 3000)


def show_specific_info_dialog(tmdb_id, specific_type, season=1, episode=1):
    """
    Afișează info dialog pentru un Sezon sau Episod specific.
    Dacă sezonul/episodul nu există, face fallback la info de serial.
    """
    import xbmcgui
    
    # Încercăm să luăm datele serialului mai întâi (pentru fallback și date suplimentare)
    show_data = None
    try:
        show_url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=videos"
        show_data = get_json(show_url)
    except:
        pass
    
    # Construim URL-ul pentru sezon/episod
    data = None
    if specific_type == 'season':
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
        data = get_json(url)
    elif specific_type == 'episode':
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
        data = get_json(url)
    
    # FALLBACK: Dacă sezonul/episodul nu există, afișăm info de serial
    if not data or data.get('success') == False:
        log(f"[SPECIFIC-INFO] Season/Episode not found (S{season}E{episode}), falling back to TV show info")
        if show_data:
            # Apelăm show_info_dialog pentru serial
            show_info_dialog({'tmdb_id': str(tmdb_id), 'type': 'tv'})
            return
        else:
            xbmcgui.Dialog().notification("TMDb Info", "Sezonul/Episodul nu există", xbmcgui.NOTIFICATION_WARNING)
            return

    # Metadata mapping
    title = data.get('name', 'Unknown')
    overview = data.get('overview', '')
    
    # Fallback Plot de la Serial
    if not overview and show_data:
        overview = show_data.get('overview', '')

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
    
    # Setam TVShowTitle
    if show_data:
        tag.setTvShowTitle(show_data.get('name', ''))
    
    # --- LOGICA TRAILER ---
    trailer_url = ''
    priority_types = ['Trailer', 'Teaser']
    
    # 1. Cautam trailer in datele sezonului/episodului
    videos = data.get('videos', {}).get('results', [])
    for vid_type in priority_types:
        for v in videos:
            if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                trailer_url = f"plugin://plugin.video.youtube/play/?video_id={v.get('key')}"
                break
        if trailer_url:
            break
    
    # 2. FALLBACK: Daca nu am gasit, cautam la nivel de serial
    if not trailer_url and show_data:
        show_videos = show_data.get('videos', {}).get('results', [])
        for vid_type in priority_types:
            for v in show_videos:
                if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                    trailer_url = f"plugin://plugin.video.youtube/play/?video_id={v.get('key')}"
                    break
            if trailer_url:
                break
    
    if trailer_url:
        tag.setTrailer(trailer_url)

    # Cast
    cast = []
    source_cast = data.get('guest_stars', []) + data.get('credits', {}).get('cast', [])
    for p in source_cast[:15]:
        if not p.get('name'):
            continue
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
        
    if show_data:
        if show_data.get('backdrop_path'):
            art['fanart'] = f"{BACKDROP_BASE}{show_data['backdrop_path']}"
        if not art.get('poster') and show_data.get('poster_path'):
            art['poster'] = f"{IMG_BASE}{show_data['poster_path']}"

    li.setArt(art)
    xbmcgui.Dialog().info(li)


def perform_search(params):
    """Cere input și afișează rezultatele - REFRESH SAFE folosind cache!"""
    search_type = params.get('type', 'multi')
    query = params.get('query')
    
    # 1. Dacă avem query în URL (redirect) - afișăm direct
    if query:
        from urllib.parse import unquote
        build_search_result(search_type, unquote(query))
        return
    
    # 2. Verificăm cache-ul pentru Container.Refresh
    cache_key = f'tmdb_search_{search_type}'
    cached_query = xbmcgui.Window(10000).getProperty(cache_key)
    
    # Detectăm dacă suntem deja pe pagina de rezultate (refresh)
    container_path = xbmc.getInfoLabel('Container.FolderPath')
    is_refresh = cached_query and 'perform_search' in container_path
    
    if is_refresh:
        # E un refresh - folosim query-ul din cache
        build_search_result(search_type, cached_query)
        return
    
    # 3. Căutare nouă - cerem input
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Căutare...", type=xbmcgui.INPUT_ALPHANUM)
    
    if new_query:
        add_search_to_history(new_query, search_type)
        # Salvăm în cache pentru refresh-uri viitoare
        xbmcgui.Window(10000).setProperty(cache_key, new_query)
        # Afișăm rezultatele direct
        build_search_result(search_type, new_query)
    else:
        # Cancel
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def perform_search_query(params):
    """Execută direct o căutare din istoric."""
    search_type = params.get('type', 'multi')
    query = params.get('query', '')
    
    if query:
        from urllib.parse import unquote
        query = unquote(query)
        add_search_to_history(query, search_type)
        # Salvăm în cache pentru refresh
        xbmcgui.Window(10000).setProperty(f'tmdb_search_{search_type}', query)
        build_search_result(search_type, query)
    else:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def get_tmdb_search_results(query, search_type, page):
    url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&language={LANG}&query={quote(query)}&page={page}"
    return requests.get(url, timeout=10)


# --- COD EXISTENT ---
def build_search_result(search_type, query, page=1): # Adăugat parametrul page
    # --- FAST CACHE CHECK (RAM) ---
    cache_key = f"search_{search_type}_{query}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ------------------------------
    data = cache_object(get_tmdb_search_results, f"search_{search_type}_{query}_{page}", [query, search_type, page], expiration=1)

    if not data:
        xbmcplugin.endOfDirectory(HANDLE); return

    results = data.get('results', [])
    prefetch_metadata_parallel(results, search_type) # Threading metadata
    
    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True) if search_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    # Paginare pentru căutare
    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}/{total_pages}) >>[/B]"
        next_params = {'mode': 'perform_search', 'type': search_type, 'query': query, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': 'DefaultFolder.png'}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if search_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    # Save to RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


# --- COD EXISTENT ---
def list_recommendations(params):
    tmdb_id = params.get('tmdb_id')
    menu_type = params.get('menu_type', 'movie')
    page = int(params.get('page', '1'))

    # --- FAST CACHE CHECK (RAM) ---
    cache_key = f"recomm_{tmdb_id}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ------------------------------

    endpoint = 'movie' if menu_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/recommendations?api_key={API_KEY}&language={LANG}&page={page}"
    data = get_json(url)
    
    if not data:
        xbmcplugin.endOfDirectory(HANDLE); return

    results = data.get('results', [])
    prefetch_metadata_parallel(results, menu_type)

    items_to_add = []
    cache_list = []
    
    for item in results:
        processed = _process_movie_item(item, return_data=True) if menu_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    # Next Page logic...
    total_pages = min(data.get('total_pages', 1), 500)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_recommendations', 'tmdb_id': tmdb_id, 'menu_type': menu_type, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': 'DefaultFolder.png'}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if menu_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': 0, 'total_time': 0} for i in cache_list])


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
    from resources.lib.config import SESSION, get_headers
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=credits,videos,external_ids,images"

    string = f"details_{content_type}_{tmdb_id}"

    def worker(u):
        return SESSION.get(u, headers=get_headers(), timeout=10)

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
        
        # --- MODIFICARE: Extragem IMDB ID pentru My Plays---
        imdb_id = ''
        if details:
            imdb_id = details.get('external_ids', {}).get('imdb_id', '')
        # ------------------------------------
        
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
        
        cm = _get_full_context_menu(tmdb_id, 'movie', title, imdb_id=imdb_id, year=year)
        
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
        set_resume_point(li, resume_seconds, duration)
        
        # Context menu
        if cm:
            li.addContextMenuItems(cm)
        
        # Adăugare
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        # --- SFARSIT FIX RESUME ---
    
    if page < total_pages:
        add_directory(
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
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
    
    prefetch_metadata_parallel(all_results, 'tv')
    
    valid_items = []
    
    for item in all_results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        # --- MODIFICARE: Fetch detalii pentru PLOT și METADATE ---
        details = get_tmdb_item_details(tmdb_id, 'tv')
        item['overview'] = details.get('overview', '') if details else ''
        
        # --- MODIFICARE: Extragem IMDB ID pentru My Plays---
        item['imdb_id'] = details.get('external_ids', {}).get('imdb_id', '') if details else ''
        # ------------------------------------
        
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

        # --- MODIFICARE: Recuperăm imdb_id din item pt My Plays---
        imdb_id = item.get('imdb_id', '')
        # ----------------------------------------------
        
        info = {
            'mediatype': 'tvshow',
            'title': name,
            'year': year,
            'plot': f"[B][COLOR orange]Vizionat: {curr_watched}/{display_total} ({progress_pct}%)[/COLOR][/B]\n\n{plot}",
            'tvshowtitle': name,
            'rating': item.get('rating', 0),
            'votes': item.get('votes', 0),
            'premiered': item.get('premiered', ''),
            'studio': item.get('studio', ''),
            'duration': item.get('duration', 0)
        }
        
        watched_info = {'watched': curr_watched, 'total': curr_total}
        cm = _get_full_context_menu(tmdb_id, 'tv', name, year=year, imdb_id=imdb_id)

        label = f"{name} ({year})" if year else name
        label += f" [COLOR orange]({curr_watched}/{display_total})[/COLOR]"

        add_directory(
            label,
            {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': name},
            icon=poster, thumb=poster, info=info, cm=cm,
            watched_info=watched_info, folder=True
        )
    
    if page < total_pages:
        add_directory(
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
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
    
    # ASTA FACE VITEZA:
    prefetch_metadata_parallel(results, 'tv')
        
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
        
        # --- MODIFICARE: Extragem IMDB ID-ul serialului ---
        show_imdb_id = ''
        if show_details:
            if show_details.get('networks'):
                studio = show_details['networks'][0].get('name', '')
            show_imdb_id = show_details.get('external_ids', {}).get('imdb_id', '')
        # --------------------------------------------------

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
            'plot': f"[B][COLOR orange]Progres: {int(progress)}%[/COLOR][/B]\n\n{ep_plot}",
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
        
        # cm.append(('[B][COLOR FFFDBD01]TMDb Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_info&tmdb_id={tmdb_id}&type=tv)"))

        # --- MODIFICARE: Adăugăm MY PLAYS MENU manual ---
        plays_params = {
            'mode': 'show_my_plays_menu',
            'tmdb_id': tmdb_id,
            'type': 'episode',
            'title': show_title,
            'ep_name': title.replace(f"{show_title} - ", ""), # Încercare curățare titlu
            'premiered': premiered,
            'season': season,
            'episode': episode,
            'imdb_id': show_imdb_id
        }
        cm.append(('[B][COLOR FFFDBD01]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
        # ------------------------------------------------

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
        set_resume_point(li, resume_seconds, duration)
        
        # Context menu
        if cm:
            li.addContextMenuItems(cm)
        
        # Adăugare
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        # --- SFARSIT FIX RESUME ---
    
    if page < total_pages:
        add_directory(
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
            {'mode': 'in_progress_episodes', 'page': str(page + 1)},
            icon='DefaultFolder.png', folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE)


def get_next_episodes(params=None):
    """Afișează Next Episodes (Up Next) cu culori și data lansării."""
    from resources.lib import trakt_sync
    items = trakt_sync.get_next_episodes_from_db()
    today = datetime.date.today()
    if not items:
        add_directory("[COLOR gray]Nu ai episoade noi (Rulează 'Sincronizare Trakt')[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE); return

    for it in items:
        tmdb_id = it['tmdb_id']
        label = f"[B][COLOR FF00CED1]{it['show_title']}[/COLOR][/B] - S{it['season']:02d}E{it['episode']:02d} - [I]{it['ep_title']}[/I]"

        # --- MODIFICARE: Extragem IMDB ID ---
        show_details = get_tmdb_item_details(tmdb_id, 'tv')
        imdb_id = show_details.get('external_ids', {}).get('imdb_id', '') if show_details else ''
        # ------------------------------------
        
        # CULOARE ROȘIE DACĂ NU E LANSAT
        if it['air_date']:
            try:
                if datetime.datetime.strptime(it['air_date'], '%Y-%m-%d').date() > today:
                    label = f"[B][COLOR FFFF69B4]{it['show_title']} - S{it['season']:02d}E{it['episode']:02d}[/COLOR] (Lansare: {it['air_date']})[/B]"
            except: pass

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(it['season']), 'episode': str(it['episode']), 'title': it['ep_title'], 'tv_show_title': it['show_title']}
        info = {'mediatype': 'episode', 'title': it['ep_title'], 'tvshowtitle': it['show_title'], 'season': it['season'], 'episode': it['episode'], 'plot': it['overview'], 'premiered': it['air_date']}
        poster = f"{IMG_BASE}{it['poster']}" if it['poster'] and not it['poster'].startswith('http') else TRAKT_ICON

        # --- MODIFICARE: Trimitem tipul 'episode' și numerele S/E ---
        cm = _get_full_context_menu(
            tmdb_id, 
            'episode',             # AICI am corectat din 'tv' în 'episode'
            it['show_title'], 
            imdb_id=imdb_id,
            season=it['season'],   # Trimitem sezonul
            episode=it['episode']  # Trimitem episodul
        )
        # ------------------------------------------------------------
        add_directory(label, url_params, icon=poster, thumb=poster, info=info, cm=cm, folder=False)

    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE)


# =============================================================================
# MENU: MY PLAYS (Custom Player Launcher) - REPARAȚIE FINALĂ LUC_KODI
# =============================================================================
def show_my_plays_menu(params):
    import json
    import xbmc
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type') # movie, tv, season, episode
    
    # Date brute
    title = params.get('title', '') 
    year = params.get('year', '')
    season = params.get('season', '')
    episode = params.get('episode', '')
    ep_name = params.get('ep_name', '')       
    premiered = params.get('premiered', '')   
    
    safe_title = quote_plus(title)
    
    # --- FETCH DATE COMPLETE PENTRU A SIMULA TMDB HELPER ---
    poster = ''
    fanart = ''
    plot = ''
    correct_imdb_id = params.get('imdb_id', '')
    correct_tvdb_id = ''
    rating = 0.0
    votes = 0
    studio = ''
    genre = ''
    mpaa = ''
    status = ''
    cast_list = []
    director = ''
    writer = ''

    try:
        # Preluăm detaliile principale (din cache)
        main_details = get_tmdb_item_details(tmdb_id, 'movie' if c_type == 'movie' else 'tv') or {}
        
        if main_details:
            # Imagini
            if main_details.get('poster_path'):
                poster = f"{IMG_BASE}{main_details['poster_path']}"
            if main_details.get('backdrop_path'):
                fanart = f"{BACKDROP_BASE}{main_details['backdrop_path']}"
            
            # IDs
            ext_ids = main_details.get('external_ids', {})
            if not correct_imdb_id: correct_imdb_id = ext_ids.get('imdb_id', '')
            correct_tvdb_id = str(ext_ids.get('tvdb_id', ''))
            
            # Meta
            status = main_details.get('status', '')
            if main_details.get('genres'):
                genre = ' / '.join([g['name'] for g in main_details['genres']])
            if main_details.get('networks'):
                studio = main_details['networks'][0].get('name', '')
            elif main_details.get('production_companies'):
                studio = main_details['production_companies'][0].get('name', '')
            
            # Year fallback
            if not year:
                date_ref = main_details.get('release_date') or main_details.get('first_air_date')
                if date_ref: year = date_ref[:4]

        if c_type == 'episode':
            # Detalii specifice episod (Plot, Rating, Cast)
            ep_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={LANG}&append_to_response=credits"
            import requests
            r_ep = requests.get(ep_url, timeout=3)
            if r_ep.status_code == 200:
                ed = r_ep.json()
                plot = ed.get('overview', '')
                rating = float(ed.get('vote_average', 0.0))
                votes = int(ed.get('vote_count', 0))
                # Cast formatat ca listă de dict-uri (cum vrea luc_kodi)
                for actor in ed.get('credits', {}).get('guest_stars', [])[:10]:
                    cast_list.append({"name": actor['name'], "role": actor.get('character', '')})
        else:
            plot = main_details.get('overview', '')
            rating = float(main_details.get('vote_average', 0.0))
            votes = int(main_details.get('vote_count', 0))
            for actor in main_details.get('credits', {}).get('cast', [])[:10]:
                cast_list.append({"name": actor['name'], "role": actor.get('character', '')})

    except: pass

    # Fallbacks finale
    if not year and premiered: year = premiered[:4]
    
    options = []
    actions = []
    is_folder_list = [] 
    is_luc_kodi_action = [] 

    is_playable_context = (c_type in ['movie', 'episode'])
    prefix = "Play with" if is_playable_context else "Search with"

    # =========================================================================
    # 0. SERIALE (TV)
    # =========================================================================
    if c_type == 'tv':
        url = f"plugin://plugin.video.themoviedb.helper/?info=search&type=tv&query={safe_title}"
        options.append(f"[B]Search with [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
        actions.append(url)
        is_folder_list.append(True) 
        is_luc_kodi_action.append(False)
        
        ret = xbmcgui.Dialog().contextmenu(options)
        if ret >= 0:
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{actions[ret]}",return)')
        return

    # =========================================================================
    # 1. POV, Fen & Fen Light
    # =========================================================================
    if c_type != 'season':
        # POV
        if c_type == 'movie':
            pov_url = f"plugin://plugin.video.pov/?mode=play_media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&tmdb_id={tmdb_id}&autoplay=false"
        else:
            pov_url = f"plugin://plugin.video.pov/?mode=play_media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&autoplay=false"
        options.append(f"[B]{prefix} [COLOR FFB041FF]POV[/COLOR][/B]")
        actions.append(pov_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(False)

        # FEN LIGHT (Fix: Adaugat poster, ep_name si premiered)
        if c_type == 'movie':
            fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
        else:
            fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
        options.append(f"[B]{prefix} [COLOR lightskyblue]Fen Light[/COLOR][/B]")
        actions.append(fen_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(False)

        # FEN (Fix: Adaugat poster, ep_name si premiered)
        if c_type == 'movie':
            fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
        else:
            fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
        options.append(f"[B]{prefix} [COLOR blue]Fen[/COLOR][/B]")
        actions.append(fen_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(False)

    
    # =========================================================================
    # 2. luc_Kodi
    # =========================================================================
    if c_type != 'season':
        # Construim meta exact ca în log-ul functional de Fallout
        meta_obj = {
            "premiered": premiered,
            "plot": plot,
            "tmdb": str(tmdb_id),
            "poster": poster,
            "thumb": poster,
            "fanart": fanart,
            "rating": rating,
            "votes": votes,
            "imdb": correct_imdb_id,
            "imdbnumber": correct_imdb_id,
            "code": correct_imdb_id,
            "year": str(year),
            "mediatype": c_type,
            "studio": studio,
            "genre": genre,
            "status": status,
            "castandart": cast_list # Listă de obiecte
        }
        
        if c_type == 'episode':
            meta_obj.update({
                "title": ep_name,
                "tvshowtitle": title,
                "label": ep_name,
                "season": int(season), # Integer
                "episode": int(episode), # Integer
                "tvdb": correct_tvdb_id
            })
            meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
            lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&title={quote_plus(ep_name)}&tvshowtitle={safe_title}&season={season}&episode={episode}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"
        else:
            meta_obj.update({"title": title, "originaltitle": title})
            meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
            lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&title={safe_title}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"

        options.append(f"[B]{prefix} [COLOR ff00fa9a]luc_[/COLOR]Kodi[/B]")
        actions.append(lk_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(True)

    # =========================================================================
    # 3. UMBRELLA (Adaugat Nou - foloseste meta_enc generat de luc_kodi)
    # =========================================================================
        if c_type == 'movie':
            umb_url = f"plugin://plugin.video.umbrella/?action=play&title={safe_title}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&meta={meta_enc}&select=0"
        else:
            umb_url = f"plugin://plugin.video.umbrella/?action=play&title={quote_plus(ep_name)}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&season={season}&episode={episode}&tvshowtitle={safe_title}&premiered={premiered}&meta={meta_enc}&select=0"
        
        options.append(f"[B]{prefix} [COLOR FFE41B17]Umbrella[/COLOR][/B]")
        actions.append(umb_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(True) # Umbrella merge cu RunPlugin, nu are nevoie de PlayMedia forcat ca luc_kodi


    # =========================================================================
    # 4. ELEMENTUM (Adaugat Nou)
    # =========================================================================

    if c_type != 'season':
        if c_type == 'movie':
            elem_url = f"plugin://plugin.video.elementum/library/play/movie/{tmdb_id}"
        else:
            elem_url = f"plugin://plugin.video.elementum/library/play/show/{tmdb_id}/season/{season}/episode/{episode}"
        
        options.append(f"[B]{prefix} [COLOR FF786D5F]Elementum[/COLOR][/B]")
        actions.append(elem_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(True)

    # =========================================================================
    # 5. CINEBOX (Adaugat Nou)
    # =========================================================================
    if c_type != 'season':
        if c_type == 'movie':
            cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=movie&title={safe_title}&year={year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
        else:
            cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=tvshow&title={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
        
        options.append(f"[B]{prefix} [COLOR FFA70D2A]CINEBOX[/COLOR][/B]")
        actions.append(cine_url)
        is_folder_list.append(False)
        is_luc_kodi_action.append(True) # Cinebox gestionează intern dialogul de căutare surse
        
    # =========================================================================
    # 6. MRSP Lite
    # =========================================================================
    if c_type != 'season':
        if c_type == 'movie':
            mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=movie"
        else:
            try: s_str = f"s{int(season):02d}"
            except: s_str = f"s{season}"
            mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{s_str}&showname={safe_title}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=episode"
        
        options.append(f"[B]{prefix} [COLOR orange]MRSP Lite[/COLOR][/B]")
        actions.append(mrsp_url)
        is_folder_list.append(True)
        is_luc_kodi_action.append(False)


    # =========================================================================
    # 7. Extra: Search TMDbH (Filme)
    # =========================================================================
    if c_type == 'movie':
        actions.append(f"plugin://plugin.video.themoviedb.helper/?info=search&type=movie&query={safe_title}")
        options.append(f"[B]Search with [COLOR gold]TMDB Helper[/COLOR][/B]")
        is_folder_list.append(True)
        is_luc_kodi_action.append(False)

    # =========================================================================
    # 8. TMDb Helper
    # =========================================================================
    url = ""
    if c_type == 'movie':
        url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=movie&tmdb_id={tmdb_id}"
    elif c_type == 'episode':
        url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=episode&tmdb_id={tmdb_id}&season={season}&episode={episode}"
    elif c_type == 'season':
        url = f"plugin://plugin.video.themoviedb.helper/?info=search&type=tv&query={safe_title}"
    
    if url:
        options.append(f"[B]{'Search' if c_type=='season' else prefix} [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
        actions.append(url)
        is_folder_list.append(c_type == 'season')
        is_luc_kodi_action.append(False)


    # --- EXECUȚIE ---
    ret = xbmcgui.Dialog().contextmenu(options)
    if ret >= 0:
        target = actions[ret]
        if is_luc_kodi_action[ret]:
            xbmc.executebuiltin('Dialog.Close(all,true)')
            xbmc.sleep(300)
            # Doar luc_kodi are nevoie de PlayMedia pentru a deschide playerul din resolving
            xbmc.executebuiltin(f"PlayMedia({target})")
        elif is_folder_list[ret]:
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{target}",return)')
        else:
            xbmc.executebuiltin(f"RunPlugin({target})")


# =============================================================================
# BACKGROUND WARM-UP & PREFETCH ENGINE (V7 - GHOST MODE)
# =============================================================================

def process_single_list_warmup(action, content_type, page=1):
    """Procesează o listă în fundal cu întrerupere forțată (Zero Hang)."""
    monitor = xbmc.Monitor()
    cache_key = f"list_{content_type}_{action}_{page}"
    
    # Verificăm dacă există deja sau dacă Kodi vrea să închidă addon-ul
    if monitor.abortRequested() or get_fast_cache(cache_key): return

    results = None
    try:
        # Citim din DB (WAL mode previne blocajul)
        results = trakt_sync.get_tmdb_from_db(action, page)
        
        # Dacă nu e în DB, facem request API, dar cu timeout FOARTE mic
        if not results:
            if monitor.abortRequested(): return
            string = f"{action}_{page}_{LANG}"
            # Folosim o funcție worker care respectă monitorul
            data = cache_object(get_tmdb_movies_standard if content_type == 'movie' else get_tmdb_tv_standard, 
                                string, [action, page], expiration=1)
            if data: results = data.get('results', [])
    except: pass
    
    if not results or monitor.abortRequested(): return

    cache_list = []
    # Procesăm DOAR primele 15 iteme în fundal (suficient pentru viteză, dar mai ușor pentru procesor)
    items_to_process = results[:15] 
    
    for item in items_to_process:
        if monitor.abortRequested(): return # Ieșire instantanee la orice click al utilizatorului
        
        try:
            if content_type == 'movie':
                processed = _process_movie_item(item, return_data=True)
            else:
                processed = _process_tv_item(item, return_data=True)
            
            if processed:
                cache_list.append({
                    'label': processed['label'], 'url': processed['url'], 
                    'is_folder': processed['is_folder'], 'art': processed['art'], 
                    'info': processed['info'], 'cm': processed['cm_items'], 
                    'resume_time': processed['resume_time'], 'total_time': processed['total_time']
                })
        except: continue

    # Adăugăm butonul de Next Page (manual)
    if len(cache_list) > 0 and not monitor.abortRequested():
        mode_str = 'build_movie_list' if content_type == 'movie' else 'build_tvshow_list'
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': mode_str, 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        
        cache_list.append({
            'label': next_label, 'url': next_url, 'is_folder': True,
            'art': {'icon': 'DefaultFolder.png', 'thumb': 'DefaultFolder.png'},
            'info': {'mediatype': 'video', 'plot': 'Next Page'},
            'cm': [], 'resume_time': 0, 'total_time': 0, 'li': None
        })
        set_fast_cache(cache_key, cache_list)

def run_background_warmup(content_type):
    import threading
    window = xbmcgui.Window(10000)
    
    # Singleton: Nu pornim dacă rulează deja sau dacă suntem în proces de încărcare activă
    if window.getProperty('tmdbmovies_warmup_busy') == 'true' or \
       window.getProperty('tmdbmovies_loading_active') == 'true':
        return
        
    def master_worker():
        window.setProperty('tmdbmovies_warmup_busy', 'true')
        monitor = xbmc.Monitor()
        
        try:
            # --- LISTA COMPLETĂ (TOATE CATEGORIILE) ---
            if content_type == 'movie':
                actions = [
                    'tmdb_movies_trending_day', 'tmdb_movies_trending_week', 
                    'tmdb_movies_popular', 'tmdb_movies_top_rated',
                    'tmdb_movies_premieres', 'tmdb_movies_latest_releases', 
                    'tmdb_movies_box_office', 'tmdb_movies_now_playing',
                    'tmdb_movies_upcoming', 'tmdb_movies_anticipated', 
                    'tmdb_movies_blockbusters',
                    'hindi_movies_trending', 'hindi_movies_popular', 
                    'hindi_movies_premieres', 'hindi_movies_in_theaters', 
                    'hindi_movies_upcoming', 'hindi_movies_anticipated',
                    'trakt_movies_trending', 'trakt_movies_popular',
                    'trakt_movies_anticipated', 'trakt_movies_boxoffice'
                ]
                delay = 0.3 # Filmele se procesează repede
            else:
                actions = [
                    'tmdb_tv_trending_day', 'tmdb_tv_trending_week', 
                    'tmdb_tv_popular', 'tmdb_tv_top_rated',
                    'tmdb_tv_premieres', 'tmdb_tv_airing_today', 
                    'tmdb_tv_on_the_air', 'tmdb_tv_upcoming',
                    'trakt_tv_trending', 'trakt_tv_popular', 'trakt_tv_anticipated'
                ]
                delay = 0.7 # Serialele sunt mai lente

            if monitor.waitForAbort(1.0): return

            for act in actions:
                # Verificare agresivă: dacă user-ul a dat click pe orice, oprim warmup-ul complet
                # Nu doar îl punem în pauză, îl oprim de tot pentru această sesiune
                if monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true':
                    log("[WARMUP] User activity detected. Killing background task for stability.")
                    break # Ieșim din buclă, thread-ul moare.
                
                process_single_list_warmup(act, content_type, 1)
                
                if monitor.waitForAbort(delay): break
        finally:
            window.clearProperty('tmdbmovies_warmup_busy')

    t = threading.Thread(target=master_worker)
    t.daemon = True
    t.start()

def trigger_next_page_warmup(action, current_page, content_type):
    """Încarcă pagina următoare în fundal cu prioritate scăzută."""
    import threading
    def worker():
        monitor = xbmc.Monitor()
        # --- MODIFICARE: VERIFICARE AGRESIVĂ ---
        # Așteptăm 4 secunde, dar verificăm în fiecare secundă dacă userul a ieșit
        for _ in range(4):
            if monitor.waitForAbort(1): return # Dacă ieși din addon, thread-ul moare aici
            if xbmcgui.Window(10000).getProperty('tmdbmovies_loading_active') == 'true':
                return # Dacă deja încarci altceva, oprim acest prefetch
        
        if monitor.abortRequested(): return
        process_single_list_warmup(action, content_type, current_page + 1)
    
    t = threading.Thread(target=worker)
    t.daemon = True
    t.start()
    
